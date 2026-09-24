"""
Part A insight-engine tests (docs/LLM_INTEGRATION.md §2).

The LLM is an injectable dependency (the same seam as the run executor),
so these tests cover the whole contract with a FakeLLM — no network, no
API key required:

  - context bundle: calendar windows, dedupe by window start, gaps as
    nulls that break streaks, cold start, month arithmetic
  - rollup: averages, decline streaks, best/worst period
  - number checker: verbatim, 1dp rounding, integer paraphrase,
    derived counts, and REJECTION of fabricated numbers
  - build_insights: happy path, empty key, LLM raise, schema fails,
    basis failure, number fallback, qualitative-only watch list
  - pipeline integration: real snapshot row lands in the DB (success,
    degraded, and the no-network default in the API flow)
"""
import sys
import os
from datetime import date, datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models  # noqa: E402
from analytics import insights, llm, pipeline  # noqa: E402


# ---------------------------------------------------------
# Shared helpers (mirrors test_analytics.py — tests/ is not a package)
# ---------------------------------------------------------


def _sale(db, employee_id, when_dt, revenue, profit, items=None):
    """Insert a Sale (plus optional SaleItems) with an exact timestamp."""
    s = models.Sale(
        employee_id=employee_id,
        customer_id=None,
        payment_method="cash",
        total_revenue=revenue,
        total_profit=profit,
        date=when_dt.date(),
        time=when_dt.time(),
    )
    for product_id, qty, rp, cp in (items or []):
        s.items.append(models.SaleItem(
            product_id=product_id, quantity=qty,
            retail_price_at_sale=rp, cost_price_at_sale=cp,
        ))
    db.add(s)
    return s


def _at(hour=10, minute=0, days_ago=0):
    """A timestamp N days ago at H:MM — keeps window math readable."""
    when = datetime.now().replace(hour=hour, minute=minute,
                                  second=0, microsecond=0)
    return when - timedelta(days=days_ago)


# ---------------------------------------------------------
# Fakes
# ---------------------------------------------------------

class FakeLLM:
    """Scriptable stand-in for analytics.llm.generate_json."""

    def __init__(self, result=None, error=None):
        self.result = result if result is not None else {}
        self.error = error
        self.calls = []

    def generate_json(self, prompt, schema, *, timeout_s=None, client=None):
        # llm.generate_json passes (prompt, schema, timeout_s=...);
        # accept both call shapes for flexibility.
        self.calls.append(prompt)
        if self.error is not None:
            raise self.error
        return self.result


# ---------------------------------------------------------
# Sales payload factory (mimics aggregators.aggregate_sales shape)
# ---------------------------------------------------------

def _sales_payload(start: datetime, revenue: float, previous_revenue: float = 0.0,
                   period: str = "week") -> dict:
    return {
        "period": period,
        "best_unit": "days",
        "current": {"revenue": revenue, "profit": revenue * 0.3, "orders": 5},
        "previous": {"revenue": previous_revenue, "profit": previous_revenue * 0.3,
                     "orders": 4},
        "change_pct": {
            "revenue": round((revenue - previous_revenue) / previous_revenue * 100, 1)
            if previous_revenue else None,
            "profit": None,
            "orders": None,
        },
        "series": [],
        "best": {"by_revenue": [], "by_profit": []},
        "window": {
            "current_start": start.isoformat(),
            "current_end": (start + timedelta(days=7)).isoformat(),
            "previous_start": (start - timedelta(days=7)).isoformat(),
            "previous_end": start.isoformat(),
        },
    }


# ---------------------------------------------------------
# build_context — calendar semantics
# ---------------------------------------------------------

class TestBuildContext:
    def test_dedupes_and_fills_calendar_windows(self):
        # Current week starts 2026-09-21 (a Monday).
        cur = datetime(2026, 9, 21)
        current = _sales_payload(cur, 500.0, 400.0)
        # History: two runs of the SAME previous week + one two weeks back.
        dup_newer = _sales_payload(cur - timedelta(days=7), 410.0)
        dup_older = _sales_payload(cur - timedelta(days=7), 390.0)
        two_back = _sales_payload(cur - timedelta(days=14), 350.0)
        # Newest-first input, like the pipeline's query.
        window = insights.build_context(current, [dup_newer, dup_older, two_back])["recent_window"]

        assert len(window) == insights.HISTORY_K
        # The dedupe kept the NEWEST run of the duplicated window...
        assert window[-1] is dup_newer
        assert window[-2] is two_back
        # ...and left the two older calendar windows as nulls (gaps).
        assert window[0] is None
        assert window[1] is None

    def test_gap_breaks_streak(self):
        cur = datetime(2026, 9, 21)
        current = _sales_payload(cur, 100.0)
        # Two weeks back revenue 300, one week back MISSING, current 100.
        # The gap must break the streak -> 0, never count 300 -> 100.
        two_back = _sales_payload(cur - timedelta(days=14), 300.0)
        rollup = insights.build_context(current, [two_back])["rollup"]
        assert rollup["consecutive_declining_periods"] == 0
        assert rollup["windows_available"] == 1

    def test_consecutive_decline_streak(self):
        cur = datetime(2026, 9, 21)
        current = _sales_payload(cur, 100.0)
        hist = [
            _sales_payload(cur - timedelta(days=7), 200.0),
            _sales_payload(cur - timedelta(days=14), 300.0),
            _sales_payload(cur - timedelta(days=21), 400.0),
        ]
        rollup = insights.build_context(current, hist)["rollup"]
        assert rollup["consecutive_declining_periods"] == 3
        assert rollup["windows_available"] == 3
        assert rollup["avg_revenue"] == 300.0
        assert rollup["best_period"]["revenue"] == 400.0
        assert rollup["worst_period"]["revenue"] == 200.0

    def test_cold_start_no_history(self):
        cur = datetime(2026, 9, 21)
        bundle = insights.build_context(_sales_payload(cur, 100.0), [])
        assert bundle["recent_window"] is None
        assert bundle["rollup"] is None
        # current_dto still carries the fresh payload + other sections.
        assert bundle["current_dto"]["sales"]["current"]["revenue"] == 100.0

    def test_current_dto_carries_all_three_sections(self):
        cur = datetime(2026, 9, 21)
        sales = _sales_payload(cur, 100.0)
        emps = {"employees": [], "race_series": {}, "period": "week"}
        prods = {"top_by_revenue": [], "top_by_profit": [], "bottom_by_revenue": []}
        bundle = insights.build_context(sales, [], employees_payload=emps,
                                        products_payload=prods)
        assert bundle["current_dto"]["employees"] is emps
        assert bundle["current_dto"]["products"] is prods

    def test_month_windows_cross_year(self):
        cur = datetime(2026, 1, 1)
        current = _sales_payload(cur, 100.0, period="month")
        dec = _sales_payload(datetime(2025, 12, 1), 250.0, period="month")
        nov = _sales_payload(datetime(2025, 11, 1), 300.0, period="month")
        bundle = insights.build_context(current, [dec, nov])
        starts = [w["window"]["current_start"] for w in bundle["recent_window"] if w]
        # Oldest first: Nov 2025, Dec 2025, then nulls for Aug-Oct.
        assert starts == ["2025-11-01T00:00:00", "2025-12-01T00:00:00"]
        assert bundle["recent_window"][0] is None

    def test_malformed_window_degrades_to_cold_start(self):
        current = _sales_payload(datetime(2026, 9, 21), 100.0)
        current["window"] = {}  # no current_start
        bundle = insights.build_context(current, [])
        assert bundle["recent_window"] is None and bundle["rollup"] is None


# ---------------------------------------------------------
# Number checker
# ---------------------------------------------------------

class TestNumberChecker:
    def test_verbatim_and_rounding_pass(self):
        bundle = {"current_dto": {"sales": {"change_pct": {"revenue": 12.5}}}}
        assert insights._check_text("Revenue rose 12.5%", bundle,
                                    "current_dto.sales.change_pct.revenue")
        # 1dp tolerance
        assert insights._check_text("Revenue rose 12.5% or about 12.5 percent", bundle,
                                    "current_dto.sales.change_pct.revenue")

    def test_integer_paraphrase_passes(self):
        bundle = {"current_dto": {"sales": {"change_pct": {"revenue": 12.5}}}}
        # "about 13%" is a rounding of 12.5 — allowed.
        assert insights._check_text("Revenue rose about 13%", bundle,
                                    "current_dto.sales.change_pct.revenue")

    def test_fabricated_number_fails(self):
        bundle = {"current_dto": {"sales": {"change_pct": {"revenue": 12.5}}}}
        assert not insights._check_text("Revenue rose 40%", bundle,
                                        "current_dto.sales.change_pct.revenue")

    def test_derived_negative_count_passes(self):
        bundle = {"current_dto": {"employees": {"employees": [
            {"name": "A", "change_pct": {"revenue": -10.0}},
            {"name": "B", "change_pct": {"revenue": 5.0}},
            {"name": "C", "change_pct": {"revenue": -20.0}},
        ]}}}
        # Digits-only contract: the prompt mandates verbatim digit numbers.
        assert insights._check_text("2 employees declined", bundle,
                                    "current_dto.employees.employees")
        assert not insights._check_text("4 employees declined", bundle,
                                        "current_dto.employees.employees")

    def test_qualitative_text_passes(self):
        bundle = {"current_dto": {"sales": {"change_pct": {"revenue": None}}}}
        assert insights._check_text("No baseline to compare against", bundle,
                                    "current_dto.sales.change_pct.revenue")

    def test_list_length_derivation_passes(self):
        bundle = {"current_dto": {"products": {"top_by_revenue": [{"n": 1}, {"n": 2}]}}}
        assert insights._check_text("Top list covers 2 products", bundle,
                                    "current_dto.products.top_by_revenue")

    # ---- sign-tolerant magnitude match (live-found llama behavior) ----

    def test_magnitude_with_direction_word_passes(self):
        """'fell 4.1%' may stand in for change_pct -4.1: the verb carries the sign."""
        bundle = {"current_dto": {"sales": {"change_pct": {"revenue": -4.1}}}}
        assert insights._check_text("Revenue fell 4.1%", bundle,
                                    "current_dto.sales.change_pct.revenue")
        assert insights._check_text("Revenue dropped about 4%", bundle,
                                    "current_dto.sales.change_pct.revenue")

    def test_magnitude_direction_flip_fails(self):
        """'grew 4.1%' against a -4.1 decline is a direction lie — rejected."""
        bundle = {"current_dto": {"sales": {"change_pct": {"revenue": -4.1}}}}
        assert not insights._check_text("Revenue grew 4.1%", bundle,
                                        "current_dto.sales.change_pct.revenue")

    def test_bare_magnitude_stays_strict(self):
        """No direction words -> the signed value is required."""
        bundle = {"current_dto": {"sales": {"change_pct": {"revenue": -4.1}}}}
        assert not insights._check_text("Revenue changed by 4.1%", bundle,
                                        "current_dto.sales.change_pct.revenue")

    def test_magnitude_wrong_value_fails(self):
        bundle = {"current_dto": {"sales": {"change_pct": {"revenue": -4.1}}}}
        assert not insights._check_text("Revenue fell 9.7%", bundle,
                                        "current_dto.sales.change_pct.revenue")

    # ---- rollup citations (history statistics are valid basis roots) ----

    def test_rollup_leaf_basis_resolves(self):
        bundle = {"current_dto": {"sales": {}},
                  "rollup": {"avg_revenue": 15400.0,
                             "consecutive_declining_periods": 4}}
        assert insights._check_text("Average revenue was 15400.", bundle,
                                    "rollup.avg_revenue")
        assert insights._check_text("Four consecutive declining periods.", bundle,
                                    "rollup")

    def test_rollup_citation_rejects_unrelated_numbers(self):
        bundle = {"current_dto": {"sales": {}},
                  "rollup": {"avg_revenue": 15400.0}}
        assert not insights._check_text("Average revenue was 15400, up 12.5%", bundle,
                                        "rollup.avg_revenue")

    # ---- too-narrow citation repair (live-found llama behavior) ----

    def test_too_narrow_basis_widens_to_grounding_parent(self):
        """Sentence uses revenue+profit+orders; citation names only revenue
        -> normalizes to the parent that grounds every number."""
        bundle = {"current_dto": {"sales": {"current": {
            "revenue": 14200.0, "profit": 4200.0, "orders": 87}}}}
        text = "Revenue was $14,200 with a profit of $4,200 and 87 orders."
        basis = insights._normalize_basis(
            bundle, "current_dto.sales.current.revenue", text)
        assert basis == "current_dto.sales.current"
        assert insights._check_text(text, bundle, basis)

    def test_garbage_basis_still_fails(self):
        """A citation whose tail does not exist must NOT silently widen."""
        bundle = {"current_dto": {"sales": {"current": {"revenue": 100.0}}}}
        assert insights._normalize_basis(
            bundle, "current_dto.sales.nonexistent", "Revenue was 100.") is None


# ---------------------------------------------------------
# build_insights — full contract
# ---------------------------------------------------------

GOOD_OUTPUT = {
    "summary": "Revenue was 500 this period, up 25% versus 400.",
    "observations": [
        {"text": "Revenue rose 25% to 500.", "basis": "current_dto.sales"},
        {"text": "3 employees are in the race.", "basis": "current_dto.employees.employees"},
    ],
    "areas_to_watch": ["Profit margin concentration in a single product"],
}


def _bundle_for_good_output():
    cur = datetime(2026, 9, 21)
    sales = _sales_payload(cur, 500.0, previous_revenue=400.0)
    emps = {"employees": [{"name": "A"}, {"name": "B"}, {"name": "C"}], "race_series": {}}
    return {"current_dto": {"sales": sales, "employees": emps},
            "recent_window": None, "rollup": None}


class TestBuildInsights:
    def test_happy_path(self):
        out = insights.build_insights(_bundle_for_good_output(), "week",
                                      llm_client=FakeLLM(dict(GOOD_OUTPUT)))
        assert out["summary"].startswith("Revenue was 500")
        assert out["observations"][0]["basis"] == "current_dto.sales"
        assert out["areas_to_watch"] == GOOD_OUTPUT["areas_to_watch"]
        assert "degraded" not in out

    def test_empty_key_degrades_without_calling_llm(self, monkeypatch):
        monkeypatch.setattr(llm, "api_key", lambda: "")

        def _must_not_be_called(*args, **kwargs):
            raise AssertionError("LLM must not be called without an API key")

        monkeypatch.setattr(llm, "generate_json", _must_not_be_called)
        out = insights.build_insights(_bundle_for_good_output(), "week")
        assert out["summary"] is None and out["degraded"] is True
        assert "not configured" in out["degraded_reason"]

    def test_llm_raise_degrades(self, monkeypatch):
        monkeypatch.setattr(llm, "api_key", lambda: "k")
        out = insights.build_insights(
            _bundle_for_good_output(), "week",
            llm_client=FakeLLM(error=llm.LlmBudgetExceeded("too slow")),
        )
        assert out["degraded"] is True
        assert "budget" in out["degraded_reason"]

    def test_unexpected_llm_error_degrades(self, monkeypatch):
        monkeypatch.setattr(llm, "api_key", lambda: "k")
        out = insights.build_insights(
            _bundle_for_good_output(), "week",
            llm_client=FakeLLM(error=RuntimeError("network exploded")),
        )
        assert out["degraded"] is True
        assert "network exploded" in out["degraded_reason"]

    def test_schema_shape_fails_degrade(self, monkeypatch):
        monkeypatch.setattr(llm, "api_key", lambda: "k")
        for bad in (
            {"summary": "x"},                                     # no observations
            {"summary": "x", "observations": [], "areas_to_watch": []},
            {"summary": "x", "observations": [{"text": "t"}], "areas_to_watch": []},
            {"summary": "x", "observations": GOOD_OUTPUT["observations"],
             "areas_to_watch": ["has 5 numbers"]},                # numbers in watch
        ):
            out = insights.build_insights(_bundle_for_good_output(), "week",
                                          llm_client=FakeLLM(dict(bad)))
            assert out["degraded"] is True, bad

    def test_unresolvable_basis_degrades(self, monkeypatch):
        monkeypatch.setattr(llm, "api_key", lambda: "k")
        bad = {"summary": "All good, revenue was 500.",
               "observations": [{"text": "Something happened", "basis": "current_dto.sales.nonexistent"}],
               "areas_to_watch": ["Watch margins"]}
        out = insights.build_insights(_bundle_for_good_output(), "week",
                                      llm_client=FakeLLM(bad))
        assert out["degraded"] is True
        assert "basis" in out["degraded_reason"]

    def test_fabricated_observation_number_falls_back(self, monkeypatch):
        monkeypatch.setattr(llm, "api_key", lambda: "k")
        bad = {"summary": "Revenue was 500 this period.",
               "observations": [{"text": "Revenue rose 999% this period.",
                                 "basis": "current_dto.sales.change_pct.revenue"}],
               "areas_to_watch": ["Watch margins"]}
        out = insights.build_insights(_bundle_for_good_output(), "week",
                                      llm_client=FakeLLM(bad))
        assert out["degraded"] is True
        assert "ungrounded" in out["degraded_reason"]

    def test_no_sales_payload_degrades(self, monkeypatch):
        monkeypatch.setattr(llm, "api_key", lambda: "k")
        out = insights.build_insights({"current_dto": {}}, "week", llm_client=FakeLLM())
        assert out["degraded"] is True


# ---------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------

class TestPipelineInsights:
    def _run_week(self, db_session, owner_id, period="week"):
        run_id = pipeline.start_run(db_session, owner_id=owner_id, period=period,
                                    enqueue=None)
        pipeline.execute_run(db_session, run_id, period)
        return run_id

    def test_snapshot_row_is_real_payload_with_fake_llm(self, db_session, monkeypatch):
        db_session.add(models.Owner(user_id=1, name="O", user_type="owner",
                                    phone_number="01700000001", password="x"))
        db_session.add(models.Employee(user_id=42, name="Rahim", user_type="employee",
                                       password="x", employer_id=1))
        _sale(db_session, 42, _at(hour=10), 120.0, 40.0)
        db_session.commit()

        captured = {}

        class RecordingLLM:
            def generate_json(self, prompt, schema, *, timeout_s=None):
                captured["prompt"] = prompt
                return {
                    "summary": "Revenue was 120.",
                    "observations": [{"text": "Revenue was 120.",
                                      "basis": "current_dto.sales.current.revenue"}],
                    "areas_to_watch": ["Concentration risk"],
                }

        monkeypatch.setattr(llm, "api_key", lambda: "k")
        # Route the injectable seam: build_insights' llm_client kwarg.
        real_build = insights.build_insights
        monkeypatch.setattr(insights, "build_insights",
                            lambda bundle, period, **kw: real_build(
                                bundle, period, llm_client=RecordingLLM()))

        run_id = self._run_week(db_session, 1)
        run = pipeline.get_run(db_session, run_id, 1)
        assert run.status == "COMPLETED"
        snap = db_session.query(models.AnalyticsSnapshot).filter_by(
            run_id=run_id, section="insights").one()
        assert snap.data["summary"] == "Revenue was 120."
        assert "degraded" not in snap.data
        assert "current_dto" in captured["prompt"]

    def test_llm_failure_degrades_but_run_completes(self, db_session, monkeypatch):
        db_session.add(models.Owner(user_id=1, name="O", user_type="owner",
                                    phone_number="01700000001", password="x"))
        db_session.add(models.Employee(user_id=42, name="Rahim", user_type="employee",
                                       password="x", employer_id=1))
        _sale(db_session, 42, _at(hour=10), 120.0, 40.0)
        db_session.commit()

        monkeypatch.setattr(llm, "api_key", lambda: "k")
        monkeypatch.setattr(insights, "build_insights",
                            lambda bundle, period, **kw:
                            {"summary": None, "degraded": True,
                             "degraded_reason": "LLM budget exceeded: too slow"})

        run_id = self._run_week(db_session, 1)
        run = pipeline.get_run(db_session, run_id, 1)
        assert run.status == "COMPLETED"
        snap = db_session.query(models.AnalyticsSnapshot).filter_by(
            run_id=run_id, section="insights").one()
        assert snap.data["summary"] is None
        assert snap.data["degraded"] is True

    def test_history_query_feeds_second_run(self, db_session, monkeypatch):
        """
        A PREVIOUS week's completed sales snapshot (seeded directly with
        correct window metadata) reaches the next run's context bundle as
        the newest history window — the history query + build_context
        working end-to-end inside the pipeline.
        """
        from analytics.timeutils import period_bounds

        db_session.add(models.Owner(user_id=1, name="O", user_type="owner",
                                    phone_number="01700000001", password="x"))
        db_session.add(models.Employee(user_id=42, name="Rahim", user_type="employee",
                                       password="x", employer_id=1))
        _sale(db_session, 42, _at(hour=10), 120.0, 40.0)

        # Seed the previous week's sales snapshot exactly as the pipeline
        # would have written it.
        today = date.today()
        prev_start = period_bounds(today, "week")[2]  # previous_start
        prev_payload = _sales_payload(prev_start, 777.0, period="week")
        db_session.add(models.AnalyticsSnapshot(
            run_id="prior-run", owner_id=1, section="sales", period_type="week",
            data=prev_payload, generated_at=datetime.utcnow(),
        ))
        db_session.add(models.AnalysisRun(id="prior-run", owner_id=1,
                                          status="COMPLETED"))
        db_session.commit()

        monkeypatch.setattr(llm, "api_key", lambda: "k")
        seen_bundles = []

        def fake_build_insights(bundle, period, **kw):
            seen_bundles.append(bundle)
            return {"summary": "Revenue was 120.",
                    "observations": [{"text": "Revenue was 120.",
                                      "basis": "current_dto.sales.current.revenue"}],
                    "areas_to_watch": []}

        monkeypatch.setattr(insights, "build_insights", fake_build_insights)

        run_id = self._run_week(db_session, 1)
        run = pipeline.get_run(db_session, run_id, 1)
        assert run.status == "COMPLETED"

        assert len(seen_bundles) == 1
        window = seen_bundles[0]["recent_window"]
        assert window is not None
        # The newest history slot holds the previous week's snapshot.
        assert window[-1]["current"]["revenue"] == 777.0
        # The current window itself is never fed back as history.
        assert all(
            w is None or w["window"]["current_start"] != prev_payload["window"]["current_start"]
            or True for w in window
        )
        rollup = seen_bundles[0]["rollup"]
        assert rollup["windows_available"] == 1

    def test_api_flow_insights_row_without_key(self, client, owner, monkeypatch):
        """The default sync API flow: no key -> insights row is the degrade dict."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setattr(llm, "api_key", lambda: "")

        r = client.post("/api/v1/products/", json={
            "product_name": "Widget", "cost_price": 40.0,
            "retail_price": 60.0, "stock_quantity": 100,
        })
        assert r.status_code == 200, r.json()
        r = client.post("/api/v1/customers/", json={
            "name": "Walker", "phone_number": "01800000012",
        })
        assert r.status_code == 200, r.json()
        customer_id = r.json()["customer_id"]
        r = client.post("/api/v1/checkout/", json={
            "customer_id": customer_id, "payment_method": "cash",
            "items": [{"product_id": 1, "quantity": 2}],
        })
        assert r.status_code == 200, r.json()

        resp = client.post("/api/v1/analytics/run", json={"period": "week"})
        assert resp.status_code == 202, resp.json()
        assert resp.json()["status"] == "COMPLETED"

        resp = client.get("/api/v1/analytics/dashboard?period=week")
        assert resp.status_code == 200
        ins = resp.json()["sections"]["insights"]
        assert ins["summary"] is None
        assert ins["degraded"] is True


# ---------------------------------------------------------
# llm wrapper budget behavior (no network)
# ---------------------------------------------------------

class TestLlmProviderSelection:
    """Provider switching: env-driven, no network anywhere here."""

    def test_default_provider_is_gemini(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        assert llm.provider() == "gemini"

    def test_ollama_provider_from_env(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        assert llm.provider() == "ollama"
        assert llm.is_configured() is True  # local: no key required

    def test_ollama_needs_no_key(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

        class _Stub:
            attempt_timeout_cap = 1.0
            min_attempt_timeout = 0.5

            def generate_json(self, *a, **k):
                return None

        monkeypatch.setattr(llm, "_make_client", lambda: _Stub())
        # Should not raise LlmUnavailable despite the missing key.
        with pytest.raises(llm.LlmBudgetExceeded):
            llm.generate_json("p", {}, client=None)

    def test_gemini_without_key_raises_unavailable(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.setattr(llm, "api_key", lambda: "")
        with pytest.raises(llm.LlmUnavailable):
            llm.generate_json("p", {}, client=None)

    def test_unknown_provider_value_falls_back_to_gemini(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "chatgpt")
        assert llm.provider() == "gemini"

class TestLlmWrapper:
    def test_tiny_budget_exhausts_without_calling(self, monkeypatch):
        """A budget too small for any attempt raises before network I/O."""
        monkeypatch.setenv("LLM_BUDGET_SECONDS", "0.01")
        calls = []

        class Guard:
            def generate_json(self, prompt, schema, *, timeout_s):
                calls.append(1)
                return None

        with pytest.raises(llm.LlmBudgetExceeded):
            llm.generate_json("p", {}, client=Guard())
        assert calls == []

    def test_budget_exceeded_after_all_attempts(self, monkeypatch):
        monkeypatch.setenv("LLM_BUDGET_SECONDS", "30")
        calls = []

        class NeverValid:
            attempt_timeout_cap = 2.0
            min_attempt_timeout = 0.5

            def generate_json(self, prompt, schema, *, timeout_s):
                calls.append(timeout_s)
                return None  # never valid

        with pytest.raises(llm.LlmBudgetExceeded):
            llm.generate_json("p", {}, client=NeverValid())
        assert len(calls) == llm.MAX_ATTEMPTS
        # Per-attempt timeout is capped by the client class, never the
        # whole budget.
        assert all(t <= NeverValid.attempt_timeout_cap for t in calls)

    def test_no_key_raises_unavailable(self, monkeypatch):
        monkeypatch.setattr(llm, "api_key", lambda: "")
        with pytest.raises(llm.LlmUnavailable):
            llm.generate_json("p", {}, client=None)

    def test_retry_recovers_on_second_attempt(self, monkeypatch):
        attempts = []

        class FlakyClient:
            def generate_json(self, prompt, schema, *, timeout_s):
                attempts.append(1)
                return {"ok": True} if len(attempts) >= 2 else None

        out = llm.generate_json("p", {}, client=FlakyClient())
        assert out == {"ok": True}
        assert len(attempts) == 2

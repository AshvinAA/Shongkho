"""
Part B conversational-analytics tests (docs/LLM_INTEGRATION.md §3, §6).

The LLM is an injectable dependency (llm.chat_decide is monkeypatched
with a scriptable fake) — no network, no key required:

  - range_buckets: resolution boundaries, 60-bucket ceiling, errors
  - tools: date/metric/limit validation, scope injection (only the
    store's own sales), name filter + unknown-name ValueError, math
  - agent loop: final-first, tool->final, ValueError corrective retry,
    loop-cap exhaustion, narration check (keeps ui_blocks), refusal
  - caps & config: daily cap 429, empty key 503 (via route contract)
  - routes: owner-only 403, envelope shape, history reload
  - window projection: roles + tool names only, never payloads
"""
import copy
import sys
import os
from datetime import date, datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models  # noqa: E402
from analytics import assistant, llm, timeutils, tools  # noqa: E402


# ---------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------
def _sale(db, employee_id, when_dt, revenue, profit, items=None):
    s = models.Sale(
        employee_id=employee_id, customer_id=None, payment_method="cash",
        total_revenue=revenue, total_profit=profit,
        date=when_dt.date(), time=when_dt.time(),
    )
    for product_id, qty, rp, cp in (items or []):
        s.items.append(models.SaleItem(
            product_id=product_id, quantity=qty,
            retail_price_at_sale=rp, cost_price_at_sale=cp,
        ))
    db.add(s)
    return s


def _seed_store(db, with_owner=True):
    """Owner + two employees + one product + sales across a few days.
    with_owner=False when the API fixture already created owner #1."""
    if with_owner:
        db.add(models.Owner(user_id=1, name="The Owner", user_type="owner",
                            phone_number="01700000001", password="x"))
    db.add(models.Employee(user_id=2, name="Rahim", user_type="employee",
                           password="x", employer_id=1))
    db.add(models.Employee(user_id=3, name="Karim", user_type="employee",
                           password="x", employer_id=1))
    db.add(models.Product(product_id=1, product_name="Mustard Oil 1L",
                          cost_price=35.0, retail_price=50.0, stock_quantity=100))
    now = datetime.now()
    _sale(db, 2, now.replace(hour=10), 300.0, 90.0, [(1, 4, 50.0, 35.0)])
    _sale(db, 3, now.replace(hour=11), 200.0, 60.0, [(1, 2, 50.0, 35.0)])
    _sale(db, 2, now - timedelta(days=3), 150.0, 45.0, [(1, 3, 50.0, 35.0)])
    db.commit()


class ScriptedChat:
    """Scriptable stand-in for llm.chat_decide."""

    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.contexts = []

    def __call__(self, context, tools_summary, **kwargs):
        # Deep-copy: handle_message mutates its context dict in place
        # (adds tool_results), which would otherwise rewrite history.
        self.contexts.append(copy.deepcopy(context))
        if len(self.decisions) == 0:
            raise llm.ChatDecisionError("script exhausted")
        return self.decisions.pop(0)


@pytest.fixture()
def configured(monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda: True)


# ---------------------------------------------------------
# timeutils.range_buckets
# ---------------------------------------------------------
class TestRangeBuckets:
    def test_short_range_is_daily(self):
        s, e, keys, labels = timeutils.range_buckets(date(2026, 9, 1),
                                                     date(2026, 9, 7))
        assert len(keys) == 7
        assert keys[0] == date(2026, 9, 1)
        assert "Sep 01" in labels[keys[0]]

    def test_31_day_boundary_is_daily(self):
        _, _, keys, _ = timeutils.range_buckets(date(2026, 8, 1), date(2026, 8, 31))
        assert len(keys) == 31  # daily

    def test_32_days_goes_weekly(self):
        _, _, keys, _ = timeutils.range_buckets(date(2026, 8, 1), date(2026, 9, 1))
        assert all(isinstance(k, date) for k in keys)
        assert (keys[1] - keys[0]).days == 7

    def test_180_day_boundary_is_weekly(self):
        _, _, keys, _ = timeutils.range_buckets(date(2026, 3, 5), date(2026, 8, 31))
        assert (keys[1] - keys[0]).days == 7

    def test_long_range_degrades_to_monthly(self):
        _, _, keys, _ = timeutils.range_buckets(date(2025, 1, 1), date(2026, 9, 1))
        assert keys[0] == (2025, 1)
        assert (2026, 9) in keys

    def test_60_bucket_ceiling_enforced(self):
        # >60 monthly buckets (6+ years) must raise, not silently truncate.
        with pytest.raises(ValueError, match="60-bucket"):
            timeutils.range_buckets(date(2019, 1, 1), date(2026, 9, 1))

    def test_inverted_range_raises(self):
        with pytest.raises(ValueError):
            timeutils.range_buckets(date(2026, 9, 10), date(2026, 9, 1))

    def test_missing_range_raises(self):
        with pytest.raises(ValueError):
            timeutils.range_buckets(None, date(2026, 9, 1))


# ---------------------------------------------------------
# Tools
# ---------------------------------------------------------
class TestTools:
    def test_sales_metrics_math_and_scope(self, db_session):
        _seed_store(db_session)
        today = date.today().isoformat()
        out = tools.execute(db_session, 1, "get_sales_metrics",
                            {"start": today, "end": today})
        # Only TODAY's sales: 300 + 200 (the 3-days-ago sale is excluded).
        assert out["totals"]["revenue"] == 500.0
        assert out["totals"]["orders"] == 2
        assert len(out["series"]) == 1

    def test_other_store_sales_are_invisible(self, db_session):
        _seed_store(db_session)
        db_session.add(models.Owner(user_id=99, name="Rival", user_type="owner",
                                    phone_number="01999999999", password="x"))
        db_session.add(models.Employee(user_id=98, name="Mole", user_type="employee",
                                       password="x", employer_id=99))
        _sale(db_session, 98, datetime.now().replace(hour=9), 999.0, 1.0)
        db_session.commit()
        today = date.today().isoformat()
        out = tools.execute(db_session, 1, "get_sales_metrics",
                            {"start": today, "end": today})
        assert out["totals"]["revenue"] == 500.0  # rival's 999 excluded

    def test_bad_date_raises_valueerror(self, db_session):
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            tools.execute(db_session, 1, "get_sales_metrics",
                          {"start": "09/2026", "end": "2026-09-25"})

    def test_unknown_tool_raises(self, db_session):
        with pytest.raises(ValueError, match="unknown tool"):
            tools.execute(db_session, 1, "delete_everything", {})

    def test_store_id_arg_is_stripped(self, db_session):
        """The LLM may try to pass store_id — it must be ignored, not error."""
        _seed_store(db_session)
        today = date.today().isoformat()
        out = tools.execute(db_session, 1, "get_sales_metrics",
                            {"start": today, "end": today, "store_id": 99})
        assert out["totals"]["revenue"] == 500.0  # scoped to owner 1

    def test_employee_name_filter(self, db_session):
        _seed_store(db_session)
        today = date.today().isoformat()
        out = tools.execute(db_session, 1, "get_employee_performance",
                            {"start": today, "end": today,
                             "employee_name": "rahim"})
        assert len(out["employees"]) == 1
        assert out["employees"][0]["name"] == "Rahim"
        assert out["employees"][0]["revenue"] == 300.0

    def test_unknown_employee_name_raises(self, db_session):
        _seed_store(db_session)
        today = date.today().isoformat()
        with pytest.raises(ValueError, match="no employee matching"):
            tools.execute(db_session, 1, "get_employee_performance",
                          {"start": today, "end": today,
                           "employee_name": "Nobody"})

    def test_top_products_metric_and_limit(self, db_session):
        _seed_store(db_session)
        today = date.today().isoformat()
        out = tools.execute(db_session, 1, "get_top_products",
                            {"start": today, "end": today,
                             "metric": "profit", "limit": 1})
        assert out["products"][0]["name"] == "Mustard Oil 1L"
        # Today: Rahim 4 units + Karim 2 units = 6 units * (50-35) = 90 profit
        assert out["products"][0]["profit"] == 90.0

    def test_top_products_bad_metric_raises(self, db_session):
        _seed_store(db_session)
        today = date.today().isoformat()
        with pytest.raises(ValueError, match="metric"):
            tools.execute(db_session, 1, "get_top_products",
                          {"start": today, "end": today, "metric": "discount"})

    def test_top_products_limit_cap(self, db_session):
        _seed_store(db_session)
        today = date.today().isoformat()
        with pytest.raises(ValueError, match="between 1 and 10"):
            tools.execute(db_session, 1, "get_top_products",
                          {"start": today, "end": today, "limit": 99})


# ---------------------------------------------------------
# The agent loop
# ---------------------------------------------------------
class TestAgentLoop:
    def test_final_first_no_tools(self, db_session, configured, monkeypatch):
        _seed_store(db_session)
        script = ScriptedChat([
            {"action": "final", "message": "Steady day — keep it up!"}])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(db_session, 1, "How's today?")
        assert out["message"] == "Steady day — keep it up!"
        assert out["meta"]["shipped_grounded"] is True
        # Both turns persisted.
        rows = db_session.query(models.AssistantMessage).order_by(
            models.AssistantMessage.id).all()
        assert [r.role for r in rows] == ["user", "assistant"]

    def test_tool_then_final_text_only(self, db_session, configured,
                                       monkeypatch):
        _seed_store(db_session)
        today = date.today().isoformat()
        script = ScriptedChat([
            {"action": "tool", "tool": "get_sales_metrics",
             "args": {"start": today, "end": today}},
            {"action": "final",
             "message": "Revenue was 500.0 today across 2 orders."},
        ])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(db_session, 1, "How's today?")
        # Text-only product: no ui_blocks anywhere in the envelope.
        assert "ui_blocks" not in out
        assert out["meta"]["shipped_grounded"] is True
        assert out["meta"]["grounded_first_pass"] is True
        # tool_calls persisted as names + args only.
        assert out["tool_calls"] == [
            {"tool": "get_sales_metrics", "args": {"start": today, "end": today}}]
        row = db_session.query(models.AssistantMessage).filter_by(
            role="assistant").one()
        assert row.ui_blocks is None

    def test_valueerror_gives_one_counted_retry(self, db_session, configured,
                                                monkeypatch):
        _seed_store(db_session)
        today = date.today().isoformat()
        script = ScriptedChat([
            {"action": "tool", "tool": "get_top_products",
             "args": {"start": today, "end": today, "metric": "discount"}},
            {"action": "tool", "tool": "get_top_products",
             "args": {"start": today, "end": today, "metric": "profit"}},
            {"action": "final", "message": "Mustard Oil leads with 60.0 profit."},
        ])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(db_session, 1, "Top product by profit?")
        # The bad call consumed a round; the retry succeeded (text-only:
        # verify via the tool_calls audit + telemetry).
        assert out["tool_calls"][-1]["tool"] == "get_top_products"
        assert out["tool_calls"][-1]["args"]["metric"] == "profit"
        assert out["meta"]["tool_calls_ok"] == 1
        # Round 2 context saw exactly the ERROR observation from round 1
        # (self-correction) — no result yet.
        assert len(script.contexts[1]["tool_results"]) == 1
        assert "metric" in script.contexts[1]["tool_results"][0]["error"]
        # Round 3 context saw the error AND the successful result.
        assert len(script.contexts[2]["tool_results"]) == 2
        assert "result" in script.contexts[2]["tool_results"][1]

    def test_loop_cap_exhaustion_falls_back(self, db_session, configured,
                                            monkeypatch):
        _seed_store(db_session)
        today = date.today().isoformat()
        # Every round asks for a tool; never a final — cap must stop it.
        script = ScriptedChat([
            {"action": "tool", "tool": "get_sales_metrics",
             "args": {"start": today, "end": today}},
        ] * (assistant.TOOL_CALL_CAP + 2))
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(db_session, 1, "trend?")
        assert out["message"] == assistant.FALLBACK_MESSAGE
        assert out["meta"]["fallback_reason"] == "cap_exhausted"

    def test_narration_double_fail_synthesizes_from_data(self, db_session,
                                                         configured,
                                                         monkeypatch):
        _seed_store(db_session)
        today = date.today().isoformat()
        # Two consecutive fabricated narrations: the first earns one
        # self-correction round, the second hits the post-loop gate —
        # but with a right-domain payload in hand, the deterministic
        # synthesizer ships a correct answer built from the tool data
        # instead of an apology.
        script = ScriptedChat([
            {"action": "tool", "tool": "get_sales_metrics",
             "args": {"start": today, "end": today}},
            {"action": "final",
             "message": "Revenue was 999999.0 today, a record!"},  # fabricated
            {"action": "final",
             "message": "Revenue was 12345.0, unbelievable!"},    # fabricated again
        ])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(db_session, 1, "How's today?")
        # Seeded today: 300 + 200 revenue, 90 + 60 profit, 2 orders.
        assert out["message"] == (
            "Your store took 500.0 in revenue across 2 orders "
            "(profit 150.0) today.")
        assert out["meta"]["fallback_reason"] == "synthesized"
        assert out["meta"]["shipped_grounded"] is True

    def test_narration_double_fail_no_synth_falls_back(self, db_session,
                                                       configured,
                                                       monkeypatch):
        """Unclassifiable question (domain None) + a payload the
        synthesizer has no template for (top products without a product
        question): the honest narration fallback still ships."""
        _seed_store(db_session)
        today = date.today().isoformat()
        script = ScriptedChat([
            {"action": "tool", "tool": "get_top_products",
             "args": {"start": today, "end": today, "metric": "profit"}},
            {"action": "final",
             "message": "Revenue was 999999.0 today, a record!"},
            {"action": "final",
             "message": "Revenue was 12345.0, unbelievable!"},
        ])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(db_session, 1, "zzz")
        assert out["message"] == assistant.NARRATION_FALLBACK
        assert out["meta"]["fallback_reason"] == "narration_double_fail"
        assert out["meta"]["shipped_grounded"] is True

    def test_synth_employee_answer(self, db_session, configured,
                                   monkeypatch):
        """Employee question + double narration fail: the synthesizer
        builds the ranking answer from the employee payload."""
        _seed_store(db_session)
        today = date.today().isoformat()
        script = ScriptedChat([
            {"action": "tool", "tool": "get_employee_performance",
             "args": {"start": today, "end": today}},
            {"action": "final",
             "message": "Rahim sold 999999.0 today!"},
            {"action": "final",
             "message": "Karim sold 12345.0!"},
        ])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(db_session, 1,
                                       "Who is the worst performing employee?")
        # Seeded today: Rahim 300/90, Karim 200/60.
        assert "Rahim leads your staff with 300.0 in revenue" in out["message"]
        assert "Karim trails at 200.0" in out["message"]
        assert out["meta"]["fallback_reason"] == "synthesized"
        assert out["meta"]["shipped_grounded"] is True

    def test_vague_employee_answer_specificity_retry(self, db_session,
                                                     configured,
                                                     monkeypatch):
        """Number-free hedge that names nobody (live failure: a lay-off
        question answered with 'the trailing seller') passes the reality
        and relevance gates but fails the SPECIFICITY gate — one named
        corrective, then the committed answer ships."""
        _seed_store(db_session)
        today = date.today().isoformat()
        script = ScriptedChat([
            {"action": "tool", "tool": "get_employee_performance",
             "args": {"start": today, "end": today}},
            {"action": "final",
             "message": "The trailing seller shows a significant gap — "
                        "watch the trend before acting."},
            {"action": "final",
             "message": "Karim trails today — coach, don't cut."},
        ])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(
            db_session, 1, "Should I lay off my weakest seller?")
        assert out["message"] == "Karim trails today — coach, don't cut."
        assert out["meta"]["narration_retried"] is True
        assert out["meta"]["specificity_retried"] is True
        assert out["meta"]["grounded_first_pass"] is False
        assert out["meta"]["shipped_grounded"] is True

    def test_vague_answer_double_fail_synthesizes(self, db_session, configured,
                                                  monkeypatch):
        """Two vague replies on a classified employee question: the
        second earns no retry (same cap economics as a narration
        double-fail) and the deterministic ranking template ships."""
        _seed_store(db_session)
        today = date.today().isoformat()
        script = ScriptedChat([
            {"action": "tool", "tool": "get_employee_performance",
             "args": {"start": today, "end": today}},
            {"action": "final",
             "message": "The gap is significant — watch it before it "
                        "becomes a trend."},
            {"action": "final",
             "message": "Someone is trailing the team — coach them."},
        ])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(
            db_session, 1, "Who is the worst performing employee?")
        # Seeded today: Rahim 300/90 leads, Karim 200/60 trails.
        assert "Rahim leads your staff with 300.0 in revenue" in out["message"]
        assert out["meta"]["fallback_reason"] == "synthesized"
        assert out["meta"]["specificity_retried"] is True
        assert out["meta"]["shipped_grounded"] is True

    def test_example_copied_name_is_dropped_and_fetch_rescues(self, db_session,
                                                              configured,
                                                              monkeypatch):
        """Live turn 34+36: the model copies an example NAME into the
        employee fetch ("Rahim"), narrowing the payload to one person.
        The sanitizer drops the never-mentioned name; the refused first
        decision earns the always-on refuse-rescue fetch; the whole-
        staff payload answers the question."""
        _seed_store(db_session)
        script = ScriptedChat([
            {"action": "refuse", "message": "I can't answer that."},
            {"action": "final", "message": "ok"},
        ])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(
            db_session, 1, "Which employee is performing the worst?")
        # employee_name dropped ("rahim" appears nowhere), rescue fired.
        assert out["tool_calls"][0]["args"] == {
            "start": date.today().isoformat(), "end": date.today().isoformat()}
        assert out["meta"]["auto_fetch"] is True

    def test_worst_performer_question_gets_full_staff_fetch(self, db_session,
                                                            configured,
                                                            monkeypatch):
        """Live turn 36 regression: worst-performer questions must fetch
        the WHOLE staff. The model scoped the fetch to an example-copied
        name; the sanitizer widens it back."""
        _seed_store(db_session)
        today = date.today().isoformat()
        script = ScriptedChat([
            {"action": "tool", "tool": "get_employee_performance",
             "args": {"start": today, "end": today,
                      "employee_name": "Karim"}},
            {"action": "final", "message": "Karim trails — coach them."},
        ])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(
            db_session, 1, "Which employee is performing the worst?")
        args = out["tool_calls"][0]["args"]
        # "Karim" appears nowhere in the question -> dropped -> the
        # fetch covers the whole staff.
        assert "employee_name" not in args
        assert out["meta"]["shipped_grounded"] is True

    def test_placeholder_dates_repaired_not_refused(self, db_session,
                                                    configured,
                                                    monkeypatch):
        """Live turn 34: the model copies the prompt's "<today>"/"<week
        ago>" placeholders into tool args. Repaired deterministically —
        no ValueError round burned teaching date formats."""
        _seed_store(db_session)
        script = ScriptedChat([
            {"action": "tool", "tool": "get_sales_metrics",
             "args": {"start": "<today>", "end": "<today>"}},
            {"action": "final", "message": "Revenue was 500.0 today."},
        ])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(db_session, 1, "How's today?")
        assert out["tool_calls"][0]["args"]["start"] == date.today().isoformat()
        assert out["meta"]["tool_errors"] == []
        assert out["meta"]["shipped_grounded"] is True

    def test_no_fetch_on_classified_question_is_rescued(self, db_session,
                                                         configured,
                                                         monkeypatch):
        """Live turn 38: a classified data question shipped a final with
        NO fetch — gates passed vacuously (no data = nothing false).
        The fetch-first floor catches it."""
        _seed_store(db_session)
        script = ScriptedChat([
            {"action": "final", "message": "Push more of the best-selling "
                                           "product, the"},
        ])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(
            db_session, 1, "Which product should we market more?")
        assert out["tool_calls"][0]["tool"] == "get_top_products"
        assert "Mustard Oil 1L is your top product" in out["message"]
        assert out["meta"]["fallback_reason"] == "synthesized"
        assert out["meta"]["auto_fetch"] is True
        assert out["meta"]["shipped_grounded"] is True

    def test_single_lane_synth_is_not_leads_and_trails(self, db_session,
                                                       configured,
                                                       monkeypatch):
        """Live turn 36: a one-person payload made the ranking template
        say "X leads … X trails". A scoped (but user-named) fetch is
        legal, so the template must answer honestly instead."""
        _seed_store(db_session)
        today = date.today().isoformat()
        script = ScriptedChat([
            {"action": "tool", "tool": "get_employee_performance",
             "args": {"start": today, "end": today,
                      "employee_name": "Karim"}},
            {"action": "final",
             "message": "The gap is significant — watch it before it "
                        "becomes a trend."},
            {"action": "final",
             "message": "Someone is trailing the team — coach them."},
        ])
        monkeypatch.setattr(llm, "chat_decide", script)
        # "Karim" IS in the question: the scoped fetch is kept, giving
        # a genuine single-lane payload.
        out = assistant.handle_message(
            db_session, 1, "Should I let Karim go?")
        msg = out["message"]
        assert "is the only member of your staff with sales" in msg
        assert "trails at" not in msg
        assert out["meta"]["fallback_reason"] == "synthesized"
        assert out["meta"]["shipped_grounded"] is True

    def test_domain_classifier_intent_phrasings(self, db_session):
        """Advice-intent phrasings carry no explicit employee noun —
        the intent word IS the signal (live gap Claude-flagged)."""
        _seed_store(db_session)
        db_session.commit()
        assert assistant._question_domain(
            db_session, 1, "Should I lay off my weakest seller?") == "employee"
        assert assistant._question_domain(
            db_session, 1, "Anyone struggling this week?") == "employee"
        assert assistant._question_domain(
            db_session, 1, "Should we let someone go?") == "employee"
        assert assistant._question_domain(
            db_session, 1, "Is the team doing okay?") == "employee"
        # Product override still wins over employee hints.
        assert assistant._question_domain(
            db_session, 1, "Which product is our bestseller?") == "product"

    def test_narration_self_correction_recovers(self, db_session, configured,
                                                monkeypatch):
        """Bad narration (no tool called) -> error observation -> the model
        fetches data and answers grounded, all inside the cap."""
        _seed_store(db_session)
        today = date.today().isoformat()
        script = ScriptedChat([
            {"action": "final", "message": "You made 500.0 today!"},  # no data
            {"action": "tool", "tool": "get_sales_metrics",
             "args": {"start": today, "end": today}},
            {"action": "final", "message": "Revenue was 500.0 today across 2 orders."},
        ])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(db_session, 1, "How's today?")
        # The corrected answer ships.
        assert out["message"] == "Revenue was 500.0 today across 2 orders."
        assert out["meta"]["narration_retried"] is True
        assert out["meta"]["shipped_grounded"] is True

    def test_narration_with_no_data_falls_back(self, db_session, configured,
                                               monkeypatch):
        _seed_store(db_session)
        script = ScriptedChat([
            {"action": "final", "message": "You made 500.0 today."}])  # no tools
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(db_session, 1, "How's today?")
        assert out["message"] == assistant.FALLBACK_MESSAGE
        assert out["meta"]["shipped_grounded"] is True  # fallback is clean

    def test_refusal_persisted_verbatim(self, db_session, configured,
                                        monkeypatch):
        _seed_store(db_session)
        script = ScriptedChat([
            {"action": "refuse",
             "message": "I can't answer that from store data."}])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(db_session, 1, "Who will win the world cup?")
        assert out["message"] == "I can't answer that from store data."
        row = db_session.query(models.AssistantMessage).filter_by(
            role="assistant").one()
        assert row.message == "I can't answer that from store data."

    def test_decision_error_falls_back(self, db_session, configured,
                                       monkeypatch):
        _seed_store(db_session)

        def boom(context, tools_summary, **kw):
            raise llm.ChatDecisionError("provider down")

        monkeypatch.setattr(llm, "chat_decide", boom)
        out = assistant.handle_message(db_session, 1, "hello")
        assert out["message"] == assistant.FALLBACK_MESSAGE

    def test_daily_cap_reached(self, db_session, configured, monkeypatch):
        _seed_store(db_session)
        for _ in range(assistant.DAILY_CAP):
            assistant.persist_turn(db_session, 1, "assistant", "earlier reply")
        with pytest.raises(assistant.DailyCapReached):
            assistant.handle_message(db_session, 1, "hello")

    def test_not_configured_raises(self, db_session, monkeypatch):
        monkeypatch.setattr(llm, "is_configured", lambda: False)
        with pytest.raises(assistant.AssistantUnavailable):
            assistant.handle_message(db_session, 1, "hello")

    def test_window_projection_carries_names_not_payloads(self, db_session,
                                                          configured,
                                                          monkeypatch):
        _seed_store(db_session)
        today = date.today().isoformat()
        # An earlier turn WITH tool calls must appear name-only later.
        db_session.add(models.AssistantMessage(
            owner_id=1, role="assistant", message="Earlier answer",
            tool_calls=[{"tool": "get_sales_metrics", "args": {}}],
        ))
        db_session.commit()
        script = ScriptedChat([
            {"action": "final", "message": "ok"}])
        monkeypatch.setattr(llm, "chat_decide", script)
        assistant.handle_message(db_session, 1, "and now?")
        convo = script.contexts[0]["conversation"]
        assert all("tool_results" not in turn for turn in convo)
        assert convo[0]["tool_names"] == ["get_sales_metrics"]
        assert convo[-1]["role"] == "user"


# ---------------------------------------------------------
# Route contract
# ---------------------------------------------------------
class TestChatRoutes:
    def test_employee_gets_403(self, client, employee):
        r = client.post("/api/v1/analytics/chat", json={"message": "hi"})
        assert r.status_code == 403

    def test_anonymous_gets_401(self, client):
        r = client.post("/api/v1/analytics/chat", json={"message": "hi"})
        assert r.status_code == 401

    def test_empty_key_503(self, client, owner, monkeypatch):
        monkeypatch.setattr(llm, "is_configured", lambda: False)
        r = client.post("/api/v1/analytics/chat", json={"message": "hi"})
        assert r.status_code == 503
        assert "not configured" in r.json()["detail"]

    def test_daily_cap_429(self, client, owner, monkeypatch):
        monkeypatch.setattr(llm, "is_configured", lambda: True)
        # Cap counter reached.
        monkeypatch.setattr(assistant, "messages_today",
                            lambda db, owner_id: assistant.DAILY_CAP)
        r = client.post("/api/v1/analytics/chat", json={"message": "hi"})
        assert r.status_code == 429
        assert str(assistant.DAILY_CAP) in r.json()["detail"]

    def test_happy_path_envelope(self, client, owner, monkeypatch):
        # The route runs on the app's overridden get_db — grab the same
        # session so the seeded store is what the route queries. The API
        # `owner` fixture already created owner #1, so seed only the
        # store data under it.
        import database
        from main import app
        db = next(app.dependency_overrides[database.get_db]())
        try:
            _seed_store(db, with_owner=False)
            db.commit()
        finally:
            db.close()
        today = date.today().isoformat()
        script = ScriptedChat([
            {"action": "tool", "tool": "get_sales_metrics",
             "args": {"start": today, "end": today}},
            {"action": "final", "message": "Revenue was 500.0 today."},
        ])
        monkeypatch.setattr(llm, "chat_decide", script)
        monkeypatch.setattr(llm, "is_configured", lambda: True)
        r = client.post("/api/v1/analytics/chat",
                        json={"message": "How's today?"})
        assert r.status_code == 200, r.json()
        body = r.json()
        assert body["message"] == "Revenue was 500.0 today."
        assert "ui_blocks" not in body
        assert body["meta"]["shipped_grounded"] is True
        # History endpoint returns the persisted turns (text-only).
        r = client.get("/api/v1/analytics/chat/history")
        assert r.status_code == 200
        messages = r.json()["messages"]
        roles = [m["role"] for m in messages]
        assert roles == ["user", "assistant"]
        assert all("ui_blocks" not in m for m in messages)

    def test_validation_422_on_empty_message(self, client, owner,
                                             monkeypatch):
        monkeypatch.setattr(llm, "is_configured", lambda: True)
        r = client.post("/api/v1/analytics/chat", json={"message": ""})
        assert r.status_code == 422

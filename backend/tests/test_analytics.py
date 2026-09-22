"""
Analytics pipeline tests (Track A, stage 1 — no LLM).

Covers:
  - Pure aggregators: window splitting, bucket series, deltas, rankings
  - Run lifecycle: lock (409), failure release, snapshots in one tx
  - API: owner-only gating, 202/409/404, dashboard read path

Isolation mirrors conftest.py: fresh SQLite file per test. The Celery
chord is never contacted — the run-executor dependency is overridden
with a synchronous executor (the same seam production replaces with
enqueue_run).
"""
import sys
import os
from datetime import date, datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models  # noqa: E402
from analytics import aggregators, pipeline, timeutils  # noqa: E402

# ---------------------------------------------------------
# Shared helper: insert a Sale with exact timestamp + items
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
# Time windows
# ---------------------------------------------------------


class TestTimeWindows:
    def test_day_bounds(self):
        cur_s, cur_e, prev_s, prev_e = timeutils.period_bounds(date(2026, 9, 23), "day")
        assert cur_s == datetime(2026, 9, 23, 0, 0)
        assert cur_e == datetime(2026, 9, 24, 0, 0)
        assert prev_s == datetime(2026, 9, 22, 0, 0)
        assert prev_e == datetime(2026, 9, 23, 0, 0)

    def test_week_is_monday_anchored(self):
        # 2026-09-23 is a Wednesday -> week starts Monday the 21st.
        cur_s, cur_e, _, _ = timeutils.period_bounds(date(2026, 9, 23), "week")
        assert cur_s == datetime(2026, 9, 21, 0, 0)
        assert cur_e == datetime(2026, 9, 28, 0, 0)

    def test_month_bounds_cross_year(self):
        cur_s, cur_e, prev_s, _ = timeutils.period_bounds(date(2026, 1, 15), "month")
        assert cur_s == datetime(2026, 1, 1, 0, 0)
        assert cur_e == datetime(2026, 2, 1, 0, 0)
        assert prev_s == datetime(2025, 12, 1, 0, 0)

    def test_unknown_period_raises(self):
        with pytest.raises(ValueError):
            timeutils.period_bounds(date(2026, 9, 23), "century")


# ---------------------------------------------------------
# Pure aggregators
# ---------------------------------------------------------


class TestAggregateSales:
    def test_windows_and_delta(self, db_session):
        _sale(db_session, 1, _at(hour=10), 100.0, 30.0)             # today
        _sale(db_session, 1, _at(hour=18, days_ago=1), 50.0, 10.0)  # yesterday
        db_session.commit()

        payload = aggregators.aggregate_sales(
            db_session.query(models.Sale).all(), "day", date.today()
        )
        assert payload["current"]["revenue"] == 100.0
        assert payload["previous"]["revenue"] == 50.0
        assert payload["change_pct"]["revenue"] == 100.0
        # Day period -> 24 hourly buckets, zeros included (continuous axis).
        assert len(payload["series"]) == 24
        hour_10 = next(b for b in payload["series"] if b["key"] == "10")
        assert hour_10["revenue"] == 100.0
        assert hour_10["orders"] == 1

    def test_zero_baseline_delta_is_none(self, db_session):
        payload = aggregators.aggregate_sales([], "week", date.today())
        assert payload["current"]["revenue"] == 0.0
        assert payload["change_pct"]["revenue"] is None

    def test_best_hours_excludes_empty_buckets(self, db_session):
        _sale(db_session, 1, _at(hour=9), 40.0, 10.0)
        db_session.commit()
        payload = aggregators.aggregate_sales(
            db_session.query(models.Sale).all(), "day", date.today()
        )
        assert len(payload["best"]["by_revenue"]) == 1
        assert payload["best"]["by_revenue"][0]["label"].startswith("09:00")


class TestAggregateEmployees:
    def test_race_lanes_and_deltas(self, db_session):
        _sale(db_session, 1, _at(hour=11), 200.0, 60.0)                 # today
        _sale(db_session, 1, _at(hour=11, days_ago=1), 100.0, 30.0)     # yesterday
        _sale(db_session, 2, _at(hour=12, days_ago=1), 80.0, 20.0)      # yesterday
        db_session.commit()

        participants = [
            models.Employee(user_id=1, name="Rahim", user_type="employee"),
            models.Employee(user_id=2, name="Karim", user_type="employee"),
        ]
        payload = aggregators.aggregate_employees(
            db_session.query(models.Sale).all(), participants, "day", date.today()
        )
        # Sorted by revenue descending.
        assert [lane["employee_id"] for lane in payload["employees"]] == [1, 2]
        top = payload["employees"][0]
        assert top["name"] == "Rahim"
        assert top["revenue"] == 200.0
        assert top["change_pct"]["revenue"] == 100.0
        # Emp 2 sold nothing today: still a lane, shown as a -100% decline
        # against their 80 from yesterday — the race should surface that.
        assert payload["employees"][1]["revenue"] == 0.0
        assert payload["employees"][1]["change_pct"]["revenue"] == -100.0

    def test_detached_sales_are_skipped(self, db_session):
        _sale(db_session, None, _at(hour=10), 90.0, 20.0)
        db_session.commit()
        payload = aggregators.aggregate_employees(
            db_session.query(models.Sale).all(), [], "day", date.today()
        )
        assert payload["employees"] == []


class TestAggregateProducts:
    def test_rankings_and_unit_deltas(self, db_session):
        _sale(db_session, 1, _at(hour=10), 0, 0, items=[(1, 5, 60.0, 40.0)])
        _sale(db_session, 1, _at(hour=10, days_ago=1), 0, 0, items=[(1, 10, 60.0, 40.0)])
        _sale(db_session, 1, _at(hour=10, days_ago=1), 0, 0, items=[(2, 3, 25.0, 10.0)])
        db_session.commit()

        sales = db_session.query(models.Sale).all()
        names = {1: "Widget", 2: "Gadget"}
        payload = aggregators.aggregate_products(sales, names, "day", date.today())

        top = payload["top_by_revenue"]
        assert top[0]["name"] == "Widget"
        assert top[0]["units"] == 5
        assert top[0]["revenue"] == 300.0
        assert top[0]["profit"] == 100.0
        assert top[0]["margin_pct"] == pytest.approx(33.3)
        assert top[0]["units_change_pct"] == -50.0
        # Product 2 sold nothing this period -> absent from today's ranking.
        assert all(row["product_id"] != 2 for row in top)

    def test_deleted_product_name_fallback(self, db_session):
        _sale(db_session, 1, _at(hour=10), 0, 0, items=[(77, 1, 10.0, 5.0)])
        db_session.commit()
        payload = aggregators.aggregate_products(
            db_session.query(models.Sale).all(), {}, "day", date.today()
        )
        assert payload["top_by_revenue"][0]["name"] == "Product #77"

    def test_pruned_to_top_n(self, db_session):
        for pid in range(1, 16):  # 15 distinct products, today
            _sale(db_session, 1, _at(hour=10), 0, 0, items=[(pid, 1, float(pid), 0.0)])
        db_session.commit()
        payload = aggregators.aggregate_products(
            db_session.query(models.Sale).all(), {}, "day", date.today()
        )
        assert len(payload["top_by_revenue"]) == aggregators.TOP_N


# ---------------------------------------------------------
# Run lifecycle (pipeline called directly — no Celery)
# ---------------------------------------------------------


class TestRunLifecycle:
    def test_start_run_creates_queued_row_and_enqueues(self, db_session, owner):
        calls = []
        run_id = pipeline.start_run(
            db_session, owner_id=owner["user_id"], period="week",
            enqueue=lambda rid, oid, p: calls.append((rid, oid, p)),
        )
        assert pipeline.get_run(db_session, run_id, owner["user_id"]).status == "QUEUED"
        assert calls == [(run_id, owner["user_id"], "week")]

    def test_second_run_conflicts_while_active(self, db_session, owner):
        pipeline.start_run(db_session, owner_id=owner["user_id"], period="week", enqueue=None)
        with pytest.raises(pipeline.RunConflictError):
            pipeline.start_run(db_session, owner_id=owner["user_id"], period="week", enqueue=None)

    def test_failed_run_releases_lock(self, db_session, owner):
        run_id = pipeline.start_run(db_session, owner_id=owner["user_id"], period="week", enqueue=None)
        pipeline.mark_failed_public(db_session, run_id, "boom")
        new_id = pipeline.start_run(db_session, owner_id=owner["user_id"], period="week", enqueue=None)
        assert new_id != run_id

    def test_execute_run_writes_all_sections_and_completes(self, db_session, owner):
        db_session.add(models.Employee(user_id=42, name="Rahim",
                                       user_type="employee", password="x",
                                       employer_id=owner["user_id"]))
        _sale(db_session, 42, _at(hour=10), 120.0, 40.0, items=[(7, 2, 60.0, 40.0)])
        db_session.commit()

        run_id = pipeline.start_run(db_session, owner_id=owner["user_id"], period="day", enqueue=None)
        pipeline.execute_run(db_session, run_id, "day")

        run = pipeline.get_run(db_session, run_id, owner["user_id"])
        assert run.status == "COMPLETED"
        assert run.completed_at is not None

        snaps = db_session.query(models.AnalyticsSnapshot).filter_by(run_id=run_id).all()
        assert {s.section for s in snaps} == {"sales", "employees", "products", "insights"}
        sales_data = next(s for s in snaps if s.section == "sales").data
        assert sales_data["current"]["revenue"] == 120.0
        emp_data = next(s for s in snaps if s.section == "employees").data
        assert emp_data["employees"][0]["name"] == "Rahim"
        prod_data = next(s for s in snaps if s.section == "products").data
        assert prod_data["top_by_revenue"][0]["product_id"] == 7

    def test_execute_run_marks_failed_on_error(self, db_session, owner):
        run_id = pipeline.start_run(db_session, owner_id=owner["user_id"], period="day", enqueue=None)
        # Corrupt the period to force an exception inside aggregation.
        with pytest.raises(Exception):
            pipeline.execute_run(db_session, run_id, "century")
        assert pipeline.get_run(db_session, run_id, owner["user_id"]).status == "FAILED"

    def test_watchdog_reaps_stale_runs(self, db_session, owner):
        run_id = pipeline.start_run(db_session, owner_id=owner["user_id"], period="week", enqueue=None)
        run = pipeline.get_run(db_session, run_id, owner["user_id"])
        run.started_at = datetime.utcnow() - timedelta(minutes=30)
        db_session.commit()

        assert pipeline.mark_stale_runs_failed(db_session, timeout_minutes=10) == 1
        assert pipeline.get_run(db_session, run_id, owner["user_id"]).status == "FAILED"

    def test_dashboard_returns_latest_completed(self, db_session, owner):
        # Two sequential completed runs -> dashboard reflects the newest.
        for _ in range(2):
            run_id = pipeline.start_run(db_session, owner_id=owner["user_id"],
                                        period="week", enqueue=None)
            pipeline.execute_run(db_session, run_id, "week")

        sections = pipeline.latest_snapshots(db_session, owner["user_id"], "week")
        assert set(sections.keys()) == {"sales", "employees", "products", "insights"}


# ---------------------------------------------------------
# API layer (executor overridden with a synchronous run)
# ---------------------------------------------------------


@pytest.fixture()
def sync_executor(db_session):
    """
    Override for the /analytics/run executor: run the pipeline inline
    on the test DB session (mimics the Celery chord completing fast).
    """
    def _enqueue(run_id, owner_id, period):
        pipeline.execute_run(db_session, run_id, period)
    return _enqueue


class TestAnalyticsAPI:
    def test_employee_forbidden(self, client, employee):
        resp = client.post("/api/v1/analytics/run", json={"period": "week"})
        assert resp.status_code == 403

    def test_start_poll_dashboard_flow(self, client, owner, sync_executor):
        """
        The full owner flow: seed data -> POST /run (202) -> poll status
        -> GET /dashboard. The executor dependency is overridden so no
        Redis/Celery is needed; the pipeline executes inline.
        """
        from fastapi.testclient import TestClient

        from main import app
        from routes.analytics import get_enqueue

        app.dependency_overrides[get_enqueue] = lambda: sync_executor
        try:
            owner_client = TestClient(app)
            owner_client.post("/api/v1/auth/login", json={
                "phone_number": "01700000001", "password": "secret123",
            })

            # Seed one sale through the real API (owner can sell too).
            r = owner_client.post("/api/v1/products/", json={
                "product_name": "Widget", "cost_price": 40.0,
                "retail_price": 60.0, "stock_quantity": 100,
                "category": "Gadgets",
            })
            assert r.status_code == 200, r.json()
            r = owner_client.post("/api/v1/customers/", json={
                "name": "Walker", "phone_number": "01800000009",
            })
            assert r.status_code == 200, r.json()
            customer_id = r.json()["customer_id"]

            r = owner_client.post("/api/v1/checkout/", json={
                "customer_id": customer_id,
                "payment_method": "cash",
                "items": [{"product_id": 1, "quantity": 2}],
            })
            assert r.status_code == 200, r.json()

            # Start the run -> 202 with a run id.
            resp = owner_client.post("/api/v1/analytics/run", json={"period": "week"})
            assert resp.status_code == 202, resp.json()
            run_id = resp.json()["run_id"]

            # 409 while the (already completed, hence released...) —
            # sync executor completes inline, so a second POST must 202.
            resp2 = owner_client.post("/api/v1/analytics/run", json={"period": "week"})
            assert resp2.status_code == 202

            # Status endpoint reports COMPLETED for the first run.
            resp = owner_client.get(f"/api/v1/analytics/run/{run_id}/status")
            assert resp.status_code == 200
            assert resp.json()["status"] == "COMPLETED"

            # Dashboard carries all four sections with real numbers.
            resp = owner_client.get("/api/v1/analytics/dashboard?period=week")
            assert resp.status_code == 200
            body = resp.json()
            assert set(body["sections"].keys()) == {
                "sales", "employees", "products", "insights"
            }
            # 2 units x (60 - 40) profit, 120 revenue from the checkout.
            assert body["sections"]["sales"]["current"]["revenue"] == 120.0
            assert body["sections"]["sales"]["current"]["profit"] == 40.0
        finally:
            app.dependency_overrides.pop(get_enqueue, None)

    def test_dashboard_empty_before_any_run(self, client, owner):
        resp = client.get("/api/v1/analytics/dashboard?period=week")
        assert resp.status_code == 200
        assert resp.json()["sections"] == {}

    def test_dashboard_invalid_period_400(self, client, owner):
        resp = client.get("/api/v1/analytics/dashboard?period=century")
        assert resp.status_code == 400

    def test_status_unknown_run_404(self, client, owner):
        resp = client.get("/api/v1/analytics/run/nonexistent-id/status")
        assert resp.status_code == 404

    def test_start_without_override_runs_synchronously(self, client, owner):
        """
        Default deployment (ANALYTICS_EXECUTOR=sync, no celery): POST
        /run executes the pipeline inline and reports COMPLETED, and the
        dashboard is populated immediately — no Redis, no worker.
        Regression test for the ModuleNotFoundError 500.
        """
        # Seed one sale through the real API.
        r = client.post("/api/v1/products/", json={
            "product_name": "Widget", "cost_price": 40.0,
            "retail_price": 60.0, "stock_quantity": 100,
        })
        assert r.status_code == 200, r.json()
        r = client.post("/api/v1/customers/", json={
            "name": "Walker", "phone_number": "01800000011",
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
        body = resp.json()
        # Sync executor -> finished before the response returns.
        assert body["status"] == "COMPLETED", body

        resp = client.get("/api/v1/analytics/dashboard?period=week")
        assert resp.status_code == 200
        sections = resp.json()["sections"]
        assert sections["sales"]["current"]["revenue"] == 120.0
        assert sections["sales"]["current"]["profit"] == 40.0

    def test_failed_run_snapshot_cleanup_on_retry(self, db_session, owner, monkeypatch):
        """
        A FAILED run can be re-executed: stale partial snapshots are
        cleared first, so the UNIQUE constraint never trips.
        """
        from analytics import aggregators

        run_id = pipeline.start_run(db_session, owner_id=owner["user_id"],
                                    period="week", enqueue=None)

        # First attempt: aggregation blows up mid-pipeline.
        def boom(*args, **kwargs):
            raise RuntimeError("simulated mid-run crash")
        monkeypatch.setattr(aggregators, "aggregate_sales", boom)
        with pytest.raises(RuntimeError):
            pipeline.execute_run(db_session, run_id, "week")
        assert pipeline.get_run(db_session, run_id, owner["user_id"]).status == "FAILED"

        # Second attempt (healthy): completes, exactly one snapshot set.
        # NOTE: pipeline._execute_run imported aggregate_sales directly at
        # module import (from analytics import aggregators -> pipeline
        # calls aggregators.aggregate_sales), so patching the aggregators
        # module attribute works — undo the patch explicitly before the
        # healthy pass.
        monkeypatch.undo()
        pipeline.execute_run(db_session, run_id, "week")

        run = pipeline.get_run(db_session, run_id, owner["user_id"])
        assert run.status == "COMPLETED"
        snaps = db_session.query(models.AnalyticsSnapshot).filter_by(run_id=run_id).all()
        assert len(snaps) == 4


class TestExecutorSelection:
    """The route's executor choice (sync vs Celery)."""

    def test_default_is_sync_bound_to_request_session(self):
        import functools

        from routes import analytics as analytics_routes

        executor = analytics_routes.get_enqueue(db="session-sentinel")
        assert isinstance(executor, functools.partial)
        assert executor.func is analytics_routes._sync_enqueue
        assert executor.args == ("session-sentinel",)

    def test_celery_mode_falls_back_without_celery(self, monkeypatch):
        """
        ANALYTICS_EXECUTOR=celery with celery not importable must fall
        back to sync (with a log line), never raise.
        """
        import builtins
        import functools

        from routes import analytics as analytics_routes

        monkeypatch.setenv("ANALYTICS_EXECUTOR", "celery")
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "analytics.tasks":
                raise ImportError("No module named 'celery'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        executor = analytics_routes.get_enqueue(db=None)
        assert isinstance(executor, functools.partial)
        assert executor.func is analytics_routes._sync_enqueue

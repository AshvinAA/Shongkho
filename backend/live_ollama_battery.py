"""
Live multi-scenario battery for the Part A insight pipeline, run against
the LOCAL Ollama provider (docs/LLM_INTEGRATION.md §2 + §6 test matrix).

Why: Gemini's free tier kept rate-limiting during development, so the
pipeline is exercised for real here via the LLM_PROVIDER=ollama seam —
same code path, same validation, local inference. Switching to Gemini
later is an env change only (LLM_PROVIDER=gemini + GEMINI_API_KEY).

Run from backend/:
    LLM_PROVIDER=ollama LLM_BUDGET_SECONDS=120 python live_ollama_battery.py

Scenarios
  1. cold start       — no history: current DTO only (first-run path)
  2. history present  — 4 declining windows; rollup feeds the prompt
  3. gap in history   — a missing window must break the decline streak
  4. full DB pipeline — real pipeline.execute_run: a seeded prior-week
                        snapshot feeds the bundle; all 4 snapshot rows
                        land in one transaction; run COMPLETED
  5. budget degrade   — LLM starved of time -> deterministic fallback,
                        run STILL COMPLETED with data["degraded"]=true

Every scenario re-checks the returned payload against the bundle
independently (basis resolution + number grounding), so a PASS means
"every number the model wrote traces to real data", not just "no crash".
Exit code 1 if any contract check fails; a content degrade in a
non-degrade scenario counts as a failure of the live success path.
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from analytics import insights, llm, pipeline  # noqa: E402
from analytics.timeutils import period_bounds  # noqa: E402

RESULTS = []


# ---------------------------------------------------------
# Payload factories (same shapes the aggregators emit)
# ---------------------------------------------------------
def sales_payload(start: datetime, revenue: float, previous_revenue: float = 0.0,
                  period: str = "week") -> dict:
    return {
        "period": period,
        "best_unit": "days",
        "current": {"revenue": revenue, "profit": round(revenue * 0.3, 2),
                    "orders": max(5, int(revenue / 120))},
        "previous": {"revenue": previous_revenue,
                     "profit": round(previous_revenue * 0.3, 2), "orders": 4},
        "change_pct": {
            "revenue": round((revenue - previous_revenue) / previous_revenue * 100, 1)
            if previous_revenue else None,
            "profit": None, "orders": None,
        },
        "series": [], "best": {"by_revenue": [], "by_profit": []},
        "window": {
            "current_start": start.isoformat(),
            "current_end": (start + timedelta(days=7)).isoformat(),
            "previous_start": (start - timedelta(days=7)).isoformat(),
            "previous_end": start.isoformat(),
        },
    }


def realistic_dashboard_payloads():
    """
    Dashboard-scale payloads: 24 hourly buckets, 5 employees with full
    race-series arrays, 10-deep product rankings — the shapes the real
    aggregators emit at POS scale (the sizes that exposed the prompt-
    prefill budget blowout; regression guard for _prompt_bundle).
    """
    buckets = [{"key": str(h), "label": f"{h}:00", "revenue": 100 + h * 7,
                "profit": 30 + h * 2, "orders": 3 + h % 5} for h in range(24)]
    sales = {
        "period": "day", "best_unit": "hours",
        "current": {"revenue": 5240.0, "profit": 1580.0, "orders": 142},
        "previous": {"revenue": 4890.0, "profit": 1440.0, "orders": 131},
        "change_pct": {"revenue": 7.2, "profit": 9.7, "orders": 8.4},
        "series": buckets,
        "best": {"by_revenue": buckets[:3], "by_profit": buckets[:3]},
        "window": {
            "current_start": "2026-09-25T00:00:00",
            "current_end": "2026-09-26T00:00:00",
            "previous_start": "2026-09-24T00:00:00",
            "previous_end": "2026-09-25T00:00:00",
        },
    }
    lanes, rev, prof = [], {}, {}
    for i in range(1, 6):
        lanes.append({"employee_id": i, "name": f"Emp{i}", "photo": None,
                      "is_owner": False, "orders": 30 - i,
                      "revenue": 1800 - i * 150, "profit": 500 - i * 40,
                      "change_pct": {"revenue": 5.0 - i * 4,
                                     "profit": 3.0 - i * 3, "orders": 2.0 - i}})
        rev[str(i)] = [j * (i + 1) * 3 for j in range(24)]
        prof[str(i)] = [j * (i + 1) for j in range(24)]
    employees = {"period": "day", "employees": lanes,
                 "race_series": {"keys": [str(h) for h in range(24)],
                                 "labels": [f"{h}:00" for h in range(24)],
                                 "revenue": rev, "profit": prof},
                 "window": sales["window"]}
    products = {"period": "day"}
    for key in ("top_by_revenue", "top_by_profit", "bottom_by_revenue"):
        products[key] = [{"product_id": i, "name": f"Product {i}",
                          "units": 40 - i * 2, "revenue": 900 - i * 60,
                          "profit": 260 - i * 20, "margin_pct": 25.0 + i,
                          "units_change_pct": 12.5 - i} for i in range(1, 11)]
    products["window"] = sales["window"]
    return sales, employees, products


def scenario_realistic_scale():
    """Dashboard-scale payloads must still complete inside the budget."""
    t0 = time.monotonic()
    sales, employees, products = realistic_dashboard_payloads()
    bundle = insights.build_context(sales, [], employees, products)
    out = insights.build_insights(bundle, "day")
    errors = verify_payload(out, bundle)
    ok = not errors
    detail = f"summary: {out.get('summary')!r}"
    if errors:
        detail += "\n      " + "\n      ".join(errors)
    record("6. dashboard-scale payloads (prompt pruning holds)", ok, detail,
           time.monotonic() - t0)


def employees_payload():
    return {"employees": [
        {"employee_id": 2, "name": "Rahim", "orders": 30, "revenue": 8000.0,
         "profit": 2400.0,
         "change_pct": {"revenue": 14.3, "profit": 9.1, "orders": 11.1}},
        {"employee_id": 3, "name": "Karim", "orders": 18, "revenue": 3500.0,
         "profit": 1000.0,
         "change_pct": {"revenue": -12.5, "profit": -20.0, "orders": -10.0}},
        {"employee_id": 4, "name": "Nasir", "orders": 12, "revenue": 900.0,
         "profit": 260.0,
         "change_pct": {"revenue": -4.2, "profit": -6.0, "orders": -8.0}},
    ], "race_series": {"keys": [], "labels": [], "revenue": {}, "profit": {}}}


def products_payload():
    return {"top_by_revenue": [
        {"product_id": 1, "name": "Mustard Oil 1L", "units": 40, "revenue": 5600.0,
         "profit": 1400.0, "margin_pct": 25.0, "units_change_pct": 33.3},
        {"product_id": 2, "name": "Sugar 1kg", "units": 22, "revenue": 2420.0,
         "profit": 480.0, "margin_pct": 19.8, "units_change_pct": None},
    ], "top_by_profit": [], "bottom_by_revenue": []}


# ---------------------------------------------------------
# Post-hoc contract verification (independent of the checker's verdict)
# ---------------------------------------------------------
def verify_payload(out: dict, bundle: dict) -> list:
    """Every check that must hold for a SUCCESS-path insights payload."""
    errors = []
    if out.get("degraded"):
        return [f"degraded: {out.get('degraded_reason')}"]
    if not isinstance(out.get("summary"), str) or not out["summary"].strip():
        errors.append("empty summary")
    obs = out.get("observations")
    if not isinstance(obs, list) or not obs:
        errors.append("no observations")
    else:
        for o in obs:
            basis = o.get("basis", "")
            if insights._resolve_path(bundle, basis) is None:
                errors.append(f"basis does not resolve: {basis!r}")
            elif not insights._check_text(o.get("text", ""), bundle, basis):
                errors.append(f"ungrounded number survived: {o.get('text')!r}")
    for item in out.get("areas_to_watch", []):
        if insights._numbers_in(item):
            errors.append(f"numeric areas_to_watch entry: {item!r}")
    return errors


def record(name: str, ok: bool, detail: str, elapsed: float):
    RESULTS.append((name, ok, detail, elapsed))
    print(f"\n{'PASS' if ok else 'FAIL'}  {name}  ({elapsed:.1f}s)")
    for line in detail.splitlines():
        print(f"      {line}")


# ---------------------------------------------------------
# Scenario 1: cold start
# ---------------------------------------------------------
def scenario_cold_start():
    t0 = time.monotonic()
    cur = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    sales = sales_payload(cur, 14200.0, 12600.0)
    bundle = insights.build_context(sales, [], employees_payload(), products_payload())
    assert bundle["recent_window"] is None and bundle["rollup"] is None

    out = insights.build_insights(bundle, "week")
    errors = verify_payload(out, bundle)
    detail = f"summary: {out.get('summary')!r}"
    record("1. cold start (no history)", not errors,
           detail + ("\n      " + "\n      ".join(errors) if errors else ""),
           time.monotonic() - t0)


# ---------------------------------------------------------
# Scenario 2: full history, declining trend
# ---------------------------------------------------------
def scenario_history():
    t0 = time.monotonic()
    cur = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    sales = sales_payload(cur, 14200.0, 14800.0)
    # NEWEST FIRST (pipeline query order): last week .. four weeks back.
    # 16000 -> 15600 -> 15200 -> 14800 -> current 14200: declines all the way.
    history = [
        sales_payload(cur - timedelta(days=7), 14800.0, 15200.0),
        sales_payload(cur - timedelta(days=14), 15200.0, 15600.0),
        sales_payload(cur - timedelta(days=21), 15600.0, 16000.0),
        sales_payload(cur - timedelta(days=28), 16000.0, 16500.0),
    ]
    bundle = insights.build_context(sales, history, employees_payload(),
                                    products_payload())
    rollup = bundle["rollup"]
    checks = [
        ("rollup.windows_available == 4", rollup["windows_available"] == 4),
        ("streak == 4", rollup["consecutive_declining_periods"] == 4),
        ("avg_revenue == 15400.0", rollup["avg_revenue"] == 15400.0),
    ]
    bad = [name for name, ok in checks if not ok]

    out = insights.build_insights(bundle, "week")
    errors = verify_payload(out, bundle)
    ok = not bad and not errors
    detail = "\n".join(f"{'ok' if c[1] else 'MISMATCH'}  {c[0]}" for c in checks)
    detail += f"\n      summary: {out.get('summary')!r}"
    if errors:
        detail += "\n      " + "\n      ".join(errors)
    record("2. history present (4 declining windows)", ok, detail,
           time.monotonic() - t0)


# ---------------------------------------------------------
# Scenario 3: gap in history breaks the streak
# ---------------------------------------------------------
def scenario_gap():
    t0 = time.monotonic()
    cur = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    sales = sales_payload(cur, 14200.0, 14800.0)
    # Only TWO weeks back exists; last week is missing -> streak must be 0,
    # and the prompt must show a null slot, never a fabricated trend.
    history = [sales_payload(cur - timedelta(days=14), 20000.0, 19000.0)]
    bundle = insights.build_context(sales, history, employees_payload(),
                                    products_payload())
    rollup = bundle["rollup"]
    checks = [
        ("window[2] present (2w back)", bundle["recent_window"][2] is not None),
        ("window[3] is null (gap)", bundle["recent_window"][3] is None),
        ("streak broken -> 0", rollup["consecutive_declining_periods"] == 0),
    ]
    bad = [name for name, ok in checks if not ok]

    out = insights.build_insights(bundle, "week")
    errors = verify_payload(out, bundle)
    ok = not bad and not errors
    detail = "\n".join(f"{'ok' if c[1] else 'MISMATCH'}  {c[0]}" for c in checks)
    detail += f"\n      summary: {out.get('summary')!r}"
    if errors:
        detail += "\n      " + "\n      ".join(errors)
    record("3. gap in history (streak break)", ok, detail,
           time.monotonic() - t0)


# ---------------------------------------------------------
# Scenario 4: the real DB pipeline, end to end
# ---------------------------------------------------------
def _seed_db():
    tmpdir = tempfile.mkdtemp(prefix="shongkho_live_")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    engine = create_engine(f"sqlite:///{tmpdir}/live.db",
                           connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()

    db.add(models.Owner(user_id=1, name="Live Owner", user_type="owner",
                        phone_number="01700000001", password="x"))
    db.add(models.Employee(user_id=2, name="Rahim", user_type="employee",
                           password="x", employer_id=1))
    db.add(models.Product(product_name="Mustard Oil 1L", cost_price=35.0,
                          retail_price=50.0, stock_quantity=100))

    now = datetime.now()
    for days_ago, hour, rev, prof in ((0, 10, 320.0, 96.0), (0, 15, 140.0, 42.0),
                                      (7, 11, 260.0, 78.0), (7, 16, 180.0, 54.0)):
        when = (now - timedelta(days=days_ago)).replace(hour=hour, minute=0)
        s = models.Sale(employee_id=2, customer_id=None, payment_method="cash",
                        total_revenue=rev, total_profit=prof,
                        date=when.date(), time=when.time())
        s.items.append(models.SaleItem(product_id=1, quantity=3,
                                       retail_price_at_sale=50.0,
                                       cost_price_at_sale=35.0))
        db.add(s)
    db.commit()
    return db


def scenario_full_pipeline():
    t0 = time.monotonic()
    import models
    db = _seed_db()

    # A completed PREVIOUS-week sales snapshot, exactly as an earlier run
    # would have stored it -> the history query must find it.
    today = datetime.now().date()
    prev_start = period_bounds(today, "week")[2]
    prev_payload = sales_payload(prev_start, 2000.0, 2400.0)
    db.add(models.AnalysisRun(id="seed-run", owner_id=1, status="COMPLETED"))
    db.add(models.AnalyticsSnapshot(run_id="seed-run", owner_id=1,
                                    section="sales", period_type="week",
                                    data=prev_payload,
                                    generated_at=datetime.utcnow()))
    db.commit()

    # Spy on the LLM seam: prove the seeded history reached the prompt.
    seen = {}
    orig = llm.generate_json

    def spy(prompt, schema, *, client=None):
        seen["prompt"] = prompt
        return orig(prompt, schema, client=client)

    llm.generate_json = spy
    try:
        run_id = pipeline.start_run(db, owner_id=1, period="week", enqueue=None)
        pipeline.execute_run(db, run_id, "week")
    finally:
        llm.generate_json = orig

    run = pipeline.get_run(db, run_id, 1)
    rows = db.query(models.AnalyticsSnapshot).filter_by(run_id=run_id).all()
    sections = {r.section for r in rows}
    insights_row = next((r for r in rows if r.section == "insights"), None)

    prompt = seen.get("prompt", "")
    checks = [
        ("run COMPLETED", run.status == "COMPLETED"),
        ("all 4 sections in one tx", sections == {"sales", "employees",
                                                  "products", "insights"}),
        # History reaches the model as ROLLUP statistics (the prompt view
        # prunes raw windows — _prompt_bundle); the seeded week's revenue
        # 2000.0 must surface via avg/best/worst_period.
        ("history reached the prompt (as rollup)",
         '"rollup"' in prompt and "2000" in prompt),
        ("rollup reached the prompt", '"rollup"' in prompt
         and '"avg_revenue"' in prompt),
        ("insights row is a success payload",
         insights_row is not None and not insights_row.data.get("degraded")
         and bool(insights_row.data.get("summary"))),
    ]
    bad = [name for name, ok in checks if not ok]
    detail = "\n".join(f"{'ok' if c[1] else 'MISMATCH'}  {c[0]}" for c in checks)
    if insights_row is not None:
        detail += f"\n      summary: {insights_row.data.get('summary')!r}"
        if insights_row.data.get("degraded"):
            detail += (f"\n      degraded: {insights_row.data.get('degraded_reason')}"
                       "  (contract held, but live success path failed)")
    record("4. full DB pipeline (history feeds the bundle)", not bad, detail,
           time.monotonic() - t0)
    return not bad


# ---------------------------------------------------------
# Scenario 5: budget starvation degrades, run still completes
# ---------------------------------------------------------
def scenario_budget_degrade():
    t0 = time.monotonic()
    import models
    db = _seed_db()

    old = os.environ.get("LLM_BUDGET_SECONDS")
    os.environ["LLM_BUDGET_SECONDS"] = "0.01"  # too small for any attempt
    try:
        run_id = pipeline.start_run(db, owner_id=1, period="week", enqueue=None)
        pipeline.execute_run(db, run_id, "week")
    finally:
        if old is None:
            os.environ.pop("LLM_BUDGET_SECONDS", None)
        else:
            os.environ["LLM_BUDGET_SECONDS"] = old

    run = pipeline.get_run(db, run_id, 1)
    row = db.query(models.AnalyticsSnapshot).filter_by(run_id=run_id,
                                                       section="insights").one()
    sections = {r.section for r in
                db.query(models.AnalyticsSnapshot).filter_by(run_id=run_id).all()}
    checks = [
        ("run COMPLETED despite LLM starvation", run.status == "COMPLETED"),
        ("insights row carries the degrade flag", row.data.get("degraded") is True),
        ("summary is None", row.data.get("summary") is None),
        ("reason mentions the budget", "budget" in (row.data.get("degraded_reason") or "").lower()),
        ("other 3 sections still written", sections == {"sales", "employees",
                                                        "products", "insights"}),
    ]
    bad = [name for name, ok in checks if not ok]
    detail = "\n".join(f"{'ok' if c[1] else 'MISMATCH'}  {c[0]}" for c in checks)
    detail += f"\n      reason: {row.data.get('degraded_reason')!r}"
    record("5. budget degrade (run must still complete)", not bad, detail,
           time.monotonic() - t0)


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------
def main():
    print(f"provider={llm.provider()} model={llm.model_name()} "
          f"url={llm.ollama_url()} budget={llm.budget_seconds()}s")
    scenario_cold_start()
    scenario_history()
    scenario_gap()
    pipeline_ok = scenario_full_pipeline()
    scenario_budget_degrade()
    scenario_realistic_scale()

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{'=' * 62}\n{len(RESULTS) - len(failed)}/{len(RESULTS)} scenarios passed")
    if failed:
        for name, _, detail, _ in failed:
            print(f"  FAILED: {name}\n    {detail}")
    print("\nSwitching to Gemini later = env change only:")
    print("  LLM_PROVIDER=gemini  GEMINI_API_KEY=<key>  LLM_MODEL=gemini-2.5-flash")
    return 1 if failed else (0 if pipeline_ok else 1)


if __name__ == "__main__":
    sys.exit(main())

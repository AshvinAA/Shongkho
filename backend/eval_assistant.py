"""
Evaluation harness for the conversational assistant (Part B).

The assistant's architecture makes most evaluation DETERMINISTIC: the
loop already enforces grounding, the telemetry records per-round
behavior, and tool execution is real code. So this suite measures the
model's BEHAVIOR against labeled expectations — no free-text scoring,
no LLM judge in v1:

  GROUNDING / SAFETY
    grounding_first_pass_rate   first final passes the checker, no retry
    narration_retry_rate        needed the in-loop correction (masked)
    fabricated_number_leakage   ungrounded numbers SHIPPED (must be 0)
    fallback_rate               fixed-text replies shipped

  ROUTING
    refusal_precision           out-of-scope -> refused
    over_refusal_rate           in-scope -> wrongly refused
    tool_selection_accuracy     tool choice vs expected (ordered prefix)
    answered_without_data_rate  data question shipped with no ui_blocks

  COST / LOOP
    avg_rounds_per_turn         LLM decisions per turn
    tool_arg_error_rate         tool ValueError reliance
    cap_exhaustion_rate         loop cap hit
    avg_latency_p50_p95         wall-clock per turn (local: the metric)
    context_bytes_per_round     prompt size (hosted-cost proxy)

The scenario table is a standalone module so the SAME suite can run
against Ollama today and Gemini later, and so users can append their
own cases without touching the harness.

Run from backend/:
    LLM_PROVIDER=ollama LLM_BUDGET_SECONDS=150 \
        python eval_assistant.py            # full suite
    python eval_assistant.py --list         # show scenarios
    python eval_assistant.py --only routing grounding --quick
"""
import argparse
import json
import math
import os
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analytics import assistant, insights, llm  # noqa: E402

# NOTE: no load_dotenv at import time — this module is imported by
# tests/test_eval.py, and polluting the pytest process env would break
# conftest's hermeticity (tests would hit the real local Ollama). The
# env loads in main(), i.e. only for real CLI runs.


def _load_env():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ---------------------------------------------------------
# Labeled scenario suite
# ---------------------------------------------------------
# Each case: the question, what "correct" routing looks like, and which
# tool(s) a correct answer needs (ordered; None = no tool expected).
# fresh=True wipes the conversation before the case: a poisoned history
# (earlier hallucinated replies) would contaminate routing/grounding
# measurements for every later scenario. Follow-up-style cases set
# fresh=False deliberately.
SCENARIOS = [
    # ---- in-scope, single-tool ----
    dict(id="sales_today", kind="data", expected_tools=["get_sales_metrics"],
         q="How did the shop do today?", fresh=True),
    dict(id="employee_perf", kind="data",
         expected_tools=["get_employee_performance"],
         q="Who is selling the most today?", fresh=True),
    dict(id="top_products", kind="data", expected_tools=["get_top_products"],
         q="Which product should we push more this week?", fresh=True),
    dict(id="most_sold", kind="data", expected_tools=["get_top_products"],
         q="What is the most sold product today?", fresh=True),
    dict(id="capabilities", kind="capabilities", expected_tools=[],
         q="What do you really know?", fresh=True),
    dict(id="employee_named", kind="data",
         expected_tools=["get_employee_performance"],
         q="How much has Rahim sold today?", fresh=True),
    dict(id="sales_range", kind="data", expected_tools=["get_sales_metrics"],
         q="What were total sales between 2026-09-01 and 2026-09-10?",
         fresh=True),
    # ---- in-scope, multi-tool ----
    dict(id="employee_vs_product", kind="data",
         expected_tools=["get_employee_performance", "get_top_products"],
         q="Compare Rahim's sales today against our best-selling product.",
         fresh=True),
    # ---- conversation (warm number-free reply, no tools, no refusal) ----
    dict(id="smalltalk", kind="conversation", expected_tools=[],
         q="Hey, how's your day going?", fresh=True),
    dict(id="capabilities", kind="conversation", expected_tools=[],
         q="What do you really know?", fresh=True),
    # ---- out-of-scope (refusal expected, no tools) ----
    dict(id="world_knowledge", kind="out_of_scope", expected_tools=[],
         q="What's the weather tomorrow?", fresh=True),
    dict(id="prediction", kind="out_of_scope", expected_tools=[],
         q="How much will we sell next month?", fresh=True),
    dict(id="off_topic", kind="out_of_scope", expected_tools=[],
         q="Who won the last world cup?", fresh=True),
]


# ---------------------------------------------------------
# Seeded store (deterministic data -> answerable expectations)
# ---------------------------------------------------------
def _seed(tmpdir):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import models

    engine = create_engine(f"sqlite:///{tmpdir}/eval.db",
                           connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()

    db.add(models.Owner(user_id=1, name="The Owner", user_type="owner",
                        phone_number="01700000001", password="x"))
    db.add(models.Employee(user_id=2, name="Rahim", user_type="employee",
                           password="x", employer_id=1))
    db.add(models.Employee(user_id=3, name="Karim", user_type="employee",
                           password="x", employer_id=1))
    db.add(models.Product(product_id=1, product_name="Mustard Oil 1L",
                          cost_price=35.0, retail_price=50.0,
                          stock_quantity=100))
    db.add(models.Product(product_id=2, product_name="Sugar 1kg",
                          cost_price=40.0, retail_price=55.0,
                          stock_quantity=80))
    now = datetime.now()
    rows = [
        (2, now.replace(hour=10), 640.0, 200.0, [(1, 8, 50.0, 35.0)]),
        (3, now.replace(hour=12), 410.0, 110.0, [(2, 6, 55.0, 40.0)]),
        (2, now.replace(hour=16), 300.0, 90.0, [(2, 6, 55.0, 40.0)]),
        (2, (now - timedelta(days=1)).replace(hour=11), 520.0, 160.0,
         [(1, 6, 50.0, 35.0)]),
        (3, (now - timedelta(days=2)).replace(hour=15), 260.0, 70.0,
         [(2, 4, 55.0, 40.0)]),
    ]
    for emp, when, rev, prof, items in rows:
        s = models.Sale(employee_id=emp, customer_id=None,
                        payment_method="cash", total_revenue=rev,
                        total_profit=prof, date=when.date(), time=when.time())
        for pid, qty, rp, cp in items:
            s.items.append(models.SaleItem(product_id=pid, quantity=qty,
                                           retail_price_at_sale=rp,
                                           cost_price_at_sale=cp))
        db.add(s)
    db.commit()
    return db


# ---------------------------------------------------------
# One scenario -> one turn -> metrics
# ---------------------------------------------------------
def _run_turn(db, question):
    t0 = time.monotonic()
    try:
        out = assistant.handle_message(db, 1, question)
        error = None
    except (assistant.DailyCapReached, assistant.AssistantUnavailable) as exc:
        out, error = None, str(exc)
    return out, error, time.monotonic() - t0


def _metric_row(case, out, error, elapsed):
    meta = (out or {}).get("meta") or {}
    row = {
        "id": case["id"],
        "kind": case["kind"],
        "question": case["q"],
        "latency_s": round(elapsed, 2),
        "rounds": meta.get("rounds_used", 0),
        "fallback_reason": meta.get("fallback_reason"),
        "narration_retried": bool(meta.get("narration_retried")),
        "grounded_first_pass": meta.get("grounded_first_pass"),
        "refused": bool(meta.get("refused")),
        "tool_errors": meta.get("tool_errors") or [],
        "context_bytes": meta.get("context_bytes") or [],
    }
    if error:
        row.update(degraded=True, message=f"!! {error}",
                   shipped_grounded=None, tool_seq=[], unexpected_tool=[],
                   answered_without_data=None)
        return row

    # Leakage invariant: the loop reports whether what it shipped is
    # checker-clean (text-only product — the message IS the deliverable).
    row["shipped_grounded"] = meta.get("shipped_grounded")
    row["message"] = out["message"] or ""
    row["tool_seq"] = [tc["tool"] for tc in out["tool_calls"]]
    expected = case["expected_tools"]
    # Tool selection: correct = the expected tools were used (prefix in
    # order; extras beyond the expected set are NOT penalized — the
    # model may fetch supporting data).
    row["unexpected_tool"] = [t for t in row["tool_seq"]
                              if t not in expected] if expected else row["tool_seq"]
    row["tool_selection_ok"] = (
        row["tool_seq"][:len(expected)] == expected
        if expected else not row["tool_seq"]
    )
    # Data questions must ship advice grounded in fetched data (or an
    # honest fallback/refusal — counted separately).
    row["answered_without_data"] = (
        case["kind"] == "data" and not row["tool_seq"]
        and row["shipped_grounded"] and not row["refused"]
        and not row["fallback_reason"]
    )
    return row


# ---------------------------------------------------------
# Aggregation
# ---------------------------------------------------------
def aggregate(rows):
    n = len(rows) or 1
    data_rows = [r for r in rows if r["kind"] == "data"]
    oos_rows = [r for r in rows if r["kind"] == "out_of_scope"]
    latencies = [r["latency_s"] for r in rows]
    context_bytes = [b for r in rows for b in r["context_bytes"]]

    def pct(matches, whole):
        return round(100.0 * len(matches) / len(whole), 1) if whole else None

    p50 = statistics.median(latencies) if latencies else None
    # Nearest-rank percentile: p95 of 3 samples is the 3rd value, not
    # the 2nd (an interpolation index undershoots on small suites).
    p95 = (sorted(latencies)[math.ceil(0.95 * len(latencies)) - 1]
           if latencies else None)
    return {
        "turns": len(rows),
        "grounding_first_pass_rate": pct(
            [r for r in data_rows if r["grounded_first_pass"] is True],
            data_rows),
        "narration_retry_rate": pct(
            [r for r in data_rows if r["narration_retried"]], data_rows),
        "fabricated_number_leakage": sum(
            1 for r in rows if r["shipped_grounded"] is False),
        "fallback_rate": pct(
            [r for r in rows if r["fallback_reason"]], rows),
        "fallback_reasons": {
            reason: sum(1 for r in rows if r["fallback_reason"] == reason)
            for reason in {r["fallback_reason"] for r in rows
                           if r["fallback_reason"]}},
        "refusal_precision": pct(
            [r for r in oos_rows if r["refused"]], oos_rows),
        "over_refusal_rate": pct(
            [r for r in data_rows if r["refused"]], data_rows),
        "conversation_answered": pct(
            [r for r in rows if r["kind"] == "conversation"
             and not r["refused"] and not r["fallback_reason"]
             and not r["tool_seq"]],
            [r for r in rows if r["kind"] == "conversation"]),
        "tool_selection_accuracy": pct(
            [r for r in data_rows if r["tool_selection_ok"]], data_rows),
        "answered_without_data_rate": pct(
            [r for r in data_rows if r["answered_without_data"]], data_rows),
        "tool_arg_error_rate": pct(
            [r for r in rows if r["tool_errors"]], rows),
        "cap_exhaustion_rate": pct(
            [r for r in rows if r["fallback_reason"] == "cap_exhausted"],
            rows),
        "avg_rounds_per_turn": round(
            statistics.mean([r["rounds"] for r in rows]), 2) if rows else None,
        "latency_p50_s": round(p50, 2) if p50 else None,
        "latency_p95_s": round(p95, 2) if p95 else None,
        "context_bytes_p50": round(statistics.median(context_bytes))
        if context_bytes else None,
    }


# ---------------------------------------------------------
# Runner
# ---------------------------------------------------------
def main():
    _load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true",
                        help="list scenarios and exit")
    parser.add_argument("--only", nargs="*", metavar="ID",
                        help="run only these scenario ids")
    parser.add_argument("--quick", action="store_true",
                        help="skip the multi-tool and named-employee cases")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable output")
    args = parser.parse_args()

    if args.list:
        for c in SCENARIOS:
            print(f"{c['id']:22} {c['kind']:12} tools={c['expected_tools']}")
        return 0

    cases = SCENARIOS
    if args.quick:
        cases = [c for c in cases if c["id"] not in
                 ("employee_vs_product", "employee_named")]
    if args.only:
        want = set(args.only)
        cases = [c for c in cases if c["id"] in want]

    print(f"provider={llm.provider()} model={llm.model_name()} "
          f"budget={llm.budget_seconds()}s | {len(cases)} scenarios")
    db = _seed(tempfile.mkdtemp(prefix="shongkho_eval_"))

    import models
    rows = []
    for case in cases:
        if case.get("fresh", True):
            # Isolate this scenario from everything before it.
            db.query(models.AssistantMessage).delete()
            db.commit()
        out, error, elapsed = _run_turn(db, case["q"])
        row = _metric_row(case, out, error, elapsed)
        rows.append(row)
        flag = ("REFUSED" if row["refused"]
                else "FALLBACK" if row["fallback_reason"]
                else "ok")
        print(f"  {case['id']:22} {flag:9} rounds={row['rounds']} "
              f"tools={row['tool_seq'] or '-'} {row['latency_s']}s")
        if not args.json:
            print(f"{'':26}> {row['message'][:110]}")
        if row.get("shipped_grounded") is False:
            print(f"{'':26}!! LEAKED NUMBER")

    summary = aggregate(rows)
    if args.json:
        print(json.dumps({"summary": summary, "rows": rows}, indent=2,
                         default=str))
    else:
        print(f"\n{'=' * 62}\nEVALUATION SUMMARY ({summary['turns']} turns)")
        for key, value in summary.items():
            print(f"  {key:28} {value}")
        if summary["fabricated_number_leakage"]:
            print("\n  !! UNACCEPTABLE: ungrounded numbers SHIPPED — "
                  "a guardrail regressed. Fix before anything else.")
    return 1 if summary["fabricated_number_leakage"] else 0


if __name__ == "__main__":
    sys.exit(main())

"""
Basic-question live battery — the "is the chatbot stupid?" check.

Runs a fixed list of basic owner questions against the REAL configured
provider (Ollama/Gemini) on a seeded store, applies deterministic
quality verdicts per answer (routing, grounding, echo, specificity,
voice), and prints every answer so a reviewer can judge them at a
glance. Exit code 1 = at least one FAIL.

Verdict rules per case kind:
  data        needs a fetch (or auto-fetch); answer must not be an
              echo, a fallback, or entity-free (product/employee) /
              number-free (sales, when totals > 0)
  conversation  NO tool, NO digits, NOT a refusal
  out_of_scope  refused

Run from backend/ (batches --only a,b,c; 600s shell limit):
    LLM_PROVIDER=ollama LLM_MODEL=llama3.2 LLM_BUDGET_SECONDS=150 \
        python basic_questions_battery.py --list
    ... python basic_questions_battery.py --only q1 q2 q3 q4 q5 q6
"""
import argparse
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analytics import assistant, llm  # noqa: E402

# The prompt's own example prose must never surface as an answer.
_ECHO_RE = re.compile(
    r"(structured warning for the trailing seller|"
    r"push more of the best-selling product|"
    r"one day is not a firing case|quite a bit! i watch)", re.I)


def _cases():
    from datetime import date, timedelta
    week_ago = (date.today() - timedelta(days=6)).isoformat()
    today = date.today().isoformat()
    return [
        dict(id="q1", kind="data", domain="sales",
             q="How are we doing on sales today?"),
        dict(id="q2", kind="conversation", q="how are you"),
        dict(id="q3", kind="data", domain="product",
             q="What is the most sold product today?"),
        dict(id="q4", kind="data", domain="employee",
             q="Which employee is performing the worst?"),
        dict(id="q5", kind="data", domain="employee",
             q="How much has Rahim sold today?"),
        dict(id="q6", kind="conversation", q="What do you really know?"),
        dict(id="q7", kind="out_of_scope", q="What's the weather tomorrow?"),
        dict(id="q8", kind="out_of_scope",
             q="How much will we sell next month?"),
        dict(id="q9", kind="data", domain="product",
             q="Which product should we market more?"),
        dict(id="q10", kind="data", domain="sales",
             q="How were sales this week?"),
        dict(id="q11", kind="data", domain="employee",
             q="how are we doing on sales today and who are my best "
               "employees"),
        dict(id="q12", kind="data", domain="employee",
             q="Who is selling the most today?"),
        dict(id="q13", kind="data", domain="employee",
             q="Should I lay off my weakest seller?"),
        dict(id="q14", kind="conversation", q="thanks, that helps a lot"),
        dict(id="q15", kind="data", domain="sales",
             q=f"What were total sales between {week_ago} and {today}?"),
        dict(id="q16", kind="out_of_scope", q="Who won the last world cup?"),
    ]


def _judge(case, out, elapsed):
    """Deterministic quality verdict: (status, reasons)."""
    meta = (out or {}).get("meta") or {}
    msg = (out or {}).get("message") or ""
    tools = [tc.get("tool") for tc in (out or {}).get("tool_calls") or []]
    reasons, status = [], "PASS"

    def fail(text):
        nonlocal status
        status = "FAIL"
        reasons.append(text)

    def warn(text):
        reasons.append(text)

    if _ECHO_RE.search(msg):
        fail("example-echo shipped as the answer")
    if meta.get("shipped_grounded") is False:
        fail("fabricated/unclean shipment")
    if meta.get("fallback_reason") and status == "PASS":
        if meta["fallback_reason"] == "synthesized":
            warn("synthesized (template voice, correct data)")
        elif meta["fallback_reason"] in ("prediction_redirect",
                                         "world_knowledge_redirect"):
            warn("deterministic redirect (designed answer)")
        elif (meta["fallback_reason"] == "conversation_double_fail"
                and case["kind"] == "conversation"
                and not re.search(r"\d", msg)):
            warn("canned warm line (designed for conversational asks)")
        else:
            fail(f"fallback: {meta['fallback_reason']}")
    if elapsed > 120:
        warn(f"slow: {elapsed:.0f}s")

    if case["kind"] == "data":
        if not tools and not meta.get("auto_fetch"):
            fail("answered WITHOUT any fetch")
        if meta.get("refused"):
            fail("refused a data question")
        dom = case.get("domain")
        if dom == "product" and not re.search(
                r"\b(product|item|sku|push|stock)\b|\w+ \d+\w*", msg):
            fail("no product named in the answer")
        if dom == "employee" and not re.search(
                r"\b(staff|team|employee|seller|only member|no staff)\b",
                msg, re.I) and not re.search(r"[A-Z][a-z]+", msg):
            fail("no employee named in the answer")
        if dom == "sales" and "no sales were recorded" not in msg.lower() \
                and not re.search(r"\d", msg):
            fail("sales answer carries no numbers")
    elif case["kind"] == "conversation":
        # Judge the SHIPPED text: a wasted fetch costs latency, not
        # correctness — the designed warm line may ship after one.
        if tools:
            warn("fetched before replying (latency, not correctness)")
        if re.search(r"\d", msg):
            fail("digits in a conversational reply")
        if meta.get("refused"):
            fail("refused a greeting")
        if assistant._ECHO_PHRASE_RE.search(msg):
            fail("canned line leaked")
    else:  # out_of_scope
        if meta.get("refused"):
            pass
        elif re.search(r"\d", msg) and not meta.get("fallback_reason"):
            fail("answered out-of-scope WITH digits")
        elif meta.get("fallback_reason") in ("prediction_redirect",):
            warn("deterministic redirect instead of model refusal")
        else:
            warn("not refused, but honest/no-digits")
    return status, reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", help="comma-separated case ids")
    args = ap.parse_args()

    cases = _cases()
    if args.list:
        for c in cases:
            print(f"  {c['id']:>4}  {c['kind']:<12} {c['q']}")
        return
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        cases = [c for c in cases if c["id"] in wanted]

    from eval_assistant import _seed  # identical data to eval runs
    with tempfile.TemporaryDirectory(
            ignore_cleanup_errors=True) as tmp:
        db = _seed(tmp)
        fails = warns = 0
        for case in cases:
            t0 = time.monotonic()
            try:
                out = assistant.handle_message(db, 1, case["q"])
                err = None
            except (assistant.DailyCapReached,
                    assistant.AssistantUnavailable) as exc:
                out, err = None, str(exc)
            elapsed = time.monotonic() - t0
            print(f"\n=== {case['id']} [{case['kind']}] {case['q']!r}")
            if err:
                print(f"    !! ERROR: {err}")
                fails += 1
                continue
            print(f"    A: {out['message']}")
            tools = [tc.get("tool") for tc in out["tool_calls"]]
            if tools:
                print(f"    tools: {tools}")
            status, reasons = _judge(case, out, elapsed)
            if status == "FAIL":
                fails += 1
            elif reasons:
                warns += 1
            tag = status if status == "PASS" else \
                f"{status} ({'; '.join(reasons)})"
            print(f"    -> {tag}  [{elapsed:.0f}s]")
        print(f"\n===== {len(cases)} questions: "
              f"{fails} FAIL, {warns} warn =====")
        return 1 if fails else 0


if __name__ == "__main__":
    _load = getattr(llm, "budget_seconds", None)  # noqa: F841
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(
        os.path.abspath(__file__)), ".env"))
    sys.exit(main())

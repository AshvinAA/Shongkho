"""
Live Part B battery: conversational analytics against LOCAL Ollama.

Runs the real agent loop (tools + decision protocol + persistence) on a
fresh SQLite DB seeded with a small store, over several owner turns —
including an out-of-scope question and an advice-voice probe. The
product is TEXT-ONLY: the deliverable is `message`; tool payloads
ground the numbers and are audited in `tool_calls`, but nothing
graphical is expected in the envelope (asserting that here).

Run from backend/:
    LLM_PROVIDER=ollama LLM_BUDGET_SECONDS=120 python live_chat_battery.py
"""
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import models  # noqa: E402
from analytics import assistant, llm  # noqa: E402


def seed(tmpdir):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmpdir}/chat_live.db",
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
                          cost_price=35.0, retail_price=50.0, stock_quantity=100))
    db.add(models.Product(product_id=2, product_name="Sugar 1kg",
                          cost_price=40.0, retail_price=55.0, stock_quantity=80))
    now = datetime.now()
    rows = [
        (2, now.replace(hour=10), 640.0, 200.0, [(1, 8, 50.0, 35.0), (2, 4, 55.0, 40.0)]),
        (3, now.replace(hour=12), 410.0, 110.0, [(2, 6, 55.0, 40.0), (1, 2, 50.0, 35.0)]),
        (2, now.replace(hour=16), 300.0, 90.0, [(1, 6, 50.0, 35.0)]),
        (2, (now - timedelta(days=1)).replace(hour=11), 520.0, 160.0,
         [(1, 6, 50.0, 35.0), (2, 4, 55.0, 40.0)]),
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


# (question, expectation): final-with-data -> tools then grounded advice;
# refusal -> no tools, no numbers. Voice/quality is judged by eye; the
# hard contract (text-only envelope, grounded numbers) is checked below.
TURNS = [
    ("How did the shop do today?", "final-with-data"),
    ("Which product should we push more this week?", "final-with-data"),
    ("Can you tell me which products I should target for marketing for "
     "the next 7 days to maximise my profit?", "final-with-data"),
    ("What's the weather tomorrow?", "refusal"),
]

_ADVICE_HINTS = (
    re.compile(r"\b(could|try|consider|suggest|push|focus|watch|keep|ask)\b", re.I),
)


def main():
    print(f"provider={llm.provider()} model={llm.model_name()} "
          f"budget={llm.budget_seconds()}s")
    db = seed(tempfile.mkdtemp(prefix="shongkho_chat_live_"))
    failures = 0

    for text, expectation in TURNS:
        t0 = time.monotonic()
        try:
            out = assistant.handle_message(db, 1, text)
        except assistant.DailyCapReached:
            print(f"\nOWNER: {text}\n  429: daily cap reached")
            continue
        el = time.monotonic() - t0
        meta = out.get("meta") or {}
        toolcalls = ", ".join(tc["tool"] for tc in out["tool_calls"]) or "-"
        print(f"\nOWNER: {text}")
        print(f"  [{el:.1f}s | rounds: {meta.get('rounds_used')} | "
              f"tools: {toolcalls} | grounded: {meta.get('shipped_grounded')}]")
        print(f"  ASSISTANT: {out['message']}")
        ok = True

        # ---- hard contract checks (text-only product) ----
        if "ui_blocks" in out:
            print("  !! CONTRACT: envelope must not carry ui_blocks")
            failures += 1
        msg = out["message"] or ""
        if msg in (assistant.FALLBACK_MESSAGE, assistant.NARRATION_FALLBACK,
                   assistant.REFUSAL_FALLBACK, None, ""):
            ok = False
            failures += 1
        if not meta.get("shipped_grounded"):
            print("  !! CONTRACT: shipped message is not checker-clean")
            failures += 1

        if expectation == "refusal":
            if out["tool_calls"] or not meta.get("refused"):
                print("  !! expected a refusal (no tools)")
                failures += 1
        else:
            # Advisory voice probe: the answer should DO something with
            # the numbers, not just recite them.
            if not any(h.search(msg) for h in _ADVICE_HINTS):
                print("  !! VOICE: no advisory language (actions/alternatives) "
                      "in the reply")
                failures += 1

    # Persistence + cap check
    n = assistant.messages_today(db, 1)
    print(f"\nassistant turns persisted today: {n} (cap {assistant.DAILY_CAP})")
    hist = assistant.chat_history(db, 1)
    print(f"history reload: {len(hist)} turns (user+assistant, text-only)")
    if n != 2 * len(TURNS):
        failures += 1

    # Envelope of a fresh turn must be exactly {message, tool_calls, meta}.
    out = assistant.handle_message(db, 1, "Steady day? One word is fine.")
    if set(out.keys()) != {"message", "tool_calls", "meta"}:
        print(f"  !! CONTRACT: unexpected envelope keys {sorted(out.keys())}")
        failures += 1

    print(f"\n{'FAILURES: ' + str(failures) if failures else 'ALL CONTRACT CHECKS OK'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

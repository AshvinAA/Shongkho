"""
Eval-harness tests: the METRIC layer is verified offline with a scripted
LLM (no network) — the labeled scenarios' live behavior is measured by
eval_assistant.py itself against the real provider.

Covered:
  - telemetry fields ride the envelope (meta) and record loop behavior
  - refusal sanitation: numbers inside a refusal are replaced AND the
    first pass is not credited as grounded
  - leakage detection: a shipped ungrounded number would be caught
  - aggregate(): rates, fallback reasons, latency percentiles
"""
import copy
import sys
import os
from datetime import date, datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models  # noqa: E402
from analytics import assistant, llm  # noqa: E402
import eval_assistant  # noqa: E402


def _sale(db, employee_id, when_dt, revenue, profit, items=None):
    s = models.Sale(employee_id=employee_id, customer_id=None,
                    payment_method="cash", total_revenue=revenue,
                    total_profit=profit, date=when_dt.date(),
                    time=when_dt.time())
    for product_id, qty, rp, cp in (items or []):
        s.items.append(models.SaleItem(product_id=product_id, quantity=qty,
                                       retail_price_at_sale=rp,
                                       cost_price_at_sale=cp))
    db.add(s)
    return s


def _seed(db):
    db.add(models.Owner(user_id=1, name="The Owner", user_type="owner",
                        phone_number="01700000001", password="x"))
    db.add(models.Employee(user_id=2, name="Rahim", user_type="employee",
                           password="x", employer_id=1))
    db.add(models.Product(product_id=1, product_name="Mustard Oil 1L",
                          cost_price=35.0, retail_price=50.0,
                          stock_quantity=100))
    now = datetime.now()
    _sale(db, 2, now.replace(hour=10), 300.0, 90.0, [(1, 4, 50.0, 35.0)])
    db.commit()


class ScriptedChat:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.calls = 0

    def __call__(self, context, tools_summary, **kwargs):
        self.calls += 1
        if not self.decisions:
            raise llm.ChatDecisionError("script exhausted")
        return self.decisions.pop(0)


@pytest.fixture()
def configured(monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda: True)


class TestTelemetry:
    def test_meta_rides_envelope(self, db_session, configured, monkeypatch):
        _seed(db_session)
        today = date.today().isoformat()
        script = ScriptedChat([
            {"action": "tool", "tool": "get_sales_metrics",
             "args": {"start": today, "end": today}},
            {"action": "final", "message": "Revenue was 300.0 today."},
        ])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(db_session, 1, "How's today?")
        meta = out["meta"]
        assert meta["rounds_used"] == 2
        assert meta["grounded_first_pass"] is True
        assert meta["refused"] is False
        assert meta["tool_calls_ok"] == 1
        assert meta["tool_errors"] == []
        assert meta["fallback_reason"] is None
        assert meta["context_bytes"] and all(b > 0 for b in meta["context_bytes"])
        assert meta["narration_retried"] is False

    def test_narration_retry_recorded(self, db_session, configured, monkeypatch):
        _seed(db_session)
        script = ScriptedChat([
            {"action": "final", "message": "You made 500.0 today!"},  # no data
            {"action": "final", "message": "Steady day."},            # clean
        ])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(db_session, 1, "hello")
        assert out["meta"]["narration_retried"] is True
        assert out["meta"]["grounded_first_pass"] is False
        assert out["message"] == "Steady day."

    def test_tool_error_recorded(self, db_session, configured, monkeypatch):
        _seed(db_session)
        today = date.today().isoformat()
        # Round 1: invalid metric -> ValueError observation; round 2: the
        # model corrects with another bad arg -> second error; round 3:
        # gives up with a clean number-free final.
        script = ScriptedChat([
            {"action": "tool", "tool": "get_top_products",
             "args": {"start": today, "end": today, "metric": "discount"}},
            {"action": "tool", "tool": "get_top_products",
             "args": {"start": today, "end": today, "method": "profit"}},
            {"action": "final", "message": "Steady day."},
        ])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(db_session, 1, "top product?")
        assert len(out["meta"]["tool_errors"]) == 2
        assert "metric" in out["meta"]["tool_errors"][0]["error"]

    def test_refusal_with_numbers_sanitized_and_not_credited(self, db_session,
                                                             configured,
                                                             monkeypatch):
        _seed(db_session)
        script = ScriptedChat([
            {"action": "refuse",
             "message": "I only know store data — like your 300.0 revenue."},
        ])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(db_session, 1, "weather?")
        # Number scrubbed, refusal still stands.
        assert out["message"] == assistant.REFUSAL_FALLBACK
        meta = out["meta"]
        assert meta["refused"] is True
        assert meta["grounded_first_pass"] is False  # not a clean pass

    def test_clean_refusal_credits_first_pass(self, db_session, configured,
                                              monkeypatch):
        _seed(db_session)
        script = ScriptedChat([
            {"action": "refuse",
             "message": "I can't answer that from store data."}])
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(db_session, 1, "weather?")
        assert out["meta"]["refused"] is True
        assert out["meta"]["grounded_first_pass"] is True


class TestLeakageDetection:
    def test_harness_catches_shipped_leak(self):
        """The harness's leakage invariant: a turn whose telemetry reports
        shipped_grounded=False must be flagged (this is the metric that
        must stay at 0)."""
        case = dict(id="x", kind="data",
                    expected_tools=["get_sales_metrics"], q="t")
        out = {
            "message": "Revenue was 999999.0 today!",
            "tool_calls": [{"tool": "get_sales_metrics", "args": {}}],
            "meta": {"rounds_used": 2, "narration_retried": False,
                     "grounded_first_pass": False, "refused": False,
                     "tool_calls_ok": 1, "tool_errors": [],
                     "context_bytes": [100, 200], "fallback_reason": None,
                     "shipped_grounded": False},
        }
        row = eval_assistant._metric_row(case, out, None, 1.5)
        assert row["shipped_grounded"] is False  # the leakage flag

        # And the aggregate reports it as the fatal metric.
        summary = eval_assistant.aggregate([row])
        assert summary["fabricated_number_leakage"] == 1


class TestAggregate:
    def _rows(self):
        return [
            dict(kind="data", latency_s=2.0, rounds=2,
                 grounded_first_pass=True, narration_retried=False,
                 refused=False, fallback_reason=None, tool_errors=[],
                 tool_selection_ok=True, answered_without_data=False,
                 shipped_grounded=True, context_bytes=[100, 150]),
            dict(kind="data", latency_s=8.0, rounds=3,
                 grounded_first_pass=False, narration_retried=True,
                 refused=False, fallback_reason="narration_double_fail",
                 tool_errors=[{"tool": "t", "error": "e"}],
                 tool_selection_ok=False, answered_without_data=False,
                 shipped_grounded=True, context_bytes=[120]),
            dict(kind="out_of_scope", latency_s=1.0, rounds=1,
                 grounded_first_pass=True, narration_retried=False,
                 refused=True, fallback_reason=None, tool_errors=[],
                 tool_selection_ok=True, answered_without_data=None,
                 shipped_grounded=True, context_bytes=[90]),
        ]

    def test_rates_and_percentiles(self):
        s = eval_assistant.aggregate(self._rows())
        assert s["turns"] == 3
        assert s["grounding_first_pass_rate"] == 50.0   # 1 of 2 data turns
        assert s["narration_retry_rate"] == 50.0
        assert s["fabricated_number_leakage"] == 0
        assert s["fallback_rate"] == pytest.approx(33.3)
        assert s["fallback_reasons"] == {"narration_double_fail": 1}
        assert s["refusal_precision"] == 100.0
        assert s["over_refusal_rate"] == 0.0
        assert s["tool_selection_accuracy"] == 50.0
        assert s["answered_without_data_rate"] == 0.0
        assert s["tool_arg_error_rate"] == pytest.approx(33.3)
        assert s["cap_exhaustion_rate"] == 0.0
        assert s["avg_rounds_per_turn"] == 2.0
        assert s["latency_p50_s"] == 2.0
        assert s["latency_p95_s"] == 8.0  # nearest-rank: 3rd of 3
        assert s["context_bytes_p50"] == 110  # median of [100,150,120,90]

    def test_empty_suite_is_safe(self):
        s = eval_assistant.aggregate([])
        assert s["turns"] == 0
        assert s["grounding_first_pass_rate"] is None

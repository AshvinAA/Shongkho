"""
Protik language switch tests (docs/PROTIK_BANGLA_PLAN.md §1–§4).

The LLM is scripted exactly like test_assistant.py — no network. Covers:
  - owner preference persistence (PUT /auth/me/preferences, /auth/me)
  - 'bn' force mode: prompt context carries force_language, Bangla
    fallbacks ship for deterministic answers
  - 'auto'/'en' behavior unchanged
  - Banglish/Bangla shield trigger words (conversation, prediction,
    world knowledge, domain classification)
  - dashboard language=bn serves the bn insights snapshot when one
    exists, falls back honestly when it doesn't
  - llm.detect_language Bengali-script ratio heuristic
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models  # noqa: E402
from analytics import assistant, llm, insights  # noqa: E402


def _llm_up(monkeypatch):
    """Hermetic LLM: configured + a chat_decide the test controls."""
    monkeypatch.setattr(llm, "is_configured", lambda: True)


class ScriptedChat:
    """Scriptable stand-in for llm.chat_decide (captures context)."""

    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.contexts = []

    def __call__(self, context, tools_summary, **kwargs):
        self.contexts.append(context)
        return self.decisions.pop(0)


class ScriptedChat:
    """Scriptable stand-in for llm.chat_decide (captures context)."""

    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.contexts = []

    def __call__(self, context, tools_summary, **kwargs):
        self.contexts.append(context)
        return self.decisions.pop(0)


# ---------------------------------------------------------
# Preference persistence (plan §5)
# ---------------------------------------------------------
class TestPreferences:
    def test_me_defaults_to_auto(self, client, owner):
        body = client.get("/api/v1/auth/me").json()
        assert body["assistant_language"] == "auto"

    def test_put_and_roundtrip(self, client, owner):
        r = client.put("/api/v1/auth/me/preferences",
                       json={"assistant_language": "bn"})
        assert r.status_code == 200
        assert r.json()["assistant_language"] == "bn"
        assert client.get("/api/v1/auth/me").json()["assistant_language"] == "bn"

    def test_rejects_invalid_mode(self, client, owner):
        r = client.put("/api/v1/auth/me/preferences",
                       json={"assistant_language": "fr"})
        assert r.status_code == 422

    def test_employee_gets_403(self, client, employee):
        r = client.put("/api/v1/auth/me/preferences",
                       json={"assistant_language": "bn"})
        assert r.status_code == 403

    def test_anonymous_gets_401(self, client):
        r = client.put("/api/v1/auth/me/preferences",
                       json={"assistant_language": "bn"})
        assert r.status_code == 401


# ---------------------------------------------------------
# Chat language modes (plan §1–§2)
# ---------------------------------------------------------
class TestChatLanguageModes:
    def test_bn_force_sets_context_directive(self, db_session, monkeypatch):
        script = ScriptedChat([
            {"action": "final", "message": "আজ ভালো আছি! কী দেখব?"}
        ])
        _llm_up(monkeypatch)
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(db_session, 1, "how are you",
                                       language="bn")
        # Bangla ships and the directive reached the prompt context.
        assert "আছি" in out["message"]
        assert script.contexts[0]["force_language"] == "bn"
        assert out["meta"]["language_mode"] == "bn"

    def test_bn_force_translates_fallbacks(self, db_session, monkeypatch):
        # A data question the scripted model cannot answer twice: the
        # double-fail rescue auto-fetches and the deterministic
        # synthesizer ships — in BANGLA when the mode forces it (empty
        # store -> the honest zero-sales template, Western digits).
        script = ScriptedChat([
            {"action": "final", "message": "I think 42 orders happened."},
            {"action": "final", "message": "Maybe around 12."},
            {"action": "final", "message": "Probably steady."},
        ])
        _llm_up(monkeypatch)
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(
            db_session, 1, "How are we doing on sales today?", language="bn")
        assert "বিক্রি হয়নি" in out["message"]
        assert out["meta"]["fallback_reason"] == "synthesized"

    def test_en_mode_keeps_english_fallbacks(self, db_session, monkeypatch):
        script = ScriptedChat([
            {"action": "final", "message": "I predict 999 sales tomorrow."},
            {"action": "final", "message": "Probably a lot."},
            {"action": "final", "message": "Probably steady."},
        ])
        _llm_up(monkeypatch)
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(
            db_session, 1, "How are we doing on sales today?", language="en")
        assert "no sales were recorded" in out["message"].lower()
        # English questions still detected as 'en'.
        assert out["meta"]["detected_language"] == "en"

    def test_auto_uses_owner_preference(self, db_session, monkeypatch):
        db_session.add(models.Owner(user_id=1, name="O", user_type="owner",
                                    phone_number="01700000001", password="x",
                                    assistant_language="bn"))
        db_session.commit()
        _llm_up(monkeypatch)
        monkeypatch.setattr(llm, "chat_decide", ScriptedChat([
            {"action": "final", "message": "আমি প্রতীক — আপনার সহ-পাইলট।"}
        ]))
        out = assistant.handle_message(db_session, 1, "tumi kemon acho")
        assert out["meta"]["language_mode"] == "bn"

    def test_request_overrides_persisted(self, db_session, monkeypatch):
        db_session.add(models.Owner(user_id=1, name="O", user_type="owner",
                                    phone_number="01700000001", password="x",
                                    assistant_language="bn"))
        db_session.commit()
        script = ScriptedChat([
            {"action": "final", "message": "Doing great — what shall we dig into?"}
        ])
        _llm_up(monkeypatch)
        monkeypatch.setattr(llm, "chat_decide", script)
        out = assistant.handle_message(db_session, 1, "how are you",
                                       language="en")
        assert out["meta"]["language_mode"] == "en"
        # No Bangla fallback swap on English text.
        assert "co-pilot" in out["message"] or "great" in out["message"]

    def test_route_accepts_language_field(self, client, owner, monkeypatch):
        monkeypatch.setattr(llm, "is_configured", lambda: True)
        monkeypatch.setattr(assistant, "messages_today", lambda db, oid: 0)

        captured = {}

        def fake_handle(db, owner_id, message, language=None):
            captured["language"] = language
            return {"message": "ok", "tool_calls": [], "meta": {}}

        monkeypatch.setattr(assistant, "handle_message", fake_handle)
        r = client.post("/api/v1/analytics/chat",
                        json={"message": "hi", "language": "bn"})
        assert r.status_code == 200
        assert captured["language"] == "bn"

    def test_route_rejects_bad_language(self, client, owner):
        r = client.post("/api/v1/analytics/chat",
                        json={"message": "hi", "language": "fr"})
        assert r.status_code == 422


# ---------------------------------------------------------
# Banglish / Bangla shields (plan §3)
# ---------------------------------------------------------
class TestBanglaShields:
    def test_banglish_conversation_ask(self, db_session, monkeypatch):
        _llm_up(monkeypatch)
        monkeypatch.setattr(llm, "chat_decide", ScriptedChat([
            {"action": "final", "message": "ভালো আছি! আপনি কেমন আছেন?"}
        ]))
        out = assistant.handle_message(db_session, 1, "kemon acho?",
                                       language="en")
        assert "আছি" in out["message"]

    def test_bangla_prediction_redirects(self, db_session, monkeypatch):
        _llm_up(monkeypatch)
        monkeypatch.setattr(llm, "chat_decide", ScriptedChat([
            {"action": "refuse", "message": "I can't predict that."}
        ]))
        out = assistant.handle_message(
            db_session, 1, "আগামী মাসে বিক্রি কত হবে?", language="auto")
        assert out["message"] == assistant.PREDICTION_REDIRECT
        assert out["meta"]["fallback_reason"] == "prediction_redirect"

    def test_banglish_weather_refuses(self, db_session, monkeypatch):
        _llm_up(monkeypatch)
        monkeypatch.setattr(llm, "chat_decide", ScriptedChat([
            {"action": "refuse", "message": "I only know store data."}
        ]))
        out = assistant.handle_message(
            db_session, 1, "আবহাওয়া কেমন হবে কাল?", language="auto")
        assert out["meta"]["refused"] is True

    def test_bangla_sales_domain_classified(self, db_session):
        assert assistant._question_domain(db_session, 1, "আজ বিক্রি কেমন হয়েছে?") == "sales"

    def test_banglish_employee_domain(self, db_session):
        db_session.add(models.Employee(user_id=2, name="Rahim",
                                       user_type="employee", password="x",
                                       employer_id=1))
        db_session.commit()
        assert assistant._question_domain(db_session, 1,
                                          "kormochari ra kemon koreche?") == "employee"


# ---------------------------------------------------------
# detect_language (plan §7)
# ---------------------------------------------------------
class TestDetectLanguage:
    def test_bangla_script(self):
        assert llm.detect_language("আজ বিক্রি কেমন হয়েছে?") == "bn"

    def test_english(self):
        assert llm.detect_language("How are sales today?") == "en"

    def test_banglish_is_latin(self):
        assert llm.detect_language("aj bikri kemon hoyeche?") == "en"

    def test_empty(self):
        assert llm.detect_language("") == "en"

    def test_bengali_numerals_normalized(self):
        """Plan §8 risk, live-verified: the model writes ১৩৫০ despite
        the prompt rule. Shipped text is transliterated to Western
        digits (Python \d already matches Bengali digits, so the gates
        see them — normalization keeps good replies from being replaced)."""
        assert assistant._normalize_bn_numerals(
            "আজ ১৩৫০ টাকা বিক্রি, ৪০০ লাভ।") == "আজ 1350 টাকা বিক্রি, 400 লাভ।"

    def test_bengali_digit_reply_never_ships(self, db_session, monkeypatch):
        """A Bengali-numerals reply to a greeting trips the digits gate
        (\d matches Bengali digits) — the corrective round ships a
        clean, number-free line instead."""
        _llm_up(monkeypatch)
        monkeypatch.setattr(llm, "chat_decide", ScriptedChat([
            {"action": "final", "message": "আজ ১৩৫০ টাকা বিক্রি হয়েছে।"},
            {"action": "final", "message": "ভালো আছি! আপনি কেমন আছেন?"},
        ]))
        out = assistant.handle_message(db_session, 1, "how are you",
                                       language="bn")
        assert "১৩৫০" not in out["message"]
        assert "১" not in out["message"]


# ---------------------------------------------------------
# Synthesizer templates in Bangla (plan §3)
# ---------------------------------------------------------
class TestSynthBangla:
    def _sales_payload(self):
        today = date.today().isoformat()
        return {"tool": "get_sales_metrics",
                "args": {"start": today, "end": today},
                "data": {"totals": {"revenue": 500.0, "orders": 8,
                                    "profit": 150.0}}}

    def test_sales_template_bn(self, db_session):
        out = assistant._synth_answer("আজ বিক্রি কেমন?", "sales",
                                     [self._sales_payload()], force_bn=True)
        assert "৫০০" not in out and "500.0" in out  # Western digits only
        assert "অর্ডার" in out

    def test_sales_template_en(self, db_session):
        out = assistant._synth_answer("How's today?", "sales",
                                     [self._sales_payload()], force_bn=False)
        assert "Your store took 500.0" in out


# ---------------------------------------------------------
# Dashboard insights cache by language (plan §4)
# ---------------------------------------------------------
class TestDashboardLanguage:
    def _add_insight(self, db_session, run_id, section, summary):
        db_session.add(models.AnalyticsSnapshot(
            run_id=run_id, owner_id=1, section=section,
            period_type="week",
            data={"summary": summary, "observations": [],
                  "areas_to_watch": []},
        ))

    def test_serves_bn_snapshot_when_present(self, client, owner, db_session):
        db_session.add(models.AnalysisRun(
            id="run-bn", owner_id=1, status="COMPLETED"))
        self._add_insight(db_session, "run-bn", "insights", "English summary")
        self._add_insight(db_session, "run-bn", "insights_bn",
                          "বাংলা সারসংক্ষেপ")
        db_session.commit()

        r = client.get("/api/v1/analytics/dashboard?period=week&language=bn")
        assert r.status_code == 200
        snap = r.json()["sections"]["insights"]
        assert snap["summary"] == "বাংলা সারসংক্ষেপ"
        assert snap["language"] == "bn"

    def test_falls_back_to_english_honestly(self, client, owner, db_session):
        db_session.add(models.AnalysisRun(
            id="run-en", owner_id=1, status="COMPLETED"))
        self._add_insight(db_session, "run-en", "insights", "English summary")
        db_session.commit()

        r = client.get("/api/v1/analytics/dashboard?period=week&language=bn")
        assert r.status_code == 200
        snap = r.json()["sections"]["insights"]
        assert snap["summary"] == "English summary"
        assert snap["missing_language"] == "bn"

    def test_english_request_hides_bn_section(self, client, owner, db_session):
        db_session.add(models.AnalysisRun(
            id="run-x", owner_id=1, status="COMPLETED"))
        self._add_insight(db_session, "run-x", "insights", "English summary")
        self._add_insight(db_session, "run-x", "insights_bn", "বাংলা")
        db_session.commit()

        r = client.get("/api/v1/analytics/dashboard?period=week")
        assert r.status_code == 200
        sections = r.json()["sections"]
        assert sections["insights"]["summary"] == "English summary"
        assert "insights_bn" not in sections

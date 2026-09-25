"""
Part B — conversational analytics orchestration (docs/LLM_INTEGRATION.md §3).

The agent loop, the memory split, and the response envelope:

  - MEMORY VS STORAGE: every turn is PERSISTED in assistant_messages
    (cap counting, reload, audit); the prompt window is only a
    PROJECTION of the last N turns carrying {role, message, tool_names}
    — never tool payloads (doc §3.2: results must be re-fetched, not
    remembered).
  - LOOP: bounded at ASSISTANT_TOOL_CALL_CAP tool calls. Tool errors
    (ValueError) go back to the model as the observation for ONE counted
    corrective retry. A turn that never reaches `final` degrades to a
    fixed fallback message — never a 500.
  - ENVELOPE: text-only product — the LLM writes `message`, and that
    is the deliverable. The narration runs the Part A number checker
    against the accumulated tool results; on failure the message is
    replaced with an honest fallback pointing at the dashboard charts.
    The checker keeps every shipped number real.
  - store_id/owner_id is injected server-side everywhere; the LLM never
    supplies scope and never gets write access to anything.

No DB transaction spans an LLM call: rows are committed per-turn, the
LLM calls happen between commits.
"""
from datetime import date, datetime, timedelta

from analytics import insights, llm, tools

# Env-tunable limits (doc §4 defaults).
WINDOW_TURNS = 8       # sliding-window projection size (turns)
DAILY_CAP = 20         # assistant messages / day / store
TOOL_CALL_CAP = 5      # hard agent-loop bound

# Text-only product: the charts live on the dashboard; the assistant's
# deliverable is advice in prose. Tool payloads ground the numbers and
# feed the checker — they just never render as UI blocks.

FALLBACK_MESSAGE = "I wasn't able to work that out — try rephrasing?"
NARRATION_FALLBACK = (
    "I pulled your store data but couldn't phrase the answer reliably — "
    "the dashboard charts have the numbers. Try rephrasing?"
)
NOT_CONFIGURED_MESSAGE = "Assistant is not configured"
REFUSAL_FALLBACK = "I can't answer that from store data."
# Refusal AFTER this turn fetched data — the model was told to answer
# with the results and refused again; its refusal text is untrustworthy
# there (observed: it echoes the corrective error verbatim). Ship a
# fixed honest line instead.
REFUSAL_AFTER_DATA_FALLBACK = (
    "I pulled the numbers but couldn't land on solid advice for that — "
    "try rephrasing?"
)


class AssistantUnavailable(Exception):
    """The LLM provider is not configured — deterministic 503 path."""


class DailyCapReached(Exception):
    """The owner used their assistant messages for today — 429 path."""

    def __init__(self, cap: int):
        super().__init__(f"daily cap {cap} reached")
        self.cap = cap


# ---------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------
def _today_bounds():
    now = datetime.utcnow()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def messages_today(db, owner_id: int) -> int:
    """Assistant turns persisted today — the doc §3.6 cap counter."""
    import models
    start, end = _today_bounds()
    return db.query(models.AssistantMessage).filter(
        models.AssistantMessage.owner_id == owner_id,
        models.AssistantMessage.role == "assistant",
        models.AssistantMessage.created_at >= start,
        models.AssistantMessage.created_at < end,
    ).count()


def persist_turn(db, owner_id: int, role: str, message: str,
                 tool_calls=None):
    """One assistant_messages row; committed by the caller's next commit."""
    import models
    row = models.AssistantMessage(
        owner_id=owner_id,
        role=role,
        message=message,
        tool_calls=tool_calls,
    )
    db.add(row)
    db.commit()
    return row


def chat_history(db, owner_id: int, limit: int = 50):
    """Reload projection for the frontend: newest last, text-only."""
    import models
    rows = (
        db.query(models.AssistantMessage)
        .filter(models.AssistantMessage.owner_id == owner_id)
        .order_by(models.AssistantMessage.id.desc())
        .limit(limit)
        .all()
    )
    return [{
        "role": r.role,
        "message": r.message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in reversed(rows)]


def _window_projection(db, owner_id: int):
    """
    The prompt projection (doc §3.2): last WINDOW_TURNS turns as
    {role, message, tool_names}. Payloads never re-enter the window.
    """
    import models
    rows = (
        db.query(models.AssistantMessage)
        .filter(models.AssistantMessage.owner_id == owner_id)
        .order_by(models.AssistantMessage.id.desc())
        .limit(WINDOW_TURNS)
        .all()
    )
    return [{
        "role": r.role,
        "message": r.message,
        "tool_names": [tc.get("tool") for tc in (r.tool_calls or [])
                       if isinstance(tc, dict)],
    } for r in reversed(rows)]


def _tools_summary() -> str:
    """One line per registry tool: name(args) — description."""
    lines = []
    for name, entry in tools.REGISTRY.items():
        lines.append(f"{name}({', '.join(entry['args'])}): {entry['description']}")
    return "\n".join(lines)


# ---------------------------------------------------------
# Narration check (doc §3.4) — same checker as Part A
# ---------------------------------------------------------
def _narration_grounded(message: str, tool_results: list) -> bool:
    """
    Every number in the final message must trace to the accumulated
    tool results. Reuses Part A's tolerant checker verbatim: the
    results form the grounding bundle, checked as a whole.
    """
    if not tool_results:
        # No data was fetched: only number-free prose is acceptable.
        return not insights._numbers_in(message)  # noqa: SLF001
    bundle = {"results": tool_results}
    return insights._check_text(message, bundle, "bundle")  # noqa: SLF001


# ---------------------------------------------------------
# The agent loop (doc §3.4)
# ---------------------------------------------------------
def handle_message(db, owner_id: int, user_message: str) -> dict:
    """
    One full assistant turn. Returns the response envelope:
      {"message": str, "tool_calls": [...], "meta": {...}}

    Raises AssistantUnavailable (-> 503) when the LLM is not configured,
    DailyCapReached (-> 429) when today's budget is spent. Never raises
    for LLM/tool failures — those degrade to honest fallback messages.
    """
    if not llm.is_configured():
        raise AssistantUnavailable(NOT_CONFIGURED_MESSAGE)

    used = messages_today(db, owner_id)
    if used >= DAILY_CAP:
        raise DailyCapReached(DAILY_CAP)

    # Telemetry: observational only — the eval harness and latency/cost
    # metrics read this; the frontend ignores unknown envelope keys.
    telemetry = {
        "rounds_used": 0,
        "narration_retried": False,
        "grounded_first_pass": None,   # first final: checker verdict
        "refused": False,
        "tool_calls_ok": 0,
        "tool_errors": [],             # [{tool, error}]
        "context_bytes": [],           # per-round prompt size (cost proxy)
        "fallback_reason": None,       # decision_error | cap_exhausted |
                                       # narration_double_fail | no_reply
    }

    # Persist the user turn FIRST (audit + window projection).
    persist_turn(db, owner_id, "user", user_message)

    # `tool_results` starts as an explicit empty cue (not an omitted
    # key): a 3B model treats an absent key as "nothing to do" and
    # answers from memory. With `tool_results: []` in front of it, the
    # few-shot examples in CHAT_SYSTEM_PROMPT route it to a tool call.
    context = {
        "today": date.today().isoformat(),
        "conversation": _window_projection(db, owner_id),
        "tool_results": [],
    }
    tools_summary = _tools_summary()

    accumulated = []   # successful tool payloads (grounding + audit)
    executed = []      # [{tool, args}] for persistence + audit
    observations = []  # per-round results/errors fed back to the model
    reply = None
    refused = False
    narration_retried = False

    for _round in range(TOOL_CALL_CAP):
        telemetry["rounds_used"] = _round + 1
        telemetry["context_bytes"].append(
            len(llm.dumps(context)) + len(tools_summary))
        try:
            decision = llm.chat_decide(context, tools_summary)
        except llm.ChatDecisionError as exc:
            # Provider down / budget gone / unparseable: degrade honestly
            # (doc: never a 500 for LLM failures).
            print(f"[assistant] decision failed: {exc}")
            reply = FALLBACK_MESSAGE
            telemetry["fallback_reason"] = "decision_error"
            break
        action = decision.get("action")

        if action == "refuse":
            # Refuse AFTER this turn already fetched data is a 3B-model
            # misfire (it just decided the question needed data): earn
            # one corrective retry, same economics as a bad narration.
            # A second one is untrustworthy text (observed: the model
            # echoes the corrective error verbatim) — fixed line, and
            # NOT a clean refusal for telemetry.
            if accumulated and not narration_retried \
                    and _round < TOOL_CALL_CAP - 1:
                narration_retried = True
                telemetry["narration_retried"] = True
                print("[assistant] refuse after fetching data — asking "
                      "the model to answer with the results instead")
                observations.append({
                    "error": ("You already fetched data for this "
                              "question. Refusing now is wrong: answer "
                              "with ONLY the numbers in tool_results.")
                })
                context["tool_results"] = observations
                continue
            if accumulated:
                reply = REFUSAL_AFTER_DATA_FALLBACK
                refused = True
                telemetry["refused"] = True
                telemetry["grounded_first_pass"] = False
                telemetry["fallback_reason"] = "refuse_after_data"
                break
            # Out-of-scope refusal: ship as-is when clean. A number
            # inside a refusal is ungrounded prose — sanitize to the
            # fixed text immediately (a retry cannot help: the model
            # has already decided the question is out of scope), and
            # do not credit it as a grounded first pass.
            reply = decision.get("message")
            refused = True
            telemetry["refused"] = True
            polluted = insights._numbers_in(reply or "")  # noqa: SLF001
            telemetry["grounded_first_pass"] = not polluted
            if polluted:
                print("[assistant] refusal contained numbers — "
                      "replacing with the fixed refusal text")
                reply = REFUSAL_FALLBACK
            break

        if action == "final":
            reply = decision.get("message")
            grounded = _narration_grounded(reply or "", accumulated)
            if telemetry["grounded_first_pass"] is None:
                telemetry["grounded_first_pass"] = grounded
            if grounded:
                break
            # Narration self-correction (same economics as the tool
            # ValueError retry, counted against the cap): the model
            # answered with numbers that no tool result backs — or with
            # no tool called at all. Feed the failure back once; if it
            # happens again the post-loop gate replaces the message.
            if narration_retried or _round >= TOOL_CALL_CAP - 1:
                break
            narration_retried = True
            telemetry["narration_retried"] = True
            print("[assistant] narration failed the number check — "
                  "asking the model to fetch data first")
            # The corrective message must match the failure shape: with
            # data in hand the fix is "quote verbatim" ("call the tool
            # first" makes the model drop ALL numbers instead); with no
            # data the fix is to actually fetch.
            if accumulated:
                observations.append({
                    "error": ("Your reply contained numbers that do not "
                              "appear in tool_results (computed or "
                              "invented). Rewrite it: quote ONLY numbers "
                              "that appear verbatim in tool_results — "
                              "never a difference, total or percentage "
                              "you calculated yourself.")
                })
            else:
                observations.append({
                    "error": ("Your reply contained numbers but you "
                              "called no tool this turn. Call the right "
                              "tool first, then answer using ONLY numbers "
                              "from its result.")
                })
            context["tool_results"] = observations
            reply = None
            continue

        # action == "tool"
        name = decision["tool"]
        args = decision.get("args") or {}
        executed.append({"tool": name, "args": args})
        try:
            payload = tools.execute(db, owner_id, name, args)
        except ValueError as exc:
            # Self-correction: the error text IS the observation; the
            # roundtrip is counted against the cap like any other round.
            observations.append({"tool": name, "error": str(exc)})
            telemetry["tool_errors"].append(
                {"tool": name, "error": str(exc)})
            context["tool_results"] = observations
            continue

        accumulated.append({"tool": name, "data": payload})
        telemetry["tool_calls_ok"] += 1
        observations.append({"tool": name, "result": payload})
        context["tool_results"] = observations
    else:
        # Loop cap exhausted without a final answer (doc §3.4).
        reply = FALLBACK_MESSAGE
        telemetry["fallback_reason"] = "cap_exhausted"

    # ---- narration gate: numbers in prose must trace to tool data ----
    # Text-only product: the reply IS the deliverable, so an ungrounded
    # reply degrades to an honest fallback that points at the charts
    # instead of shipping a wrong number.
    if refused:
        # Already sanitized in the loop (numbers -> fixed refusal text).
        pass
    elif not _narration_grounded(reply or "", accumulated):
        # Covers BOTH failure shapes: fabricated numbers WITH tool data,
        # and numbers with NO data behind them at all.
        print("[assistant] narration failed the number check — "
              "replacing message with the fallback")
        reply = (NARRATION_FALLBACK if accumulated else FALLBACK_MESSAGE)
        telemetry["fallback_reason"] = "narration_double_fail"
    elif not reply:
        reply = FALLBACK_MESSAGE
        telemetry["fallback_reason"] = "no_reply"

    # Shipped-grounding invariant for the eval harness: whatever leaves
    # this function must be checker-clean or a fixed no-number fallback.
    # True by construction today; a False here means a code path regressed
    # into shipping raw model text (eval_assistant.py flags it as the
    # fatal fabricated_number_leakage metric).
    if refused:
        telemetry["shipped_grounded"] = not insights._numbers_in(reply or "")  # noqa: SLF001
    else:
        telemetry["shipped_grounded"] = _narration_grounded(reply or "", accumulated)

    persist_turn(db, owner_id, "assistant", reply,
                 tool_calls=executed or None)

    return {
        "message": reply,
        "tool_calls": executed,
        "meta": telemetry,
    }

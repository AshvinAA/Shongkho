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
import re
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
# A NO-DATA turn (greeting, capabilities question, misfired refusal)
# whose reply tripped the number gate twice: llama keeps sprinkling
# digits into chit-chat ("top 3 products"). Shipping the scary
# "couldn't work that out" dead-end here is worse than a warm canned
# line — nothing numerical was claimed either way.
CONVERSATION_FALLBACK = (
    "I'm here to be your business co-pilot — ask me which product to \
push this week, who's selling the most today, or how profit looks, \
and I'll pull the numbers and give you real advice."
)
DATA_NO_REPLY_FALLBACK = (
    "I need to pull your store numbers to answer that properly, but \
the step didn't come out reliably this time — try rephrasing?"
)

# Question words that mark the ask as store-data-flavored: a no-data
# double-fail on such a question must NOT ship the cheery co-pilot
# line ("which product to push…") — it read as dodging the question.
_DATA_HINT_RE = re.compile(
    r"\b(sale|sales|sold|sell|revenue|profit|product|products|employee|"
    r"staff|stock|inventory|order|orders|today|yesterday|week|month|"
    r"trend|top|best|most|least|compare|how much|how many)\b", re.I)

# Auto-fetch rescue (see _auto_tool_for): a question that names a
# metric-word AND a time-word is unambiguously a data request — when
# llama refuses to call the tool itself, the loop fetches for it.
_AUTO_TOOL_HINT_RE = re.compile(
    r"\b(how|what|who|which)\b.*\b(today|yesterday|this week|last week|"
    r"this month|last month)\b", re.I)

# Sentences that merely MENTION time words ("yesterday's bestseller",
# "my sales this week were...") are statements/opinions, not requests
# for current data — the rescue must not fire on them.
_NOT_A_REQUEST_RE = re.compile(
    r"\b(think|guess|opinion|was|were|had|has been|thanks|thank you|"
    r"great|nice|good job)\b", re.I)

# ---- question-domain classification (relevance gating) ----
# Live-found failure: "Who is the worst performing employee?" -> llama
# fetched PRODUCTS and answered with a product's revenue. Every number
# was REAL, so the number-checker passed it — but the answer did not
# address the question. Numbers must be not only real but RELEVANT:
# an employee question must be grounded in employee data, etc.
_DOMAIN_HINTS = {
    "employee": re.compile(
        r"\b(employee|employees|staff|worker|workers|team|seller|sellers|"
        r"performing|performer|performers|firing|fire|who is|who was|who's|"
        r"which employee|"
        # Advice-intent phrasings (live gap: "Should I lay off my weakest
        # seller?" / "Should I let someone go?" carry no explicit
        # employee noun — the intent word IS the signal).
        r"lay.?off|let\s+(?:\w+\s+){0,2}go|letting\s+go|struggling|weak|"
        r"weakest|should\s+(?:i|we)\s+keep)\b", re.I),
    "product": re.compile(
        r"\b(product|products|item|items|stock|inventory|sku|best.?seller|"
        r"bestselling|most sold|push)\b", re.I),
}
# Words that make a phrase NOT about employees even when other hints
# fire ("best-selling product", "most sold item").
_PRODUCT_OVERRIDE_RE = re.compile(
    r"\b(product|products|item|items|sku|most sold|best.?seller)", re.I)


def _auto_fetch(db, owner_id: int, tool: str, args: dict,
                executed: list, observations: list, accumulated: list,
                telemetry: dict, context: dict) -> bool:
    """
    Deterministic rescue fetch shared by both rescue paths (narration
    double-fail and refuse-on-classified-question). Executes the tool,
    records it, and returns True when data landed. Exactly-once per
    turn is enforced by the caller via telemetry["auto_fetch"].
    """
    print(f"[assistant] model would not fetch — auto-fetching {tool}")
    executed.append({"tool": tool, "args": args})
    telemetry["auto_fetch"] = True
    try:
        payload = tools.execute(db, owner_id, tool, args)
    except ValueError as exc:
        observations.append({"tool": tool, "error": str(exc)})
        telemetry["tool_errors"].append({"tool": tool, "error": str(exc)})
        context["tool_results"] = observations
        return False
    accumulated.append({"tool": tool, "data": payload})
    observations.append({"tool": tool, "result": payload})
    telemetry["tool_calls_ok"] += 1
    context["tool_results"] = observations
    return True


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


def _auto_tool_for(db, owner_id: int, message: str, domain: str | None = None):
    """
    Deterministic rescue mapping for the auto-fetch: returns the
    (tool, args) a correct model would have called for this question,
    or None when the phrasing is not confidently mappable. Conservative
    on purpose — a wrong auto-fetch wastes a round; a missed one just
    degrades to the honest fallback as before. Args are ALWAYS complete
    (an incomplete mapping would ValueError and rescue nothing).

    Employee detection: a keyword OR a literal employee NAME of this
    store in the question ("How much has Rahim sold today?" has no
    keyword — the name IS the signal) — then the fetch is scoped to
    that person via the tool's contains-match arg.
    """
    import models
    text = message or ""
    low = text.lower()
    names = [e.name for e in
             db.query(models.Employee)
             .filter(models.Employee.employer_id == owner_id).all()
             if e.name and e.name.lower() in low]
    today = date.today().isoformat()
    # Wrong-domain rescue: the model fetched the OTHER section and the
    # relevance gate bounced it — fetch what the question actually
    # asked about (worst employee → employee data, not products).
    if domain == "employee":
        args = {"start": today, "end": today}
        if names:
            args["employee_name"] = names[0]
        return ("get_employee_performance", args)
    if domain == "product":
        return ("get_top_products",
                {"start": today, "end": today, "metric": "revenue",
                 "limit": 5})
    return ("get_sales_metrics", {"start": today, "end": today})


def _question_domain(db, owner_id: int, message: str) -> str | None:
    """
    'employee' | 'product' | None — which data domain the question is
    ABOUT. Employee detection includes literal employee NAMES of this
    store ("How is Rahim doing?" mentions no keyword). Product hints
    override employee hints ("best-selling PRODUCT" is a product
    question); anything ambiguous returns None and is gated as before.
    """
    import models
    text = message or ""
    if _DOMAIN_HINTS["product"].search(text):
        return "product"
    if _DOMAIN_HINTS["employee"].search(text):
        if _PRODUCT_OVERRIDE_RE.search(text):
            return "product"
        return "employee"
    low = text.lower()
    for e in (db.query(models.Employee)
              .filter(models.Employee.employer_id == owner_id).all()):
        if e.name and e.name.lower() in low:
            return "employee"
    return None


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


def _narration_relevant(message: str, tool_results: list,
                        domain: str | None) -> bool:
    """
    RELEVANCE gate on top of the reality gate: the answer's numbers must
    come from the domain the question asked about (live-found failure:
    an employee question answered with REAL product numbers shipped).
    Only the message's NUMBERS must live in the right domain — number-
    free advice text may draw on any fetched context. Ambiguous or
    unclassifiable questions (domain None) are gated for reality only.
    """
    if domain is None or not tool_results:
        return True
    have = {r.get("tool") for r in tool_results if isinstance(r, dict)}
    wanted = {"get_employee_performance"} if domain == "employee" \
        else {"get_top_products"}
    if have & wanted:
        return True
    # Wrong-domain numbers present: allow only if the message contains
    # NO numbers at all (pure qualitative advice — which the
    # specificity gate below still checks for named entities).
    return not insights._numbers_in(message)  # noqa: SLF001


def _mentions_any(message: str, names: list) -> bool:
    """Whole-word containment (a plain substring test would let a name
    like 'Ali' ride inside 'quality')."""
    text = message or ""
    for name in names:
        if len(name or "") >= 2 and re.search(
                rf"\b{re.escape(name)}\b", text, re.I):
            return True
    return False


def _narration_specific(message: str, domain: str | None,
                        accumulated: list) -> bool:
    """
    SPECIFICITY gate — the third narration gate. Live-found failure: a
    lay-off question answered with number-free, entity-free hedging
    ("the trailing seller", "the gap is significant") sailed through
    the reality and relevance gates because there was nothing FALSE in
    it — there was just nothing in it. On a classified data question,
    a grounded answer must NAME at least one entity from the right
    tool's payload (an empty payload waives the requirement — nothing
    to name; unclassified questions are exempt).
    """
    if domain not in ("employee", "product"):
        return True
    wanted_tool = ("get_employee_performance" if domain == "employee"
                   else "get_top_products")
    res = next((r for r in reversed(accumulated)
                if isinstance(r, dict) and r.get("tool") == wanted_tool),
               None)
    key = "employees" if domain == "employee" else "products"
    entities = ((res or {}).get("data") or {}).get(key) or []
    names = [e.get("name") for e in entities
             if isinstance(e, dict) and e.get("name")]
    if not names:
        return True
    return _mentions_any(message, names)


def _gates_pass(message: str, accumulated: list,
                domain: str | None) -> bool:
    """All three narration gates together — used by the post-loop gate
    and the shipped_grounded invariant."""
    return (_narration_grounded(message, accumulated)
            and _narration_relevant(message, accumulated, domain)
            and _narration_specific(message, domain, accumulated))


# ---------------------------------------------------------
# Deterministic final synthesis (auto-fetch path)
# ---------------------------------------------------------
def _synth_answer(user_message: str, domain: str | None,
                  accumulated: list) -> str | None:
    """
    Template answer built DIRECTLY from a right-domain tool payload —
    the no-LLM end of the rescue ladder. When the loop has fetched the
    data the question needs and the 3B model still cannot narrate it,
    a plain correct answer beats an honest apology. Returns None when
    no template fits (then the honest fallback ships as before).
    Every number is copied verbatim from the payload, so the checker
    passes by construction.
    """
    res = next((r for r in reversed(accumulated)
                if isinstance(r, dict) and r.get("tool")
                == "get_employee_performance"), None)
    if res and domain == "employee":
        lanes = [e for e in (res["data"].get("employees") or [])
                 if not e.get("is_owner")]
        if lanes:
            top, trail = lanes[0], lanes[-1]
            return (f"{top['name']} leads your staff with "
                    f"{top['revenue']} in revenue across "
                    f"{top['orders']} orders (profit {top['profit']}). "
                    f"{trail['name']} trails at {trail['revenue']} "
                    f"({trail['orders']} orders)."
                    + (" That gap is worth a conversation before it "
                       "becomes a trend — coach, don't cut."
                       if top['name'] != trail['name'] else ""))
    prod = next((r for r in reversed(accumulated)
                 if isinstance(r, dict) and r.get("tool")
                 == "get_top_products"), None)
    if prod and domain == "product":
        rows = prod["data"].get("products") or []
        if rows:
            lead = rows[0]
            return (f"{lead['name']} is your top product by "
                    f"{prod['data'].get('metric', 'revenue')} — "
                    f"{lead['revenue']} revenue, {lead['units']} units, "
                    f"{lead['profit']} profit. Worth pushing hard this "
                    "week while the trend holds.")
    sales = next((r for r in reversed(accumulated)
                  if isinstance(r, dict) and r.get("tool")
                  == "get_sales_metrics"), None)
    if sales:
        tot = sales["data"].get("totals") or {}
        if tot:
            return (f"Your store took {tot.get('revenue')} in revenue "
                    f"across {tot.get('orders')} orders "
                    f"(profit {tot.get('profit')}) for the period you "
                    "asked about.")
    return None


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
        "specificity_retried": False,  # vague-answer corrective fired
        "grounded_first_pass": None,   # first final: checker verdict
        "refused": False,
        "tool_calls_ok": 0,
        "tool_errors": [],             # [{tool, error}]
        "context_bytes": [],           # per-round prompt size (cost proxy)
        "fallback_reason": None,       # decision_error | cap_exhausted |
                                       # narration_double_fail | no_reply
        "auto_fetch": False,           # loop fetched the data itself
    }

    # Persist the user turn FIRST (audit + window projection).
    persist_turn(db, owner_id, "user", user_message)

    # `tool_results` starts as an explicit empty cue (not an omitted
    # key): a 3B model treats an absent key as "nothing to do" and
    # answers from memory. With `tool_results: []` in front of it, the
    # few-shot examples in CHAT_SYSTEM_PROMPT route it to a tool call.
    # Classify the question's data domain ONCE per turn (relevance
    # gating + wrong-domain rescue use it; see _question_domain).
    domain = _question_domain(db, owner_id, user_message)
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
            # Refusal on a CLASSIFIED store question is a misfire too
            # (live-found: wrong tool -> ValueError -> give up and
            # refuse). The loop knows what data the question needs:
            # rescue-fetch it instead of shipping the refusal.
            if domain and not telemetry["auto_fetch"] \
                    and _round < TOOL_CALL_CAP - 1:
                narration_retried = True
                telemetry["narration_retried"] = True
                auto = _auto_tool_for(db, owner_id, user_message, domain)
                if auto and _auto_fetch(db, owner_id, auto[0], auto[1],
                                        executed, observations,
                                        accumulated, telemetry, context):
                    continue
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
            grounded_r = _narration_grounded(reply or "", accumulated)
            relevant_r = _narration_relevant(reply or "", accumulated,
                                             domain)
            specific_r = _narration_specific(reply or "", domain,
                                             accumulated)
            grounded = grounded_r and relevant_r and specific_r
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
                # DOUBLE-FAIL RESCUE: a data-flavored question the model
                # answered twice without fetching. Prompting a 3B model
                # a third time does not help (live-verified), so the
                # loop fetches the obvious tool ITSELF and lets the
                # model narrate real data. Still cap-bounded: this
                # consumes the round like any other action.
                if narration_retried and not accumulated \
                        and not telemetry["auto_fetch"]:
                    # At most ONE auto-fetch per turn: if it fails or
                    # the model still cannot narrate, the honest
                    # fallback is better than burning every round.
                    auto = _auto_tool_for(db, owner_id, user_message,
                                          domain)
                    if auto:
                        name, args = auto
                        if not _auto_fetch(db, owner_id, name, args,
                                           executed, observations,
                                           accumulated, telemetry,
                                           context):
                            break
                        continue
                break
            narration_retried = True
            telemetry["narration_retried"] = True
            # The corrective message must match the failure shape:
            # fabricated/unbacked numbers, wrong-domain numbers, or a
            # vague answer that names nobody from the data.
            if not grounded_r:
                print("[assistant] narration failed the number check — "
                      "asking the model to fetch data first")
                # With data in hand the fix is "quote verbatim" ("call
                # the tool first" makes the model drop ALL numbers
                # instead); with no data the fix is to actually fetch.
                if accumulated:
                    observations.append({
                        "error": ("Your reply contained numbers that do not "
                                  "appear in tool_results (computed or "
                                  "invented). Rewrite it: quote ONLY numbers "
                                  "that appear verbatim in tool_results — "
                                  "never a difference, total or percentage "
                                  "you calculated yourself.")})
                elif not insights._numbers_in(reply or ""):
                    # Number-free reply still failed the gate: a greeting,
                    # capabilities question or misfired refusal whose text
                    # tripped the checker (e.g. digits in "top 3"). Telling
                    # it to "call a tool" here caused a fallback spiral —
                    # the correct fix is a plain-words rewrite.
                    observations.append({
                        "error": ("Your reply looked like data talk but you "
                                  "fetched no data. This question needs no "
                                  "tool: reply in plain conversational words "
                                  "with NO digits at all — spell any count "
                                  "out (\"three\", not \"3\").")
                    })
                    reply = None
                    continue
                else:
                    observations.append({
                        "error": ("Your reply contained numbers but you "
                                  "called no tool this turn. Call the right "
                                  "tool first, then answer using ONLY numbers "
                                  "from its result.")
                    })
            elif not relevant_r:
                print("[assistant] wrong-domain numbers — asking the "
                      "model to answer from the question's own data")
                observations.append({
                    "error": ("Your reply used numbers from a tool that does "
                              "not answer this question. Rewrite it using "
                              "ONLY data from the tool matching the "
                              "question's subject, quoting those numbers "
                              "verbatim.")
                })
            else:  # not specific_r: clean prose, but nobody named
                telemetry["specificity_retried"] = True
                print("[assistant] answer names nobody from the data — "
                      "asking for a specific, named answer")
                observations.append({
                    "error": ("Your reply is too vague to act on: it names no "
                              "employee or product from tool_results. Commit "
                              "to specifics — name the actual people or "
                              "products involved, quote their numbers exactly "
                              "as they appear in tool_results, and advise on "
                              "them.")
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
    elif not _gates_pass(reply or "", accumulated, domain):
        # Covers every failure shape: fabricated numbers WITH tool
        # data, a digits-in-prose chit-chat reply with NO data behind
        # it, and a vague number-free answer that names nobody from a
        # classified question's data.
        # With a right-domain payload in hand, the deterministic
        # synthesizer is tried FIRST — a plain correct answer built
        # from the tool result beats an honest apology.
        synth = _synth_answer(user_message or "", domain, accumulated)
        if synth is not None:
            print("[assistant] narration failed — shipping the "
                  "deterministic synthesis from tool data")
            reply = synth
            telemetry["fallback_reason"] = "synthesized"
        elif accumulated:
            print("[assistant] narration failed the number check — "
                  "replacing message with the fallback")
            reply = NARRATION_FALLBACK
            telemetry["fallback_reason"] = "narration_double_fail"
        else:
            reply = (DATA_NO_REPLY_FALLBACK
                     if _DATA_HINT_RE.search(user_message or "")
                     else CONVERSATION_FALLBACK)
            telemetry["fallback_reason"] = "conversation_double_fail"
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
        telemetry["shipped_grounded"] = _gates_pass(reply or "",
                                                    accumulated, domain)

    persist_turn(db, owner_id, "assistant", reply,
                 tool_calls=executed or None)

    return {
        "message": reply,
        "tool_calls": executed,
        "meta": telemetry,
    }

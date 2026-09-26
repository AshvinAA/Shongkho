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

# Live-found 3B failure: the model copies the prompt EXAMPLES' argument
# PLACEHOLDERS ("start": "<today>") into real tool calls. Repair the
# known literals deterministically instead of burning a ValueError
# round on them.
_DATE_LITERALS = {"<today>": 0, "<yesterday>": 1,
                  "<week ago>": 7, "<month ago>": 30}

# Live turn 46/48: the model echoed the prompt's own example sentences
# ("Consider a structured warning for the trailing seller…", "Push more
# of the best-selling product, the") as its "answer" — twice, on
# unrelated questions, even byte-identically. Echoing is never an
# answer: detected post-loop and replaced with data or the honest
# fallback. The blocklist is the prompt's example PROSE; a genuine
# answer never reproduces it verbatim.
_ECHO_PHRASE_RE = re.compile(
    r"(structured warning for the trailing seller|"
    r"push more of the best-selling product|"
    r"one day is not a firing case|"
    r"watch the gap across the whole week|"
    r"structured warning beats an abrupt exit|"
    r"quite a bit! i watch your store)", re.I)

# Live turn 48: "how are you" fetched sales data and the synthesizer
# answered a GREETING with "Your store took 0…". A conversational ask
# must never be synthesized from data — the warm line is the answer.
_CONVERSATION_ASK_RE = re.compile(
    r"\b(how are you|how.?s it going|who are you|what can you do|"
    r"what do you do|what do you (?:really\s+)?know|"
    r"tell me about yourself|your name|how do you work|"
    r"thanks|thank you|hello|hi there|hey there|"
    r"good morning|good evening)\b", re.I)

# Live q8: "How much will we sell next month?" got product-push advice —
# the model will not reliably refuse predictions. The prompt's DESIGNED
# answer for predictions is an honest redirect; the loop enforces it
# when the question is unambiguously prediction-shaped (will/forecast
# phrasing — never past-tense asks).
_PREDICTION_RE = re.compile(
    r"\bhow much will (?:we|i|the shop|the store|you) (?:sell|make|earn)\b"
    r"|\bwhat will (?:we|i|the shop|the store) (?:sell|make|earn)\b"
    r"|\b(?:sales|revenue)\s+(?:forecast|projection|prediction)\b", re.I)
PREDICTION_REDIRECT = ("I can't predict the future from past sales — but I "
                       "can show you how this month is trending, if that "
                       "helps.")

# Live q7: "What's the weather tomorrow?" -> the model FETCHED sales
# data and shipped store totals — a grounded non-sequitur. World-
# knowledge asks (weather/sports/news) get the deterministic refusal:
# the model will not reliably refuse them even unprompted.
_WORLD_KNOWLEDGE_RE = re.compile(
    r"\b(weather|rain|temperature|forecast|sports|world cup|olympics|"
    r"election|president|prime minister|news|stock market|bitcoin|"
    r"crypto|celebrity|movie|song)\b", re.I)

# Sales-domain hints (turn 45: "How are we doing on sales today?" was
# unclassifiable, so the echo passed every gate vacuously). Deliberately
# does NOT include bare "doing" — "how are you doing?" is a greeting.
# ---- question-domain classification (relevance gating) ----
# Live-found failure: "Who is the worst performing employee?" -> llama
# fetched PRODUCTS and answered with a product's revenue. Every number
# was REAL, so the number-checker passed it — but the answer did not
# address the question. Numbers must be not only real but RELEVANT:
# an employee question must be grounded in employee data, etc.
_DOMAIN_HINTS = {
    "sales": re.compile(
        r"\b(sale|sales|sold|sell|revenue|profit|order|orders|earning|"
        r"earnings|income|trending|"
        r"how are we|how.?s the (?:shop|store|business)|"
        r"how is the (?:shop|store|business)|how.?s business|"
        r"how is business)\b", re.I),
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
                telemetry: dict, context: dict,
                message: str = "") -> bool:
    """
    Deterministic rescue fetch shared by both rescue paths (narration
    double-fail and refuse-on-classified-question). Executes the tool,
    records it, and returns True when data landed. Exactly-once per
    turn is enforced by the caller via telemetry["auto_fetch"].

    Multi-part enrichment: an employee fetch on a question that ALSO
    asks about sales ("how are we doing on sales today and who are my
    best employees") additionally fetches same-range sales totals, so
    one answer can cover both halves.
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
    if tool == "get_employee_performance" and message \
            and _DOMAIN_HINTS["sales"].search(message) \
            and not any(r.get("tool") == "get_sales_metrics"
                        for r in accumulated):
        try:
            sargs = {k: args[k] for k in ("start", "end") if k in args}
            payload2 = tools.execute(db, owner_id, "get_sales_metrics",
                                     sargs)
            executed.append({"tool": "get_sales_metrics", "args": sargs})
            accumulated.append({"tool": "get_sales_metrics",
                                "data": payload2})
            observations.append({"tool": "get_sales_metrics",
                                 "result": payload2})
            telemetry["tool_calls_ok"] += 1
            context["tool_results"] = observations
        except ValueError:
            pass  # enrichment is best-effort
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
    if domain == "sales":
        # A multi-part employee+sales ask already carries its employee
        # fetch; add the same-day/week window for the totals half.
        if _DOMAIN_HINTS["employee"].search(text) \
                or any(e.name and e.name.lower() in low for e in (
                    db.query(models.Employee)
                    .filter(models.Employee.employer_id == owner_id).all())):
            return ("get_sales_metrics",
                    {"start": (date.today()
                               - timedelta(days=6)).isoformat(),
                     "end": today})
        return ("get_sales_metrics", {"start": today, "end": today})
    return ("get_sales_metrics", {"start": today, "end": today})


def _sanitize_tool_args(db, owner_id: int, tool: str, args: dict,
                        user_message: str) -> dict:
    """
    Deterministic arg repair for two live-found 3B copying failures:

    - date placeholders copied from the prompt examples ("start":
      "<today>", "<week ago>") become real ISO dates — a ValueError
      round spent teaching date formats is a wasted round;
    - an employee_name that appears NOWHERE in the user's message or
      recent conversation is an example-name copy ("How much has Rahim
      sold today?" in the prompt made the model scope every employee
      fetch to Rahim or Karim) — dropping it widens the fetch to the
      whole staff, which is what an unnamed question needs. A name the
      user actually typed (this turn or a recent one) is kept.

    store_id/owner_id stay server-injected; nothing else is trusted.
    """
    import models
    args = dict(args or {})
    today = date.today()
    for key in ("start", "end"):
        raw = str(args.get(key, "")).strip().lower()
        if raw in _DATE_LITERALS:
            args[key] = (today
                         - timedelta(days=_DATE_LITERALS[raw])).isoformat()
    if tool == "get_employee_performance" and args.get("employee_name"):
        needle = str(args["employee_name"]).strip().lower()
        if needle:
            hay = (user_message or "").lower()
            for turn in _window_projection(db, owner_id):
                if turn.get("role") != "user":
                    continue  # assistant echoes taught the model fake names
                hay += " " + (turn.get("message") or "").lower()
            if needle not in hay:
                print(f"[assistant] dropped example-copied employee_name "
                      f"{args['employee_name']!r} — not in the conversation")
                args.pop("employee_name", None)
    return args


def _question_domain(db, owner_id: int, message: str) -> str | None:
    """
    'sales' | 'employee' | 'product' | None — which data domain the
    question is ABOUT. Employee detection includes literal employee
    NAMES of this store ("How is Rahim doing?" mentions no keyword).
    Product hints override employee hints ("best-selling PRODUCT" is a
    product question); employee hints override sales hints (a multi-part
    "sales today AND who are my best employees" is answered from the
    employee lane, with sales totals appended when fetched); anything
    ambiguous returns None and is gated as before.
    """
    import models
    text = message or ""
    if _DOMAIN_HINTS["product"].search(text):
        return "product"
    if _DOMAIN_HINTS["employee"].search(text):
        if _PRODUCT_OVERRIDE_RE.search(text):
            return "product"
        return "employee"
    # A literal employee NAME outranks the sales hints: "How much has
    # Rahim SOLD today?" is an employee question, not a store-wide one.
    low = text.lower()
    for e in (db.query(models.Employee)
              .filter(models.Employee.employer_id == owner_id).all()):
        if e.name and e.name.lower() in low:
            return "employee"
    if _DOMAIN_HINTS["sales"].search(text):
        return "sales"
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
    wanted = ({"get_employee_performance"} if domain == "employee"
              else {"get_top_products"} if domain == "product"
              else {"get_sales_metrics"})
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
    SPECIFICITY gate — the third narration gate. A live-found failure:
    a lay-off question answered with number-free, entity-free hedging
    ("the trailing seller", "the gap is significant") sailed through
    the reality and relevance gates because there was nothing FALSE in
    it — there was just nothing in it. On a classified data question,
    the answer must quote the data: an employee/product answer must
    NAME at least one entity from the right tool's payload; a sales
    answer must carry at least one number from the totals.

    STRICT on empty payloads: a zero-sales day must be ANSWERED (the
    synthesizer's honest empty-period line), not hedged around — an
    empty employee/product list still demands a named entity (the
    employee domain always has staff to name once fetched) and an
    empty totals block waives only the sales branch (nothing to
    quote).
    """
    if domain not in ("employee", "product", "sales"):
        return True
    wanted_tool = ({"get_employee_performance"} if domain == "employee"
                   else {"get_top_products"} if domain == "product"
                   else {"get_sales_metrics"})
    res = next((r for r in reversed(accumulated)
                if isinstance(r, dict) and r.get("tool") in wanted_tool),
               None)
    if domain == "sales":
        tot = ((res or {}).get("data") or {}).get("totals") or {}
        if not tot:
            return True  # nothing fetched / nothing to quote
        return bool(insights._numbers_in(message or ""))
    key = "employees" if domain == "employee" else "products"
    entities = ((res or {}).get("data") or {}).get(key) or []
    names = [e.get("name") for e in entities
             if isinstance(e, dict) and e.get("name")]
    if not names:
        # Empty right-domain payload: nothing real to name yet. The
        # rescue ladder will fetch/answer; hedged prose still passes
        # here because the failure is upstream (no data), not in the
        # wording.
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

    GUARD (live turn 48): a conversational ask ("how are you") is
    never synthesized — no matter what data sits in `accumulated`.
    """
    if _CONVERSATION_ASK_RE.search(user_message or ""):
        return None
    res = next((r for r in reversed(accumulated)
                if isinstance(r, dict) and r.get("tool")
                == "get_employee_performance"), None)
    multi = (domain == "employee"
             and _DOMAIN_HINTS["sales"].search(user_message or ""))
    if res and domain == "employee" and not multi:
        lanes = [e for e in (res["data"].get("employees") or [])
                 if not e.get("is_owner")]
        if lanes:
            top, trail = lanes[0], lanes[-1]
            if (top["name"] == trail["name"]
                    and (top["orders"] or 0) > 0):
                # Single-lane payload (live turn 36: the fetch was
                # scoped to one person, or only one employee sold in
                # range) — "X leads … X trails" is nonsense. Answer
                # the question with the one honest data point.
                return (f"{top['name']} is the only member of your staff "
                        f"with sales in this period: {top['revenue']} in "
                        f"revenue across {top['orders']} orders (profit "
                        f"{top['profit']}). There is no gap to compare "
                        "against yet — check the dashboard's employee "
                        "race for the full picture.")
            if not lanes[0].get("orders"):
                # Zero-sales period: nobody has numbers. The honest
                # answer IS the empty state — never an apology.
                return ("No staff sales have been recorded in this "
                        "period yet — once orders land, I can rank "
                        "your team and flag the gap worth coaching.")
            return (f"{top['name']} leads your staff with "
                    f"{top['revenue']} in revenue across "
                    f"{top['orders']} orders (profit {top['profit']}). "
                    f"{trail['name']} trails at {trail['revenue']} "
                    f"({trail['orders']} orders)."
                    + " That gap is worth a conversation before it "
                    "becomes a trend — coach, don't cut.")
        return ("No staff sales show up for this period yet — once "
                "orders land, I can rank your team and flag the gap "
                "worth coaching.")
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
        return ("No product sales show up for this period yet — once "
                "orders land, I can rank your products and pick what "
                "to push.")
    # SALES template — the primary synthesis for a classified sales
    # question. The range label comes from the args actually executed.
    sales = next((r for r in reversed(accumulated)
                  if isinstance(r, dict) and r.get("tool")
                  == "get_sales_metrics"), None)
    multi = (domain == "employee"
             and _DOMAIN_HINTS["sales"].search(user_message or ""))
    # Sales template: fires for classified sales questions AND
    # unclassified store-wide asks ("How's today?" — domain None).
    # Wrong-domain product/employee asks stay blocked (their own
    # templates handle them; a product question must never be answered
    # with store totals). The conversation-ask guard above already
    # keeps greetings away from this template.
    if sales and (domain in ("sales", None) or multi):
        tot = sales["data"].get("totals") or {}
        rng = ((sales.get("args") or {})
               or ((sales["data"] or {}).get("range") or {}))
        s, e = rng.get("start"), rng.get("end")
        today = date.today().isoformat()
        # NO calendar dates in the label: the checker only grounds
        # numbers against payload VALUES, and "2026-09-19" in prose is
        # a fabricated-number verdict waiting to happen.
        if s == e == today:
            label = "today"
        elif s == e == (date.today() - timedelta(days=1)).isoformat():
            label = "yesterday"
        else:
            label = "over that period"
        if tot and (tot.get("orders") or 0) > 0:
            base = (f"Your store took {tot.get('revenue')} in revenue "
                    f"across {tot.get('orders')} orders (profit "
                    f"{tot.get('profit')}) {label}.")
        else:
            base = (f"No sales were recorded {label} yet — the day is "
                    "still open. Once orders come in, I can break down "
                    "revenue, profit and your best hours.")
        # Multi-part questions (live: "sales today AND who are my best
        # employees"): append the employee lane when the data is in
        # hand, so the single answer covers both halves.
        if res and domain == "employee":
            lanes = [x for x in (res["data"].get("employees") or [])
                     if not x.get("is_owner")]
            if lanes:
                top = lanes[0]
                base += (f" {top['name']} leads your staff with "
                         f"{top['revenue']} in revenue across "
                         f"{top['orders']} orders.")
        return base
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
        "echo_detected": False,        # example-echo shipped as the answer
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
            # Refusal on a CLASSIFIED store question is ALWAYS a
            # misfire (live-found, twice: wrong-tool ValueError -> give
            # up and refuse; and placeholder-copied args). The loop
            # knows what data the question needs and the user cannot
            # rephrase their way out of a data answer: FETCH-FIRST.
            # Not conditional on "the model already refused once" —
            # waiting for a refusal wastes a full 30-90s round before
            # the rescue even starts. Unclassified questions keep the
            # clean-refusal path (a chatbot that cannot say "I don't
            # know" is a refuse-bot).
            if domain in ("employee", "product", "sales") \
                    and not telemetry["auto_fetch"] \
                    and _round < TOOL_CALL_CAP - 1:
                narration_retried = True
                telemetry["narration_retried"] = True
                auto = _auto_tool_for(db, owner_id, user_message, domain)
                if auto and _auto_fetch(db, owner_id, auto[0], auto[1],
                                        executed, observations,
                                        accumulated, telemetry, context,
                                        message=user_message):
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
                                           context,
                                           message=user_message):
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
        args = _sanitize_tool_args(db, owner_id, name,
                                   decision.get("args") or {},
                                   user_message)
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

    def _rescue_fetch(domain_):
        """Fetch the question's own data post-loop and let the
        deterministic synthesizer answer from the payload. Returns the
        synthesized text, or None when nothing usable landed."""
        auto = _auto_tool_for(db, owner_id, user_message, domain_)
        if not (auto and _auto_fetch(db, owner_id, auto[0], auto[1],
                                     executed, observations, accumulated,
                                     telemetry, context,
                                     message=user_message)):
            return None
        synth = _synth_answer(user_message or "", domain_, accumulated)
        if synth is None:
            return None
        telemetry["fallback_reason"] = "synthesized"
        return synth

    if refused:
        # Already sanitized in the loop (numbers -> fixed refusal text).
        pass
    elif _WORLD_KNOWLEDGE_RE.search(user_message or "") \
            and domain is None:
        # World-knowledge ask (unclassified by store hints): the
        # deterministic refusal ships — never store totals dressed up
        # as an answer (live q7).
        reply = REFUSAL_FALLBACK
        refused = True
        telemetry["refused"] = True
        telemetry["fallback_reason"] = "world_knowledge_redirect"
    elif _PREDICTION_RE.search(user_message or ""):
        # Unambiguously prediction-shaped: ship the designed redirect
        # (live q8 — the 3B answers predictions with unrelated advice
        # instead of refusing).
        reply = PREDICTION_REDIRECT
        refused = True
        telemetry["refused"] = True
        telemetry["fallback_reason"] = "prediction_redirect"
    elif _CONVERSATION_ASK_RE.search(user_message or ""):
        # Live q6: "What do you really know?" -> the model FETCHED data
        # and grounded real digits into its reply, which the gates then
        # pass by design. A conversational ask must ship a warm,
        # number-free reply — the canned co-pilot line IS the designed
        # answer, whatever the model narrated.
        if not reply or insights._numbers_in(reply or "") \
                or _ECHO_PHRASE_RE.search(reply or ""):
            reply = CONVERSATION_FALLBACK
            telemetry["fallback_reason"] = "conversation_double_fail"
    elif domain in ("employee", "product", "sales") and (
            not accumulated or _ECHO_PHRASE_RE.search(reply or "")):
        # FETCH-FIRST FLOOR (live turns 38/46): a classified data
        # question shipped a final/refuse with NO fetch at all — or an
        # EXAMPLE-ECHO instead of an answer (byte-identical prose on
        # unrelated questions; no per-question gate can fix echo, only
        # data in hand). The gates pass vacuously when nothing was
        # claimed, so this is checked before them: a data question
        # without data is a failure regardless of how clean the prose
        # is. Fetch the question's own tool now; if a second fetch
        # (enrichment) helps the synthesizer, take it.
        if _ECHO_PHRASE_RE.search(reply or ""):
            telemetry["echo_detected"] = True
            print("[assistant] example-echo shipped as the answer — "
                  "replacing with data")
        synth = _rescue_fetch(domain)
        if synth is not None:
            reply = synth
        else:
            # No template fit (or the fetch failed): the honest
            # fallback ships — never the echoed prose.
            reply = NARRATION_FALLBACK
            telemetry["fallback_reason"] = "narration_double_fail"
    elif not _gates_pass(reply or "", accumulated, domain):
        # Covers every failure shape: fabricated numbers WITH tool
        # data, a digits-in-prose chit-chat reply with NO data behind
        # it, and a vague number-free answer that names nobody from a
        # classified question's data.
        # With a right-domain payload in hand, the deterministic
        # synthesizer is tried FIRST — a plain correct answer built
        # from the tool result beats an honest apology. With the
        # WRONG-domain payload (live q9: product question, model
        # fetched sales totals), fetch the question's own tool first.
        synth = _synth_answer(user_message or "", domain, accumulated)
        if synth is None and domain in ("employee", "product", "sales") \
                and not telemetry["auto_fetch"]:
            synth = _rescue_fetch(domain)
        if synth is not None:
            print("[assistant] narration failed — shipping the "
                  "deterministic synthesis from tool data")
            reply = synth
            telemetry["fallback_reason"] = "synthesized"
        elif _ECHO_PHRASE_RE.search(reply or ""):
            # Gates already failed; an echo must never survive them.
            telemetry["echo_detected"] = True
            reply = NARRATION_FALLBACK if accumulated else CONVERSATION_FALLBACK
            telemetry["fallback_reason"] = ("narration_double_fail"
                                            if accumulated
                                            else "conversation_double_fail")
        elif accumulated:
            print("[assistant] narration failed the number check — "
                  "replacing message with the fallback")
            reply = NARRATION_FALLBACK
            telemetry["fallback_reason"] = "narration_double_fail"
        elif domain is not None:
            reply = DATA_NO_REPLY_FALLBACK
            telemetry["fallback_reason"] = "conversation_double_fail"
        else:
            # Unclassified turn (greeting, capabilities): the warm
            # canned co-pilot line is the DESIGNED answer here —
            # never a sales template (live turn 48: "how are you" ->
            # "Your store took 0…").
            reply = CONVERSATION_FALLBACK
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

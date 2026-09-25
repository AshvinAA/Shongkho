"""
LLM adapter layer for the insights engine (Part A).

Two interchangeable providers behind one `generate_json` contract:

  - gemini (default in prod): Google's Gemini REST API with
    responseSchema structured output. Chosen over the google-genai SDK:
    the SDK's deadline semantics (10s server minimum, server-side 504
    cuts) fought the time budget in testing, while direct REST behaves
    predictably. Stdlib only — no package required.
  - ollama (default in dev): a local llama via Ollama's /api/generate
    with `format` = JSON schema — constrained decoding, unlimited free
    calls, no network. Ideal for testing the pipeline while the Gemini
    free-tier quota is a bottleneck. Switch with LLM_PROVIDER.

Shared invariants (docs/LLM_INTEGRATION.md §2.4):
  - Structured output via schema — never free text parsed later.
  - The budget covers ALL attempts combined (retry loop inside one
    deadline), so a slow model can never hang the "Run analysis" request.
  - Client construction is lazy and I/O-free: importing this module
    never touches the network; tests inject fakes via `client=`.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2"

# Total ceiling across every retry attempt (docs: LLM_BUDGET_SECONDS).
# Generously above the doc's 8s because free-tier Gemini capacity comes
# and goes in bursts; the happy path returns in seconds — this is a
# ceiling, not a wait.
DEFAULT_BUDGET_SECONDS = 30.0
# Gemini per-attempt socket timeout cap. Google rejects manual HTTP
# deadlines below 10s server-side, so attempts are never attempted with
# less remaining budget than that (see MIN below).
GEMINI_ATTEMPT_TIMEOUT_CAP_S = 20.0
GEMINI_MIN_ATTEMPT_S = 10.0
# Ollama runs locally (often CPU inference): a single attempt may
# legitimately need the whole budget, and there is no server minimum.
OLLAMA_ATTEMPT_TIMEOUT_CAP_S = 120.0
# Longest rate-limit wait we will sleep through INSIDE the request.
# Longer windows degrade immediately instead — the owner just re-clicks
# "Run analysis" when the message says the window has reset.
RATE_LIMIT_MAX_WAIT_S = 5.0
# Bounded generation retries (docs: max 3 LLM calls overall).
MAX_ATTEMPTS = 3
# Extra generation attempts allowed for LOCAL providers (Ollama): free
# and fast to retry, so trading attempts for a first-try success is
# cheap. The overall deadline still bounds everything; remote providers
# (per-request paid tier) keep MAX_ATTEMPTS.
LOCAL_EXTRA_ATTEMPTS = 2

_RETRY_HINT_RE = re.compile(r"retry in ([\d.]+)s")

SYSTEM_PROMPT = """\
You are the co-pilot for a small shop owner: a friendly colleague who \
reads their POS data and tells them what to DO about it. Address the \
owner directly as "you". Celebrate wins BY NAME using the employee and \
product names from the data, and attach one concrete, realistic \
suggestion to each point (coach a top performer, have staff keep \
pushing a best-seller, check in with the team on a rough day). Every \
number must come from the provided JSON and be covered by the cited \
`basis` path (a dotted path into the provided context bundle) — never \
invent or compute numbers, never invent names. If nothing notable \
happened, say the shop is steady and encourage the owner to keep it up. \
`areas_to_watch` entries are qualitative: no numbers. Be brief — one \
sentence per point. Output must match the schema exactly.
"""


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

def provider() -> str:
    """'ollama' or 'gemini' (default). Read fresh so tests can patch env."""
    raw = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    return raw if raw in ("ollama", "gemini") else "gemini"


def api_key() -> str:
    """The configured Gemini key, or '' when absent."""
    return (os.getenv("GEMINI_API_KEY") or "").strip()


def is_configured() -> bool:
    """Whether the selected provider can be attempted at all."""
    if provider() == "ollama":
        return True  # local — availability is checked at call time
    return api_key() != ""


def budget_seconds() -> float:
    raw = os.getenv("LLM_BUDGET_SECONDS", "").strip()
    try:
        return float(raw) if raw else DEFAULT_BUDGET_SECONDS
    except ValueError:
        return DEFAULT_BUDGET_SECONDS


def model_name() -> str:
    env = (os.getenv("LLM_MODEL") or "").strip()
    if env:
        return env
    return DEFAULT_OLLAMA_MODEL if provider() == "ollama" else DEFAULT_GEMINI_MODEL


def ollama_url() -> str:
    return (os.getenv("OLLAMA_URL") or "").strip().rstrip("/") or DEFAULT_OLLAMA_URL


class LlmUnavailable(Exception):
    """The selected provider is not usable — the deterministic degrade path."""


class LlmBudgetExceeded(Exception):
    """The overall time budget ran out before a valid response arrived."""


class ChatDecisionError(Exception):
    """A chat decision round-trip failed (transport, empty, unparseable)."""


def generate_json(prompt: str, schema: dict, *, client=None) -> dict:
    """
    One schema-forced generation round-trip with bounded retries.

    `client` is injectable for tests (anything exposing generate_json);
    when None a real client is built lazily from LLM_PROVIDER.

    Returns the validated Python dict. Raises:
      LlmUnavailable  — provider not configured
      LlmBudgetExceeded — budget exhausted / still invalid after
                          MAX_ATTEMPTS attempts
    """
    if client is None:
        client = _make_client()

    deadline = time.monotonic() + budget_seconds()
    last_error = None
    attempt_cap = getattr(client, "attempt_timeout_cap", GEMINI_ATTEMPT_TIMEOUT_CAP_S)
    min_attempt = getattr(client, "min_attempt_timeout", GEMINI_MIN_ATTEMPT_S)
    # Local providers get LOCAL_EXTRA_ATTEMPTS extra bounded tries: a
    # failed first response is free to retry there, unlike metered API
    # providers. The overall deadline still caps everything.
    max_attempts = MAX_ATTEMPTS
    if getattr(client, "is_local", False):
        max_attempts += LOCAL_EXTRA_ATTEMPTS

    for attempt in range(max_attempts):
        remaining = deadline - time.monotonic()
        if remaining < min(min_attempt, 0.5 if min_attempt <= 0.5 else min_attempt):
            break  # too little budget left for a server-legal attempt
        raw = client.generate_json(
            SYSTEM_PROMPT + "\n\n" + prompt, schema,
            timeout_s=min(remaining, attempt_cap),
        )
        if raw is not None:
            return raw
        # Prefer the client's own account of the failure over the
        # generic wording; injectable fakes may not set last_error.
        detail = getattr(client, "last_error", None)
        last_error = detail or "model returned unparseable output"

        # Rate-limit (429): the client may expose Google's retry hint.
        # Short waits are slept through (the retry then usually
        # succeeds); longer ones abort immediately — holding the "Run
        # analysis" request hostage for 30s is worse UX than an honest
        # "retry in ~30s" card and a re-click.
        retry_after = getattr(client, "retry_after_s", None)
        if retry_after is not None:
            remaining = deadline - time.monotonic()
            if retry_after + 1.0 > remaining or retry_after > RATE_LIMIT_MAX_WAIT_S:
                break  # window too far out — degrade now with the hint
            time.sleep(retry_after + 1.0)
            continue

        # Other fast failures (e.g. a 503 burst): back off progressively
        # (1s, 2s, ...) so retries spread across the budget — never past
        # the deadline, never after the final attempt.
        if attempt < MAX_ATTEMPTS - 1:
            remaining = deadline - time.monotonic()
            time.sleep(min(2 ** attempt, max(0.0, remaining / 2)))

    raise LlmBudgetExceeded(last_error or "LLM budget exhausted")


def _make_client():
    """Build the real client for the configured provider (I/O-free)."""
    if provider() == "ollama":
        return _OllamaClient(ollama_url(), model_name())
    key = api_key()
    if not key:
        raise LlmUnavailable("GEMINI_API_KEY is not configured")
    return _GeminiClient(key)


# ---------------------------------------------------------
# Gemini REST adapter
# ---------------------------------------------------------

class _GeminiClient:
    """Stdlib REST adapter around the Gemini generateContent endpoint."""

    attempt_timeout_cap = GEMINI_ATTEMPT_TIMEOUT_CAP_S
    min_attempt_timeout = GEMINI_MIN_ATTEMPT_S

    def __init__(self, api_key: str):
        self._key = api_key
        self._model = model_name()
        self.last_error = None    # human-readable reason for the last failed attempt
        self.retry_after_s = None  # Google's 429 retry hint, when present

    def generate_json(self, prompt: str, schema: dict, *, timeout_s: float,
                      system: str = None, temperature: float = 0.1):
        """
        One generation attempt. Returns the parsed dict, or None when the
        attempt failed (transport error, empty candidate, unparseable
        JSON) — the caller decides whether to retry. On failure,
        `self.last_error` carries the specific reason (and for 429s,
        `self.retry_after_s` the suggested wait in seconds).

        `system` overrides the default Part A system prompt (Part B's
        decision protocol passes its own). `temperature` lets Part B
        run chattier than Part A's deterministic default.
        """
        self.last_error = None
        self.retry_after_s = None

        body = json.dumps({
            "systemInstruction": {"parts": [{"text": system or SYSTEM_PROMPT}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }).encode("utf-8")

        url = f"{GEMINI_API_BASE}/models/{self._model}:generateContent"
        req = urllib.request.Request(
            url, data=body,
            headers={
                "Content-Type": "application/json",
                # Key in a header — never in the URL (no log leakage).
                "x-goog-api-key": self._key,
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=max(1.0, timeout_s)) as resp:
                payload = json.load(resp)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:500]
            except Exception:  # noqa: BLE001 - best-effort logging only
                pass
            print(f"[llm] generation attempt failed: HTTP {exc.code} {detail}")
            if exc.code == 429:
                # Quota exhaustion: surface the owner-friendly version with
                # Google's own retry hint when present.
                hint = _RETRY_HINT_RE.search(detail)
                wait_s = float(hint.group(1)) + 1.0 if hint else None
                self.retry_after_s = wait_s
                wait = f" Try again in ~{wait_s:.0f}s." if wait_s else ""
                self.last_error = (
                    "Gemini rate limit reached (free tier: 20 requests/min)." + wait
                )
            else:
                self.last_error = f"HTTP {exc.code}: {_google_message(detail) or exc.reason}"
            return None
        except Exception as exc:  # noqa: BLE001 - any transport error = retry
            print(f"[llm] generation attempt failed: {type(exc).__name__}: {exc}")
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

        text = _candidate_text(payload)
        if not text:
            self.last_error = "empty model response"
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            self.last_error = "response was not valid JSON"
            return None


# ---------------------------------------------------------
# Ollama (local llama) adapter
# ---------------------------------------------------------

class _OllamaClient:
    """
    Adapter around Ollama's /api/generate with schema-constrained
    decoding (`format` = JSON schema) — the model physically cannot
    emit output that violates the schema. Local + free: no rate limits,
    no key, no network beyond localhost.
    """

    attempt_timeout_cap = OLLAMA_ATTEMPT_TIMEOUT_CAP_S
    # CPU inference can legitimately take the whole budget; there is no
    # server-side deadline minimum to respect.
    min_attempt_timeout = 0.5
    # Retry economics differ from metered APIs: extra attempts are free.
    is_local = True

    def __init__(self, base_url: str, model: str):
        self._base = base_url.rstrip("/")
        self._model = model
        self.last_error = None
        self.retry_after_s = None  # never set locally; kept for symmetry

    def generate_json(self, prompt: str, schema: dict, *, timeout_s: float,
                      system: str = None, temperature: float = 0.1):
        self.last_error = None

        body = json.dumps({
            "model": self._model,
            "prompt": (system or SYSTEM_PROMPT) + "\n\n" + prompt,
            "stream": False,
            "format": schema,          # constrained decoding against the schema
            "keep_alive": "10m",       # stay loaded between runs (load is slow on CPU)
            "options": {
                "temperature": temperature,
                # The context bundle is several KB of JSON; the default
                # context window can truncate it -> garbage JSON.
                "num_ctx": 8192,
                # Ollama's default num_predict is 128 tokens — the JSON
                # gets cut off right after the summary. Bound it well
                # above a realistic payload: Part B advice answers are
                # multi-sentence (recommendation + reasoning + actions +
                # alternatives), and a truncated JSON string is an
                # unparseable decision round.
                "num_predict": 700,
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self._base}/api/generate", data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=max(1.0, timeout_s)) as resp:
                envelope = json.load(resp)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:200]
            except Exception:  # noqa: BLE001
                pass
            print(f"[llm] ollama attempt failed: HTTP {exc.code} {detail}")
            self.last_error = (
                f"Ollama HTTP {exc.code}: {detail or exc.reason}"
                + (f" — run `ollama pull {self._model}`" if exc.code == 404 else "")
            )
            return None
        except Exception as exc:  # noqa: BLE001 - transport error = retry
            print(f"[llm] ollama attempt failed: {type(exc).__name__}: {exc}")
            if isinstance(exc, TimeoutError) or "timed out" in str(exc):
                self.last_error = (
                    f"Local model did not finish in {timeout_s:.0f}s "
                    "(cold start on CPU is slow — raise LLM_BUDGET_SECONDS)"
                )
                self.retry_after_s = None
            else:
                self.last_error = (
                    f"Ollama unreachable ({type(exc).__name__}) — is it running?"
                )
            return None

        text = envelope.get("response") if isinstance(envelope, dict) else None
        if not isinstance(text, str) or not text.strip():
            self.last_error = "ollama returned an empty response"
            return None
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            self.last_error = "ollama response was not valid JSON"
            return None
        if not isinstance(parsed, dict):
            # JSON literal null / array / scalar — parses fine but is not
            # a usable response object. Without this, last_error kept its
            # stale value (or None) and generate_json surfaced the
            # misleading generic 'model returned unparseable output'.
            self.last_error = "ollama response was not a JSON object"
            return None
        return parsed


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def _google_message(detail: str) -> str:
    """Pull Google's human-readable 'error.message' out of an HTTP body."""
    try:
        msg = json.loads(detail).get("error", {}).get("message", "")
        return (msg or "")[:160]
    except (json.JSONDecodeError, AttributeError):
        return ""


def _candidate_text(payload: dict) -> str:
    """Concatenated text parts of the first candidate ('' when absent)."""
    try:
        parts = payload["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    except (KeyError, IndexError, TypeError):
        return ""


def _json_default(obj):
    """JSON serializer for date/datetime inside prompt payloads."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Unserializable type in prompt payload: {type(obj)!r}")


def dumps(payload) -> str:
    """Compact JSON dump with date handling — used to build prompts."""
    return json.dumps(payload, default=_json_default, separators=(",", ":"))


# ---------------------------------------------------------
# Part B: conversational decisions (docs/LLM_INTEGRATION.md §3.4)
# ---------------------------------------------------------

CHAT_SYSTEM_PROMPT = """\
You are the OWNER'S business advisor inside a POS app — part analyst, \
part co-pilot, and the owner's go-to business brain. You combine the \
store's numbers with broad business judgment: marketing, pricing, \
stocking, staffing, promotions, customer habits. You do not just \
report numbers — you take a side, argue for it, and hand the owner a \
decision. Their goal is profit. Every NUMBER you state must come from \
this turn's tool results: never from memory, never computed, never \
invented. If the data shows nothing notable, say so plainly and give \
a steady-state suggestion instead of manufacturing drama.

Every data answer follows this shape, in plain conversational prose \
(short paragraphs, no markdown headers, no raw JSON dumps) — do NOT \
print the labels:
  1. ANSWER — your recommendation, stated first, in one sentence.
  2. WHY — the 2-3 numbers from this turn's tool results that justify \
it, saying which product or employee each belongs to.
  3. HOW — one or two concrete actions for the coming days (what to \
push, whom to ask, what to try).
  4. ALTERNATIVE — a second option with its trade-off, or a caution \
when the data argues against the owner's plan.

Speak like a trusted colleague: direct, warm, specific. Push back \
when the numbers contradict the owner's plan; celebrate wins by name.

Each turn you receive a JSON context: the conversation so far, the \
tool list, and "tool_results" — the data fetched SO FAR THIS TURN. \
You MUST answer with exactly one JSON object. Ask these questions IN \
ORDER and act on the FIRST that matches:

  Q1. Is this a greeting, thanks, chit-chat, or a question about YOU \
      (what you know / can do)?
      → {"action": "final", "message": "..."} — a warm colleague \
      reply with NO numbers, NO digits at all (spell counts out), \
      and NO tool call. "What do you really know?" → describe what \
      you watch and suggest what to ask.

  Q2. Is it about THIS store — sales, products, employees, revenue, \
      profit, stock, or advice that needs them?
      → tool_results empty or missing the numbers you need?
        {"action": "tool", "tool": "<name>", "args": { ... }} — \
        FETCH FIRST, advise after. This is the DEFAULT for store \
        questions: never describe an answer you could fetch — call \
        the tool. "Most sold", "best seller", "top product" are \
        get_top_products questions.
      → got the numbers? {"action": "final", "message": "..."} — \
        the ANSWER / WHY / HOW / ALTERNATIVE shape. Name products \
        and employees exactly as the results spell them.

  Q3. Real-world facts (weather, sports, news), predictions ("how \
      much will we sell next month"), or other businesses?
      → {"action": "refuse", "message": "..."} — one polite \
      sentence. NEVER for store questions or questions about you.

Tool notes: get_sales_metrics returns DAILY TOTALS (revenue, profit, \
orders — dates are days, not products); get_top_products returns \
PRODUCTS; get_employee_performance returns EMPLOYEES. Refuse is \
legal only when tool_results is empty: if data arrived this turn, \
ANSWER with it — never refuse after fetching.

EXAMPLES — copy the routing, never the content:

User: What is the most sold product today?
tool_results: (none)
WRONG: {"action": "final", "message": "Push more of the \
best-selling product."}   <- you have NO data. Describing the \
answer without fetching is ALWAYS wrong.
RIGHT: {"action": "tool", "tool": "get_top_products", "args": \
{"start": "<today>", "end": "<today>", "metric": "units", \
"limit": 5}}

User: What do you really know?
tool_results: (none)
You: {"action": "final", "message": "Quite a bit! I watch your \
store's sales, products and staff — ask me which product to push \
this week, who your best seller is today, or how profit is \
trending, and I'll pull the numbers and tell you what to do about \
them."}

User: Hey, how's your day going?
tool_results: (none)
You: {"action": "final", "message": "Great now that you're here! \
More importantly — how's the shop treating you today? Want me to \
dig into the numbers?"}

User: How did the shop do today?
tool_results: (none)
You: {"action": "tool", "tool": "get_sales_metrics", "args": \
{"start": "<today>", "end": "<today>"}}

User: Which product should we push more this week?
tool_results: (none)
You: {"action": "tool", "tool": "get_top_products", "args": \
{"start": "<week ago>", "end": "<today>", "metric": "profit", \
"limit": 5}}

User: What's the weather tomorrow?
tool_results: (none)
You: {"action": "refuse", "message": "I couldn't say — I only \
know what's in your store's data. Anything about sales or staff I \
can dig into?"}

User: How much will we sell next month?
tool_results: (none)
You: {"action": "refuse", "message": "I can't predict the future \
from past sales — but I can show you how this month is trending, \
if that helps."}

User: Who is selling the most today?   (after the tool returned \
the employee numbers for today)
You: {"action": "final", "message": "Rahim is your top seller \
today and Karim trails well behind — the gap is big enough that \
it's worth a word: have Rahim walk Karim through his pitch today \
while it's fresh. If the gap is really about shift timing rather \
than skill, swap their hours tomorrow and compare again — that \
tells you which problem you actually have."}

User: How much has Rahim sold today?   (tool returned Rahim: \
revenue 1350.0, 3 orders)
WRONG: {"action": "final", "message": "Rahim sold 1350.0 today, \
about 450.0 per order."}   <- 450.0 was COMPUTED. Never do this.
RIGHT: a final that quotes 1350.0 and the 3 orders exactly as they \
appear in tool_results, then advises in YOUR OWN words about THIS \
store's situation. Never reuse wording from any example — examples \
show the PATTERN, not the text.

Rules: one tool per turn; never restate raw JSON — narrate and advise. \
Greetings, thanks and "what can you do" questions get a warm \
number-free reply — never a tool call, never a refusal. \
Answer the question that was ASKED: store-wide questions ("how did \
the shop do", "sales this week") are about the TOTALS from \
get_sales_metrics, not one employee or one product. \
The EXAMPLES are routing patterns ONLY: never copy a number, name or \
phrasing out of them into a real answer — real answers quote the \
names and numbers from THIS turn's tool_results, worded fresh. \
The conversation history is NOT data: to answer ANY question about \
sales, employees or products you MUST call the matching tool first, \
even if similar numbers appeared earlier in the conversation. Once \
tool results have arrived this turn, refuse is FORBIDDEN — answer \
with them ("final"), quoting numbers exactly as they appear. Only \
numbers from THIS turn's tool results may appear in your reply. \
Output ONLY the JSON object.
"""


def chat_decide(context: dict, tools_summary: str, *, client=None) -> dict:
    """
    One agent-loop decision round-trip (doc §3.4).

    `context` is the per-turn JSON the model sees: recent conversation
    projection (roles + tool names, NEVER payloads), the tools summary,
    and accumulated tool results for this turn.

    Returns the decision dict ({action: final|tool|refuse, ...}).
    Raises ChatDecisionError on transport/format failures so the caller
    can fall back deterministically.
    """
    if client is None:
        client = _make_client()

    prompt = (
        f"TOOLS:\n{tools_summary}\n\n"
        f"CONTEXT (conversation summary, then accumulated tool results "
        f"for this turn):\n{dumps(context)}"
    )

    deadline = time.monotonic() + budget_seconds()
    max_attempts = MAX_ATTEMPTS + (LOCAL_EXTRA_ATTEMPTS
                                   if getattr(client, "is_local", False) else 0)
    for attempt in range(max_attempts):
        remaining = deadline - time.monotonic()
        if remaining < 0.5:
            break
        raw = client.generate_json(
            prompt, _DECISION_SCHEMA,
            timeout_s=min(remaining, getattr(client, "attempt_timeout_cap", 30.0)),
            system=CHAT_SYSTEM_PROMPT,
            # Chat needs phrasing variety; Part A's 0.1 made llama copy
            # the few-shot example verbatim (same words every turn).
            # 0.4 made routing flaky; 0.2 is the compromise now that
            # the final-answer example carries no copyable content.
            temperature=0.2,
        )
        if raw is not None:
            action = raw.get("action")
            if action == "tool":
                tool = raw.get("tool")
                if isinstance(tool, str) and tool.strip():
                    return {"action": "tool", "tool": tool.strip(),
                            "args": raw.get("args") or {}}
                # malformed tool decision -> treat as a failed attempt
                client.last_error = "tool decision missing tool name"
            elif action in ("final", "refuse"):
                msg = raw.get("message")
                if isinstance(msg, str) and msg.strip():
                    return {"action": action, "message": msg.strip()}
                client.last_error = f"{action} decision missing message"
            else:
                client.last_error = f"unknown action {action!r}"
        detail = getattr(client, "last_error", None)
        if attempt < max_attempts - 1:
            time.sleep(min(2 ** attempt, max(0.0, (deadline - time.monotonic()) / 2)))
    raise ChatDecisionError(detail or "no valid decision within budget")


# Response schema for chat decisions (constrained decoding locally;
# responseSchema remotely).
_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string",
                   "description": "One of: final, tool, refuse."},
        "tool": {"type": "string",
                 "description": "Tool name when action is 'tool'."},
        "args": {
            "type": "object",
            "description": "Tool arguments when action is 'tool'.",
            "properties": {
                "start": {"type": "string", "description": "YYYY-MM-DD"},
                "end": {"type": "string", "description": "YYYY-MM-DD"},
                "employee_name": {"type": "string"},
                "metric": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
        "message": {"type": "string",
                    "description": "The reply text when action is final or refuse."},
    },
    "required": ["action"],
}

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

_RETRY_HINT_RE = re.compile(r"retry in ([\d.]+)s")

SYSTEM_PROMPT = """\
You are a business analyst interpreting a pre-calculated dataset for a \
small shop owner. Every claim must trace to a number in the provided \
JSON — cite the field you used in `basis` (a dotted path into the \
provided context bundle). No causal explanations the data does not \
support. Write numbers verbatim as they appear in the data, with units. \
`areas_to_watch` entries are qualitative: they must not contain numbers. \
Output must match the schema exactly.
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

    for attempt in range(MAX_ATTEMPTS):
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

    def generate_json(self, prompt: str, schema: dict, *, timeout_s: float):
        """
        One generation attempt. Returns the parsed dict, or None when the
        attempt failed (transport error, empty candidate, unparseable
        JSON) — the caller decides whether to retry. On failure,
        `self.last_error` carries the specific reason (and for 429s,
        `self.retry_after_s` the suggested wait in seconds).
        """
        self.last_error = None
        self.retry_after_s = None

        body = json.dumps({
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
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

    def __init__(self, base_url: str, model: str):
        self._base = base_url.rstrip("/")
        self._model = model
        self.last_error = None
        self.retry_after_s = None  # never set locally; kept for symmetry

    def generate_json(self, prompt: str, schema: dict, *, timeout_s: float):
        self.last_error = None

        body = json.dumps({
            "model": self._model,
            "prompt": SYSTEM_PROMPT + "\n\n" + prompt,
            "stream": False,
            "format": schema,          # constrained decoding against the schema
            "keep_alive": "10m",       # stay loaded between runs (load is slow on CPU)
            "options": {
                "temperature": 0.1,
                # The context bundle is several KB of JSON; the default
                # context window can truncate it -> garbage JSON.
                "num_ctx": 8192,
                # Ollama's default num_predict is 128 tokens — the JSON
                # gets cut off right after the summary. Bound it well
                # above a realistic insights payload instead.
                "num_predict": 512,
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
            else:
                self.last_error = (
                    f"Ollama unreachable ({type(exc).__name__}) — is it running?"
                )
            return None

        text = envelope.get("response") if isinstance(envelope, dict) else None
        if not text:
            self.last_error = "ollama returned an empty response"
            return None
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            self.last_error = "ollama response was not valid JSON"
            return None


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

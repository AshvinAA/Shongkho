"""
Thin Gemini REST wrapper for the insights engine (Part A).

Design (per docs/LLM_INTEGRATION.md §2.4):
  - Structured output via responseSchema — never free text parsed later.
  - Plain REST over the google-genai SDK: the SDK's HttpOptions deadline
    semantics (10s server minimum, server-side 504 cuts) fought the time
    budget in testing, while direct REST calls behave predictably. The
    stdlib client also means no extra package is required.
  - The model choice / budget / retries are read from env with sane
    defaults so tests and dev need no configuration.
  - The budget covers ALL attempts combined (retry loop inside one
    deadline), so a slow model can never hang the "Run analysis" request.
  - Client construction is lazy: importing this module never performs
    network I/O — the API and the test suite run without a key, exactly
    like the Celery seam in analytics/tasks.py.

The rest of the codebase never touches HTTP directly; everything goes
through `generate_json(...)` so tests can swap the whole LLM out.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime

_RETRY_HINT_RE = re.compile(r"retry in ([\d.]+)s")

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.5-flash"
# Total ceiling across every retry attempt (docs: LLM_BUDGET_SECONDS).
# Generously above the doc's 8s because free-tier flash capacity comes
# and goes in bursts; the happy path returns in seconds — this is a
# ceiling, not a wait.
DEFAULT_BUDGET_SECONDS = 30.0
# Per-attempt socket timeout (each attempt gets at most this).
MAX_ATTEMPT_TIMEOUT_S = 20.0
# Longest rate-limit wait we will sleep through INSIDE the request.
# Longer windows degrade immediately instead — the owner just re-clicks
# "Run analysis" when the message says the window has reset.
RATE_LIMIT_MAX_WAIT_S = 5.0
# Bounded generation retries (docs: max 3 LLM calls overall).
MAX_ATTEMPTS = 3

SYSTEM_PROMPT = """\
You are a business analyst interpreting a pre-calculated dataset for a \
small shop owner. Every claim must trace to a number in the provided \
JSON — cite the field you used in `basis` (a dotted path into the \
provided context bundle). No causal explanations the data does not \
support. Write numbers verbatim as they appear in the data, with units. \
`areas_to_watch` entries are qualitative: they must not contain numbers. \
Output must match the schema exactly.
"""


def api_key() -> str:
    """The configured key, or '' when absent (deterministic degrade path)."""
    return (os.getenv("GEMINI_API_KEY") or "").strip()


def budget_seconds() -> float:
    raw = os.getenv("LLM_BUDGET_SECONDS", "").strip()
    try:
        return float(raw) if raw else DEFAULT_BUDGET_SECONDS
    except ValueError:
        return DEFAULT_BUDGET_SECONDS


def model_name() -> str:
    return (os.getenv("LLM_MODEL", "").strip() or DEFAULT_MODEL)


class LlmUnavailable(Exception):
    """No API key configured — the deterministic degrade path."""


class LlmBudgetExceeded(Exception):
    """The overall time budget ran out before a valid response arrived."""


def generate_json(prompt: str, schema: dict, *, client=None) -> dict:
    """
    One schema-forced generation round-trip with bounded retries.

    `client` is injectable for tests (anything exposing generate_json);
    when None a real Gemini REST client is built lazily (requires
    GEMINI_API_KEY to be set).

    Returns the validated Python dict. Raises:
      LlmUnavailable  — no key configured
      LlmBudgetExceeded — budget exhausted / still invalid after
                          MAX_ATTEMPTS attempts
    """
    if client is None:
        key = api_key()
        if not key:
            raise LlmUnavailable("GEMINI_API_KEY is not configured")
        client = _RestClient(key)

    deadline = time.monotonic() + budget_seconds()
    last_error = None

    for attempt in range(MAX_ATTEMPTS):
        remaining = deadline - time.monotonic()
        if remaining <= 0.5:
            break  # no budget left for a meaningful attempt
        raw = client.generate_json(
            SYSTEM_PROMPT + "\n\n" + prompt, schema,
            timeout_s=min(remaining, MAX_ATTEMPT_TIMEOUT_S),
        )
        if raw is not None:
            return raw
        # Prefer the client's own account of the failure (e.g. "HTTP 503
        # ... high demand") over the generic wording; injectable fakes
        # may not set last_error at all.
        detail = getattr(client, "last_error", None)
        last_error = detail or "model returned unparseable output"

        # Rate-limit (429): Google tells us exactly when the window
        # resets. Short waits are slept through (the retry then usually
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
        # (1s, 2s, ...) so retries spread across the whole budget instead
        # of burning all attempts in the first seconds — but never sleep
        # past the deadline, and never after the final attempt.
        if attempt < MAX_ATTEMPTS - 1:
            remaining = deadline - time.monotonic()
            time.sleep(min(2 ** attempt, max(0.0, remaining / 2)))

    raise LlmBudgetExceeded(last_error or "LLM budget exhausted")


# ---------------------------------------------------------
# Real REST adapter (loaded lazily — see module docstring)
# ---------------------------------------------------------

class _RestClient:
    """
    Stdlib REST adapter around the Gemini generateContent endpoint.

    No third-party package: urllib with a socket timeout, which really
    aborts a stalled connection (unlike a server-side deadline hint).
    """

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

        url = f"{API_BASE}/models/{self._model}:generateContent"
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

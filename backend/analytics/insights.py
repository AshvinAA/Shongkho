"""
Part A — the insight engine (docs/LLM_INTEGRATION.md §2).

Turns the aggregated section payloads into short, structured business
commentary, with every number validated against the data it claims to
describe. Design pillars:

  - History is CALENDAR-based, not run-based: the last K windows of the
    same period_type, deduped by window start (two runs of one week are
    one window), with missing windows as nulls that BREAK streaks.
  - The rollup is computed in Python from those deterministic payloads —
    never from prior LLM prose.
  - Every observation carries `basis`: a dotted path into the context
    bundle. The number checker resolves each basis path and tolerantly
    matches every number in the text against that known value (plus
    whitelisted derivations). Fabricated numbers have no valid path.
  - ALL failure modes degrade (fallback + degraded flag) — none fails
    the run. The three chart sections are always valid; an LLM outage
    must never cost the owner their charts.

Pure module: no DB access (the pipeline fetches history rows), no
Celery, and the LLM is an injectable dependency (the same seam pattern
as the run executor).
"""
import math
import re
import time
from datetime import timedelta

from analytics import llm

# Calendar windows of history fed to the model (docs: K=4).
HISTORY_K = 4

# Tolerance when matching the 1dp-rounded percentages the DTO stores.
PCT_TOLERANCE = 0.05
# Tolerance when matching an integer rounding of a bundle value.
INT_TOLERANCE = 0.5

# Validation rounds: the first response plus one corrective retry when
# validation fails (mis-cited basis, ungrounded number). Bounded by the
# same overall deadline as the transport retries in llm.generate_json.
VALIDATION_ATTEMPTS = 2


# ---------------------------------------------------------
# Output contract (docs §2.3)
# ---------------------------------------------------------

# The Gemini response_schema (the OpenAPI-ish subset the SDK accepts).
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "2-3 sentences describing this period's performance.",
        },
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string",
                             "description": "One insight; every number must trace to basis."},
                    "basis": {"type": "string",
                              "description": "Dotted path into the provided JSON grounding this "
                                             "claim: the SMALLEST subtree that contains EVERY "
                                             "number used in the text. MUST start with "
                                             "'current_dto.' (e.g. current_dto.sales)."},
                },
                "required": ["text", "basis"],
            },
        },
        "areas_to_watch": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Qualitative risks/trends. No numbers allowed.",
        },
    },
    "required": ["summary", "observations", "areas_to_watch"],
}

FALLBACK_SUMMARY = (
    "Automated insights are unavailable for this run, but your sales, "
    "employee, and product data below are up to date."
)

# Small local models (llama3.2-class) follow ONE simple rule better than a
# combined paragraph. Each observation gets its own focused instruction —
# notably: never merge numbers from different sections into one sentence.
# Kept here (not in llm.SYSTEM_PROMPT) because the paths it references are
# only visible next to the context bundle in the user prompt.
OBSERVATION_RULES = """\
Rules for each observation:
1. One section per observation: use ONLY numbers from the single section \
your `basis` path points at. Never mix sales numbers with employee or \
product numbers in one observation — make a separate observation instead.
2. `basis` MUST be EXACTLY ONE dotted path starting with `current_dto.` \
into the context bundle — never a list, never commas. When a sentence \
uses several fields, cite their common parent (e.g. `current_dto.sales`, \
not each field inside it). It must contain EVERY number used in the text.
3. Write numbers exactly as they appear in the data (same digits, commas, \
decimals). Never compute or round new numbers.
"""


# ---------------------------------------------------------
# Context bundle: calendar history + deterministic rollup
# ---------------------------------------------------------

def build_context(sales_payload: dict, history: list,
                  employees_payload: dict = None,
                  products_payload: dict = None,
                  *, k: int = HISTORY_K) -> dict:
    """
    Assemble the LLM context bundle.

    `history` is the pipeline's list of recent completed sales-snapshot
    `data` dicts for this owner+period, NEWEST FIRST. Calendar mapping
    happens here:

      - Dedupe by window start — two runs of the same week collapse to
        the newest (first hit in the newest-first list wins).
      - The K windows immediately preceding the current one get fixed
        positions; an absent window is None. Nulls BREAK streaks — they
        are never skipped, because skipping fabricates a trend from gaps.
      - Cold start (no usable history): recent_window and rollup are
        None — a first-class path, not an edge case.

    current_dto carries ALL THREE fresh section payloads so basis paths
    can reference employees and products too.
    """
    current_dto = {"sales": sales_payload}
    if employees_payload is not None:
        current_dto["employees"] = employees_payload
    if products_payload is not None:
        current_dto["products"] = products_payload

    bundle = {"current_dto": current_dto, "recent_window": None, "rollup": None}

    current_start = (sales_payload.get("window") or {}).get("current_start")
    if not current_start:
        return bundle  # malformed payload — degrade to cold start
    try:
        from datetime import datetime
        cur_start = datetime.fromisoformat(current_start)
    except ValueError:
        return bundle

    period = sales_payload.get("period", "week")

    # Starts of the K preceding calendar windows, OLDEST first.
    if period == "day":
        expected = [cur_start - timedelta(days=i) for i in range(k, 0, -1)]
    elif period == "week":
        expected = [cur_start - timedelta(days=7 * i) for i in range(k, 0, -1)]
    elif period == "month":
        starts = []
        y, m = cur_start.year, cur_start.month
        for _ in range(k):
            m -= 1
            if m == 0:
                m, y = 12, y - 1
            starts.append(cur_start.replace(year=y, month=m, day=1))
        expected = starts[::-1]
    else:
        return bundle

    # Newest-first input -> first hit per window start is the newest run.
    by_start = {}
    for snap in history or []:
        ws = (snap.get("window") or {}).get("current_start")
        if ws and ws not in by_start:
            by_start[ws] = snap

    recent_window = [by_start.get(exp.isoformat()) for exp in expected]
    if not any(recent_window):
        return bundle  # cold start — nothing to roll up

    bundle["recent_window"] = recent_window
    bundle["rollup"] = _rollup(recent_window, sales_payload)
    return bundle


def _rollup(recent_window: list, current_payload: dict) -> dict:
    """
    Deterministic history rollup (docs §2.2) — computed in Python from
    the snapshot payloads, never from prior LLM prose.

    recent_window is in chronological order (oldest first) and may
    contain None gaps. A gap BREAKS the decline streak. The CURRENT
    period walks as the newest entry, so "revenue declined N periods
    in a row" counts the decline into this period too.
    """
    revenues = [
        (w.get("current") or {}).get("revenue")
        for w in recent_window if w is not None
    ]
    revenues = [r for r in revenues if isinstance(r, (int, float)) and not isinstance(r, bool)]

    rollup = {
        "windows_available": len(revenues),
        "avg_revenue": round(sum(revenues) / len(revenues), 2) if revenues else 0.0,
        "consecutive_declining_periods": 0,
        "best_period": None,
        "worst_period": None,
    }

    # Decline streak walk: history windows + the current period as the
    # newest entry. Each slot is judged against its IMMEDIATE predecessor
    # slot; a None slot (missing window) resets both the streak and the
    # previous revenue — a decline across a gap is never counted.
    walk = list(recent_window) + [{
        "current": current_payload.get("current"),
        "window": current_payload.get("window"),
    }]
    streak, prev_rev = 0, None
    for w in walk:
        rev = (w.get("current") or {}).get("revenue") if w else None
        if not isinstance(rev, (int, float)) or isinstance(rev, bool):
            streak, prev_rev = 0, None  # gap breaks the streak
            continue
        if prev_rev is not None and rev < prev_rev:
            streak += 1
        else:
            streak = 0
        prev_rev = rev
    rollup["consecutive_declining_periods"] = streak

    filled = []
    for w in recent_window:
        if not w:
            continue
        rev = (w.get("current") or {}).get("revenue")
        if isinstance(rev, (int, float)) and not isinstance(rev, bool):
            filled.append(((w.get("window") or {}).get("current_start"), rev))
    if filled:
        best = max(filled, key=lambda p: p[1])
        worst = min(filled, key=lambda p: p[1])
        rollup["best_period"] = {"start": best[0], "revenue": best[1]}
        rollup["worst_period"] = {"start": worst[0], "revenue": worst[1]}

    return rollup


# ---------------------------------------------------------
# Number checking (docs §2.4)
# ---------------------------------------------------------

_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _resolve_path(bundle: dict, path: str):
    """Dotted-path lookup into the context bundle; None when unresolvable."""
    node = bundle
    for part in (path or "").split("."):
        part = part.strip()
        if not part:
            return None
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit():
            idx = int(part)
            node = node[idx] if 0 <= idx < len(node) else None
        else:
            return None
    return node


def _numbers_in(text: str):
    """Every numeric token in `text`, as floats (commas stripped)."""
    out = []
    for m in _NUM_RE.finditer(text or ""):
        try:
            out.append(float(m.group().replace(",", "")))
        except ValueError:  # pragma: no cover - regex guarantees parseable
            continue
    return out


def _iter_values(node):
    """Flatten a JSON-ish tree into its numeric leaves."""
    if isinstance(node, dict):
        for v in node.values():
            yield from _iter_values(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_values(v)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield node


def _number_grounded(num: float, targets) -> bool:
    """One number vs the allowed targets (docs §2.4 a/b/c)."""
    for t in targets:
        if num == t:                                   # (a) exact
            return True
        if abs(num - t) <= PCT_TOLERANCE:              # (a) 1dp rounding
            return True
        # (b) integer paraphrase: "about 13%" for 12.5 — the number is
        # near-integer itself and within half a unit of the target's
        # half-up rounding (math.floor(t + 0.5), NOT banker's round()).
        if (abs(num - round(num)) <= 1e-9
                and abs(num - math.floor(t + 0.5)) <= INT_TOLERANCE + 1e-9):
            return True
    return False


def _derivation_allowance(bundle: dict) -> set:
    """
    Whitelisted bundle-wide derived counts (docs §2.4 c) — statements a
    model can truthfully make that are NOT verbatim bundle fields:

      - the length of any list in the bundle ("7 days of data")
      - the count of employees whose change_pct.<metric> is negative
        ("three employees declined")
    """
    allowed = set()

    def _collect(node):
        if isinstance(node, dict):
            for v in node.values():
                _collect(v)
        elif isinstance(node, list):
            allowed.add(float(len(node)))
            for v in node:
                _collect(v)

    _collect(bundle)

    emp_root = bundle.get("current_dto", {})
    if isinstance(emp_root, dict):
        lanes = (emp_root.get("employees") or {}).get("employees")
        if isinstance(lanes, list):
            for metric in ("revenue", "profit", "orders"):
                allowed.add(float(sum(
                    1 for lane in lanes
                    if isinstance(lane, dict)
                    and isinstance((lane.get("change_pct") or {}).get(metric), (int, float))
                    and lane["change_pct"][metric] < 0
                )))
    return allowed


def _check_text(text: str, bundle: dict, basis_path: str) -> bool:
    """
    Validate one text field. Every number must be grounded either by the
    cited basis path (the point of `basis`) or by a whitelisted
    derivation. basis_path="bundle" allows the whole bundle (used for
    the summary, which may reference several sections at once).
    """
    numbers = _numbers_in(text)
    if not numbers:
        return True  # qualitative-only — nothing to check

    if basis_path == "bundle":
        targets = [float(v) for v in _iter_values(bundle)]
    else:
        basis_val = _resolve_path(bundle, basis_path)
        if isinstance(basis_val, (int, float)) and not isinstance(basis_val, bool):
            targets = [float(basis_val)]
        else:
            targets = [float(v) for v in _iter_values(basis_val)] if basis_val else []

    allowed = _derivation_allowance(bundle)
    for num in numbers:
        if num in allowed:
            continue
        if _number_grounded(num, targets):
            continue
        return False
    return True


# ---------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------

def _prompt(bundle: dict, period: str) -> str:
    return (
        f"Period type: {period}. Interpret the CURRENT period for the "
        f"store owner using the context bundle below.\n\n"
        f"BASIS RULE: every number you write in summary or observation text "
        f"must be covered by that field's cited basis path — cite the "
        f"SMALLEST subtree that contains ALL the numbers used in that text "
        f"(e.g. current_dto.sales when a sentence mixes revenue and a "
        f"percentage). Write numbers exactly as they appear in the data.\n"
        f"{OBSERVATION_RULES}"
        f"Return 1-3 observations and 1-3 areas_to_watch entries.\n\n"
        f"Context bundle (current_dto = this period's full aggregates for "
        f"sales, employees and products; recent_window = up to {HISTORY_K} "
        f"previous same-type windows in chronological order, null = no data "
        f"for that window; rollup = pre-computed history statistics):\n\n"
        f"{llm.dumps(bundle)}"
    )


# ---------------------------------------------------------
# Public entry point
# ---------------------------------------------------------

def build_insights(bundle: dict, period: str, *, llm_client=None) -> dict:
    """
    Produce the insights snapshot payload from the context bundle.

    Success:
      {"summary": str, "observations": [{"text", "basis"}],
       "areas_to_watch": [str]}
    ANY failure (empty key / budget / schema / basis / numbers):
      {"summary": None, "degraded": True, "degraded_reason": str}

    Never raises. The caller writes whichever dict arrives as the
    insights snapshot; the run completes either way.
    """
    def _degrade(reason: str) -> dict:
        print(f"[insights] degraded: {reason}")
        return {"summary": None, "degraded": True, "degraded_reason": reason}

    if not llm.is_configured() and llm_client is None:
        return _degrade(
            "LLM not configured (set GEMINI_API_KEY or LLM_PROVIDER=ollama)"
        )
    if not bundle.get("current_dto", {}).get("sales"):
        return _degrade("no current data to interpret")

    prompt = _prompt(bundle, period)
    last_reason = "unknown validation failure"
    try:
        for attempt in range(VALIDATION_ATTEMPTS):
            output = llm.generate_json(prompt, OUTPUT_SCHEMA, client=llm_client)
            cleaned, reason = _validate_output(output, bundle)
            if cleaned is not None:
                return cleaned
            last_reason = reason
            print(f"[insights] validation failed: {reason}")
            if attempt < VALIDATION_ATTEMPTS - 1:
                # One corrective retry: name the failure, ask for a fix.
                # Shares the overall LLM deadline via llm.generate_json.
                prompt = (
                    f"Your previous response failed validation: {reason}\n"
                    f"Return the full corrected JSON. Every number in "
                    f"summary/observation text must be covered by that "
                    f"field's cited basis path (the smallest subtree "
                    f"containing all its numbers).\n\n{prompt}"
                )
    except llm.LlmUnavailable as exc:
        return _degrade(str(exc))
    except llm.LlmBudgetExceeded as exc:
        return _degrade(f"LLM budget exceeded: {exc}")
    except Exception as exc:  # noqa: BLE001 - the LLM step NEVER fails the run
        return _degrade(f"unexpected {type(exc).__name__}: {exc}")
    return _degrade(last_reason)


def _normalize_basis(bundle: dict, basis: str) -> str | None:
    """
    Interpret a model-cited basis path tolerantly; None when nothing
    sensible resolves. Small local models emit two recurring shapes:

      - a missing `current_dto.` root ("employees.change_pct.revenue")
      - several comma-separated leaf paths instead of their common
        parent ("current_dto.current.revenue, current_dto.current.orders")

    For a multi-path citation the smallest common ancestor of the paths
    that resolve is returned — exactly what the model meant under the
    "smallest subtree containing every number" rule. Number grounding is
    enforced against whatever subtree this returns, so normalization can
    only widen WHICH real-data subtree is eligible, never let a
    fabricated number through.
    """
    basis = (basis or "").strip().strip("`").strip()
    if _resolve_path(bundle, basis) is not None:
        return basis

    # Several paths in one string: keep the resolvable ones, then walk
    # their token lists to the deepest shared prefix.
    if "," in basis or " and " in basis:
        token_lists = []
        for part in basis.replace(" and ", ",").split(","):
            part = part.strip().strip("`").strip(".")
            if part and _resolve_path(bundle, part) is not None:
                token_lists.append(part.split("."))
        if token_lists:
            common = token_lists[0]
            for tokens in token_lists[1:]:
                cut = 0
                for a, b in zip(common, tokens):
                    if a != b:
                        break
                    cut += 1
                common = common[:cut]
            if common:
                return ".".join(common)

    # Missing root: prepend and accept only if that resolves.
    rooted = f"current_dto.{basis.strip('.')}"
    return rooted if _resolve_path(bundle, rooted) is not None else None


def _validate_output(output, bundle):
    """
    Enforce the response contract beyond the JSON schema: shape,
    resolvable basis paths, grounded numbers, qualitative watch list.

    Returns (cleaned_payload, None) on success or (None, reason).
    """
    # ---- shape checks beyond what the response schema enforces ----
    if not isinstance(output, dict):
        return None, "model output was not an object"
    summary = output.get("summary")
    observations = output.get("observations")
    watch = output.get("areas_to_watch")
    if not isinstance(summary, str) or not summary.strip():
        return None, "missing summary"
    if not isinstance(observations, list) or not observations:
        return None, "missing observations"
    if not isinstance(watch, list):
        return None, "missing areas_to_watch"

    cleaned_obs = []
    for obs in observations:
        if not isinstance(obs, dict):
            return None, "malformed observation"
        text, basis = obs.get("text"), obs.get("basis")
        if not isinstance(text, str) or not text.strip():
            return None, "empty observation text"
        if not isinstance(basis, str) or not basis.strip():
            return None, "empty observation basis"
        # Tolerant citation handling (see _normalize_basis): accepts the
        # rooted path, a `current_dto.`-prepend, or multi-path lists via
        # their common ancestor. Ungroundable numbers are still rejected
        # below — normalization never relaxes number checking.
        basis = _normalize_basis(bundle, basis)
        if basis is None:
            return None, "observation basis does not resolve"
        if not _check_text(text, bundle, basis):
            return None, f"ungrounded number in observation: {text!r}"
        cleaned_obs.append({"text": text.strip(), "basis": basis})

    # Summary may reference several sections — checked against the
    # whole bundle, still real data only.
    if not _check_text(summary, bundle, "bundle"):
        return None, "ungrounded number in summary"

    cleaned_watch = []
    for item in watch:
        if not isinstance(item, str) or not item.strip():
            return None, "malformed areas_to_watch entry"
        if _numbers_in(item):
            return None, "areas_to_watch must be qualitative (no numbers)"
        cleaned_watch.append(item.strip())

    return {
        "summary": summary.strip(),
        "observations": cleaned_obs,
        "areas_to_watch": cleaned_watch,
    }, None

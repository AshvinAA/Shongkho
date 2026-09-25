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

# Validation rounds (docs: max 3 LLM calls overall). The first response
# plus one corrective retry when validation fails. LOCAL providers get
# the doc's full three calls: retries are free, and 3B models converge
# on a named failure less reliably than hosted models. The overall LLM
# deadline (LLM_BUDGET_SECONDS) remains the hard bound either way.
VALIDATION_ATTEMPTS = 2
LOCAL_VALIDATION_ATTEMPTS = 3


def validation_attempts() -> int:
    """Rounds allowed for the validator loop, by provider."""
    return LOCAL_VALIDATION_ATTEMPTS if llm.provider() == "ollama" else VALIDATION_ATTEMPTS


# ---------------------------------------------------------
# Output contract (docs §2.3)
# ---------------------------------------------------------

# The Gemini response_schema (the OpenAPI-ish subset the SDK accepts).
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "2-3 sentences telling the owner how TODAY is going "
                           "and what to do about it, in a friendly direct voice.",
        },
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string",
                             "description": "One insight with one concrete "
                                            "suggestion; every number must trace "
                                            "to basis. Celebrate or flag by name."},
                    "basis": {"type": "string",
                              "description": "Dotted path into the provided JSON grounding this "
                                             "claim: the SMALLEST subtree that contains EVERY "
                                             "number used in the text. Start with 'current_dto.' "
                                             "(e.g. current_dto.sales) or 'rollup.' for history "
                                             "statistics (e.g. rollup.avg_revenue)."},
                },
                "required": ["text", "basis"],
            },
        },
        "areas_to_watch": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Qualitative risks/trends worth keeping an eye on. "
                           "No numbers allowed.",
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
1. One topic per observation, from ONE place in the data. Use ONLY numbers \
from the single subtree your `basis` path points at. Never mix sales \
numbers with employee, product or history-rollup numbers in one \
observation — make a separate observation instead.
2. `basis` is EXACTLY ONE dotted path (no commas, no lists, NO [0] \
indexes): `current_dto.` followed by the fields you used (e.g. \
`current_dto.sales`, `current_dto.employees`) — NEVER \
`current_dto.employees[0]` or `current_dto.employees.0`; cite the \
section (`current_dto.employees`) when the sentence covers any \
employee — or `rollup.` for history statistics (e.g. \
`rollup.avg_revenue`) when history exists.
3. Write numbers exactly as they appear in the data (same digits, commas, \
decimals). Never compute or round new numbers.
4. Voice (placeholders X and Y — write the REAL numbers from the data, \
never X or Y):
   {"text": "Employee1 is on fire today — $X in sales! Ask the team to \
learn from their approach.", "basis": "current_dto.employees"}
   {"text": "ProductA is doing magnificently — $X profit so far. Have the \
staff keep offering it.", "basis": "current_dto.products"}
   {"text": "Sales are struggling today, down X%. Worth checking in with \
the team on what's going on.", "basis": "current_dto.sales"}
5. Every observation carries ONE concrete suggestion or a clear takeaway; \
when nothing stands out, say the day is steady and tell the owner to \
keep it up. Name employees/products exactly as the data spells them.
6. areas_to_watch: describe the RISK in words — NEVER any digit. Say \
"Karim's sales are slipping" NOT "Karim is down 12%".
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


def _magnitude_match(num: float, t: float) -> bool:
    """|num| matches |t| under the same tolerances as _number_grounded."""
    if abs(abs(num) - abs(t)) <= PCT_TOLERANCE:
        return True
    return (abs(num - round(num)) <= 1e-9
            and abs(abs(num) - math.floor(abs(t) + 0.5)) <= INT_TOLERANCE + 1e-9)


# Direction vocabulary for the sign-tolerant match below. The bundle
# stores SIGNED change percentages (a decline is -4.1); small models
# habitually write the magnitude with the sign carried by the verb
# ("revenue fell 4.1%"). The magnitude may stand in for a signed value
# ONLY when the sentence's direction words agree with the value's sign —
# so a direction-flip claim ("grew" against a decline) still fails.
_DECLINE_RE = re.compile(
    r"\b(fell|drop|dropped|decline[ds]?|down|decrease[ds]?|lost|lower|"
    r"reduced?|reduction|shrank|weaker)\b"
)
_GROWTH_RE = re.compile(
    r"\b(rose|grew|grown|increase[ds]?|up|climbed|gained|higher|jumped|stronger)\b"
)


def _direction_agrees(text: str, target: float) -> bool:
    """
    Gate for magnitude-only matches: exactly one direction kind present,
    and it matches the target's sign. Both kinds (mixed sentence) or
    neither (bare number) stay strict — the signed value is required.
    """
    lowered = (text or "").lower()
    declined = bool(_DECLINE_RE.search(lowered))
    grew = bool(_GROWTH_RE.search(lowered))
    if declined and not grew:
        return target < 0
    if grew and not declined:
        return target > 0
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
        # Sign-tolerant magnitude match: |num| == |t| AND the sentence's
        # direction words agree with the target's sign ("fell 4.1%" may
        # stand in for change_pct -4.1; "grew 4.1%" against a decline is
        # still rejected as a direction lie).
        if any(_magnitude_match(num, t) and _direction_agrees(text, t)
               for t in targets):
            continue
        return False
    return True


# ---------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------

def _prompt_bundle(bundle: dict) -> dict:
    """
    Prompt-only projection of the context bundle.

    The number checker always validates against the FULL bundle — this
    projection only decides what the MODEL sees. A real dashboard bundle
    measures ~20k chars (~5k tokens): per-bucket chart series (24 hourly
    cells), race-over-time arrays (employees × buckets × 2 metrics),
    10-deep product rankings, and K full history windows. Prefilling that
    on CPU-only local inference alone exhausts the whole LLM budget before
    a single token is generated (live-verified). None of that bulk feeds
    the commentary — the owner-facing numbers live in the summary objects,
    change_pct maps, best-lists and the rollup, which are kept whole.

    What is dropped or summarized:
      - sales.series       -> peak bucket + point count (trend shape is
                              already captured by current/previous totals)
      - employees.race_series -> dropped (cumulative arrays per employee)
      - product rankings   -> top 3 rows per ranking, name+numbers only
      - recent_window      -> dropped (rollup already summarizes it)
    """
    dto = bundle.get("current_dto") or {}
    view = {"current_dto": {}}

    sales = dto.get("sales")
    if isinstance(sales, dict):
        view["current_dto"]["sales"] = {
            "period": sales.get("period"),
            "current": sales.get("current"),
            "previous": sales.get("previous"),
            "change_pct": sales.get("change_pct"),
            "best": sales.get("best"),
            "window": sales.get("window"),
            "series_points": len(sales.get("series") or []),
            "peak_series_bucket": max(
                (sales.get("series") or []),
                key=lambda c: c.get("revenue", 0) or 0,
                default=None,
            ),
        }

    employees = dto.get("employees")
    if isinstance(employees, dict):
        lanes = employees.get("employees") or []
        view["current_dto"]["employees"] = {
            "employees": [
                {k: lane.get(k) for k in
                 ("name", "is_owner", "orders", "revenue", "profit", "change_pct")
                 if k in lane}
                for lane in lanes
            ],
        }

    products = dto.get("products")
    if isinstance(products, dict):
        prod_view = {}
        for key in ("top_by_revenue", "top_by_profit", "bottom_by_revenue"):
            prod_view[key] = [
                {k: row.get(k) for k in
                 ("name", "units", "revenue", "profit", "margin_pct", "units_change_pct")
                 if k in row}
                for row in (products.get(key) or [])[:3]
            ]
        view["current_dto"]["products"] = prod_view

    view["rollup"] = bundle.get("rollup")
    return view


def _prompt(bundle: dict, period: str) -> str:
    return (
        f"Period type: {period}. Interpret the CURRENT period for the "
        f"store owner using the context bundle below.\n\n"
        f"BASIS RULE: every number you write in summary or observation text "
        f"must be covered by that field's cited basis path — cite the "
        f"SMALLEST subtree that contains ALL the numbers used in that text "
        f"(e.g. current_dto.sales when a sentence mixes revenue and a "
        f"percentage; rollup.avg_revenue for the history average). Write "
        f"numbers exactly as they appear in the data. Address the owner as "
        f"\"you\" and give ONE concrete suggestion per point.\n"
        f"{OBSERVATION_RULES}"
        f"Return 1-3 observations and 1-3 areas_to_watch entries.\n\n"
        f"Context bundle (current_dto = this period's aggregates for sales, "
        f"employees and products; rollup = pre-computed history statistics, "
        f"null = no history yet; chart series are summarized — every number "
        f"you may cite is in this bundle):\n\n"
        f"{llm.dumps(_prompt_bundle(bundle))}"
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
        attempts = validation_attempts()
        for attempt in range(attempts):
            output = llm.generate_json(prompt, OUTPUT_SCHEMA, client=llm_client)
            cleaned, reason = _validate_output(output, bundle)
            if cleaned is not None:
                return cleaned
            last_reason = reason
            print(f"[insights] validation failed: {reason}")
            if attempt < attempts - 1:
                # One corrective retry: name the failure, ask for a fix.
                # Shares the overall LLM deadline via llm.generate_json.
                prompt = (
                    f"Your previous response failed validation: {reason}\n"
                    f"Return the full corrected JSON. Every number in "
                    f"summary/observation text must be covered by that "
                    f"field's cited basis path (the smallest subtree "
                    f"containing all its numbers). Cite the SECTION as a \
plain dotted path — never an indexed element: `current_dto.employees` \
for anything about one or more employees, `current_dto.products` for \
products. If a change percentage "
                    f"in the data is NEGATIVE, sales DECLINED: write the "
                    f"minus sign or a word like 'fell'/'dropped' — never "
                    f"say 'up'/'grew' for a negative value, and never "
                    f"compute new percentages.\n\n{prompt}"
                )
    except llm.LlmUnavailable as exc:
        return _degrade(str(exc))
    except llm.LlmBudgetExceeded as exc:
        return _degrade(f"LLM budget exceeded: {exc}")
    except Exception as exc:  # noqa: BLE001 - the LLM step NEVER fails the run
        return _degrade(f"unexpected {type(exc).__name__}: {exc}")
    return _degrade(last_reason)


def _repair_nested_index(bundle: dict, basis: str) -> str | None:
    """
    One-shot fix for section/index shorthand citations (llama3.2):
    'current_dto.employees.0.revenue' means 'current_dto.employees.
    employees.0.revenue' in the real bundle shape {employees: {employees:
    [...]}}. When an index token does NOT resolve where the path stands
    but the parent resolved to a SECTION DICT, duplicate the previous
    token (the section name) so the index reaches the nested list. Every
    insertion is verified by resolving the final path — notation repair
    only; it can never make a fabricated number groundable.
    """
    tokens = basis.split(".")
    if not any(t.isdigit() for t in tokens):
        return None  # nothing index-shaped to repair
    out = []
    for tok in tokens:
        if out:
            node = _resolve_path(bundle, ".".join(out))
            if (node is not None and isinstance(node, dict) and tok.isdigit()
                    and _resolve_path(bundle, ".".join(out + [tok])) is None
                    and out[-1] != tok):
                out.append(out[-1])   # employees.0 -> employees.employees.0
        out.append(tok)
    repaired = ".".join(out)
    return repaired if _resolve_path(bundle, repaired) is not None else None


def _common_ancestor(bundle: dict, token_lists: list) -> str | None:
    """
    Deepest shared dotted prefix of the given path token lists that
    actually resolves in the bundle — the smallest subtree containing
    every cited path (docs §2.3's "smallest subtree" rule).
    """
    common = token_lists[0]
    for tokens in token_lists[1:]:
        cut = 0
        for a, b in zip(common, tokens):
            if a != b:
                break
            cut += 1
        common = common[:cut]
    while common:
        if _resolve_path(bundle, ".".join(common)) is not None:
            return ".".join(common)
        common = common[:-1]  # a cited sibling was itself unresolvable — widen
    return None


def _normalize_basis(bundle: dict, basis: str, text: str = "") -> str | None:
    """
    Interpret a model-cited basis path tolerantly; None when nothing
    sensible resolves. Small local models emit three recurring shapes:

      - a missing `current_dto.` root ("employees.change_pct.revenue")
      - several comma-separated leaf paths instead of their common
        parent ("current_dto.current.revenue, current_dto.current.orders")
      - a TOO-NARROW single path: the sentence cites revenue but also
        uses the profit / orders / change_pct numbers that live in the
        same parent object

    The first two are accepted as-is (or joined at their common
    ancestor). For the third, the cited path is WALKED UP to the
    shallowest RESOLVING ancestor whose subtree grounds every number in
    the text — exactly what the model meant under the "smallest subtree
    containing every number" rule, it just cited one leaf of it.

    Strictness elsewhere is deliberate: a citation whose tail does not
    exist in the bundle still fails, and when no ancestor grounds the
    numbers the ORIGINAL citation is returned so the checker reports the
    precise "ungrounded number" failure. Normalization only ever widens
    WHICH real-data subtree is eligible — a fabricated number matches
    nothing at ANY depth, so it can never be let through.
    """
    basis = (basis or "").strip().strip("`").strip()
    # Notation tolerance: models write JSONPath-style indices
    # ("…top_by_revenue[0].revenue"). Convert to our dotted form; this
    # only changes NOTATION — the path still has to exist in the bundle.
    basis = re.sub(r"\[(\d+)\]", r".\1", basis)
    # Nested-section repair: llama cites 'current_dto.employees[0]'
    # when the bundle stores {employees: {employees: [...]}} — the
    # bracket converts to 'employees.0' but the SECTION name must be
    # repeated for the path to resolve. Insert it (verified against the
    # bundle, index in range) so the observation is judged on its
    # numbers, not discarded over citation shorthand.
    if _resolve_path(bundle, basis) is None:
        basis = _repair_nested_index(bundle, basis) or basis
    if _resolve_path(bundle, basis) is not None:
        if _numbers_in(text):
            # Too-narrow-citation repair: keep the deepest level while it
            # grounds the text; otherwise step up to the smallest
            # resolving ancestor that does. Nothing grounds it -> keep
            # the original (the checker then rejects the text).
            tokens = basis.split(".")
            while tokens:
                candidate = ".".join(tokens)
                if _check_text(text, bundle, candidate):
                    return candidate
                tokens = tokens[:-1]
            return basis
        return basis  # qualitative text — the citation stands as given

    # Several paths in one string: keep the resolvable ones, then walk
    # their token lists to the deepest shared prefix.
    if "," in basis or " and " in basis:
        token_lists = []
        for part in basis.replace(" and ", ",").split(","):
            part = part.strip().strip("`").strip(".")
            if part and _resolve_path(bundle, part) is not None:
                token_lists.append(part.split("."))
        if token_lists:
            ancestor = _common_ancestor(bundle, token_lists)
            if ancestor:
                return ancestor

    # Missing root: prepend and accept only if that resolves.
    rooted = f"current_dto.{basis.strip('.')}"
    if _resolve_path(bundle, rooted) is not None:
        return rooted

    return None  # unresolvable citation — degrade per the contract


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
        # rooted path, a `current_dto.`-prepend, multi-path lists via
        # their common ancestor, or a too-narrow leaf widened to the
        # parent that grounds the text. Ungroundable numbers are still
        # rejected below — normalization never relaxes number checking.
        basis = _normalize_basis(bundle, basis, text)
        if basis is None:
            # Quote the citation so logs show WHAT the model invented
            # (hallucinated field, typo, or a path pruned from the prompt).
            return None, f"observation basis does not resolve: {obs.get('basis')!r}"
        if not _check_text(text, bundle, basis):
            return None, f"ungrounded number in observation: {text!r}"
        cleaned_obs.append({"text": text.strip(), "basis": basis})

    # Summary may reference several sections — checked against the
    # whole bundle, still real data only. The reason quotes the text so
    # logs show WHICH number the model fabricated.
    if not _check_text(summary, bundle, "bundle"):
        return None, f"ungrounded number in summary: {summary!r}"

    cleaned_watch = []
    dropped_watch = 0
    for item in watch:
        if not isinstance(item, str) or not item.strip():
            return None, "malformed areas_to_watch entry"
        if _numbers_in(item):
            # Salvage, not fail: areas_to_watch is decorative (the doc:
            # qualitative-only). Dropping a numeric entry keeps the
            # payload available without ever SHOWING an ungrounded
            # number; summary/observations above stay fully strict.
            dropped_watch += 1
            continue
        cleaned_watch.append(item.strip())
    if dropped_watch:
        print(f"[insights] salvaged: dropped {dropped_watch} numeric "
              "areas_to_watch entries")

    return {
        "summary": summary.strip(),
        "observations": cleaned_obs,
        "areas_to_watch": cleaned_watch,
    }, None

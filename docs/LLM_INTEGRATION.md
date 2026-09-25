# Shongkho LLM Integration — Final Architecture (v3)

Supersedes v2. The philosophy is unchanged; v3 nails down the four things v2 left
implicit that would have broken in production, and upgrades the hallucination
guard from "exact match, tighten later" to "basis-anchored and tolerant, at launch."

## 0. Resolved decisions (what changed from v2, and why)

| # | Topic | v2 said | v3 says | Why |
|---|---|---|---|---|
| 1 | History semantics | "last 2–4 periods, full JSON" | Last **K=4 calendar windows** of the same `period_type`, sourced from completed `sales` snapshots, **deduped by `window.current_start`** (latest run wins). A missing window is `null` and **breaks streaks** — it is never skipped. `sales` snapshots are exempt from future pruning. | Snapshots exist only when someone clicks "Run analysis." "Last N runs" is ambiguous under irregular click history; two runs of the same week must collapse to one; a naive pruning job would delete exactly the history the rollup consumes. |
| 2 | LLM call vs DB transaction | "write all 4 rows in one tx" (LLM position ambiguous) | Compute payloads → **call the LLM with an 8s total budget** → *then* open the tx and write 4 rows. Never hold a DB transaction across a network call. | Connection-pool exhaustion and lock contention under concurrent load; unbounded retries (schema loop) could hang the "Run analysis" button for 10s+. |
| 3 | Chat persistence | "no persistence" | Persist **every turn** in an `assistant_messages` table; the sliding window is only the **prompt projection**. | "No LLM memory" ≠ "store nothing." The table carries the daily cap (a Redis counter resets on restart), reload parity with the existing store chat, and an audit trail of fallbacks/refusals. |
| 4 | Window contents | append the whole `{message, ui_blocks}` envelope | Append `message` + tool **names/args** only. Payloads never re-enter the window. | Re-sending 60-bucket payloads every turn contradicts "re-fetch, don't remember" principle and is pure token waste. |
| 5 | Hallucination guard | strict extract-and-match; `basis` "only if observed" | **`basis` ships at launch.** Checker = basis-path resolution + tolerant number match + derivation whitelist. The same checker guards Part B narration. | An exact-match checker false-positives on rounded ("about 13%" for 12.5) and derived-but-correct numbers ("three employees declined"), silently replacing correct insights with fallbacks — that erodes trust faster than the occasional real hallucination. Basis anchoring fixes both directions: the checker knows *which* number a claim must match, and a fabricated number has no valid path to cite. |
| 6 | Transport | SSE | **POST for v1**; SSE deferred as a sequencing decision, not a correction. | A 5-call-capped loop is ~5–15s — a plain POST survives that. The loop is transport-agnostic; the codebase has zero streaming infra; the test suite is POST-shaped. Wrap in SSE later only if real usage shows the wait hurts. |
| 7 | Redis tool cache | 5-min TTL, args-hash keys | **Deferred** to a later Part B iteration. | Indexed lookups at POS scale don't need it; one less moving part in v1. (When it lands: canonicalize args — sorted keys — or near-identical calls silently miss.) |

Also fixed: an **empty `GEMINI_API_KEY`** degrades deterministically (stage-1
placeholder for Part A, `503` for Part B) — stage 1 explicitly guarantees this
configuration must work, so the LLM may never make it fail.

---

## 1. Shared principle (unchanged from v1/v2)

**The LLM is never the source of a number.** Every number it ever outputs — in
commentary or in chat — traces to the current DTO, a deterministically computed
rollup, or a live tool result. Never to something an LLM said earlier, and never
retyped by the LLM when it could be passed through verbatim. `basis` (2.3) is the
mechanism that makes this checkable rather than aspirational.

---

## 2. Part A — Generative Analysis

### 2.1 Trigger and placement

Runs once per "Run analysis" click, inside `pipeline._execute_run`, **after** the
three aggregators produce their JSON payloads and **before** the snapshot
transaction. Same call site for the sync and celery executors — the LLM step is
just part of the pipeline function, which is why both executors get it for free.

### 2.2 Context bundle (history semantics)

```python
build_context(db, owner_id, period) -> {
    "current_dto": {...},          # the three fresh section payloads
    "recent_window": [...] | None, # K=4 previous calendar windows, sales DTOs
    "rollup": {...} | None,        # computed over recent_window, in Python
}
```

- **Source rows:** completed `analytics_snapshots` where `section='sales'` and
  `period_type` matches, newest first.
- **Dedupe** by `data["window"]["current_start"]` — two runs of the same week
  collapse to the row with the highest id (latest run wins).
- **Calendar mapping:** the K windows immediately preceding the current one.
  An absent window is `null` at its position. Nulls **break** streaks — they are
  never skipped, because skipping fabricates a trend out of gaps.
- **Cold start** (no history at all): `recent_window` and `rollup` are `None`;
  the prompt renders from the current DTO alone. First-run is a first-class
  path, not an edge case.
- **Rollup v1** (computed in Python from the deterministic snapshot payloads —
  never from prior LLM prose):
  - `avg_revenue` across available windows
  - `consecutive_declining_periods` — consecutive non-null windows with
    declining revenue, ending at the window before current
  - `best_period` / `worst_period` by revenue
  - (trend_slope is cut: a regression over ≤4 points is noise. Revisit if K grows.)

### 2.3 Output contract (with basis)

```python
class Observation(BaseModel):
    text: str      # prose; every number in it must trace to `basis`
    basis: str     # dotted path into the bundle, e.g. "sales.change_pct.revenue"

class AnalysisOutput(BaseModel):
    summary: str                        # 2–3 sentences, numbers checked
    observations: list[Observation]     # 3–5
    areas_to_watch: list[str]           # qualitative ONLY — digits are rejected
```

Forced structured output via Gemini `response_schema` — never free text parsed
after the fact. Temperature 0.1.

Why `basis` at launch (not "if observed"): it makes the tolerant checker
tractable. Tolerance alone can't tell "about 13%" (fine, 12.5 rounded) from
"about 40%" (fabricated). With basis, the checker compares against one known
value instead of scanning the whole bundle.

### 2.4 Validation pipeline

```
LLM call  (8s total budget across ALL attempts — budget dominates count)
  │
  ├─ Pydantic/schema validation
  │     fail → retry with the validator's error text (max 3 LLM calls overall)
  │
  ├─ basis paths resolve in the bundle?  ── no ──▶ fail
  │
  ├─ number check, per text field — every number must be one of:
  │     (a) the value at a cited basis path, after normalization
  │         (%-signs, thousand separators stripped; ±0.05 for 1dp percentages)
  │     (b) a whitelisted derivation: item count of a list/array in the
  │         bundle; count of negative `change_pct` values among employees
  │     (c) an integer rounding of a bundle value within 0.5
  │
  ├─ pass → insights payload = {summary, observations, areas_to_watch}
  │
  └─ any failure → deterministic fallback string, insights row still written,
                   run still COMPLETED, row flagged:
                   data["degraded"]=true, data["degraded_reason"]="…"
```

Failure taxonomy — **all degrade, none fail the run**: empty key · timeout ·
schema-fail ×3 · unresolved basis · number mismatch. The other three sections
are always valid; an LLM outage must never cost the owner their charts.

### 2.5 Transaction boundary (the rule)

```
payloads = aggregate_sales/employees/products()   # pure functions, no tx open
insights = build_insights(bundle, llm)            # network call — NO tx open
tx: write 4 snapshot rows in one commit; run → COMPLETED
```

### 2.6 System prompt sketch

> You are a business analyst interpreting a pre-calculated dataset for a small
> shop owner. Every claim must trace to a number in the provided JSON — cite the
> field you used in `basis`. No causal explanations the data doesn't support.
> Write numbers verbatim as they appear, with units. `areas_to_watch` is
> qualitative: no numbers. Output must match the schema exactly.

---

## 3. Part B — Conversational Analytics (v1 scope)

### 3.1 Transport: POST

`POST /api/v1/analytics/chat` — synchronous, returns the full envelope. The
agent loop (below) is transport-agnostic; SSE later wraps the same loop with
`status`/`tool_result` events. Owner-only (`require_owner`), same gate as the
dashboard and reports.

### 3.2 Memory vs storage — the split

| Layer | Contents | Purpose |
|---|---|---|
| `assistant_messages` (DB, persisted) | role, message text, `ui_blocks`, `tool_calls` (names+args), created_at | reload history, daily cap, audit of fallbacks/refusals |
| sliding window (prompt projection) | last N=8 turns as `{role, message, tool_names}` | context only |

The DB row stores everything needed to **render** a turn; the window carries
only what's useful to **think** with. If a follow-up needs the data again, that's
a new tool call — the design already treats that as cheap and correct.

### 3.3 Tools (closed registry — v1 ships 3)

| Tool | Backing | Scope-injected param |
|---|---|---|
| `get_sales_metrics(start, end)` | `aggregators` + new `timeutils.range_buckets` | `store_id` |
| `get_employee_performance(start, end, employee_id?)` | `aggregate_employees` over arbitrary range | `store_id` |
| `get_top_products(start, end, metric, limit)` | `aggregate_products` over arbitrary range | `store_id` |

**Payload shaping (unchanged from v2):** tools return pre-aggregated buckets,
never raw rows. New pure function `timeutils.range_buckets(start, end)`:

- span ≤ 31 days → daily buckets · ≤ 180 days → weekly · else monthly
- hard ceiling of 60 buckets — a two-year request degrades to monthly
  resolution instead of silently answering only the first month

**Self-correction:** a tool raises `ValueError` on bad args (e.g.
`metric="discount"`); the error text is returned to the LLM as the tool's
observation; it gets one corrective retry — counted against the cap, not on top
of it. Still failing → surfaced "I couldn't complete that" message, never a 500.

`store_id` is always injected server-side from the session — never an
LLM-supplidable argument, in any tool.

### 3.4 Agent loop

```
loop_count = 0
while loop_count < MAX_TOOL_CALLS (5):
    decision = llm.next_action(context)
    if decision.type == "final_response": break
    if decision.type == "tool_call":
        result = execute_tool(decision)     # ValueError path = 1 counted retry
        loop_count += 1
        context.append(result)
if never got final_response:
    return fallback: "I wasn't able to work this out — try rephrasing?"
```

**Narration check (new):** the final `message` runs through the same number
checker as Part A, against the loop's accumulated tool results. On failure the
`ui_blocks` are kept — the components carry the real numbers — and `message` is
replaced with a template ("Here's what I found."). The narration is decoration;
the data never depends on it.

**Out-of-scope questions** get an explicit persisted refusal ("I can't answer
that from store data"), never improvisation.

### 3.5 Response envelope — narration and data are separate channels

```json
{
  "message": "Here are your top products by revenue this month — Mustard Oil is well ahead.",
  "ui_blocks": [
    { "type": "product_table", "source_tool": "get_top_products", "data": [ /* raw tool result, untouched */ ] }
  ]
}
```

The LLM writes `message` only. The backend attaches `ui_blocks` from the raw
tool results via the fixed mapping — the LLM never touches this step, never
retypes numbers, never invents UI structure:

| `source_tool` | component type | frontend rendering |
|---|---|---|
| `get_sales_metrics` | `sales_chart` | reuse SalesTrend's chart |
| `get_employee_performance` | `employee_leaderboard` | reuse EmployeeRace's bars |
| `get_top_products` | `product_table` | reuse TopProducts' table |

Adding a visual later = one mapping line, not an LLM contract change.

### 3.6 Cost control

**20 assistant messages / day / store**, enforced *before* the LLM call by
counting today's rows in `assistant_messages` (survives restarts — a Redis
counter would not). `429` with a friendly message when hit. Cap applies to
assistant turns (the expensive ones), not user messages.

### 3.7 Empty API key

`503 { "detail": "Assistant is not configured" }` — deterministic and testable,
same philosophy as Part A's degrade.

---

## 4. Data model & configuration

New table only — no changes to existing tables:

```
assistant_messages
  id          PK
  owner_id    int, indexed        # store scope
  role        'user' | 'assistant'
  message     Text
  ui_blocks   JSON, nullable      # assistant turns with visuals
  tool_calls  JSON, nullable      # names + args (never results)
  created_at  DateTime
```

Env (all optional, sane defaults):

| Var | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | *(empty = degrade)* | both parts |
| `LLM_MODEL` | `gemini-2.5-flash` | cost/latency-appropriate for both |
| `LLM_BUDGET_SECONDS` | `8` | Part A total LLM budget |
| `ASSISTANT_WINDOW` | `8` | sliding-window turns |
| `ASSISTANT_DAILY_CAP` | `20` | Part B cap |
| `ASSISTANT_TOOL_CALL_CAP` | `5` | Part B loop bound |

`requirements.txt`: add `google-genai` (the current SDK; `google-generativeai`
is deprecated).

---

## 5. Code layout

```
backend/
  analytics/
    insights.py      # Part A: build_context (history+rollup), build_insights, checker
    llm.py           # thin Gemini wrapper: client, response_schema, budget, retries
    tools.py         # Part B registry: 3 tools, ValueError contract
    assistant.py     # Part B: agent loop, window projection, envelope assembly
  models.py          # + AssistantMessage
  routes/analytics.py  # + POST /chat, GET /chat/history
frontend/src/
  components/analytics/InsightsCard.jsx   # summary + observations + areas_to_watch
  components/assistant/…                  # panel + ui_blocks renderers (reuse above)
  api/assistant.js
```

## 6. Testing

Both parts take the LLM as an injectable dependency — the same seam pattern as
`get_enqueue`. Tests use a `FakeLLM`; no network, no key needed:

- Part A: happy path · empty key · timeout · schema-retry-then-pass ·
  schema-fail ×3 → fallback · unresolved basis · number mismatch ·
  history dedupe / missing-window streak break / cold start
- `timeutils.range_buckets`: resolution boundaries, 60-bucket ceiling
- Part B: tool ValueError + corrective retry · loop-cap exhaustion ·
  narration-check fallback keeps ui_blocks · daily cap 429 · empty key 503 ·
  window projection excludes payloads

## 7. Build order

1. **Part A** — smallest unit of value, rides the existing pipeline seam,
   prerequisite for B's `get_latest_insight` later.
2. **Part B** — 3 tools + POST envelope; the one genuinely new piece of math is
   `range_buckets`.
3. **Stage 4 infra** — beat watchdog, pruning, SSE — only when prod usage demands.

## 8. Pruning contract (binds stage 4)

Whatever job prunes snapshots must retain `section='sales'` rows covering the
last 8 calendar windows per period_type (rollup needs K=4; 2× buffer).
`insights` prunable beyond the latest few runs; `employees`/`products` freely
prunable. This contract is why the pruning job must not be written before this
document exists.

## 9. Shared guardrail checklist (final)

- [ ] LLM never has write access to any database, directly or via tool
- [ ] `store_id` always server-injected, never LLM-supplied
- [ ] Structured output enforced via schema, not parsed from free text
- [ ] Every number traces to real data — enforced by basis + tolerant checker in **both** parts
- [ ] No LLM-authored text fed back into a future LLM call as fact (window carries names, never results)
- [ ] Explicit coded fallback for "no tool fits" / validation failure — never improvise past capability
- [ ] Tool payloads pre-aggregated/bucketed at the source, 60-bucket ceiling
- [ ] Agent loop hard cap at 5; self-correction counts against it
- [ ] Schema failures: bounded retries inside an 8s budget, then fallback
- [ ] `ui_blocks` vs `message` separate channels — backend assembles, LLM narrates
- [ ] LLM call never inside a DB transaction
- [ ] Empty API key degrades deterministically in both parts
- [ ] Chat persisted for cap/UX/audit; window is only a prompt projection

## 10. Explicitly deferred

- SSE wrapper for Part B (sequencing decision — the loop is ready for it)
- Redis tool cache (+ args canonicalization when it lands)
- `get_latest_insight()` tool — ships once Part A is stable in production
- `trend_slope` in the rollup (needs more history than K=4 to mean anything)
- Rendering `basis` in the UI — it is a validation artifact, not user-facing

---

## 11. Implementation addendum (v3.1) — local-provider calibration

Part A was developed and hardened against a local Ollama model
(`LLM_PROVIDER=ollama`, llama3.2 3B) because Gemini free-tier quotas kept
interrupting development. The guardrails were NOT relaxed for it; the
following tolerance refinements were added after live failures showed
where a small model's CORRECT claims get rejected by a naive checker.
All of them preserve the invariant "a fabricated number matches nothing
at any depth":

1. **`rollup.*` is a citable basis root.** The doc says "dotted path into
   the bundle" — the rollup is deterministic precomputed Python output,
   so `rollup.avg_revenue` etc. resolve like any other subtree. Mixed
   sales+rollup sentences are still rejected (smallest-subtree rule).
2. **Common-ancestor citation join.** Multi-path citations
   ("…current.revenue, …current.orders") resolve to their deepest shared
   resolving prefix instead of failing.
3. **Too-narrow-citation repair.** A resolvable citation whose subtree
   misses numbers used in the text is walked UP to the smallest ancestor
   that grounds every number. Unresolvable (garbage-tail) citations still
   fail — only genuinely-cited-but-too-deep paths widen.
4. **Sign-tolerant magnitude match, direction-gated.** DTOs store SIGNED
   change percentages; small models write "revenue fell 4.1%" for -4.1.
   |num|≈|t| passes ONLY when the sentence carries exactly one direction
   kind (decline/growth vocabulary) and it agrees with the value's sign.
   "grew 4.1%" against a decline still fails; a bare "4.1%" still requires
   the signed match.
5. **Local retry economics.** Extra attempts are free on localhost:
   Ollama gets 5 transport attempts (vs 3 remote) and 3 validation rounds
   (vs 2), all inside the same LLM_BUDGET_SECONDS deadline. Set
   LLM_BUDGET_SECONDS=120 locally — CPU inference of a 3B model takes
   10–70s per call.
6. **Prompt pruning (dashboard scale).** A real dashboard bundle measures
   ~20k chars (~5k tokens): chart series, race-over-time arrays, 10-deep
   product rankings, K full history windows. Prefilling that on CPU-only
   local inference exhausted the entire LLM budget before one output
   token (live-verified: 170s+ timeout; the frontend showed the degrade
   card with a misleading reason). Fix: `insights._prompt_bundle` sends
   the model a projection — totals, change_pct, best-lists, employee
   lanes, top-3 product rows, the rollup — while the checker still
   validates against the FULL bundle, so grounding never weakens.
   History reaches the model as rollup statistics, not raw windows.
   Validation-failure reasons now quote the offending basis/text.
7. **Advisory persona + watch salvage.** The insight voice is a
   co-pilot, not an analyst: celebrate/flag employees and products BY
   NAME with one concrete suggestion per point, address the owner as
   "you", "keep it up" when nothing stands out. Grounding is unchanged.
   `areas_to_watch` stays qualitative per the doc — numeric entries are
   now DROPPED (salvage) instead of failing the payload; the doc's
   checker contract for summary/observations is untouched. Additional
   small-model tolerances: JSONPath-style citation indices
   ("…[0].revenue") convert to dotted form (existence still required),
   and the corrective retry now TEACHES the sign rule (negative
   change_pct = decline) after live runs showed direction flips
   repeating verbatim across attempts.
8. **Part B shipped (v3.1 scope).** All of §3 is implemented per the
   doc: `tools.py` (closed 3-tool registry, strict date/metric/limit
   validation, participant-scoped queries, ValueError = model-facing
   observation), `assistant.py` (agent loop capped at 5 rounds,
   window projection of roles+message+tool_names only, daily cap
   counted from assistant_messages, backend-assembled ui_blocks via
   the fixed tool->component mapping, narration check reusing Part
   A's checker), `llm.chat_decide` (final/tool/refuse decision
   protocol, schema-forced, provider-agnostic), `range_buckets`
   (daily/weekly/monthly resolution, 60-bucket ceiling), routes
   (POST /analytics/chat with the 429/503 contract, GET
   /analytics/chat/history), AssistantMessage persistence, and the
   frontend panel reusing SalesTrend/EmployeeRace/TopProducts as
   ui_blocks. Two live-driven deviations from the literal doc text:
   the narration check is not only a post-hoc gate — the FIRST bad
   narration earns ONE in-loop self-correction round (an error
   observation like a tool ValueError, counted against the cap);
   only a SECOND bad narration swaps in the template. And the
   decision prompt explicitly forbids answering sales questions from
   conversation memory — a 3B model will otherwise "remember"
   numbers instead of calling tools (hosted models comply better).
   Live batteries: `backend/live_chat_battery.py` (real Ollama
   end-to-end, multi-turn) alongside `live_ollama_battery.py`.
   Tool payloads for arbitrary ranges intentionally omit change_pct:
   there is no like-for-like baseline outside the fixed windows.
9. **Part B is TEXT-ONLY (product decision, post-v3.1).** The chat is
   an advisor, not a chart host: the envelope is `{message,
   tool_calls, meta}` — no `ui_blocks` (the DB column remains, NULL,
   for migration safety). The LLM's deliverable is advisory prose:
   recommendation, the numbers behind it, concrete actions, an
   alternative with its trade-off, and pushback when the owner's plan
   is risky. CHAT_SYSTEM_PROMPT encodes that shape (ANSWER / WHY /
   HOW / ALTERNATIVE); general business knowledge is allowed for
   strategy, but every NUMBER still traces to this turn's tool
   results via the Part A checker — the guardrail is unchanged.
   Telemetry gains `shipped_grounded` (the loop's own verdict that the
   shipped message is checker-clean; eval_assistant.py treats False as
   the fatal fabricated_number_leakage metric). Fallback texts now
   point at the dashboard charts instead of "above". Frontend: the
   panel renders messages only (UiBlockList removed); suggestion
   chips ask advice questions.

Known limitation (prose quality, not grounding): a 3B model occasionally
flips a direction word ("fell" for a rise) while the number is verbatim-
correct. The checker passes it — numbers trace to real data; the verb is
decoration. Hosted models (Gemini) follow direction instructions far more
reliably; revisit if it matters after the switch.

Live-verification artifact: `backend/live_ollama_battery.py` (5 scenarios:
cold start, history rollup, gap-streak-break, full DB pipeline,
budget-degrade) — run with
`LLM_PROVIDER=ollama LLM_BUDGET_SECONDS=120 python live_ollama_battery.py`
from backend/. Switching to Gemini stays an env change only:
`LLM_PROVIDER=gemini`, `GEMINI_API_KEY=…`, `LLM_MODEL=gemini-2.5-flash`.

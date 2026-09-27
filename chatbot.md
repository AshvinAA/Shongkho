# The Chatbot (Part B — Conversational Analytics)

Architecture write-up of the store owner's chat assistant: what it is,
how a turn flows, why every guardrail exists, and what live evaluation
taught us about running it on a 3B local model.

Authoritative spec: [`docs/LLM_INTEGRATION.md`](docs/LLM_INTEGRATION.md)
(§3 is the design; §11 addendum items 8–13 are the live-driven changes
this document summarizes).

---

## 1. What it is

A text-only **business advisor** inside the POS app. The owner asks
things like *"What should we push this week?"*, *"How much has Rahim
sold today?"*, *"Who's my worst performer?"* — and gets a
recommendation with real numbers behind it, concrete actions, and
pushback when their plan is risky.

Two product decisions shape everything downstream:

1. **Text-only (no ui_blocks).** The chat is an advisor, not a chart
   host — the dashboard already renders the charts. The response
   envelope is `{message, tool_calls, meta}`. The DB column for
   ui_blocks remains (NULL) for migration safety; the frontend panel
   renders messages only.
1. **Bilingual by birth (Bangla / Banglish / English).** The owner
   writes in any mix of Bangla script, romanized Banglish, and
   English; Protik answers in the same language — or, with the
   owner's switch on বাংলা, in Bangla regardless of input
   (see §14; design in `docs/PROTIK_BANGLA_PLAN.md`).
2. **Advisor persona, not an analyst.** Every data answer follows an
   implicit ANSWER / WHY / HOW / ALTERNATIVE shape: recommendation
   first, the 2–3 numbers that justify it, concrete actions for the
   coming days, and a second option with its trade-off. The assistant
   takes a side, argues for it, and celebrates wins by name. General
   business judgment is allowed for strategy — but **every NUMBER
   must trace to this turn's tool results** (see §5, the reality
   gate).

## 2. The 3-tool closed registry (`backend/analytics/tools.py`)

The model can only call these; nothing else exists:

| Tool | Returns | Typical question |
|---|---|---|
| `get_sales_metrics(start, end)` | `{totals:{revenue,profit,orders}, series, best}` | "How did we do today?" |
| `get_employee_performance(start, end, employee_name?)` | `{employees:[{name,is_owner,orders,revenue,profit}]}` | "Who sells the most?" |
| `get_top_products(start, end, metric, limit)` | `{metric, products:[{name,units,revenue,profit,margin_pct}]}` | "Most sold product?" |

Contract highlights:

- **Scope injection:** `store_id`/`owner_id` is injected server-side;
  the LLM never supplies scope and never gets write access to
  anything. Every query is scoped to the owner's participants
  (employees + the owner); an empty participant list matches nothing.
- **Pre-aggregated payloads, never raw rows** — shaped like the
  dashboard sections the frontend already knows.
- **Bad arguments raise ValueError with model-facing text** (strict
  ISO dates, explicit metric/limit enums). The agent loop feeds that
  error text back as an observation, buying the model ONE counted
  corrective retry.
- Unknown `employee_name` uses a case-insensitive contains-match and
  raises a helpful ValueError so the model can re-ask or re-scope.

## 3. Memory vs storage — the split (`docs/LLM_INTEGRATION.md` §3.2)

- **Every turn is persisted** in `assistant_messages` (roles + message
  + `tool_calls` for audit; the daily cap counts these rows; the
  frontend reloads from them).
- **The prompt window is only a projection**: the last `WINDOW_TURNS = 8`
  turns as `{role, message, tool_names}` — **never tool payloads**.
  Results must be re-fetched, not remembered. This also blocks the
  classic 3B failure of "remembering" numbers from an earlier turn
  and quoting them without a fresh fetch.

## 4. The agent loop (`backend/analytics/assistant.py`, `handle_message`)

One turn, start to finish:

1. Config check → `AssistantUnavailable` (503) if no provider.
   Daily cap check (`DAILY_CAP = 20` assistant messages/day/store)
   → `DailyCapReached` (429).
2. Persist the user turn.
3. Resolve the **language mode** (`auto | bn | en`): the request's
   `language` field wins, else the owner's persisted
   `owners.assistant_language`, else `auto`. Detect the message
   language (`llm.detect_language`, Bengali-unicode ratio).
4. Classify the question's **data domain** once (`_question_domain`):
   `employee` / `product` / `None` — from keywords (English, Bangla
   and Banglish) plus this store's literal employee names ("How is
   Rahim doing?" has no keyword; the name IS the signal). Product
   hints override employee hints ("best-selling product"). Used by
   the relevance gate and the wrong-domain rescue.
5. Build the context: `{today, conversation: window projection,
   tool_results: [], force_language, message_language}` — the
   `tool_results` key starts as an explicit **empty cue**, because a
   3B model treats an absent key as "nothing to do" and answers from
   memory; `force_language` is what the prompt's LANGUAGE rule reads.
6. Loop, bounded at `TOOL_CALL_CAP = 5` rounds. Each round:
   `llm.chat_decide(...)` returns exactly one JSON decision —
   `tool` (fetch), `final` (answer), or `refuse`. Tool results and
   error observations accumulate into `context.tool_results`.
   Tool ValueErrors go back as observations (one counted corrective
   retry). The loop **never raises** for LLM/tool failures — those
   degrade to honest fallbacks, never a 500.
7. Post-loop **narration gate** + rescue ladder (§6), Bengali-numeral
   transliteration + (under `bn`) Bangla fallback swap, telemetry
   stamped, assistant turn persisted, envelope returned:
   `{message, tool_calls, meta}`.

Telemetry (`meta`) is observational: `rounds_used`,
`narration_retried`, `specificity_retried`, `grounded_first_pass`,
`refused`, `tool_calls_ok`, `tool_errors`, `context_bytes`,
`auto_fetch`, `rate_limit_waited`, `fallback_reason` ∈
{`decision_error`, `cap_exhausted`, `narration_double_fail`,
`conversation_double_fail`, `refuse_after_data`, `synthesized`,
`no_reply`, `prediction_redirect`, `world_knowledge_redirect`}, and
`shipped_grounded` — the loop's own verdict that the shipped message
is checker-clean (the eval harness treats a False as the fatal
`fabricated_number_leakage`).

## 5. Guardrails: the reality gate + the relevance gate

**Reality gate (numbers must be real).** The final message runs
through Part A's number checker (`insights._check_text`) against the
accumulated tool results as a grounding bundle
(`_narration_grounded`). Every number in prose must appear verbatim
in a tool result — never computed ("about 450 per order" from 1350
and 3 is rejected), never invented, never from conversation memory.
With no data fetched, only number-free prose passes.

**Relevance gate (real numbers must be the RIGHT numbers).** Live-run
failure: "Who is the worst performing employee?" was answered with a
PRODUCT's real revenue — the reality gate passed it because the
numbers were real; nothing required them to be relevant.
`_narration_relevant` additionally requires the message's numbers to
come from the question's domain tool (employee question →
`get_employee_performance` data, etc.). Number-free advice text may
draw on any fetched context. Ambiguous questions (domain `None`) are
gated for reality only.

**Specificity gate (a grounded answer must SAY something).**
External-review-found hole (Claude, verified in code): a lay-off
question answered with number-free, entity-free hedging ("the trailing
seller", "the gap is significant") passed BOTH gates above — nothing
false in it, and nothing in it either. `_narration_specific` requires
that on a classified employee/product question whose right-domain tool
returned rows, the final message NAMEs at least one entity from the
payload (whole-word match). Empty payload waives it; unclassified
questions are exempt.

Together the three gates (`_gates_pass` = reality ∧ relevance ∧
specificity) enforce the invariants that held across **all** live eval
runs: **zero fabricated numbers ever shipped**, and no vague dodge on
a pointed data question.

## 6. The rescue ladder

The 3B model's failures are predictable, so the loop compensates
deterministically. In order, from cheapest to most drastic:

0. **429 smoothing (`rate_limit_wait_s`).** A rate-limit decision
   failure carries Google's own retry hint. A short window
   (≤ `RATE_LIMIT_MAX_WAIT_S`) is slept out and the SAME round retried
   once (`meta.rate_limit_waited`); a longer window degrades
   immediately to the honest fallback — holding the owner's click
   hostage for a minute is worse UX than an honest retry-now card.
   Local providers are never rate-limited, so their errors carry no
   hint and this rung never fires on Ollama.

1. **Corrective narration retry (once, counted against the cap).**
   The first failed narration gets an error observation whose wording
   matches the failure shape — reality, relevance, or specificity
   (checked in that order):
   - reality, has data → "quote ONLY numbers that appear verbatim in
     tool_results — never a difference, total or percentage you
     calculated yourself";
   - reality, no data, number-free reply that still tripped the
     checker (digits in "top 3 products" chit-chat) → "reply in plain
     words with NO digits — spell counts out";
   - reality, no data, numbers in reply → "call the right tool first,
     then answer using ONLY numbers from its result."
   - relevance → "rewrite using ONLY data from the tool matching the
     question's subject";
   - specificity → "too vague to act on: commit to specifics — name
     the actual people or products involved, quote their numbers."
2. **Refuse-after-fetch retry.** Refusing after this turn already
   fetched data is a misfire (the model was told to answer with the
   results). One corrective retry; a second refusal ships the fixed
   `REFUSAL_AFTER_DATA_FALLBACK` (the model's own refusal text was
   observed echoing the corrective error verbatim — untrustworthy).
3. **Auto-fetch rescue (`_auto_tool_for` + `_auto_fetch`).** When the
   model WILL NOT call the tool for a data question — or refuses one
   — the loop fetches the obvious tool ITSELF: employee keyword or a
   literal employee name → `get_employee_performance` (scoped to that
   name only when the user typed it); product domain →
   `get_top_products(metric=revenue, limit=5)`; otherwise
   `get_sales_metrics` — args always complete. Exactly one auto-fetch
   per turn (`meta.auto_fetch`), cap-bounded. Fires on a no-data
   narration double-fail AND immediately on any refusal of a
   classified question (fetch-first — waiting for a second refusal
   wastes a full 30–90s round).

   Every model-supplied tool call passes through `_sanitize_tool_args`
   first: date placeholders copied from the prompt examples
   ("\<today\>", "\<week ago\>") become real ISO dates, and an
   employee_name that appears nowhere in the conversation is dropped
   (an example-name copy narrows the payload to one person — exactly
   what happened live).
4. **Deterministic synthesis (`_synth_answer`).** If the model still
   cannot narrate real, right-domain data — or twice answered a
   classified question with vague, entity-free prose — the loop builds
   the final answer DIRECTLY from the tool payload: employee ranking
   ("X leads your staff with … Y trails at …"), top-product push, or
   sales totals — every number copied verbatim, checker-clean by
   construction. `fallback_reason: "synthesized"`. (The specificity
   gate is what routes vague answers here: the ranking template names
   exactly the entities the model refused to name.)
5. **Honest fallbacks + deterministic shields.** Nothing synthetic
   fits, or there is no data (the fetch-first floor closes the last
   hole: a classified question that ships with NO fetch at all —
   gates pass vacuously when nothing was claimed — gets its tool
   called and synthesized from):
   - data was fetched → `NARRATION_FALLBACK` ("I pulled your store
     data but couldn't phrase the answer reliably — the dashboard
     charts have the numbers…");
   - no data on a data-flavored question (`_DATA_HINT_RE`) →
     `DATA_NO_REPLY_FALLBACK`;
   - no data on a conversational ask → `CONVERSATION_FALLBACK`
     (the co-pilot pitch — the designed answer for a misfired
     greeting).

   Priority note (Gemini-eval-fixed): the prediction/world-knowledge
   shields fire BEFORE the refuse-after-data apology — a prediction
   ask that fetched data and then refused ships `PREDICTION_REDIRECT`,
   never a generic apology for a question the design already answers.

Order of last resort: **model narration → synthesis → honest
fallback**. A right-domain fetch plus an honest fallback always beats
a wrong-domain answer.

## 7. Routing: the ordered question-asker (`CHAT_SYSTEM_PROMPT`)

`llm.chat_decide` sends the context plus a schema-forced decision
prompt under `CHAT_SYSTEM_PROMPT` (`backend/analytics/llm.py`). The
prompt is an **ordered question-asker** — act on the FIRST that
matches:

- **Q1 — conversation.** Greetings, thanks, chit-chat, "what do you
  know / can do" → warm colleague reply, **NO digits at all**, NO
  tool call, NO refusal. (This is where the capabilities answer
  lives.)
- **Q2 — store data.** Sales, products, employees, revenue, profit,
  stock, hiring/firing, advice that needs them → **fetch first,
  advise after** (the default for store questions). "Most sold" /
  "best seller" / "top product" = `get_top_products`; employee
  questions = `get_employee_performance` **never** product data;
  store-wide "how did we do" = `get_sales_metrics` totals. Got the
  numbers? → final in the ANSWER/WHY/HOW/ALTERNATIVE shape.
- **Q3 — refuse.** Real-world facts (weather, sports, news),
  predictions ("how much will we sell next month"), other businesses
  → one polite sentence. Refuse is legal only when
  `tool_results` is empty — never after fetching.

Hard rules also in the prompt: one tool per turn; never restate raw
JSON; history is NOT data (always re-fetch); only this turn's tool
numbers may appear in the reply; output only the JSON object.

## 8. Few-shot strategy — what llama3.2 (3B) taught us

Hard-won lessons, each paid for with live failures:

- **Examples outperform rules by a wide margin.** Every observed
  failure shape got a WRONG/RIGHT example pair (describe-without-
  fetching, computed numbers, refusing in-scope).
- **Option-framing swings behavior wildly.** A refuse-first ordering
  made it a refuse-bot (refusing in-scope questions); a tool-first
  "default" made it fetch on "how are you". The Q1/Q2/Q3 order
  balances both.
- **Final-answer examples must carry NO copyable numerals.** The
  model copies example numbers/names verbatim into real answers
  (the checker correctly killed them). Examples teach ROUTING, never
  content — "copy the routing, never the content".
- **Corrective messages must match the failure shape** (§6.1): "call
  the tool first" on a has-data failure makes the model drop ALL
  numbers; "plain words, no digits" is the right fix for digit-
  sprinkled chit-chat.
- **Domain classification includes advice INTENT.** "Lay off", "let
  go", "struggling", "weakest", "should I keep" classify as employee
  questions even without an explicit employee noun — the intent word
  IS the signal (a live gap: "Should I lay off my weakest seller?"
  was unclassifiable, so nothing rescued it).
- **An absent key reads as "nothing to do"** — hence the explicit
  `tool_results: []` cue.

**Temperature:** chat decisions run at `0.2`. At `0.4` routing was
flaky; at `0.1` the model verbatim-copied the examples; `0.2` is the
compromise now that the final-answer example carries no copyable
content. `num_predict 1100` (700 truncated long advice answers
mid-sentence — "…the best-selling product, the").

## 9. Configuration & limits

| Knob | Value | Where |
|---|---|---|
| `WINDOW_TURNS` | 8 | assistant.py |
| `DAILY_CAP` | 20 assistant messages / day / store | assistant.py |
| `TOOL_CALL_CAP` | 5 rounds | assistant.py |
| Chat temperature | 0.2 | llm.py `chat_decide` |
| `num_predict` | 1100 (Ollama), `num_ctx` 8192 | Ollama client |
| `LLM_BUDGET_SECONDS` | 30 (Gemini); was 90 on Ollama (CPU-only inference takes 10–190s per call) | backend/.env |
| Provider | `LLM_PROVIDER=gemini`, `GEMINI_API_KEY=…`, `LLM_MODEL=gemini-3.5-flash-lite` (dev switched 2026-09-27; free-tier limits are per model — flash-lite 15/min, flash tiers 5/min) | backend/.env |
| Language mode | `owners.assistant_language` = `auto \| bn \| en` (owner-persisted); per-turn override via the chat request's `language` field — `PUT /auth/me/preferences` | models.py, routes/auth.py, routes/analytics.py |

Dev currently runs on Gemini; the Ollama row of history remains
one env edit away (`LLM_PROVIDER=ollama`, `LLM_MODEL=llama3.2`) — the
pipeline is provider-agnostic (`generate_json` / `chat_decide`
contract, schema-forced output both ways). Two provider-neutral
tightenings shipped with the switch (§17 of docs/LLM_INTEGRATION.md):
schema enums on `action`/`tool`/`metric` (Gemini's responseSchema
otherwise free-texts tool names), and date-arg inference in
`_sanitize_tool_args` (the optional-args schema otherwise lets Gemini
emit `args: {}` and burn rounds on ValueErrors).

Switching to Gemini is an env change only — `LLM_PROVIDER=gemini`,
`GEMINI_API_KEY=…`, `LLM_MODEL=gemini-3.5-flash-lite` — no code changes;
the whole pipeline is provider-agnostic (`generate_json` /
`chat_decide` contract, schema-forced output both ways).

## 10. Evaluation

**Hermetic harness** (`backend/eval_assistant.py`): seeds a
deterministic store (Owner + Rahim + Karim + 2 products + labeled
sales), runs the REAL loop against the configured provider, and
scores model **behavior** against labeled expectations — no free-text
scoring, no LLM judge. 12 scenarios across kinds: `data` (sales_today,
employee_perf, top_products, most_sold, employee_named, sales_range,
multi-part employee_vs_product), `conversation` (smalltalk,
capabilities — must answer warmly, NOT refuse), `out_of_scope`
(world_knowledge, prediction, off_topic). Each scenario is history-
isolated (`fresh=True` wipes its conversation — a poisoned history
would contaminate every later measurement).

Note: `eval_assistant.py` must not `load_dotenv` at import (it is
imported by pytest; `tests/conftest.py` scrubs `LLM_*` env to stay
hermetic). Env loads inside `main()` only.

Metrics: `grounding_first_pass_rate`, `narration_retry_rate`,
`fabricated_number_leakage` (must be 0 — the run exits non-zero if
not), `fallback_rate`, `refusal_precision`, `over_refusal_rate`,
`tool_selection_accuracy`, `conversation_answered`, `avg_rounds_per_turn`,
`tool_arg_error_rate`, `cap_exhaustion_rate`, latency p50/p95,
`context_bytes_per_round`.

```bash
# from backend/ — Ollama live runs; batches of ≤5 scenarios
# (600s shell timeouts kill longer batches)
LLM_PROVIDER=ollama LLM_MODEL=llama3.2 LLM_BUDGET_SECONDS=150 \
    python eval_assistant.py            # full suite
python eval_assistant.py --list
python eval_assistant.py --only employee_perf smalltalk --quick
```

`backend/live_chat_battery.py` is the contract battery: asserts the
text-only envelope (exactly `{message, tool_calls, meta}`, no
ui_blocks key), `shipped_grounded`, and an advice-voice probe.

```bash
# self-review: 22 basic questions (EN + BN/Banglish), per-answer verdicts
# and per-language eval gates; --gap keeps free-tier RPM honest, --lang
# pins a default mode for cases without their own
PYTHONUTF8=1 python basic_questions_battery.py --gap 8
PYTHONUTF8=1 python basic_questions_battery.py --gap 8 --only q17,q18,q19,q20,q21,q22
```

**Live results trajectory (llama3.2 3B, CPU-only):**

- `fabricated_number_leakage = 0` across **every** run — the
  guardrail invariant never broke, through every prompt iteration.
- Employee questions: ~50% fallback run-to-run → **0% fallback** after
  the relevance gate + auto-fetch + synthesis landed.
- Basic-question battery: after the §11.16 hardening round (sales
  domain, echo detector, conversation/prediction/world-knowledge
  shields, synth discipline), **16/16 basic owner questions pass**
  deterministic verdicts live — no echoes, no wrong refusals, no
  fabricated numbers across ~20 live turns.
- `most_sold` answers correctly with real advice ("Push more of
  Sugar 1kg… highest units sold"); capabilities/smalltalk answered
  conversationally; `refusal_precision` hit 100% on the out-of-scope
  batch.
- `grounding_first_pass` reached 83–100% on data scenarios.
- Residual 3B limits: multi-part `employee_vs_product` still
  oscillates between a perfect answer and an honest fallback
  run-to-run; latency p50 ~30–60s, p95 up to ~190s on CPU; occasional
  `cap_exhaustion` / `tool_arg_error`. One live session also exposed
  (and drove fixes for) example-content copying: placeholder dates
  ("\<today\>") and example names ("Rahim") pasted into real tool
  calls, byte-identical echoed answers on unrelated questions, and a
  one-person "leads … trails" synthesis — see
  `docs/LLM_INTEGRATION.md` §11 item 15 for the turn-by-turn
  forensics.## 11. Tests

Backend suite (`cd backend && python -m pytest tests/ -p no:warnings -q`,
300 passing) covers, chatbot-relevant:

- `tests/test_assistant.py` — loop behavior with fake decision
  clients: fetch-then-answer, narration retries per failure shape,
  refuse-after-fetch, wrong-domain rescue, auto-fetch, synthesis
  (employee ranking, sales totals), daily cap, scope isolation, window
  projection (payloads never in history).
- `tests/test_language.py` — the language switch: preference
  persistence, `bn` force (prompt directive + Bangla fallbacks),
  Banglish shields, synth templates in Bangla, Bengali-numeral
  normalization, dashboard `language=bn` cache + honest fallback.
- `tests/test_eval.py` — harness aggregation, leakage detection,
  hermeticity.
- `tests/test_insights.py` — Part A checker (the reality gate),
  nested-index citation repair.
- `tests/test_analytics.py` — tools, pipeline (incl. stale-run
  reaping), aggregators.

Frontend (`cd frontend && npx vitest run`, 41 passing) covers the
text-only assistant panel, API client, and the Protik language switch
(`ProtikLanguage.test.jsx`).

## 12. File map

| File | Role |
|---|---|
| `backend/analytics/assistant.py` | Agent loop, rescue ladder, domain classification (EN/BN/Banglish), relevance gate, synthesis (EN+BN templates), language resolution, Bangla fallbacks, numeral transliteration, telemetry, caps, persistence |
| `backend/analytics/llm.py` | Provider clients (Ollama/Gemini), `chat_decide`, `CHAT_SYSTEM_PROMPT` (+ LANGUAGE rule), `_DECISION_SCHEMA`, `detect_language`, Part A `generate_json` |
| `backend/analytics/tools.py` | Closed 3-tool registry, scope injection, model-facing ValueErrors |
| `backend/analytics/insights.py` | Part A checker (`_check_text`, `_numbers_in`) — the reality gate; citation repair |
| `backend/routes/analytics.py` | `POST /analytics/chat` (429/503 contract), `GET /analytics/chat/history` |
| `backend/models.py` | `AssistantMessage` (role, message, tool_calls JSON, created_at) |
| `backend/eval_assistant.py` | Labeled scenario eval harness + metrics |
| `backend/live_chat_battery.py` | Text-only contract battery (live provider) |
| `frontend/src/components/assistant/AssistantPanel.jsx` | Text-only chat panel (messages only) |
| `frontend/src/api/assistant.js` | Envelope client |
| `backend/basic_questions_battery.py` | 22-question live battery (EN + BN/Banglish), per-answer verdicts, per-language eval gates, `--lang` (self-review tool) |
| `docs/LLM_INTEGRATION.md` | Authoritative spec; §11 items 8–19 are this doc's source of record |
| `docs/PROTIK_BANGLA_PLAN.md` | The Bangla/Banglish design — now fully implemented (§6 steps 1–5) |

## 13. The model ceiling — and why the architecture compensates

The pipeline was hardened against **llama3.2 3B (CPU-only, Ollama)** —
free, unlimited, local, but weak at tool discipline. Everything in §6
(auto-fetch, refuse-retry, corrective retry shapes, synthesis) exists
to compensate for the 3B ceiling, and it now does so well enough that
employee-question fallbacks went to 0%.

The longer-term fix is the model, not more scaffolding: on a hosted
model (Gemini) most of the rescue ladder becomes redundant — but it
**stays as a safety net**, and the reality/relevance gates are
provider-independent invariants, not 3B workarounds. That is the
design bet: guardrails belong in the loop, not in the model's
goodwill.

**Known limitation (prose, not grounding):** a 3B model occasionally
flips a direction word ("fell" for a rise) while the number itself is
verbatim-correct. The checker passes it — the number traces to real
data; the verb is decoration. Hosted models follow direction
instructions far more reliably.

**Gemini verified (2026-09-27):** the thesis holds live. On
`gemini-3.5-flash-lite` the battery went 16/16 with genuine model
prose (named entities, verbatim numbers, one concrete action per
point, honest about zero-sale days) and the rescue ladder fired on
only 2 of 16 questions. The guardrails are quiet precisely because
the model is good — and still standing if the model is not.

## 14. The language switch — Bangla / Banglish / English (2026-09-28)

Full implementation of `docs/PROTIK_BANGLA_PLAN.md` (spec:
`docs/LLM_INTEGRATION.md` §19). The architectural bet, unchanged:
**translate at the model, never in a layer** — an MT sandwich would
compound grounding drift and sever the number-checker from the text
the owner reads.

**The mode.** `auto | bn | en`, persisted per owner
(`owners.assistant_language`, `PUT /auth/me/preferences`) with a
per-turn override on the chat request. `auto` mirrors the message
language; `bn` forces Bangla even on English questions; `en` is the
historical behavior. The context tells the model what to do
(`force_language` + `message_language`); the system prompt's LANGUAGE
rule enforces it.

**What goes bilingual — and what does not.**

| Layer | In `bn` mode |
|---|---|
| Model prose (chat answers) | Bangla, always |
| Part A commentary | own `insights_bn` snapshot, served via `?language=bn` (honest `missing_language` fallback — no live re-billing) |
| Deterministic fallbacks / refusals / redirects | Bangla pairs, swapped exact-match post-loop |
| Synth templates (auto-fetch answers) | parallel Bangla tables, numbers verbatim |
| Shields (conversation, prediction, world-knowledge, domain hints) | Bangla-script + Banglish triggers |
| The checker & gates | UNCHANGED — Western digits (`\d` matches Bengali digits too) + original-script names are language-agnostic |
| Receipts / POS | English (decided) |

**Two live traps worth remembering:**

1. **`\b` and Bengali.** Python `re` treats combining vowel signs
   (ি ে ো) as non-word characters, so `\b` after a Bengali word ending
   in one never matches. All Bangla-script regex alternatives use
   Bengali-block lookarounds instead.
2. **Bengali numerals ship anyway.** The model writes ১৩৫০ despite the
   prompt rule. The gates catch it (`\d` matches Unicode decimals — no
   vacuous pass), but good replies were replaced; every shipped reply
   is now transliterated to Western digits (`_normalize_bn_numerals`)
   before the shipped-grounded invariant.

Also worth knowing: a Bangla prediction ("আগামী মাসে বিক্রি কত হবে?")
classifies as a SALES question (the বিক্রি hint fires), so the
fetch-first rescue must skip prediction-shaped asks — the redirect is
the designed answer in any language.

**Eval.** Battery: 22 cases (q17–q22 Bangla/Banglish), `--lang` flag,
per-language eval gates in the summary, expected-language judge
(Bengali-unicode presence; English-fallback leak fails under `bn`).
Full run 22/22 PASS on `gemini-3.5-flash-lite`. The battery raises
`DAILY_CAP` for its own scratch store — 22 questions outpace the
product's 20/day cap.

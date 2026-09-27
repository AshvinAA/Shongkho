# Protik (প্রতীক) — Bangla / Banglish Translation Plan

**Status: PLAN ONLY — nothing here is implemented yet.**

Goal: the owner writes in Bangla (বাংলা) or Banglish (romanized Bangla
mixed with English), Protik understands both, and replies in Bangla.
A language switch (AUTO / বাংলা / EN) shifts the entire Protik tab —
chat AND the generative analysis — to Bangla.

---

## 1. Language model (the switch)

Three modes, stored **per owner** (new `assistant_language` column on
`owners`, or a small `user_preferences` table):

| Mode | Meaning |
|---|---|
| `auto` (default) | Detect per message: Bangla or Banglish in → Bangla reply; English in → English reply |
| `bn` | Force Bangla everywhere — replies AND the Part A generative analysis, regardless of input language |
| `en` | Current behavior (English everywhere) |

The mode travels with every request:

- `POST /analytics/chat` gains an optional `language` field
  (default `auto`) — the frontend sends the current switch state.
- `GET /analytics/dashboard` gains `language` — when `bn`, the
  insights section is requested (and cached) in Bangla.

A per-owner persisted default (set on the Protik page next to the
switch) means the choice survives reloads; the request field only
exists so the UI's in-session switch works without a round-trip first.

## 2. Why "translate at the model" (the big decision)

Two architectures exist:

- **A. Machine-translation layer** (Bangla→English→LLM→English→Bangla)
  — rejected: double translation compounds grounding drift, loses
  Banglish idioms, adds latency and cost, and the number-checking
  gates would run against prose that no longer matches the reply the
  user reads.
- **B. Native bilingual generation** (chosen): the model READS Bangla
  or Banglish directly and is instructed to answer in the target
  language. Gemini handles code-mixed Banglish well; all our
  guardrails (grounding checker, entity naming, refusal shields) keep
  operating unchanged because they are language-agnostic
  (digits, name matching).

Consequences of B:

- `CHAT_SYSTEM_PROMPT` gains a language directive:
  "Reply in the SAME language the user wrote in — Bangla script,
  Banglish, or English. When `force_language` is 'bn', ALWAYS answer
  in Bangla script, even for English questions."
- Banglish understanding needs no transliteration layer up front; if
  quality disappoints later, add a small transliteration normalizer
  (BKSP/Avro-style rules) as a PRE-prompt hint, never as a rewrite.
- The Part A engine gets the same directive via `SYSTEM_PROMPT` +
  a `language` parameter threaded through `insights.generate()`.

## 3. Grounding & safety in Bangla (the subtle part)

- The number checker (`_numbers_in`, grounding gates) is
  language-agnostic: digits are digits in Bangla prose. **But** we
  must decide whether the model may write Bengali numerals (১২৩৪).
  Recommendation: prompt rule "write numbers in Western digits
  (1234, not ১২৩৪)" so every existing gate, the synthesizer, and the
  frontend `fmtMoney` keep working unchanged.
- `_synth_answer` templates need Bangla variants (deterministic
  fallbacks must speak Bangla when the mode is Bangla — an English
  fallback inside a Bangla conversation breaks trust). Keep them as
  parallel template tables keyed by language.
- The echo/example-copy shields: few-shot examples stay English (the
  model translates naturally); extend `_ECHO_PHRASE_RE` only if
  Bangla echoes of examples appear live.
- Refusal shields (`_PREDICTION_RE`, `_WORLD_KNOWLEDGE_RE`,
  `_CONVERSATION_ASK_RE`) are English regexes today. Add Bangla +
  Banglish trigger words ("আগামী মাসে কত বিক্রি", "prediction/agami",
  "weather/আবহাওয়া", "tumi kemon acho") — a shared trigger-vocab
  table in one module so chat and Part A stay in sync.
- Daily-cap and rate-limit UX strings shown in the UI need i18n
  entries so the whole panel feels Bangla, not just the model output.

## 4. Part A (generative analysis) in Bangla

- `insights.generate(..., language='bn')` appends the language
  directive; the JSON schema does not change (fields stay English;
  only the *values* — summary/observations — come back in Bangla).
- Cache key becomes `(owner, period, language)` so an English run and
  a Bangla run can coexist; switching the toggle re-renders from the
  right snapshot without re-billing the LLM.
- Degraded/empty states on the Protik hero get Bangla UI strings.

## 5. Frontend UX (Protik tab)

- A three-way segmented switch in the page header:
  `AUTO | বাংলা | EN`, persisted per owner (`PUT /me/preferences`).
- The switch state is passed to `AssistantPanel` (per-request
  `language`) and to the dashboard fetch (`language` query param).
- Suggested opening questions get Bangla variants:
  "এই সপ্তাহে কোন পণ্য বেশি চাপ দেওয়া উচিত?", "আজ কে সবচেয়ে ভালো
  বিক্রি করেছে?" — shown when the switch is on বাংলা.
- Font stack: add a Bangla-capable webfont (Noto Sans Bengali) so the
  huge hero type renders cleanly; `lang="bn"` on the hero container
  for correct shaping.

## 6. Rollout order (each step shippable alone)

1. **Banglish passthrough** (zero backend change): prompt rule
   "reply in the user's language". Ship, then evaluate with the
   battery extended by 4–6 Bangla/Banglish cases.
2. **Per-owner switch + `bn` force mode** (chat): `language` field,
   prompt directive, eval cases pinned to Bangla output.
3. **Part A in Bangla**: language directive + cache-key change +
   hero UI strings.
4. **Deterministic layer i18n**: Bangla synth templates, shield
   trigger words, UI strings.
5. **Polish**: Noto Sans Bengali, `lang` attributes, suggestion
   chips, evaluation dashboard per language.

## 7. Evaluation before calling it done

Extend `basic_questions_battery.py` with Bangla/Banglish cases
(q17–q22: Bangla script in, Banglish in, English-in-with-bn-force,
prediction-in-Bangla → Bangla redirect, capabilities in Bangla,
date-range in Bangla) with deterministic judges: expected-language
heuristic (Bengali unicode range ratio), same grounding rules, no
English fallback leakage when `bn` is forced. Battery must hit 100%
before the switch ships to the UI.

## 8. Risks & open questions

- **Bengali numerals** leaking from the model → gate + prompt rule
  (decided: Western digits only).
- **Banglish ambiguity** ("kal" = yesterday or tomorrow) → the model
  should ask ONE clarifying question rather than guess; add an eval
  case for it.
- **Mixed-language grounded names**: employees/products have English
  names in the DB; prompt rule: "keep product and people names in
  their original script, quote numbers exactly."
- **Token cost**: Bangla script is ~1.5–2× tokens vs English; free
  tier still fine at chat volumes, note it for Part A frequency.
- Open question for the owner: should the POS/receipt stay English
  even in বাংলা mode? (Recommended: yes — receipts stay English,
  Protik speaks Bangla.)

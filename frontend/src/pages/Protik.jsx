import { useCallback, useEffect, useRef, useState } from 'react'
import { Zap } from 'lucide-react'
import { useAuth } from '../context/AuthContext.jsx'
import { getDashboard, getRunStatus, startRun } from '../api/analytics.js'
import { updateMyPreferences } from '../api/auth.js'
import { SegmentedControl, Button, Badge } from '../components/ui/index.jsx'
import AssistantPanel from '../components/assistant/AssistantPanel.jsx'
import { PROTIK } from '../components/assistant/identity.js'

const PERIOD_OPTIONS = [
  { value: 'day', label: 'Day' },
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
]

// বাংলা mode relabels the page chrome too (docs/PROTIK_BANGLA_PLAN.md §5).
const PERIOD_OPTIONS_BN = [
  { value: 'day', label: 'দিন' },
  { value: 'week', label: 'সপ্তাহ' },
  { value: 'month', label: 'মাস' },
]

// Protik's language mode (docs/PROTIK_BANGLA_PLAN.md §1/§5):
// auto = mirror the owner's language; bn = force Bangla everywhere;
// en = plain English. Persisted per owner via PUT /auth/me/preferences.
const LANG_OPTIONS = [
  { value: 'auto', label: 'Auto' },
  { value: 'bn', label: 'বাংলা' },
  { value: 'en', label: 'EN' },
]

const POLL_MS = 1500

/**
 * Protik (প্রতীক) — the store's AI co-pilot, on his own tab.
 *
 * Both LLM integrations live here on one screen:
 *   - Part A: the generative analysis from the latest analytics run as a
 *     BI hero — headline summary in huge type, supporting observations,
 *     areas-to-watch chips, generated-at stamp.
 *   - Part B: the advisor chat (shared AssistantPanel) beside the hero.
 *
 * The run lifecycle mirrors Analytics.jsx (start -> poll -> refetch)
 * but renders only the insights section, so this page stays focused.
 */
export default function Protik() {
  const { user } = useAuth()
  const isOwner = user?.role === 'owner'

  const [period, setPeriod] = useState('week')
  // The switch's initial value is the owner's persisted preference
  // (hydrated by /auth/me); changing it refetches AND persists.
  const [lang, setLang] = useState(user?.assistant_language || 'auto')
  const [insights, setInsights] = useState(null)
  const [generatedAt, setGeneratedAt] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [run, setRun] = useState(null)
  const pollRef = useRef(null)

  const loadDashboard = useCallback(async (p = period, quiet = false, l = lang) => {
    if (!quiet) setLoading(true)
    try {
      const data = await getDashboard(p, l)
      setInsights(data.sections?.insights || null)
      setGeneratedAt(data.generated_at)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [period, lang])

  useEffect(() => {
    if (isOwner) loadDashboard(period)
  }, [isOwner, period, loadDashboard])

  useEffect(() => () => clearInterval(pollRef.current), [])

  // Flip the switch: refetch the commentary in the chosen language and
  // persist the choice (fire-and-forget — the UI never waits on it).
  function changeLang(mode) {
    setLang(mode)
    Promise.resolve(
      updateMyPreferences({ assistantLanguage: mode }),
    ).catch(() => {}) // persistence is best-effort; the session choice stands
  }

  function pollRun(runId) {
    clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const status = await getRunStatus(runId)
        setRun({ id: runId, status: status.status, reason: status.failure_reason })
        if (status.status === 'COMPLETED' || status.status === 'FAILED') {
          clearInterval(pollRef.current)
          if (status.status === 'COMPLETED') loadDashboard(period, true)
        }
      } catch (e) {
        if (e.status === 404) {
          clearInterval(pollRef.current)
          setRun({ id: runId, status: 'FAILED', reason: 'Run not found' })
        }
      }
    }, POLL_MS)
  }

  async function handleRun() {
    setError(null)
    try {
      const res = await startRun(period)
      setRun({ id: res.run_id, status: res.status || 'QUEUED' })
      if (res.status === 'COMPLETED') {
        await loadDashboard(period, true)
      } else {
        pollRun(res.run_id)
      }
    } catch (e) {
      if (e.status === 409 && run?.id) {
        pollRun(run.id)
      } else if (e.status === 409) {
        setError(lang === 'bn'
          ? 'একটা বিশ্লেষণ ইতিমধ্যে চলছে — একটু অপেক্ষা করুন…'
          : 'An analysis is already running. Give it a moment…')
      } else {
        setError(e.message)
      }
    }
  }

  if (!isOwner) {
    return <p className="muted">Protik is available to store owners only.</p>
  }

  const running = run && (run.status === 'QUEUED' || run.status === 'RUNNING')
  const forceBn = lang === 'bn'
  const periodOptions = forceBn ? PERIOD_OPTIONS_BN : PERIOD_OPTIONS

  return (
    <div className="page protik-page">
      <div className="page-header">
        <div>
          <h1>{PROTIK.name} <span className="protik-bangla">{PROTIK.nameBn}</span></h1>
          <p className="muted">
            {forceBn
              ? 'আপনার এআই সহ-পাইলট — উপরে বড় ছবি, নিচে কথা।'
              : 'Your AI co-pilot — the big picture up top, the conversation below.'}
          </p>
        </div>
        <div className="protik-controls">
          <SegmentedControl
            options={LANG_OPTIONS}
            value={lang}
            onChange={changeLang}
            ariaLabel="Protik language"
          />
          <SegmentedControl
            options={periodOptions}
            value={period}
            onChange={(p) => setPeriod(p)}
          />
          <Button onClick={handleRun} loading={!!running}>
            {running ? (forceBn ? 'বিশ্লেষণ চলছে…' : 'Analysing…')
              : (
                <>
                  <Zap size={15} aria-hidden="true" />
                  {forceBn ? 'বিশ্লেষণ চালান' : 'Run analysis'}
                </>
              )}
          </Button>
        </div>
      </div>

      {error && <div className="alert alert-error" role="alert">{error}</div>}

      <div className="protik-layout">
        {/* ---- Hero: the generative analysis ---- */}
        <section className="protik-hero" aria-live="polite" lang={forceBn ? 'bn' : undefined}>
          {loading ? (
            <div className="page-loading" role="status">
              <div className="spinner" />
              <p className="muted">{PROTIK.name} is reading your numbers…</p>
            </div>
          ) : (
            <InsightsHero insights={insights} period={period} generatedAt={generatedAt} forceBn={forceBn} />
          )}
          {running && (
            <p className="protik-refreshing muted">
              {forceBn ? 'প্রতীক একটা নতুন বিশ্লেষণ প্রস্তুত করছে…' : `${PROTIK.name} is crunching a fresh analysis…`}
            </p>
          )}
        </section>

        {/* ---- The advisor chat, beside the hero ---- */}
        <section className="protik-chat-section" aria-label={`${PROTIK.name} chat`}>
          <AssistantPanel language={lang} />
        </section>
      </div>
    </div>
  )
}

/**
 * The hero statement. Success = huge summary + supporting observations +
 * watch chips + generated-at stamp. Degraded/pending/empty get honest,
 * quieter states — never fake prose. `forceBn` (বাংলা switch): the hero's
 * own chrome speaks Bangla too. An English snapshot served while no
 * Bangla cache exists yet carries `missing_language: 'bn'` — labeled
 * honestly, never faked.
 */
function InsightsHero({ insights, period, generatedAt, forceBn = false }) {
  const t = forceBn ? {
    empty: 'একটা বিশ্লেষণ চালান, আমি আপনার দোকানের সংকেতগুলো বলে দেব।',
    emptyHint: `এই ${period === 'day' ? 'দিনের' : period === 'month' ? 'মাসের' : 'সপ্তাহের'} বিশ্লেষণ নেই — উপরে Run analysis চাপুন।`,
    degraded: (p) => `এই ${p} নির্ভরযোগ্য মন্তব্য লিখতে পারিনি — Analytics ট্যাবের চার্টগুলোই আসল উৎস।`,
    reason: 'কারণ',
    steady: 'আপনার দোকান স্থির — এই সংখ্যাগুলোতে কোনো নাটক নেই।',
    watch: 'নজরে',
    stamp: (d) => `তৈরি হয়েছে ${d} · নিচে প্রতীককে যেকোনো প্রশ্ন করুন`,
    englishOnly: 'বাংলা সংস্করণ এখনো তৈরি হয়নি — চাইলে একটা নতুন বিশ্লেষণ চালান।',
  } : {
    empty: "Run an analysis and I'll tell you what your store is trying to say.",
    emptyHint: null,
    degraded: null,
    reason: null,
    steady: null,
    watch: null,
    stamp: null,
    englishOnly: null,
  }

  if (!insights) {
    return (
      <div className="protik-hero-inner">
        <p className="protik-hero-summary">{t.empty}</p>
        {t.emptyHint ? (
          <p className="muted">{t.emptyHint}</p>
        ) : (
          <p className="muted">
            No analysis for this {period} yet — hit <strong><Zap size={13} aria-hidden="true" /> Run analysis</strong> above.
          </p>
        )}
      </div>
    )
  }
  if (insights.pending) {
    return (
      <div className="protik-hero-inner">
        <p className="protik-hero-summary">{insights.pending}</p>
      </div>
    )
  }
  if (insights.degraded) {
    return (
      <div className="protik-hero-inner">
        <p className="protik-hero-summary">
          {t.degraded
            ? t.degraded(period)
            : `I couldn't write a reliable commentary for this ${period} — your charts on the Analytics tab remain the source of truth.`}
        </p>
        {insights.degraded_reason && (
          <p className="card-sub muted" title={insights.degraded_reason}>
            {t.reason ? `${t.reason}: ` : 'Reason: '}{insights.degraded_reason}
          </p>
        )}
      </div>
    )
  }

  const observations = Array.isArray(insights.observations) ? insights.observations : []
  const watch = Array.isArray(insights.areas_to_watch) ? insights.areas_to_watch : []

  return (
    <div className="protik-hero-inner">
      {insights.missing_language === 'bn' && forceBn && (
        <Badge variant="warning" className="protik-lang-note">
          {t.englishOnly}
        </Badge>
      )}

      {insights.summary ? (
        <p className="protik-hero-summary">{insights.summary}</p>
      ) : (
        <p className="protik-hero-summary">
          {t.steady || 'Your store is steady — no drama in these numbers.'}
        </p>
      )}

      {observations.length > 0 && (
        <ul className="protik-points">
          {observations.map((obs, i) => (
            <li key={i} className="protik-point">
              <span className="protik-point-marker" aria-hidden="true">▸</span>
              <span>{obs.text}</span>
            </li>
          ))}
        </ul>
      )}

      {watch.length > 0 && (
        <div className="protik-watch">
          <span className="protik-watch-label">
            {t.watch ? `👀 ${t.watch}` : '👀 Watching'}
          </span>
          <div className="protik-watch-chips">
            {watch.map((w, i) => (
              <Badge key={i} variant="warning">{w}</Badge>
            ))}
          </div>
        </div>
      )}

      {generatedAt && (
        <p className="protik-hero-stamp muted">
          {t.stamp
            ? t.stamp(new Date(generatedAt).toLocaleString())
            : <>Generated {new Date(generatedAt).toLocaleString()} · ask {PROTIK.name} anything below</>}
        </p>
      )}
    </div>
  )
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../../context/AuthContext.jsx'
import { getChatHistory, sendChat } from '../../api/assistant.js'
import { PROTIK } from './identity.js'
import ProtikMark from './ProtikMark.jsx'
import { Button } from '../ui/index.jsx'
import Avatar from '../Avatar.jsx'

const SUGGESTIONS = [
  'What should I focus on to maximise profit this week?',
  'Who is selling the most today?',
  'Which product should we push more this week?',
]

// Bangla suggestion chips — shown when the switch forces বাংলা (plan §5).
const SUGGESTIONS_BN = [
  'এই সপ্তাহে কোন পণ্য বেশি চাপ দেওয়া উচিত?',
  'আজ কে সবচেয়ে ভালো বিক্রি করেছে?',
  'লাভ বাড়াতে কী করব?',
]

/**
 * Conversational business advisor (Part B) — TEXT-ONLY by design.
 *
 * Advisor-toned surface, visually related to the dashboard cards but
 * clearly its own: identity header from the ONE identity constant,
 * prose replies, compact user bubbles, suggestion chips on empty,
 * "working on it" status, daily-cap indicator, honest error notes.
 *
 * Each turn POSTs /analytics/chat with the current language mode
 * (plan §1: 'auto' mirrors the message, 'bn' forces Bangla); history
 * reloads on mount so the conversation survives refreshes. Error
 * contract is honest: 429 (daily cap) and 503 (not configured) surface
 * as system notes; the input re-enables either way.
 */
export default function AssistantPanel({ language = 'auto' } = {}) {
  const { user } = useAuth()
  const [history, setHistory] = useState([]) // [{role, message}]
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState(null)
  const [cap, setCap] = useState(null) // {used, limit}
  const scrollRef = useRef(null)

  const forceBn = language === 'bn'
  const suggestions = forceBn ? SUGGESTIONS_BN : SUGGESTIONS

  // UX strings follow the switch so the whole panel feels Bangla, not
  // just the model output (docs/PROTIK_BANGLA_PLAN.md §3 i18n note).
  const t = forceBn ? {
    empty: 'দোকান নিয়ে জিজ্ঞেস করুন — আমি সংখ্যা তুলে এনে পরামর্শ, বিকল্প আর প্রয়োজনে সৎ আপত্তি দেব।',
    grounded: 'আমি যেকোনো সংখ্যা সরাসরি আপনার দোকানের ডেটা থেকে বলি — কিছু বানাই না, আর ডেটা উত্তর না দিলে সৎভাবে বলি।',
    thinking: `${PROTIK.nameBn} ভাবছে…`,
    cap429: 'আজকের সব প্রশ্ন শেষ — কাউন্টার মধ্যরাত (UTC) এ রিসেট হবে।',
    not503: 'এই সার্ভারে প্রতীক এখনো কনফিগার করা হয়নি।',
    placeholder: 'বাংলায় বা ইংরেজিতে জিজ্ঞেস করুন…',
    capLabel: (u, l) => `আজ ${u}/${l} প্রশ্ন`,
  } : {
    empty: "Ask me about your store — I'll pull the numbers and give you advice, alternatives, and honest pushback when a plan looks risky.",
    grounded: "Every number I quote comes straight from your store data — I won't invent figures, and I'll say so when the data can't answer something.",
    thinking: `${PROTIK.name} is thinking…`,
    cap429: null,
    not503: null,
    placeholder: null,
    capLabel: (u, l) => `${u}/${l} questions today`,
  }

  const scrollToEnd = useCallback(() => {
    requestAnimationFrame(() => {
      const el = scrollRef.current
      if (el) el.scrollTop = el.scrollHeight
    })
  }, [])

  useEffect(() => {
    let alive = true
    getChatHistory(50)
      .then((data) => {
        if (!alive) return
        setHistory((data.messages || []).map(({ role, message }) => ({ role, message })))
        // Daily-cap indicator ships in the history envelope's meta (if the
        // backend exposes it); absent meta just hides the indicator.
        const m = data.meta || {}
        if (m.daily_used != null && m.daily_limit != null) {
          setCap({ used: m.daily_used, limit: m.daily_limit })
        }
      })
      .catch(() => {}) // a dead backend just means an empty panel
    return () => {
      alive = false
    }
  }, [])

  const send = async (text) => {
    const message = (text ?? input).trim()
    if (!message || busy) return
    setInput('')
    setNote(null)
    setHistory((h) => [...h, { role: 'user', message }])
    setBusy(true)
    scrollToEnd()
    try {
      const out = await sendChat(message, language)
      setHistory((h) => [...h, { role: 'assistant', message: out.message }])
      // Bump the cap indicator optimistically when the envelope reports it.
      const m = out.meta || {}
      if (m.daily_used != null && m.daily_limit != null) {
        setCap({ used: m.daily_used, limit: m.daily_limit })
      } else {
        setCap((c) => (c ? { ...c, used: Math.min(c.used + 1, c.limit) } : c))
      }
    } catch (e) {
      if (e.status === 429) setCap((c) => (c ? c : { used: c?.limit ?? 20, limit: c?.limit ?? 20 }))
      setNote(
        e.status === 429
          ? (t.cap429 || "You've used all your assistant messages for today — the counter resets at midnight UTC.")
          : e.status === 503
            ? (t.not503 || 'The assistant is not configured on this server.')
            : e.message,
      )
    } finally {
      setBusy(false)
      scrollToEnd()
    }
  }

  return (
    <div className="assistant-panel advisor-panel">
      <div className="advisor-head">
        <ProtikMark size={38} className="advisor-avatar protik-avatar" />
        <div className="advisor-head-text">
          <strong>{PROTIK.name} <span className="protik-bangla">{PROTIK.nameBn}</span></strong>
          <span className="muted">{forceBn ? PROTIK.taglineBn : PROTIK.tagline}</span>
        </div>
        {cap ? (
          <span
            className={`ui-badge ${cap.used >= cap.limit ? 'ui-badge-danger' : 'ui-badge-neutral'} advisor-cap`}
            title={forceBn ? t.cap429 || '' : "Daily assistant message cap — resets midnight UTC"}
          >
            {t.capLabel(cap.used, cap.limit)}
          </span>
        ) : null}
      </div>

      <div className="assistant-scroll" ref={scrollRef}>
        {history.length === 0 && (
          <div className="assistant-empty muted">
            <p>{t.empty}</p>
            <div className="assistant-suggestions">
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="advisor-chip"
                  disabled={busy}
                  onClick={() => send(s)}
                >
                  {s}
                </button>
              ))}
            </div>
            <p className="card-sub muted advisor-grounded">
              <ProtikMark size={13} className="advisor-spark-mark" aria-hidden="true" /> {t.grounded}
            </p>
          </div>
        )}

        {history.map((turn, i) => (
          <div key={i} className={`assistant-turn assistant-${turn.role}`}>
            <span className="assistant-who muted">
              {turn.role === 'user' ? (user?.name || 'You') : `${PROTIK.name} ${PROTIK.nameBn}`}
            </span>
            <p className="assistant-msg">{turn.message}</p>
          </div>
        ))}
        {busy && (
          <p className="muted assistant-typing" role="status">
            <ProtikMark size={13} className="advisor-spark-mark advisor-spark" aria-hidden="true" /> {t.thinking}
          </p>
        )}
        {note && (
          <div className={`alert ${note === t.cap429 || /daily|cap|config/i.test(note) ? 'alert-warning advisor-note' : 'alert-error advisor-note'}`}>
            {note}
          </div>
        )}
      </div>

      <form className="assistant-input" onSubmit={(e) => { e.preventDefault(); send() }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={t.placeholder || 'Ask for advice — pricing, staffing, what to push…'}
          disabled={busy}
          aria-label="Message Protik"
        />
        <Button type="submit" disabled={busy || !input.trim()} loading={busy}>
          {forceBn ? 'পাঠান' : 'Send'}
        </Button>
      </form>
    </div>
  )
}

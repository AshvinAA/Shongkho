import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../../context/AuthContext.jsx'
import { getChatHistory, sendChat } from '../../api/assistant.js'

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
 * Conversational business assistant (Part B) — TEXT-ONLY by design.
 *
 * The assistant is an advisor: it fetches store numbers with tools and
 * answers with grounded advice, arguments and alternatives in prose.
 * Charts live on the dashboard above; the chat never renders graphs.
 *
 * Each turn POSTs /analytics/chat with the current language mode
 * (plan §1: 'auto' mirrors the message, 'bn' forces Bangla); history
 * reloads on mount so the conversation survives refreshes (persistence
 * in assistant_messages). Error contract is honest: 429 (daily cap)
 * and 503 (not configured) surface as system notes; the input
 * re-enables either way.
 */
export default function AssistantPanel({ language = 'auto' } = {}) {
  const { user } = useAuth()
  const [history, setHistory] = useState([])   // [{role, message}]
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState(null)
  const scrollRef = useRef(null)

  const forceBn = language === 'bn'
  const suggestions = forceBn ? SUGGESTIONS_BN : SUGGESTIONS

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
        scrollToEnd()
      })
      .catch(() => {}) // a dead backend just means an empty panel
    return () => { alive = false }
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
    } catch (e) {
      setNote(
        e.status === 429
          ? "You've used all your assistant messages for today — the counter resets at midnight UTC."
          : e.status === 503
            ? 'The assistant is not configured on this server.'
            : e.message
      )
    } finally {
      setBusy(false)
      scrollToEnd()
    }
  }

  return (
    <div className="assistant-panel">
      <div className="assistant-scroll" ref={scrollRef}>
        {history.length === 0 && (
          <div className="assistant-empty muted">
            <p>
              Ask me about your store — I'll pull the numbers and give you
              advice, alternatives, and honest pushback when a plan looks
              risky.
            </p>
            <div className="assistant-suggestions">
              {suggestions.map((s) => (
                <button key={s} type="button" className="btn btn-outline"
                        disabled={busy} onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
            <p className="card-sub muted">
              Every number I quote comes straight from your store data —
              I won't invent figures, and I'll say so when the data can't
              answer something.
            </p>
          </div>
        )}

        {history.map((turn, i) => (
          <div key={i} className={`assistant-turn assistant-${turn.role}`}>
            <span className="assistant-who muted">
              {turn.role === 'user' ? (user?.name || 'You') : 'Protik প্রতীক'}
            </span>
            <p className="assistant-msg">{turn.message}</p>
          </div>
        ))}
        {busy && <p className="muted assistant-typing">Protik is thinking…</p>}
        {note && <div className="alert alert-error">{note}</div>}
      </div>

      <form className="assistant-input" onSubmit={(e) => { e.preventDefault(); send() }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask for advice — pricing, staffing, what to push…"
          disabled={busy}
          aria-label="Message Protik"
        />
        <button type="submit" className="btn" disabled={busy || !input.trim()}>
          {busy ? '…' : 'Send'}
        </button>
      </form>
    </div>
  )
}

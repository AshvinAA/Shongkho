import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../../context/AuthContext.jsx'
import { getChatHistory, sendChat } from '../../api/assistant.js'
import UiBlockList from './UiBlockList.jsx'

const SUGGESTIONS = [
  'How did the shop do today?',
  'Who is selling the most today?',
  'Which product should we push more this week?',
]

/**
 * Conversational analytics panel (Part B, doc §3).
 *
 * Owner-only. Each turn POSTs /analytics/chat; the envelope's message
 * and ui_blocks render in one scrollback (data blocks reuse the
 * dashboard's chart components via UiBlockList). History reloads on
 * mount so the conversation survives refreshes — persistence lives in
 * assistant_messages, the panel is only a view of it.
 *
 * Error contract is honest: 429 (daily cap) and 503 (not configured)
 * surface as system notes; the input re-enables either way.
 */
export default function AssistantPanel() {
  const { user } = useAuth()
  const [history, setHistory] = useState([])   // [{role, message, ui_blocks}]
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState(null)
  const scrollRef = useRef(null)

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
        setHistory(data.messages || [])
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
    setHistory((h) => [...h, { role: 'user', message, ui_blocks: [] }])
    setBusy(true)
    scrollToEnd()
    try {
      const out = await sendChat(message)
      setHistory((h) => [...h, {
        role: 'assistant',
        message: out.message,
        ui_blocks: out.ui_blocks || [],
      }])
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
            <p>Ask me anything about your store — sales, employees, products.</p>
            <div className="assistant-suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" className="btn btn-outline"
                        disabled={busy} onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
            <p className="card-sub muted">
              I only answer from your store's own data — no opinions, no
              predictions, no outside facts.
            </p>
          </div>
        )}

        {history.map((turn, i) => (
          <div key={i} className={`assistant-turn assistant-${turn.role}`}>
            <span className="assistant-who muted">
              {turn.role === 'user' ? (user?.name || 'You') : 'Assistant'}
            </span>
            <p className="assistant-msg">{turn.message}</p>
            {turn.role === 'assistant' && turn.ui_blocks?.length > 0 && (
              <UiBlockList blocks={turn.ui_blocks} />
            )}
          </div>
        ))}
        {busy && <p className="muted assistant-typing">Assistant is thinking…</p>}
        {note && <div className="alert alert-error">{note}</div>}
      </div>

      <form className="assistant-input" onSubmit={(e) => { e.preventDefault(); send() }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about today's sales, an employee, a product…"
          disabled={busy}
          aria-label="Message the analytics assistant"
        />
        <button type="submit" className="btn" disabled={busy || !input.trim()}>
          {busy ? '…' : 'Send'}
        </button>
      </form>
    </div>
  )
}

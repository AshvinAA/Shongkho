import { useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../context/AuthContext.jsx'
import Avatar from '../components/Avatar.jsx'
import * as chatApi from '../api/chat.js'
import { fmtTime, fmtDate } from '../utils/format.js'

const POLL_MS = 3000

function dayKey(value) {
  return String(value).slice(0, 10)
}

function dayLabel(iso) {
  const d = new Date(`${iso}T00:00:00`)
  if (Number.isNaN(d.getTime())) return iso
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  const same = (a, b) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
  if (same(d, today)) return 'Today'
  if (same(d, yesterday)) return 'Yesterday'
  return d.toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })
}

/** WhatsApp-style store group chat (owner + employees) with reply-to-message. */
export default function Chat() {
  const { user } = useAuth()

  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [replyTo, setReplyTo] = useState(null) // message being replied to

  const lastIdRef = useRef(0)
  const listRef = useRef(null)
  const stickToBottomRef = useRef(true)
  const draftRef = useRef('') // mirror for the polling closure

  useEffect(() => {
    draftRef.current = draft
  }, [draft])

  // ------------------------------------------------ load + poll
  useEffect(() => {
    let cancelled = false

    async function fetchNew() {
      const afterId = lastIdRef.current
      const rows = await chatApi.listMessages(afterId ? { afterId } : {})
      if (cancelled || !Array.isArray(rows) || rows.length === 0) return rows
      lastIdRef.current = rows[rows.length - 1].message_id
      setMessages((prev) => {
        const known = new Set(prev.map((m) => m.message_id))
        const fresh = rows.filter((m) => !known.has(m.message_id))
        return fresh.length ? [...prev, ...fresh] : prev
      })
      return rows
    }

    async function run() {
      try {
        // First load: full history. Deletions are rare; a full refresh on
        // remount keeps things simple, polling handles new messages.
        await fetchNew()
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    run()
    const timer = setInterval(() => {
      fetchNew().catch((err) => {
        if (!cancelled && err?.status !== 401) setError(err.message)
      })
    }, POLL_MS)

    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  // ------------------------------------------------ autoscroll
  useEffect(() => {
    if (stickToBottomRef.current && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }, [messages])

  function handleScroll() {
    const el = listRef.current
    if (!el) return
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  // ------------------------------------------------ send
  async function handleSend(e) {
    e.preventDefault()
    const body = draft.trim()
    if (!body || sending) return

    setSending(true)
    setError(null)
    try {
      const msg = await chatApi.sendMessage(body, replyTo?.message_id ?? null)
      setMessages((prev) =>
        prev.some((m) => m.message_id === msg.message_id) ? prev : [...prev, msg],
      )
      lastIdRef.current = Math.max(lastIdRef.current, msg.message_id)
      setDraft('')
      setReplyTo(null)
      stickToBottomRef.current = true
    } catch (err) {
      setError(err.message)
    } finally {
      setSending(false)
    }
  }

  // ------------------------------------------------ delete own
  async function handleDelete(messageId) {
    const previous = messages
    setMessages((prev) =>
      prev.map((m) => (m.message_id === messageId ? { ...m, deleted: true, body: '' } : m)),
    )
    try {
      await chatApi.deleteMessage(messageId)
    } catch (err) {
      setMessages(previous) // restore on failure
      setError(err.message)
    }
  }

  const groups = useMemo(() => {
    // Group messages by day for WhatsApp-style dividers
    const out = []
    let currentDay = null
    for (const m of messages) {
      const key = dayKey(m.date)
      if (key !== currentDay) {
        out.push({ type: 'divider', key: `d-${key}`, label: dayLabel(key) })
        currentDay = key
      }
      out.push({ type: 'message', key: `m-${m.message_id}`, message: m })
    }
    return out
  }, [messages])

  return (
    <div className="page chat-page">
      <div className="page-header">
        <div>
          <h1>Store Chat</h1>
          <p className="muted">Everyone in the store — owner &amp; employees — in one group</p>
        </div>
        <span className="chat-live-dot" title="Live — updates automatically" />
      </div>

      {error && (
        <div className="alert alert-error alert-dismiss" role="alert">
          <span>{error}</span>
          <button type="button" className="alert-close" onClick={() => setError(null)}>×</button>
        </div>
      )}

      <div className="card chat-card">
        {/* ---------------- messages ---------------- */}
        <div className="chat-scroll" ref={listRef} onScroll={handleScroll}>
          {loading ? (
            <div className="page-loading" role="status">
              <div className="spinner" />
              <p className="muted">Loading chat…</p>
            </div>
          ) : messages.length === 0 ? (
            <div className="chat-empty">
              <p>👋 No messages yet.</p>
              <p className="muted">Say hello to your team — everyone in the store can see this chat.</p>
            </div>
          ) : (
            groups.map((g) =>
              g.type === 'divider' ? (
                <div className="chat-day" key={g.key}>
                  <span>{g.label}</span>
                </div>
              ) : (
                <ChatBubble
                  key={g.key}
                  message={g.message}
                  isOwn={g.message.sender.user_id === user?.user_id}
                  onReply={() => setReplyTo(g.message)}
                  onDelete={() => handleDelete(g.message.message_id)}
                />
              ),
            )
          )}
        </div>

        {/* ---------------- reply preview bar ---------------- */}
        {replyTo && (
          <div className="chat-reply-bar">
            <div className="chat-quote chat-quote-own-bar">
              <div className="chat-quote-head">{replyTo.sender.name}</div>
              <div className="chat-quote-body">{replyTo.deleted ? 'Deleted message' : replyTo.body}</div>
            </div>
            <button type="button" className="chat-reply-cancel" onClick={() => setReplyTo(null)} aria-label="Cancel reply">
              ×
            </button>
          </div>
        )}

        {/* ---------------- composer ---------------- */}
        <form className="chat-composer" onSubmit={handleSend}>
          <input
            type="text"
            className="chat-input"
            placeholder="Type a message…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            maxLength={4000}
            aria-label="Message"
          />
          <button type="submit" className="chat-send" disabled={sending || !draft.trim()} aria-label="Send">
            {sending ? '…' : '➤'}
          </button>
        </form>
      </div>
    </div>
  )
}

function ChatBubble({ message, isOwn, onReply, onDelete }) {
  const m = message
  const showSender = !isOwn // group chat: show name on others' bubbles
  const longPress = useLongPress(isOwn ? onDelete : null)

  return (
    <div className={`chat-row ${isOwn ? 'chat-own' : 'chat-other'}`}>
      {!isOwn && <Avatar user={m.sender} size="sm" className="chat-avatar" />}
      <div className="chat-bubble-wrap">
        <div className={`chat-bubble ${isOwn ? 'chat-bubble-own' : 'chat-bubble-other'}`}>
          {showSender && (
            <div className={`chat-sender ${m.sender.user_type === 'owner' ? 'chat-sender-owner' : ''}`}>
              {m.sender.name}
              {m.sender.user_type === 'owner' && <span className="chat-owner-tag">Owner</span>}
            </div>
          )}

          {m.reply_to && (
            <div className="chat-quote">
              <div className="chat-quote-head">{m.reply_to.sender_name}</div>
              <div className="chat-quote-body">
                {m.reply_to.deleted ? 'Deleted message' : m.reply_to.body}
              </div>
            </div>
          )}

          {m.deleted ? (
            <div className="chat-body chat-body-deleted">🚫 This message was deleted</div>
          ) : (
            <div className="chat-body">{m.body}</div>
          )}

          <div className="chat-meta">
            <span>{fmtTime(m.time)}</span>
            {isOwn && !m.deleted && (
              <button type="button" className="chat-delete" onClick={onDelete} title="Delete message">
                🗑
              </button>
            )}
          </div>
        </div>
        {!m.deleted && (
          <button type="button" className="chat-reply-btn" onClick={onReply} title="Reply">
            ↩ Reply
          </button>
        )}
        {longPress.pressing && <span className="sr-only">pressed</span>}
      </div>
    </div>
  )
}

/** Long-press (touch) helper — desktop users have the visible ↩ button. */
function useLongPress(onLongPress) {
  const [pressing, setPressing] = useState(false)
  const timerRef = useRef(null)

  function start() {
    if (!onLongPress) return
    timerRef.current = setTimeout(() => {
      setPressing(false)
      onLongPress()
    }, 500)
  }
  function cancel() {
    clearTimeout(timerRef.current)
    setPressing(false)
  }

  return { pressing, start, cancel }
}

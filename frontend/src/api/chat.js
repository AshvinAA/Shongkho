import { get, post, del } from './client.js'

/**
 * Store group chat history.
 * @param {object} opts
 * @param {number} [opts.afterId] only fetch messages newer than this id (polling)
 * @param {number} [opts.limit]
 */
export function listMessages({ afterId = 0, limit = 200 } = {}) {
  return get(`/chat/messages${afterId ? `?after_id=${afterId}&limit=${limit}` : `?limit=${limit}`}`)
}

/** Send a message; pass replyToId to quote another message. */
export function sendMessage(body, replyToId = null) {
  return post('/chat/messages', { body, reply_to_id: replyToId })
}

/** Delete your own message (soft delete — shows as "deleted" to everyone). */
export function deleteMessage(messageId) {
  return del(`/chat/messages/${messageId}`)
}

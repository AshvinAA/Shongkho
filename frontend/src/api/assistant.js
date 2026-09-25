import { get, post } from './client.js'

/**
 * One conversational-analytics turn (Part B) — text-only product.
 * Returns { message, tool_calls, meta }. Throws Error with
 * .status === 429 (daily cap) / 503 (assistant not configured).
 */
export function sendChat(message) {
  return post('/analytics/chat', { message })
}

/** Reload the persisted conversation: { messages: [{role, message, created_at}] } */
export function getChatHistory(limit = 50) {
  return get(`/analytics/chat/history${limit ? `?limit=${limit}` : ''}`)
}

import { get, post } from './client.js'

/**
 * One conversational-analytics turn (Part B) — text-only product.
 * language: 'auto' | 'bn' | 'en' (Protik's switch state, plan §1) —
 * 'bn' forces a Bangla reply even on English questions.
 * Returns { message, tool_calls, meta }. Throws Error with
 * .status === 429 (daily cap) / 503 (assistant not configured).
 */
export function sendChat(message, language) {
  return post('/analytics/chat', language ? { message, language } : { message })
}

/** Reload the persisted conversation: { messages: [{role, message, created_at}] } */
export function getChatHistory(limit = 50) {
  return get(`/analytics/chat/history${limit ? `?limit=${limit}` : ''}`)
}

/**
 * Centralized fetch wrapper for the Shongkho API.
 *
 * - Always sends cookies (`credentials: 'include'`) so the FastAPI
 *   session cookie flows with every request.
 * - Unwraps FastAPI's `{ detail: ... }` error shape into a clean
 *   Error object (`err.message`), including 422 field validation.
 */

const BASE_URL = '/api/v1'

function extractDetail(data) {
  if (!data) return null
  // Standard FastAPI error: { detail: "message" }
  if (typeof data.detail === 'string') return data.detail
  // Validation error: { detail: [{ loc, msg, type }, ...] }
  if (Array.isArray(data.detail)) {
    return data.detail
      .map((e) => {
        const field = Array.isArray(e.loc) ? e.loc.filter((p) => p !== 'body').join('.') : ''
        return field ? `${field}: ${e.msg}` : e.msg
      })
      .join('; ')
  }
  if (data.message) return data.message
  return null
}

export async function request(endpoint, options = {}) {
  const {
    headers = {},
    body,
    ...rest
  } = options

  const config = {
    credentials: 'include',
    ...rest,
    headers: {
      ...(body !== undefined && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
      ...headers,
    },
  }

  if (body !== undefined) {
    config.body = body instanceof FormData ? body : JSON.stringify(body)
  }

  let response
  try {
    response = await fetch(`${BASE_URL}${endpoint}`, config)
  } catch {
    throw new Error('Could not connect to the server. Is the backend running?')
  }

  // 204 / empty body
  if (response.status === 204) return null

  let data = null
  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    data = await response.json().catch(() => null)
  }

  if (!response.ok) {
    const err = new Error(extractDetail(data) || `Request failed (${response.status})`)
    err.status = response.status
    err.data = data
    throw err
  }

  return data
}

export function get(endpoint) {
  return request(endpoint, { method: 'GET' })
}

export function post(endpoint, body) {
  return request(endpoint, { method: 'POST', body })
}

export function put(endpoint, body) {
  return request(endpoint, { method: 'PUT', body })
}

export function patch(endpoint, body) {
  return request(endpoint, { method: 'PATCH', body })
}

export function del(endpoint) {
  return request(endpoint, { method: 'DELETE' })
}

/**
 * Build a query string from an object, skipping null/undefined/'' values.
 */
export function qs(params = {}) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') {
      search.set(key, String(value))
    }
  }
  const s = search.toString()
  return s ? `?${s}` : ''
}

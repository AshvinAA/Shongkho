import { get, post, put } from './client.js'

// ---------------------------------------------------------
// Owner-only: manage one employee's warnings & commission
// ---------------------------------------------------------

/** Owner-only: issue a formal warning to one employee. */
export function issueWarning(userId, reason) {
  return post(`/staff/employees/${userId}/warnings`, { reason })
}

/** Owner-only: warning history for one employee (newest first). */
export function listWarnings(userId) {
  return get(`/staff/employees/${userId}/warnings`)
}

/** Owner-only: the commission policy set for one employee. */
export function getCommission(userId) {
  return get(`/staff/employees/${userId}/commission`)
}

/** Owner-only: set (or clear with rate: null) the commission policy. */
export function setCommission(userId, { basis, rate }) {
  return put(`/staff/employees/${userId}/commission`, { basis, rate })
}

// ---------------------------------------------------------
// Self-view (employee dashboard)
// ---------------------------------------------------------

/** Your own warning history (owners get an empty list). */
export function getMyWarnings() {
  return get('/staff/me/warnings')
}

/** Your commission card: policy + live payout from your own sales. */
export function getMyCommission() {
  return get('/staff/me/commission')
}

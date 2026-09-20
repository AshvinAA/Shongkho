import { get, put, del, qs } from './client.js'

/** Any role: view your own profile. */
export function getMyProfile() {
  return get('/employees/me/profile')
}

/** Any role: edit your own name / phone / photo. */
export function updateMyProfile(payload) {
  return put('/employees/me/profile', payload)
}
/** Owner-only: list employees. */
export function listEmployees({ skip = 0, limit = 100 } = {}) {
  return get(`/employees/${qs({ skip, limit })}`)
}

/** Owner-only: search employees by name/position/phone. */
export function searchEmployees(query) {
  return get(`/employees/search/${qs({ query })}`)
}

/** Owner-only: revenue/profit per employee. */
export function getPerformance({ skip = 0, limit = 100 } = {}) {
  return get(`/employees/performance${qs({ skip, limit })}`)
}

/** Owner-only: update employee info / role. */
export function updateEmployee(userId, payload) {
  return put(`/employees/${userId}`, payload)
}

/** Owner-only: delete an employee account. */
export function deleteEmployee(userId) {
  return del(`/employees/${userId}`)
}

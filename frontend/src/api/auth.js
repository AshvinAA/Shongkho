import { get, post } from './client.js'

/** Login with phone + password. Sets the session cookie. */
export function login(credentials) {
  return post('/auth/login', credentials)
}

/** Hydrate the current session user (401 when anonymous). */
export function fetchMe() {
  return get('/auth/me')
}

/** Clear the server session. */
export function logout() {
  return post('/auth/logout')
}

/**
 * Public registration.
 * payload: { name, phone_number, password, role, employer_id?, position?, salary? }
 */
export function register(payload) {
  return post('/auth/register', payload)
}

/** Owner-only: register an employee under the owner's own account. */
export function registerEmployee(payload) {
  return post('/auth/register/employee', payload)
}

/** Owner-only: create an additional owner account. */
export function registerOwner(payload) {
  return post('/auth/register/owner', payload)
}

/** Step 1 of password reset — verify the account exists. */
export function forgotPassword(phoneNumber) {
  return post('/auth/forgot-password', { phone_number: phoneNumber })
}

/** Step 2 of password reset — set the new password. */
export function resetPassword(phoneNumber, newPassword) {
  return post('/auth/reset-password', { phone_number: phoneNumber, new_password: newPassword })
}

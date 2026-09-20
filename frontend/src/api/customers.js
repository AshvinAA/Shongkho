import { get, post, put, qs } from './client.js'

/** Owner-only: full customer directory with lifetime spend. */
export function listCustomers({ skip = 0, limit = 100 } = {}) {
  return get(`/customers/${qs({ skip, limit })}`)
}

/** POS quick-add (both roles). payload: { name, phone_number } */
export function createCustomer(payload) {
  return post('/customers/', payload)
}

/** POS lookup by phone (both roles). */
export function getCustomerByPhone(phoneNumber) {
  return get(`/customers/phone/${encodeURIComponent(phoneNumber)}`)
}

/** Update a customer's name (both roles). */
export function updateCustomer(customerId, name) {
  return put(`/customers/${customerId}`, { name })
}

/** Purchase history for one customer (both roles). */
export function getCustomerHistory(customerId) {
  return get(`/customers/${customerId}/history`)
}

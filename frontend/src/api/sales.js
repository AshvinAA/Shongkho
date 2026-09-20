import { get, post, qs } from './client.js'

/**
 * Checkout. payload: { customer_id, payment_method, items: [{ product_id, quantity }] }
 * The employee identity comes from the server session.
 * Returns the created SaleResponse with items and totals.
 */
export function checkout(payload) {
  return post('/checkout/', payload)
}

/** Sales history — owner sees all, employee sees only their own. */
export function listSales({ skip = 0, limit = 100 } = {}) {
  return get(`/sales/${qs({ skip, limit })}`)
}

/** Owner-only: totals for daily/weekly/monthly periods. */
export function getSalesReport(period) {
  return get(`/sales/reports/${period}`)
}

/** Receipt for one transaction (employee: own only). */
export function getReceipt(transactionId) {
  return get(`/sales/${transactionId}/receipt`)
}

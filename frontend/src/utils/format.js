/** Format a number as Bangladeshi Taka, e.g. ৳12,450.50 */
export function fmtMoney(value) {
  const n = Number(value) || 0
  return `৳${n.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`
}

/** "2026-09-20" -> "Sep 20, 2026" (falls back to the raw string). */
export function fmtDate(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

/** "14:23:45" -> "2:23 PM" (falls back to the raw string). */
export function fmtTime(value) {
  if (!value) return '—'
  const d = new Date(`2000-01-01T${value}`)
  if (Number.isNaN(d.getTime())) return String(value)
  return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

/** Local-date ISO string (YYYY-MM-DD) used to match backend sale dates. */
export function todayISO() {
  const d = new Date()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

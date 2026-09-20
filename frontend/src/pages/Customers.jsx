import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext.jsx'
import { RoleGate } from '../components/RoleGate.jsx'
import * as customersApi from '../api/customers.js'
import Modal from '../components/Modal.jsx'
import { fmtMoney, fmtDate, fmtTime } from '../utils/format.js'

/**
 * Customers screen.
 *
 * - Owners see the full directory with lifetime spend.
 * - Employees (and owners) get a phone-number lookup with purchase history,
 *   mirroring what the backend exposes to each role.
 */
export default function Customers() {
  const { user } = useAuth()
  const isOwner = user?.role === 'owner'

  // ------------------------------------------------ directory (owner)
  const [customers, setCustomers] = useState([])
  const [loading, setLoading] = useState(isOwner)
  const [error, setError] = useState(null)

  // ------------------------------------------------ lookup (both roles)
  const [lookupPhone, setLookupPhone] = useState('018')
  const [lookupResult, setLookupResult] = useState(null)
  const [lookupBusy, setLookupBusy] = useState(false)
  const [lookupError, setLookupError] = useState(null)
  const [history, setHistory] = useState(null)
  const [historyLoading, setHistoryLoading] = useState(false)

  // ------------------------------------------------ rename modal (both roles)
  const [editTarget, setEditTarget] = useState(null)
  const [editName, setEditName] = useState('')
  const [editError, setEditError] = useState(null)
  const [editBusy, setEditBusy] = useState(false)

  useEffect(() => {
    if (!isOwner) return
    let cancelled = false

    async function load() {
      try {
        const data = await customersApi.listCustomers({ limit: 500 })
        if (!cancelled) setCustomers(data)
      } catch (err) {
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [isOwner])

  async function handleLookup(e) {
    e.preventDefault()
    const p = lookupPhone.trim()
    if (p.length < 10) {
      setLookupError('Enter a full phone number (at least 10 digits).')
      return
    }

    setLookupBusy(true)
    setLookupError(null)
    setLookupResult(null)
    setHistory(null)
    try {
      const customer = await customersApi.getCustomerByPhone(p)
      setLookupResult(customer)

      // Fetch purchase history in the background (404 = none yet)
      setHistoryLoading(true)
      customersApi
        .getCustomerHistory(customer.customer_id)
        .then((sales) => setHistory(sales))
        .catch(() => setHistory([]))
        .finally(() => setHistoryLoading(false))
    } catch (err) {
      setLookupError(err.status === 404 ? 'No customer found with that phone number.' : err.message)
    } finally {
      setLookupBusy(false)
    }
  }

  function openRename(customer) {
    setEditTarget(customer)
    setEditName(customer.name)
    setEditError(null)
  }

  async function handleRename(e) {
    e.preventDefault()
    if (!editName.trim()) {
      setEditError('Name cannot be empty.')
      return
    }
    setEditBusy(true)
    setEditError(null)
    try {
      const updated = await customersApi.updateCustomer(editTarget.customer_id, editName.trim())
      setEditTarget(null)
      // Refresh both views
      setLookupResult((prev) => (prev && prev.customer_id === updated.customer_id ? updated : prev))
      if (isOwner) {
        setCustomers((prev) => prev.map((c) => (c.customer_id === updated.customer_id ? { ...c, name: updated.name } : c)))
      }
    } catch (err) {
      setEditError(err.message)
    } finally {
      setEditBusy(false)
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Customers</h1>
          <p className="muted">{isOwner ? 'Customer directory with lifetime spend' : 'Look up customers by phone number'}</p>
        </div>
      </div>

      {error && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}

      {/* ---------------- Phone lookup (both roles) ---------------- */}
      <div className="card">
        <div className="card-title">Find Customer</div>
        <form onSubmit={handleLookup} className="filter-bar" noValidate>
          <input
            type="tel"
            className="form-control"
            placeholder="018XXXXXXXX"
            value={lookupPhone}
            onChange={(e) => setLookupPhone(e.target.value)}
          />
          <button type="submit" className="btn" disabled={lookupBusy}>
            {lookupBusy ? 'Searching…' : 'Search'}
          </button>
        </form>
        {lookupError && (
          <div className="alert alert-error" role="alert" style={{ marginTop: '0.75rem' }}>
            {lookupError}
          </div>
        )}

        {lookupResult && (
          <div className="customer-result">
            <div className="customer-card">
              <div className="avatar">{lookupResult.name.charAt(0).toUpperCase()}</div>
              <div>
                <strong>{lookupResult.name}</strong>
                <div className="muted">
                  {lookupResult.phone_number} · #{lookupResult.customer_id}
                </div>
              </div>
              <button type="button" className="btn btn-outline btn-sm" onClick={() => openRename(lookupResult)}>
                Rename
              </button>
            </div>

            <div className="card-title" style={{ marginTop: '1rem' }}>Purchase History</div>
            {historyLoading ? (
              <p className="muted">Loading history…</p>
            ) : !history || history.length === 0 ? (
              <p className="muted">No purchases yet.</p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Txn #</th>
                    <th>Date</th>
                    <th>Time</th>
                    <th>Payment</th>
                    <th>Total</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((s) => (
                    <tr key={s.transaction_id}>
                      <td>#{s.transaction_id}</td>
                      <td>{fmtDate(s.date)}</td>
                      <td>{fmtTime(s.time)}</td>
                      <td>{s.payment_method}</td>
                      <td>{fmtMoney(s.total_revenue)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>

      {/* ---------------- Directory (owner) ---------------- */}
      <RoleGate allowedRoles={['owner']}>
        <div className="card" style={{ marginTop: '1rem' }}>
          <div className="card-title">All Customers ({customers.length})</div>
          {loading ? (
            <div className="page-loading" role="status">
              <div className="spinner" />
              <p className="muted">Loading customers…</p>
            </div>
          ) : customers.length === 0 ? (
            <p className="muted">No customers yet — they are created automatically at the POS.</p>
            ) : (
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Name</th>
                    <th>Phone</th>
                    <th>Lifetime Spend</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {customers.map((c) => (
                    <tr key={c.customer_id}>
                      <td>#{c.customer_id}</td>
                      <td className="cell-strong">{c.name}</td>
                      <td>{c.phone_number}</td>
                      <td>{fmtMoney(c.total_spend)}</td>
                      <td>
                        <button type="button" className="btn btn-outline btn-sm" onClick={() => openRename(c)}>
                          Rename
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </RoleGate>

      {/* ---------------- Rename modal ---------------- */}
      <Modal open={!!editTarget} onClose={() => setEditTarget(null)} title="Rename Customer">
        <form onSubmit={handleRename} noValidate>
          {editError && <div className="alert alert-error" role="alert">{editError}</div>}
          <div className="form-group">
            <label className="form-label" htmlFor="cust-name">Name</label>
            <input
              id="cust-name"
              type="text"
              className="form-control"
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-outline" onClick={() => setEditTarget(null)}>Cancel</button>
            <button type="submit" className="btn" disabled={editBusy}>{editBusy ? 'Saving…' : 'Save'}</button>
          </div>
        </form>
      </Modal>
    </div>
  )
}

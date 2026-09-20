import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext.jsx'
import * as salesApi from '../api/sales.js'
import Modal from '../components/Modal.jsx'
import { fmtMoney, fmtDate, fmtTime } from '../utils/format.js'

const PAGE_SIZE = 20

/** Transaction history with pagination and receipt drill-down. */
export default function Sales() {
  const { user } = useAuth()
  const isOwner = user?.role === 'owner'

  const [sales, setSales] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [page, setPage] = useState(0)
  const [hasMore, setHasMore] = useState(false)

  const [receipt, setReceipt] = useState(null)
  const [receiptLoading, setReceiptLoading] = useState(false)
  const [receiptError, setReceiptError] = useState(null)

  async function loadPage(p) {
    setLoading(true)
    setError(null)
    try {
      const data = await salesApi.listSales({ skip: p * PAGE_SIZE, limit: PAGE_SIZE + 1 })
      setHasMore(data.length > PAGE_SIZE)
      setSales(data.slice(0, PAGE_SIZE))
      setPage(p)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadPage(0)
  }, [])

  async function openReceipt(txnId) {
    setReceiptLoading(true)
    setReceiptError(null)
    try {
      const data = await salesApi.getReceipt(txnId)
      setReceipt(data)
    } catch (err) {
      setReceiptError(err.message)
    } finally {
      setReceiptLoading(false)
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Sales</h1>
          <p className="muted">{isOwner ? 'All store transactions' : 'Your transactions only'}</p>
        </div>
        <button type="button" className="btn btn-outline" onClick={() => loadPage(0)} disabled={loading}>
          ⟳ Refresh
        </button>
      </div>

      {error && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}

      <div className="card">
        {loading ? (
          <div className="page-loading" role="status">
            <div className="spinner" />
            <p className="muted">Loading transactions…</p>
          </div>
        ) : sales.length === 0 ? (
          <p className="muted">No sales recorded yet.</p>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Txn #</th>
                  <th>Date</th>
                  <th>Time</th>
                  <th>Payment</th>
                  <th>Customer</th>
                  <th>Revenue</th>
                  {isOwner && <th>Profit</th>}
                  <th>Receipt</th>
                </tr>
              </thead>
              <tbody>
                {sales.map((s) => (
                  <tr key={s.transaction_id}>
                    <td>#{s.transaction_id}</td>
                    <td>{fmtDate(s.date)}</td>
                    <td>{fmtTime(s.time)}</td>
                    <td>{s.payment_method}</td>
                    <td>{s.customer_id ? `#${s.customer_id}` : 'Walk-in'}</td>
                    <td>{fmtMoney(s.total_revenue)}</td>
                    {isOwner && <td>{fmtMoney(s.total_profit)}</td>}
                    <td>
                      <button type="button" className="btn btn-outline btn-sm" onClick={() => openReceipt(s.transaction_id)}>
                        View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="pagination">
        <button type="button" className="btn btn-outline btn-sm" disabled={page === 0 || loading} onClick={() => loadPage(page - 1)}>
          ← Prev
        </button>
        <span className="muted">Page {page + 1}</span>
        <button type="button" className="btn btn-outline btn-sm" disabled={!hasMore || loading} onClick={() => loadPage(page + 1)}>
          Next →
        </button>
      </div>

      {/* ---------------- Receipt modal ---------------- */}
      <Modal
        open={!!receipt}
        onClose={() => setReceipt(null)}
        title={`Receipt — Transaction #${receipt?.transaction_id ?? ''}`}
        footer={
          <button type="button" className="btn btn-outline" onClick={() => window.print()}>
            🖨 Print
          </button>
        }
      >
        {receipt && (
          <>
            <p className="muted">
              {fmtDate(receipt.date)} {fmtTime(receipt.time)} · {receipt.payment_method}
            </p>
            <p>
              <strong>Customer:</strong> {receipt.customer_name || 'Walk-in'} · <strong>Served by:</strong>{' '}
              {receipt.employee_name || '—'}
            </p>
            <table className="table">
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Qty</th>
                  <th>Unit</th>
                  <th>Total</th>
                </tr>
              </thead>
              <tbody>
                {receipt.items?.map((it, idx) => (
                  <tr key={`${it.product_id}-${idx}`}>
                    <td>{it.product_name || `Product #${it.product_id}`}</td>
                    <td>{it.quantity}</td>
                    <td>{fmtMoney(it.unit_price)}</td>
                    <td>{fmtMoney(it.line_total)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={3}>Total</td>
                  <td>
                    <strong>{fmtMoney(receipt.total_revenue)}</strong>
                  </td>
                </tr>
              </tfoot>
            </table>
          </>
        )}
      </Modal>
    </div>
  )
}

import { useEffect, useState } from 'react'
import * as productsApi from '../api/products.js'
import * as customersApi from '../api/customers.js'
import * as salesApi from '../api/sales.js'
import { fmtMoney, fmtDate, fmtTime } from '../utils/format.js'

const PAYMENT_METHODS = ['Cash', 'Card', 'bKash', 'Nagad']

/**
 * Checkout terminal.
 *
 * Flow: search/scan a product -> add to cart -> identify the customer by
 * phone (quick-add if new) -> choose payment -> checkout. The backend
 * recalculates all totals from DB prices.
 */
export default function POS() {
  // ------------------------------------------------ data
  const [products, setProducts] = useState([])
  const [search, setSearch] = useState('')
  const [cart, setCart] = useState([])
  const [customer, setCustomer] = useState(null) // {customer_id, name, phone_number}
  const [phone, setPhone] = useState('018')
  const [custName, setCustName] = useState('')
  const [custStatus, setCustStatus] = useState(null)
  const [paymentMethod, setPaymentMethod] = useState('Cash')
  const [receipt, setReceipt] = useState(null)

  // ------------------------------------------------ ui state
  const [lookupBusy, setLookupBusy] = useState(false)
  const [checkoutBusy, setCheckoutBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    productsApi
      .listProducts({ limit: 1000 })
      .then((data) => {
        if (!cancelled) setProducts(data)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // ------------------------------------------------ derived
  const filtered = products.filter((p) => {
    const q = search.trim().toLowerCase()
    if (!q) return true
    return (
      p.product_name.toLowerCase().includes(q) ||
      p.category?.toLowerCase().includes(q) ||
      String(p.product_id) === q
    )
  })

  const subtotal = cart.reduce((sum, line) => sum + line.retail_price * line.quantity, 0)
  const tax = 0 // VAT is included in retail prices; hook point for future tax rules
  const total = subtotal + tax
  const cartCount = cart.reduce((n, line) => n + line.quantity, 0)

  // ------------------------------------------------ cart actions
  function addToCart(product, qty = 1) {
    setError(null)
    if (product.stock_quantity <= 0) {
      setError(`"${product.product_name}" is out of stock.`)
      return
    }
    setCart((prev) => {
      const existing = prev.find((l) => l.product_id === product.product_id)
      if (existing) {
        return prev.map((l) =>
          l.product_id === product.product_id
            ? { ...l, quantity: Math.min(l.quantity + qty, l.stock_quantity) }
            : l,
        )
      }
      return [...prev, { ...product, quantity: Math.min(qty, product.stock_quantity) }]
    })
  }

  function setQty(productId, qty) {
    const safe = Number.isFinite(qty) ? qty : 1
    setCart((prev) =>
      prev.map((l) =>
        l.product_id === productId
          ? { ...l, quantity: Math.max(1, Math.min(Math.floor(safe), l.stock_quantity)) }
          : l,
      ),
    )
  }

  function removeFromCart(productId) {
    setCart((prev) => prev.filter((l) => l.product_id !== productId))
  }

  function clearCart() {
    setCart([])
    setError(null)
  }

  // ------------------------------------------------ customer flow
  async function handlePhoneLookup() {
    const p = phone.trim()
    if (p.length < 10) {
      setCustStatus({ kind: 'error', text: 'Enter a full phone number (at least 10 digits).' })
      return
    }

    setLookupBusy(true)
    setCustStatus(null)
    try {
      const existing = await customersApi.getCustomerByPhone(p)
      setCustomer(existing)
      setCustName(existing.name)
      setCustStatus({ kind: 'success', text: `Existing customer: ${existing.name} (#${existing.customer_id})` })
    } catch (err) {
      if (err.status === 404) {
        setCustomer(null)
        setCustName('')
        setCustStatus({ kind: 'info', text: 'New customer — enter a name and press "＋" to quick-add.' })
      } else {
        setCustStatus({ kind: 'error', text: err.message })
      }
    } finally {
      setLookupBusy(false)
    }
  }

  async function handleQuickAdd() {
    const p = phone.trim()
    if (p.length < 10) {
      setCustStatus({ kind: 'error', text: "Enter the customer's phone number first." })
      return
    }
    if (!custName.trim()) {
      setCustStatus({ kind: 'error', text: "Enter the customer's name to quick-add." })
      return
    }

    setLookupBusy(true)
    setCustStatus(null)
    try {
      const created = await customersApi.createCustomer({ name: custName.trim(), phone_number: p })
      setCustomer(created)
      setCustStatus({ kind: 'success', text: `Customer created: ${created.name} (#${created.customer_id})` })
    } catch (err) {
      setCustStatus({ kind: 'error', text: err.message })
    } finally {
      setLookupBusy(false)
    }
  }

  function clearCustomer() {
    setCustomer(null)
    setPhone('018')
    setCustName('')
    setCustStatus(null)
  }

  // ------------------------------------------------ checkout
  async function handleCheckout() {
    if (cart.length === 0) {
      setError('Cart is empty.')
      return
    }
    if (!customer) {
      setError('Look up or quick-add a customer before checkout.')
      return
    }

    setCheckoutBusy(true)
    setError(null)
    try {
      const payload = {
        customer_id: customer.customer_id,
        payment_method: paymentMethod,
        items: cart.map((line) => ({ product_id: line.product_id, quantity: line.quantity })),
      }
      const sale = await salesApi.checkout(payload)
      setReceipt(sale)
      setCart([])
      clearCustomer()
    } catch (err) {
      setError(err.message)
    } finally {
      setCheckoutBusy(false)
    }
  }

  // ------------------------------------------------ render
  return (
    <div className="page pos-page">
      <div className="page-header">
        <h1>Point of Sale</h1>
      </div>

      {error && (
        <div className="alert alert-error alert-dismiss" role="alert">
          <span>{error}</span>
          <button type="button" className="alert-close" onClick={() => setError(null)}>×</button>
        </div>
      )}

      <div className="pos-layout">
        {/* ---------------- LEFT: catalogue + cart ---------------- */}
        <section className="pos-left">
          <div className="card">
            <label className="form-label" htmlFor="pos-search">Find Product (name, category or ID)</label>
            <input
              id="pos-search"
              type="text"
              className="form-control form-control-lg"
              placeholder="Scan barcode or search…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              autoFocus
            />
          </div>

          <div className="card pos-products">
            <div className="card-title">
              Products{' '}
              {search && (
                <span className="muted">({filtered.length} match{filtered.length === 1 ? '' : 'es'})</span>
              )}
            </div>
            {filtered.length === 0 ? (
              <p className="muted">No products match “{search}”.</p>
            ) : (
              <div className="product-grid">
                {filtered.map((p) => {
                  const out = p.stock_quantity <= 0
                  return (
                    <button
                      key={p.product_id}
                      type="button"
                      className={`product-tile ${out ? 'disabled' : ''}`}
                      onClick={() => addToCart(p)}
                      disabled={out}
                      title={out ? 'Out of stock' : `Add ${p.product_name} — ${fmtMoney(p.retail_price)}`}
                    >
                      <span className="product-name">{p.product_name}</span>
                      <span className="product-meta">
                        <strong>{fmtMoney(p.retail_price)}</strong>
                        <span
                          className={`stock-chip ${
                            p.stock_quantity === 0 ? 'stock-out' : p.stock_quantity <= 5 ? 'stock-low' : 'stock-ok'
                          }`}
                        >
                          {p.stock_quantity} in stock
                        </span>
                      </span>
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          <div className="card">
            <div className="card-title">
              Current Sale ({cartCount} item{cartCount === 1 ? '' : 's'})
            </div>
            {cart.length === 0 ? (
              <p className="muted">Cart is empty — tap a product above to add it.</p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Item</th>
                    <th>Price</th>
                    <th>Qty</th>
                    <th>Line Total</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {cart.map((line) => (
                    <tr key={line.product_id}>
                      <td>{line.product_name}</td>
                      <td>{fmtMoney(line.retail_price)}</td>
                      <td>
                        <input
                          type="number"
                          className="qty-input"
                          min="1"
                          max={line.stock_quantity}
                          value={line.quantity}
                          onChange={(e) => setQty(line.product_id, Number(e.target.value))}
                        />
                      </td>
                      <td>{fmtMoney(line.retail_price * line.quantity)}</td>
                      <td>
                        <button
                          type="button"
                          className="btn btn-danger btn-sm"
                          onClick={() => removeFromCart(line.product_id)}
                          aria-label={`Remove ${line.product_name}`}
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>

        {/* ---------------- RIGHT: customer + payment ---------------- */}
        <aside className="pos-right">
          <div className="card">
            <div className="card-title">Customer</div>

            {customer ? (
              <div className="customer-selected">
                <div>
                  <strong>{customer.name}</strong>
                  <div className="muted">
                    {customer.phone_number} · #{customer.customer_id}
                  </div>
                </div>
                <button type="button" className="btn btn-outline btn-sm" onClick={clearCustomer}>
                  Change
                </button>
              </div>
            ) : (
              <>
                <div className="form-group">
                  <label className="form-label" htmlFor="pos-phone">Phone Number</label>
                  <input
                    id="pos-phone"
                    type="tel"
                    className="form-control"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    onBlur={handlePhoneLookup}
                    onKeyDown={(e) => e.key === 'Enter' && handlePhoneLookup()}
                    placeholder="018XXXXXXXX"
                  />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="pos-custname">Customer Name</label>
                  <div className="input-group">
                    <input
                      id="pos-custname"
                      type="text"
                      className="form-control"
                      value={custName}
                      onChange={(e) => setCustName(e.target.value)}
                      placeholder="For quick-add"
                    />
                    <button
                      type="button"
                      className="btn btn-outline"
                      onClick={handleQuickAdd}
                      disabled={lookupBusy}
                      title="Quick-add customer"
                    >
                      ＋
                    </button>
                  </div>
                </div>
                {custStatus && <div className={`form-hint ${custStatus.kind}`}>{custStatus.text}</div>}
              </>
            )}
          </div>

          <div className="card pos-summary">
            <div className="summary-row">
              <span>Subtotal</span>
              <strong>{fmtMoney(subtotal)}</strong>
            </div>
            {tax > 0 && (
              <div className="summary-row muted">
                <span>Tax</span>
                <span>{fmtMoney(tax)}</span>
              </div>
            )}
            <div className="summary-row summary-total">
              <span>Total</span>
              <strong>{fmtMoney(total)}</strong>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="pos-payment">Payment Method</label>
              <select
                id="pos-payment"
                className="form-control"
                value={paymentMethod}
                onChange={(e) => setPaymentMethod(e.target.value)}
              >
                {PAYMENT_METHODS.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>

            <button
              type="button"
              className="btn btn-success btn-block btn-lg"
              onClick={handleCheckout}
              disabled={checkoutBusy || cart.length === 0 || !customer}
            >
              {checkoutBusy ? 'Processing…' : `Complete Sale — ${fmtMoney(total)}`}
            </button>
            {cart.length > 0 && (
              <button type="button" className="btn btn-outline btn-block" onClick={clearCart}>
                Clear Cart
              </button>
            )}
          </div>
        </aside>
      </div>

      {/* ---------------- Receipt after checkout ---------------- */}
      {receipt && (
        <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setReceipt(null)}>
          <div className="modal receipt-modal" role="dialog" aria-modal="true" aria-label="Sale receipt">
            <div className="modal-header">
              <h3>✅ Sale #{receipt.transaction_id} Complete</h3>
              <button type="button" className="modal-close" onClick={() => setReceipt(null)}>×</button>
            </div>
            <div className="modal-body">
              <p className="muted">
                {fmtDate(receipt.date)} {fmtTime(receipt.time)} · {receipt.payment_method}
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
                      <td>{fmtMoney(it.retail_price_at_sale)}</td>
                      <td>{fmtMoney(it.retail_price_at_sale * it.quantity)}</td>
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
            </div>
            <div className="modal-footer">
              <button type="button" className="btn btn-outline" onClick={() => setReceipt(null)}>
                New Sale
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

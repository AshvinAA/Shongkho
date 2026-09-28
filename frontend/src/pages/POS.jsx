import { useEffect, useMemo, useRef, useState } from 'react'
import { CheckCircle2, Minus, Plus, ScanBarcode, Search, Trash2 } from 'lucide-react'
import * as productsApi from '../api/products.js'
import * as customersApi from '../api/customers.js'
import * as salesApi from '../api/sales.js'
import Avatar from '../components/Avatar.jsx'
import { Button, Field, Input, Modal } from '../components/ui/index.jsx'
import { fmtMoney, fmtDate, fmtTime } from '../utils/format.js'

const PAYMENT_METHODS = ['Cash', 'Card', 'bKash', 'Nagad']

/**
 * Checkout terminal — register-speed UI.
 *
 * Left: autofocus scan/search, category chips, large product tiles.
 * Right: sticky cart panel — steppers, remove, tabular totals, payment,
 * 56px Charge button. Keyboard: F2 search, F8 clear, F9 charge.
 *
 * Flow: search/scan -> add to cart -> identify customer by phone
 * (quick-add if new) -> choose payment -> checkout. The backend
 * recalculates all totals from DB prices.
 */
export default function POS() {
  // ------------------------------------------------ data
  const [products, setProducts] = useState([])
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('All')
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
  const searchRef = useRef(null)

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
  const categories = useMemo(
    () => ['All', ...Array.from(new Set(products.map((p) => p.category).filter(Boolean)))],
    [products],
  )

  const filtered = products.filter((p) => {
    if (category !== 'All' && p.category !== category) return false
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

  // ------------------------------------------------ keyboard shortcuts
  useEffect(() => {
    function onKey(e) {
      if (e.key === 'F2') {
        e.preventDefault()
        searchRef.current?.focus()
      } else if (e.key === 'F8') {
        e.preventDefault()
        if (cart.length > 0) clearCart()
      } else if (e.key === 'F9') {
        e.preventDefault()
        if (!checkoutBusy && cart.length > 0 && customer) handleCheckout()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cart, customer, checkoutBusy])

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

  function bumpQty(line, delta) {
    setQty(line.product_id, line.quantity + delta)
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
        <p className="pos2-kbd-hint muted">
          <kbd>F2</kbd> search <kbd>F8</kbd> clear <kbd>F9</kbd> charge
        </p>
      </div>

      {error && (
        <div className="alert alert-error alert-dismiss" role="alert">
          <span>{error}</span>
          <button type="button" className="alert-close" onClick={() => setError(null)}>×</button>
        </div>
      )}

      <div className="pos2-layout">
        {/* ---------------- LEFT: search + categories + tiles ---------------- */}
        <section className="pos2-catalog" aria-label="Products">
          <div className="pos2-search">
            <ScanBarcode className="pos2-search-icon" size={20} aria-hidden="true" />
            <input
              id="pos-search"
              ref={searchRef}
              type="text"
              className="pos2-search-input"
              placeholder="Scan barcode or search name, category, ID…"
              aria-label="Find Product (name, category or ID)"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && filtered.length > 0) addToCart(filtered[0])
              }}
              autoFocus
            />
            <span className="pos2-search-count muted">
              {filtered.length} match{filtered.length === 1 ? '' : 'es'}
            </span>
          </div>

          <div className="pos2-chips" role="group" aria-label="Filter by category">
            {categories.map((cat) => (
              <button
                key={cat}
                type="button"
                className={`pos2-chip${category === cat ? ' pos2-chip-active' : ''}`}
                aria-pressed={category === cat}
                onClick={() => setCategory(cat)}
              >
                {cat}
              </button>
            ))}
          </div>

          {filtered.length === 0 ? (
            <div className="ui-empty">
              <Search className="ui-empty-icon" size={28} aria-hidden="true" />
              <h4 className="ui-empty-title">No products found</h4>
              <p className="ui-empty-body">Nothing matches “{search}” in {category === 'All' ? 'any category' : category}.</p>
            </div>
          ) : (
            <div className="pos2-grid">
              {filtered.map((p) => {
                const out = p.stock_quantity <= 0
                return (
                  <button
                    key={p.product_id}
                    type="button"
                    className={`pos2-tile${out ? ' pos2-tile-out' : ''}`}
                    onClick={() => addToCart(p)}
                    disabled={out}
                    title={out ? 'Out of stock' : `Add ${p.product_name} — ${fmtMoney(p.retail_price)}`}
                  >
                    <Avatar product={p} size="md" className="pos2-tile-avatar" />
                    <span className="pos2-tile-name">{p.product_name}</span>
                    <span className="pos2-tile-price">{fmtMoney(p.retail_price)}</span>
                    <span
                      className={`pos2-tile-stock ${
                        p.stock_quantity === 0 ? 'stock-out' : p.stock_quantity <= 5 ? 'stock-low' : 'stock-ok'
                      }`}
                    >
                      {p.stock_quantity} in stock
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </section>

        {/* ---------------- RIGHT: sticky cart + checkout ---------------- */}
        <aside className="pos2-cart" aria-label="Current sale">
          <div className="pos2-cart-card">
            <div className="pos2-cart-head">
              <h2 className="pos2-cart-title">Current Sale ({cartCount} item{cartCount === 1 ? '' : 's'})</h2>
              {cart.length > 0 && (
                <Button variant="ghost" size="sm" onClick={clearCart}>
                  <Trash2 size={14} aria-hidden="true" /> Clear Cart
                </Button>
              )}
            </div>

            <div className="pos2-lines">
              {cart.length === 0 ? (
                <p className="pos2-cart-empty muted">Cart is empty — tap a product to add it.</p>
              ) : (
                cart.map((line) => (
                  <div key={line.product_id} className="pos2-line">
                    <div className="pos2-line-info">
                      <span className="pos2-line-name">{line.product_name}</span>
                      <span className="pos2-line-unit muted">{fmtMoney(line.retail_price)} each</span>
                    </div>
                    <div className="pos2-stepper" role="group" aria-label={`Quantity of ${line.product_name}`}>
                      <button
                        type="button"
                        className="pos2-step-btn"
                        aria-label={`Decrease quantity of ${line.product_name}`}
                        onClick={() => bumpQty(line, -1)}
                        disabled={line.quantity <= 1}
                      >
                        <Minus size={16} aria-hidden="true" />
                      </button>
                      <input
                        type="number"
                        className="pos2-qty"
                        min="1"
                        max={line.stock_quantity}
                        value={line.quantity}
                        aria-label={`Quantity of ${line.product_name}`}
                        onChange={(e) => setQty(line.product_id, Number(e.target.value))}
                      />
                      <button
                        type="button"
                        className="pos2-step-btn"
                        aria-label={`Increase quantity of ${line.product_name}`}
                        onClick={() => bumpQty(line, 1)}
                        disabled={line.quantity >= line.stock_quantity}
                      >
                        <Plus size={16} aria-hidden="true" />
                      </button>
                    </div>
                    <span className="pos2-line-total">{fmtMoney(line.retail_price * line.quantity)}</span>
                    <button
                      type="button"
                      className="pos2-remove"
                      onClick={() => removeFromCart(line.product_id)}
                      aria-label={`Remove ${line.product_name}`}
                    >
                      <Trash2 size={16} aria-hidden="true" />
                    </button>
                  </div>
                ))
              )}
            </div>

            <div className="pos2-checkout">
              {/* customer */}
              <div className="pos2-customer">
                {customer ? (
                  <div className="customer-selected">
                    <div>
                      <strong>{customer.name}</strong>
                      <div className="muted">
                        {customer.phone_number} · #{customer.customer_id}
                      </div>
                    </div>
                    <Button variant="secondary" size="sm" onClick={clearCustomer}>
                      Change
                    </Button>
                  </div>
                ) : (
                  <>
                    <Field label="Phone Number">
                      <Input
                        id="pos-phone"
                        type="tel"
                        value={phone}
                        onChange={(e) => setPhone(e.target.value)}
                        onBlur={handlePhoneLookup}
                        onKeyDown={(e) => e.key === 'Enter' && handlePhoneLookup()}
                        placeholder="018XXXXXXXX"
                      />
                    </Field>
                    <Field label="Customer Name">
                      <div className="pos2-quickadd">
                        <Input
                          id="pos-custname"
                          type="text"
                          value={custName}
                          onChange={(e) => setCustName(e.target.value)}
                          placeholder="For quick-add"
                        />
                        <Button
                          variant="secondary"
                          onClick={handleQuickAdd}
                          disabled={lookupBusy}
                          title="Quick-add customer"
                          aria-label="Quick-add customer"
                        >
                          <Plus size={16} aria-hidden="true" />
                        </Button>
                      </div>
                    </Field>
                    {custStatus && <div className={`form-hint ${custStatus.kind}`}>{custStatus.text}</div>}
                  </>
                )}
              </div>

              {/* totals */}
              <div className="pos2-totals">
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
              </div>

              {/* payment */}
              <div className="pos2-payment" role="group" aria-label="Payment method">
                {PAYMENT_METHODS.map((m) => (
                  <button
                    key={m}
                    type="button"
                    className={`pos2-pay-chip${paymentMethod === m ? ' pos2-pay-active' : ''}`}
                    aria-pressed={paymentMethod === m}
                    onClick={() => setPaymentMethod(m)}
                  >
                    {m}
                  </button>
                ))}
              </div>

              <Button
                size="xl"
                className="pos2-charge"
                loading={checkoutBusy}
                disabled={cart.length === 0 || !customer}
                onClick={handleCheckout}
              >
                {checkoutBusy ? 'Processing…' : `Complete Sale — ${fmtMoney(total)}`}
              </Button>
            </div>
          </div>
        </aside>
      </div>

      {/* ---------------- Receipt after checkout ---------------- */}
      <Modal open={!!receipt} title={receipt ? `Sale #${receipt.transaction_id} complete` : ''} onClose={() => setReceipt(null)}>
        {receipt && (
          <>
            <div className="pos2-receipt-banner">
              <CheckCircle2 size={28} aria-hidden="true" />
              <div>
                <strong>Payment received</strong>
                <p className="muted">
                  {fmtDate(receipt.date)} {fmtTime(receipt.time)} · {receipt.payment_method}
                </p>
              </div>
            </div>
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
          </>
        )}
        <div className="pos2-receipt-actions">
          <Button size="lg" onClick={() => setReceipt(null)}>
            New Sale
          </Button>
        </div>
      </Modal>
    </div>
  )
}

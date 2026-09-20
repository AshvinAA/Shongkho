import { useEffect, useMemo, useRef, useState } from 'react'
import * as productsApi from '../api/products.js'
import * as uploadsApi from '../api/uploads.js'
import { useAuth } from '../context/AuthContext.jsx'
import { RoleGate } from '../components/RoleGate.jsx'
import Modal from '../components/Modal.jsx'
import Avatar from '../components/Avatar.jsx'
import CategoryInput from '../components/CategoryInput.jsx'
import { fmtMoney, fmtDate } from '../utils/format.js'

const LOW_STOCK_THRESHOLD = 5

const EMPTY_FORM = {
  product_name: '',
  category: '',
  cost_price: '',
  retail_price: '',
  stock_quantity: '',
  supplier_name: '',
}

/** Inventory management: photo tile grid, detail pop-out, owner add/edit/delete. */
export default function Inventory() {
  const { user } = useAuth()
  const isOwner = user?.role === 'owner'

  // ------------------------------------------------ data
  const [products, setProducts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // ------------------------------------------------ filters
  const [search, setSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [lowOnly, setLowOnly] = useState(false)

  // ------------------------------------------------ detail pop-out
  const [detailProduct, setDetailProduct] = useState(null)

  // ------------------------------------------------ modals
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState(null) // product object or null
  const [form, setForm] = useState(EMPTY_FORM)
  const [formPhoto, setFormPhoto] = useState(null) // File selected for upload
  const [formPhotoRemoved, setFormPhotoRemoved] = useState(false)
  const [formError, setFormError] = useState(null)
  const [saving, setSaving] = useState(false)

  const [stockTarget, setStockTarget] = useState(null) // product being restocked
  const [stockDelta, setStockDelta] = useState('')
  const [stockError, setStockError] = useState(null)
  const [stockSaving, setStockSaving] = useState(false)

  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleteBusy, setDeleteBusy] = useState(false)

  const categories = useMemo(
    () => [...new Set(products.map((p) => p.category).filter(Boolean))],
    [products],
  )

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const data = await productsApi.listProducts({ limit: 1000 })
      setProducts(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  // ------------------------------------------------ filtering
  const filtered = products.filter((p) => {
    const q = search.trim().toLowerCase()
    if (q && !p.product_name.toLowerCase().includes(q) && !String(p.product_id).includes(q)) return false
    if (categoryFilter && p.category !== categoryFilter) return false
    if (lowOnly && p.stock_quantity > LOW_STOCK_THRESHOLD) return false
    return true
  })

  // ------------------------------------------------ detail pop-out
  function openDetails(product) {
    setDetailProduct(product)
  }

  function openEditFromDetails() {
    openEdit(detailProduct)
    setDetailProduct(null)
  }

  // ------------------------------------------------ form handlers
  function openAdd() {
    setEditing(null)
    setForm(EMPTY_FORM)
    setFormPhoto(null)
    setFormPhotoRemoved(false)
    setFormError(null)
    setFormOpen(true)
  }

  function openEdit(product) {
    setEditing(product)
    setForm({
      product_name: product.product_name || '',
      category: product.category || '',
      cost_price: String(product.cost_price ?? ''),
      retail_price: String(product.retail_price ?? ''),
      stock_quantity: String(product.stock_quantity ?? ''),
      supplier_name: product.supplier_name || '',
    })
    setFormPhoto(null)
    setFormPhotoRemoved(false)
    setFormError(null)
    setFormOpen(true)
  }

  function handleFormChange(e) {
    const { name, value } = e.target
    setForm((f) => ({ ...f, [name]: value }))
  }

  function handleCategoryChange(value) {
    setForm((f) => ({ ...f, category: value }))
  }

  function handlePhotoChosen(file) {
    setFormPhoto(file)
    setFormPhotoRemoved(false)
  }

  function handlePhotoRemoved() {
    setFormPhoto(null)
    setFormPhotoRemoved(true)
  }

  function validateForm() {
    if (!form.product_name.trim()) return 'Product name is required.'
    if (!form.cost_price || Number(form.cost_price) < 0) return 'Enter a valid cost price.'
    if (!form.retail_price || Number(form.retail_price) < 0) return 'Enter a valid retail price.'
    if (form.stock_quantity === '' || !Number.isInteger(Number(form.stock_quantity)) || Number(form.stock_quantity) < 0) {
      return 'Stock quantity must be a whole number (0 or more).'
    }
    return null
  }

  async function handleSave(e) {
    e.preventDefault()
    const problem = validateForm()
    if (problem) {
      setFormError(problem)
      return
    }

    setSaving(true)
    setFormError(null)
    const payload = {
      product_name: form.product_name.trim(),
      category: form.category.trim() || null,
      cost_price: Number(form.cost_price),
      retail_price: Number(form.retail_price),
      stock_quantity: Number(form.stock_quantity),
      supplier_name: form.supplier_name.trim() || null,
    }
    if (editing && formPhotoRemoved) payload.photo = null

    try {
      let saved
      if (editing) {
        saved = await productsApi.updateProduct(editing.product_id, payload)
      } else {
        saved = await productsApi.createProduct(payload)
      }
      // A newly chosen photo needs the product to exist first
      if (formPhoto) {
        try {
          saved = await uploadsApi.uploadProductPhoto(saved.product_id, formPhoto)
        } catch (uploadErr) {
          setFormError(`Product saved, but the picture failed: ${uploadErr.message}`)
          setSaving(false)
          setFormPhoto(null)
          await load()
          return
        }
      }
      setFormOpen(false)
      setFormPhoto(null)
      await load()
    } catch (err) {
      setFormError(err.message)
    } finally {
      setSaving(false)
    }
  }

  // ------------------------------------------------ stock adjust
  function openStock(product) {
    setStockTarget(product)
    setStockDelta('')
    setStockError(null)
  }

  async function handleStockSave(e) {
    e.preventDefault()
    const delta = Number(stockDelta)
    if (!Number.isInteger(delta) || delta === 0) {
      setStockError('Enter a non-zero whole number (use a negative value to reduce).')
      return
    }

    setStockSaving(true)
    setStockError(null)
    try {
      await productsApi.adjustStock(stockTarget.product_id, delta)
      setStockTarget(null)
      await load()
    } catch (err) {
      setStockError(err.message)
    } finally {
      setStockSaving(false)
    }
  }

  // ------------------------------------------------ delete
  async function handleDelete() {
    setDeleteBusy(true)
    try {
      await productsApi.deleteProduct(deleteTarget.product_id)
      setDeleteTarget(null)
      await load()
    } catch (err) {
      setError(err.message)
      setDeleteTarget(null)
    } finally {
      setDeleteBusy(false)
    }
  }

  // ------------------------------------------------ render
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Inventory</h1>
          <p className="muted">
            {products.length} products · {products.filter((p) => p.stock_quantity <= LOW_STOCK_THRESHOLD).length} low stock
          </p>
        </div>
        <RoleGate allowedRoles={['owner']}>
          <button type="button" className="btn" onClick={openAdd}>
            ＋ Add Product
          </button>
        </RoleGate>
      </div>

      {error && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}

      <div className="card filter-bar">
        <input
          type="search"
          className="form-control"
          placeholder="Search by name or ID…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select className="form-control" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <label className="checkbox-label">
          <input type="checkbox" checked={lowOnly} onChange={(e) => setLowOnly(e.target.checked)} />
          Low stock only
        </label>
      </div>

      {loading ? (
        <div className="card page-loading" role="status">
          <div className="spinner" />
          <p className="muted">Loading inventory…</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="card">
          <p className="muted">No products found{search || categoryFilter || lowOnly ? ' with these filters.' : ' — add your first product.'}</p>
        </div>
      ) : (
        <div className="inventory-grid">
          {filtered.map((p) => {
            const low = p.stock_quantity > 0 && p.stock_quantity <= LOW_STOCK_THRESHOLD
            const out = p.stock_quantity === 0
            return (
              <button
                key={p.product_id}
                type="button"
                className={`product-card ${low ? 'is-low' : ''} ${out ? 'is-out' : ''}`}
                onClick={() => openDetails(p)}
                title={`View ${p.product_name}`}
              >
                <span className="product-card-photo">
                  <Avatar product={p} size="lg" className="product-card-avatar" />
                  {out && <span className="product-card-flag flag-out">Out of stock</span>}
                  {!out && low && <span className="product-card-flag flag-low">Low</span>}
                </span>
                <span className="product-card-name">{p.product_name}</span>
              </button>
            )
          })}
        </div>
      )}

      {/* ---------------- Detail pop-out ---------------- */}
      <Modal
        open={!!detailProduct}
        onClose={() => setDetailProduct(null)}
        title={detailProduct?.product_name ?? ''}
      >
        {detailProduct && (
          <div className="product-detail">
            <div className="product-detail-photo">
              <Avatar product={detailProduct} size="xl" />
            </div>

            <div className="product-detail-body">
              <div className="summary-row">
                <span className="muted">Product ID</span>
                <strong>#{detailProduct.product_id}</strong>
              </div>
              <div className="summary-row">
                <span className="muted">Category</span>
                <strong>{detailProduct.category || '—'}</strong>
              </div>
              <div className="summary-row">
                <span className="muted">Supplier</span>
                <strong>{detailProduct.supplier_name || '—'}</strong>
              </div>
              <div className="summary-row">
                <span className="muted">Cost Price</span>
                <strong>{fmtMoney(detailProduct.cost_price)}</strong>
              </div>
              <div className="summary-row">
                <span className="muted">Retail Price</span>
                <strong>{fmtMoney(detailProduct.retail_price)}</strong>
              </div>
              <div className="summary-row">
                <span className="muted">Stock</span>
                <span className={`stock-chip ${detailProduct.stock_quantity === 0 ? 'stock-out' : detailProduct.stock_quantity <= LOW_STOCK_THRESHOLD ? 'stock-low' : 'stock-ok'}`}>
                  {detailProduct.stock_quantity === 0 ? 'Out of stock' : `${detailProduct.stock_quantity} in stock`}
                </span>
              </div>
              <div className="summary-row">
                <span className="muted">Added</span>
                <strong>{fmtDate(detailProduct.date)}</strong>
              </div>
            </div>
          </div>
        )}
      {detailProduct && isOwner && (
          <div className="product-detail-actions">
            <button type="button" className="btn btn-outline" onClick={() => openStock(detailProduct)}>
              Adjust Stock
            </button>
            <button type="button" className="btn" onClick={openEditFromDetails}>
              ✏️ Edit Product
            </button>
          </div>
        )}
      </Modal>

      {/* ---------------- Add / Edit modal ---------------- */}
      <Modal open={formOpen} onClose={() => setFormOpen(false)} title={editing ? `Edit ${editing.product_name}` : 'Add Product'}>
        <form onSubmit={handleSave} noValidate>
          {formError && (
            <div className="alert alert-error" role="alert">{formError}</div>
          )}

          <div className="form-group">
            <label className="form-label">Product Picture</label>
            <PhotoField
              product={editing}
              file={formPhoto}
              removed={formPhotoRemoved}
              onChoose={handlePhotoChosen}
              onRemove={handlePhotoRemoved}
              disabled={saving}
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="inv-name">Product Name *</label>
            <input id="inv-name" name="product_name" type="text" className="form-control" value={form.product_name} onChange={handleFormChange} autoFocus />
          </div>

          <div className="form-row">
            <div className="form-group">
              <label className="form-label" htmlFor="inv-category">Category</label>
              <CategoryInput id="inv-category" value={form.category} onChange={handleCategoryChange} suggestions={categories} />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="inv-supplier">Supplier</label>
              <input id="inv-supplier" name="supplier_name" type="text" className="form-control" value={form.supplier_name} onChange={handleFormChange} />
            </div>
          </div>

          <div className="form-row form-row-3">
            <div className="form-group">
              <label className="form-label" htmlFor="inv-cost">Cost Price ৳ *</label>
              <input id="inv-cost" name="cost_price" type="number" min="0" step="0.01" className="form-control" value={form.cost_price} onChange={handleFormChange} />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="inv-retail">Retail Price ৳ *</label>
              <input id="inv-retail" name="retail_price" type="number" min="0" step="0.01" className="form-control" value={form.retail_price} onChange={handleFormChange} />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="inv-stock">Stock Qty *</label>
              <input id="inv-stock" name="stock_quantity" type="number" min="0" step="1" className="form-control" value={form.stock_quantity} onChange={handleFormChange} />
            </div>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-outline" onClick={() => setFormOpen(false)}>Cancel</button>
            <button type="submit" className="btn" disabled={saving}>
              {saving ? 'Saving…' : editing ? 'Save Changes' : 'Add Product'}
            </button>
          </div>
        </form>
      </Modal>

      {/* ---------------- Stock adjust modal ---------------- */}
      <Modal open={!!stockTarget} onClose={() => setStockTarget(null)} title={`Adjust Stock — ${stockTarget?.product_name ?? ''}`}>
        {stockTarget && (
          <form onSubmit={handleStockSave} noValidate>
            <p className="muted">
              Current stock: <strong>{stockTarget.stock_quantity}</strong>
            </p>
            {stockError && <div className="alert alert-error" role="alert">{stockError}</div>}
            <div className="form-group">
              <label className="form-label" htmlFor="inv-delta">Quantity Change *</label>
              <input
                id="inv-delta"
                type="number"
                step="1"
                className="form-control"
                value={stockDelta}
                onChange={(e) => setStockDelta(e.target.value)}
                placeholder="e.g. 50 to add, -3 to remove"
                autoFocus
              />
              <p className="form-hint info">New stock = current + change (cannot go below 0).</p>
            </div>
            <div className="modal-footer">
              <button type="button" className="btn btn-outline" onClick={() => setStockTarget(null)}>Cancel</button>
              <button type="submit" className="btn" disabled={stockSaving}>{stockSaving ? 'Saving…' : 'Apply'}</button>
            </div>
          </form>
        )}
      </Modal>

      {/* ---------------- Delete confirm ---------------- */}
      <Modal
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Product"
        footer={
          <>
            <button type="button" className="btn btn-outline" onClick={() => setDeleteTarget(null)}>Cancel</button>
            <button type="button" className="btn btn-danger" onClick={handleDelete} disabled={deleteBusy}>
              {deleteBusy ? 'Deleting…' : 'Delete'}
            </button>
          </>
        }
      >
        <p>
          Delete <strong>{deleteTarget?.product_name}</strong>?
        </p>
        <p className="muted">
          Products with recorded sales cannot be deleted — set stock to 0 instead.
        </p>
      </Modal>
    </div>
  )
}

/**
 * Photo picker used by the add/edit form.
 * - Add mode: choose a file; it uploads right after the product is created.
 * - Edit mode: preview the current photo, replace or clear it.
 */
function PhotoField({ product, file, removed, onChoose, onRemove, disabled }) {
  const inputRef = useRef(null)

  const previewUrl = useMemo(() => (file ? URL.createObjectURL(file) : null), [file])
  const serverPhoto = product?.photo && !removed && !file ? product.photo : null

  // Revoke object URLs to avoid memory leaks
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl)
    }
  }, [previewUrl])

  return (
    <div className="photo-upload-row">
      {previewUrl || serverPhoto ? (
        <img src={previewUrl || serverPhoto} alt="Product preview" className="photo-preview photo-preview-square" />
      ) : (
        <div className="photo-preview photo-placeholder photo-preview-square">📦</div>
      )}
      <div>
        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/gif"
          onChange={(e) => {
            const f = e.target.files?.[0]
            e.target.value = ''
            if (f) onChoose(f)
          }}
          disabled={disabled}
          style={{ display: 'none' }}
        />
        <div className="row-actions">
          <button type="button" className="btn btn-outline btn-sm" onClick={() => inputRef.current?.click()} disabled={disabled}>
            {file ? 'Change image…' : 'Choose image…'}
          </button>
          {(file || serverPhoto) && (
            <button type="button" className="btn btn-outline btn-sm" onClick={onRemove} disabled={disabled}>
              Remove
            </button>
          )}
        </div>
        {!file && !product && <p className="form-hint info">You can add a picture now or later.</p>}
        {file && <p className="form-hint info">Picture uploads when you save.</p>}
      </div>
    </div>
  )
}

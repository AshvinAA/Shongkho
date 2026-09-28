import { useEffect, useMemo, useRef, useState } from 'react'
import { Package, PackageSearch, Pencil, Plus, Search } from 'lucide-react'
import * as productsApi from '../api/products.js'
import * as uploadsApi from '../api/uploads.js'
import { useAuth } from '../context/AuthContext.jsx'
import { RoleGate } from '../components/RoleGate.jsx'
import CategoryInput from '../components/CategoryInput.jsx'
import { fmtMoney, fmtDate } from '../utils/format.js'
import {
  Badge,
  Button,
  Card,
  Drawer,
  EmptyState,
  ErrorState,
  Input,
  Modal,
  Select,
  Skeleton,
} from '../components/ui/index.jsx'

const LOW_STOCK_THRESHOLD = 5

const EMPTY_FORM = {
  product_name: '',
  category: '',
  cost_price: '',
  retail_price: '',
  stock_quantity: '',
  supplier_name: '',
}

function stockTone(qty) {
  if (qty === 0) return 'danger'
  if (qty <= LOW_STOCK_THRESHOLD) return 'warning'
  return 'success'
}

function stockText(qty) {
  if (qty === 0) return 'Out of stock'
  if (qty <= LOW_STOCK_THRESHOLD) return `Low · ${qty} left`
  return `${qty} in stock`
}

/** Inventory management: photo tile grid, detail drawer, owner add/edit/delete. */
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

  // ------------------------------------------------ detail drawer
  const [detailProduct, setDetailProduct] = useState(null)

  // ------------------------------------------------ form drawer
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

  const lowCount = products.filter((p) => p.stock_quantity <= LOW_STOCK_THRESHOLD).length

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

  // ------------------------------------------------ detail drawer
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
            {products.length} products · {lowCount} low stock
          </p>
        </div>
        {isOwner && (
          <Button onClick={openAdd}>
            <Plus size={16} aria-hidden="true" /> Add Product
          </Button>
        )}
      </div>

      {error && <ErrorState onRetry={load}>{error}</ErrorState>}

      <Card className="inv-toolbar">
        <div className="ui-input-icon-wrap inv-search">
          <Search size={16} aria-hidden="true" />
          <Input
            type="search"
            placeholder="Search by name or ID…"
            aria-label="Search products"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <Select
          aria-label="Filter by category"
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
        >
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </Select>
        <label className="checkbox-label inv-low-toggle">
          <input type="checkbox" checked={lowOnly} onChange={(e) => setLowOnly(e.target.checked)} />
          Low stock only
        </label>
      </Card>

      {loading ? (
        <div className="inv-grid" aria-label="Loading inventory" role="status">
          {Array.from({ length: 8 }, (_, i) => (
            <div key={i} className="inv-card inv-card-skeleton">
              <Skeleton width="100%" height="7rem" />
              <Skeleton width="70%" height="0.9rem" />
              <Skeleton width="45%" height="0.9rem" />
            </div>
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <Card>
          <EmptyState icon={PackageSearch} title="No products found">
            {search || categoryFilter || lowOnly
              ? 'Nothing matches these filters — try clearing the search or category.'
              : 'Add your first product to start selling.'}
          </EmptyState>
        </Card>
      ) : (
        <div className="inv-grid">
          {filtered.map((p) => {
            const low = p.stock_quantity > 0 && p.stock_quantity <= LOW_STOCK_THRESHOLD
            const out = p.stock_quantity === 0
            return (
              <button
                key={p.product_id}
                type="button"
                className={`inv-card ${low ? 'is-low' : ''} ${out ? 'is-out' : ''}`}
                onClick={() => openDetails(p)}
                title={`View ${p.product_name}`}
              >
                <span className={`inv-card-photo ${out ? 'is-out' : ''}`}>
                  <img
                    src={p.photo || undefined}
                    alt=""
                    className="inv-card-img"
                    onError={(e) => { e.currentTarget.style.display = 'none' }}
                  />
                  {!p.photo && <span className="inv-card-fallback" aria-hidden="true">{p.product_name.slice(0, 1).toUpperCase()}</span>}
                  {out && <Badge variant="danger" className="inv-card-flag">Out of stock</Badge>}
                  {!out && low && <Badge variant="warning" className="inv-card-flag">Low</Badge>}
                </span>
                <span className="inv-card-name">{p.product_name}</span>
                <span className="inv-card-meta">
                  <span className="inv-card-price">{fmtMoney(p.retail_price)}</span>
                  <Badge variant={stockTone(p.stock_quantity)}>{stockText(p.stock_quantity)}</Badge>
                </span>
              </button>
            )
          })}
        </div>
      )}

      {/* ---------------- Detail drawer ---------------- */}
      <Drawer
        open={!!detailProduct}
        onClose={() => setDetailProduct(null)}
        title={detailProduct?.product_name ?? ''}
      >
        {detailProduct && (
          <div className="inv-detail">
            <div className="inv-detail-photo">
              <img
                src={detailProduct.photo || undefined}
                alt={`Photo of ${detailProduct.product_name}`}
                className="inv-detail-img"
                onError={(e) => { e.currentTarget.style.display = 'none' }}
              />
              {!detailProduct.photo && (
                <span className="inv-detail-fallback" aria-hidden="true">
                  {detailProduct.product_name.slice(0, 1).toUpperCase()}
                </span>
              )}
            </div>

            <div className="ui-detail-facts">
              <div className="ui-fact">
                <span className="ui-fact-label">Product ID</span>
                <span className="ui-fact-value">#{detailProduct.product_id}</span>
              </div>
              <div className="ui-fact">
                <span className="ui-fact-label">Category</span>
                <span className="ui-fact-value">{detailProduct.category || '—'}</span>
              </div>
              <div className="ui-fact">
                <span className="ui-fact-label">Supplier</span>
                <span className="ui-fact-value">{detailProduct.supplier_name || '—'}</span>
              </div>
              <div className="ui-fact">
                <span className="ui-fact-label">Cost Price</span>
                <span className="ui-fact-value ui-num">{fmtMoney(detailProduct.cost_price)}</span>
              </div>
              <div className="ui-fact">
                <span className="ui-fact-label">Retail Price</span>
                <span className="ui-fact-value ui-num">{fmtMoney(detailProduct.retail_price)}</span>
              </div>
              <div className="ui-fact">
                <span className="ui-fact-label">Stock</span>
                <span className="ui-fact-value">
                  <Badge variant={stockTone(detailProduct.stock_quantity)}>
                    {stockText(detailProduct.stock_quantity)}
                  </Badge>
                </span>
              </div>
              <div className="ui-fact">
                <span className="ui-fact-label">Added</span>
                <span className="ui-fact-value">{fmtDate(detailProduct.date)}</span>
              </div>
            </div>

            {isOwner && (
              <div className="ui-overlay-footer">
                <Button variant="secondary" onClick={() => openStock(detailProduct)}>
                  Adjust Stock
                </Button>
                <Button onClick={openEditFromDetails}>
                  <Pencil size={15} aria-hidden="true" /> Edit Product
                </Button>
              </div>
            )}
          </div>
        )}
      </Drawer>

      {/* ---------------- Add / Edit drawer ---------------- */}
      <Drawer
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title={editing ? `Edit ${editing.product_name}` : 'Add Product'}
      >
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
            <Input id="inv-name" name="product_name" type="text" value={form.product_name} onChange={handleFormChange} autoFocus />
          </div>

          <div className="form-row">
            <div className="form-group">
              <label className="form-label" htmlFor="inv-category">Category</label>
              <CategoryInput id="inv-category" value={form.category} onChange={handleCategoryChange} suggestions={categories} />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="inv-supplier">Supplier</label>
              <Input id="inv-supplier" name="supplier_name" type="text" value={form.supplier_name} onChange={handleFormChange} />
            </div>
          </div>

          <div className="form-row form-row-3">
            <div className="form-group">
              <label className="form-label" htmlFor="inv-cost">Cost Price ৳ *</label>
              <Input id="inv-cost" name="cost_price" type="number" min="0" step="0.01" value={form.cost_price} onChange={handleFormChange} />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="inv-retail">Retail Price ৳ *</label>
              <Input id="inv-retail" name="retail_price" type="number" min="0" step="0.01" value={form.retail_price} onChange={handleFormChange} />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="inv-stock">Stock Qty *</label>
              <Input id="inv-stock" name="stock_quantity" type="number" min="0" step="1" value={form.stock_quantity} onChange={handleFormChange} />
            </div>
          </div>

          <div className="ui-overlay-footer">
            <Button type="button" variant="secondary" onClick={() => setFormOpen(false)}>Cancel</Button>
            <Button type="submit" loading={saving}>
              {saving ? 'Saving…' : editing ? 'Save Changes' : 'Add Product'}
            </Button>
          </div>
        </form>
      </Drawer>

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
              <Input
                id="inv-delta"
                type="number"
                step="1"
                value={stockDelta}
                onChange={(e) => setStockDelta(e.target.value)}
                placeholder="e.g. 50 to add, -3 to remove"
                autoFocus
              />
              <p className="form-hint info">New stock = current + change (cannot go below 0).</p>
            </div>
            <div className="ui-overlay-footer">
              <Button type="button" variant="secondary" onClick={() => setStockTarget(null)}>Cancel</Button>
              <Button type="submit" loading={stockSaving}>{stockSaving ? 'Saving…' : 'Apply'}</Button>
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
            <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button variant="danger" onClick={handleDelete} loading={deleteBusy}>
              {deleteBusy ? 'Deleting…' : 'Delete'}
            </Button>
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
        <div className="photo-preview photo-placeholder photo-preview-square">
          <Package size={28} aria-hidden="true" />
        </div>
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
          <Button type="button" variant="secondary" size="sm" onClick={() => inputRef.current?.click()} disabled={disabled}>
            {file ? 'Change image…' : 'Choose image…'}
          </Button>
          {(file || serverPhoto) && (
            <Button type="button" variant="secondary" size="sm" onClick={onRemove} disabled={disabled}>
              Remove
            </Button>
          )}
        </div>
        {!file && !product && <p className="form-hint info">You can add a picture now or later.</p>}
        {file && <p className="form-hint info">Picture uploads when you save.</p>}
      </div>
    </div>
  )
}

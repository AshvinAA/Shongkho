import { get, post, put, patch, del, qs } from './client.js'

/** List products. Both roles. */
export function listProducts({ skip = 0, limit = 100 } = {}) {
  return get(`/products/${qs({ skip, limit })}`)
}

/** Search products by name/category. Both roles. */
export function searchProducts(query) {
  return get(`/products/search/${qs({ query })}`)
}

/** One product. Both roles. */
export function getProduct(productId) {
  return get(`/products/${productId}`)
}

/** Owner-only: create product. */
export function createProduct(payload) {
  return post('/products/', payload)
}

/** Owner-only: update product fields. */
export function updateProduct(productId, payload) {
  return put(`/products/${productId}`, payload)
}

/** Owner-only: delete a product (blocked if it has sales). */
export function deleteProduct(productId) {
  return del(`/products/${productId}`)
}

/** Owner-only: adjust stock by a delta (can be negative). */
export function adjustStock(productId, quantityChange) {
  return patch(`/products/${productId}/stock`, { quantity_change: quantityChange })
}

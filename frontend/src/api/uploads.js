import { request } from './client.js'

/**
 * Upload a profile picture for the logged-in user.
 * Returns { photo_url }.
 */
export function uploadProfilePhoto(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request('/uploads/profile-photo', { method: 'POST', body: formData })
}

/**
 * Owner-only: upload a picture for a product.
 * Returns the updated product object.
 */
export function uploadProductPhoto(productId, file) {
  const formData = new FormData()
  formData.append('file', file)
  return request(`/products/${productId}/photo`, { method: 'POST', body: formData })
}

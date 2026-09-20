import { useState, useRef } from 'react'
import { request } from '../api/client.js'

const MAX_SIZE = 5 * 1024 * 1024 // 5 MB, matches the backend limit
const ACCEPTED = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']

/**
 * Reusable image upload field.
 *
 * Uploads a chosen image to /api/v1/uploads/profile-photo and hands the
 * returned URL to the parent via onUpload(url).
 *
 * props:
 *  - label        field label (default "Photo")
 *  - currentUrl   existing image URL to preview (optional)
 *  - onUpload     (url) => void, called with the server URL on success
 *  - onError      optional (message) => void, else error shown inline
 */
export default function PhotoUpload({ label = 'Photo', currentUrl, onUpload, onError }) {
  const [uploading, setUploading] = useState(false)
  const [preview, setPreview] = useState(currentUrl || null)
  const [error, setError] = useState(null)
  const inputRef = useRef(null)

  function handleError(message) {
    setError(message)
    onError?.(message)
  }

  async function handleFileChange(e) {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-selecting the same file
    if (!file) return

    setError(null)

    if (!ACCEPTED.includes(file.type)) {
      handleError('Please choose a JPEG, PNG, WebP or GIF image.')
      return
    }
    if (file.size > MAX_SIZE) {
      handleError('Image must be 5 MB or smaller.')
      return
    }

    // Local preview while uploading
    const localPreview = URL.createObjectURL(file)
    setPreview(localPreview)

    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const data = await request('/uploads/profile-photo', { method: 'POST', body: formData })
      // Revoke the local preview once the real URL is available
      URL.revokeObjectURL(localPreview)
      setPreview(data.photo_url)
      onUpload?.(data.photo_url)
    } catch (err) {
      URL.revokeObjectURL(localPreview)
      setPreview(currentUrl || null)
      handleError(err.message || 'Upload failed.')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="photo-upload">
      {label && <label className="form-label">{label}</label>}
      <div className="photo-upload-row">
        {preview ? (
          <img src={preview} alt="Preview" className="photo-preview" />
        ) : (
          <div className="photo-preview photo-placeholder">🖼️</div>
        )}
        <div>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED.join(',')}
            onChange={handleFileChange}
            disabled={uploading}
            style={{ display: 'none' }}
          />
          <button
            type="button"
            className="btn btn-outline btn-sm"
            onClick={() => inputRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? 'Uploading…' : 'Choose image…'}
          </button>
        </div>
      </div>
      {error && <div className="form-error" role="alert">{error}</div>}
    </div>
  )
}

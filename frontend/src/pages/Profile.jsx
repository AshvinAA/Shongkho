import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext.jsx'
import * as employeesApi from '../api/employees.js'
import PhotoUpload from '../components/PhotoUpload.jsx'

/**
 * Self-service profile page (owner and employee).
 *
 * Editable: photo, name, phone number.
 * Read-only: role, position — those are managed by the owner on /staff.
 */
export default function Profile() {
  const { user, refreshUser } = useAuth()

  const [profile, setProfile] = useState(null)
  const [form, setForm] = useState({ name: '', phone_number: '', photo: null })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const data = await employeesApi.getMyProfile()
        if (cancelled) return
        setProfile(data)
        setForm({
          name: data.name ?? '',
          phone_number: data.phone_number ?? '',
          photo: data.photo ?? null,
        })
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
  }, [])

  function handleChange(e) {
    const { name, value } = e.target
    setForm((f) => ({ ...f, [name]: value }))
    setSaved(false)
    setError(null)
  }

  function handlePhotoUploaded(url) {
    setForm((f) => ({ ...f, photo: url }))
    setSaved(false)
  }

  function validate() {
    if (!form.name.trim()) return 'Name is required.'
    if (!/^\d{10,15}$/.test(form.phone_number.trim())) {
      return 'Enter a valid phone number (10–15 digits).'
    }
    return null
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (saving) return

    const problem = validate()
    if (problem) {
      setError(problem)
      return
    }

    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      const updated = await employeesApi.updateMyProfile({
        name: form.name.trim(),
        phone_number: form.phone_number.trim(),
        photo: form.photo,
      })
      setProfile(updated)
      setSaved(true)
      // Backend keeps the session in sync — refresh so the navbar shows the new name.
      await refreshUser()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="page page-loading" role="status">
        <div className="spinner" />
        <p className="muted">Loading your profile…</p>
      </div>
    )
  }

  if (!profile) {
    return (
      <div className="page">
        <div className="alert alert-error" role="alert">
          {error || 'Could not load your profile.'}
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>My Profile</h1>
          <p className="muted">Update your personal details and profile picture.</p>
        </div>
      </div>

      <div className="dashboard-columns">
        <div className="card">
          <PhotoUpload
            label="Profile Picture"
            currentUrl={form.photo}
            onUpload={handlePhotoUploaded}
            onError={setError}
          />

          <div className="form-group" style={{ marginTop: '1rem' }}>
            <label className="form-label">Role</label>
            <p>
              <span className={`role-badge role-${profile.user_type}`}>{profile.user_type}</span>
              {profile.position && <span className="muted"> · {profile.position}</span>}
            </p>
          </div>
        </div>

        <form className="card" onSubmit={handleSubmit} noValidate>
          <div className="card-title">Personal Details</div>

          {error && (
            <div className="alert alert-error" role="alert">
              {error}
            </div>
          )}
          {saved && (
            <div className="alert alert-success" role="status">
              Profile saved. ✓
            </div>
          )}

          <div className="form-group">
            <label htmlFor="profile-name" className="form-label">Full Name</label>
            <input
              id="profile-name"
              name="name"
              type="text"
              className="form-control"
              value={form.name}
              onChange={handleChange}
              autoComplete="name"
            />
          </div>

          <div className="form-group">
            <label htmlFor="profile-phone" className="form-label">Phone Number</label>
            <input
              id="profile-phone"
              name="phone_number"
              type="tel"
              className="form-control"
              value={form.phone_number}
              onChange={handleChange}
              autoComplete="tel"
            />
            <p className="form-hint muted">You sign in with this number — keep it correct.</p>
          </div>

          <button type="submit" className="btn btn-block" disabled={saving}>
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
        </form>
      </div>
    </div>
  )
}

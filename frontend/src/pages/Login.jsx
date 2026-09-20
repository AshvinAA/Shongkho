import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

/** Login form (phone + password) with validation and error alerts. */
export default function Login() {
  const { login, isAuthenticated } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [form, setForm] = useState({
    phone_number: location.state?.registeredPhone || '',
    password: '',
  })
  const [errors, setErrors] = useState({})
  const [apiError, setApiError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const from = location.state?.from?.pathname || '/'

  if (isAuthenticated) {
    return <Navigate to={from} replace />
  }

  function validate() {
    const next = {}
    if (!/^\d{10,15}$/.test(form.phone_number.trim())) {
      next.phone_number = 'Enter a valid phone number (10–15 digits).'
    }
    if (form.password.length < 4) {
      next.password = 'Password must be at least 4 characters.'
    }
    setErrors(next)
    return Object.keys(next).length === 0
  }

  function handleChange(e) {
    const { name, value } = e.target
    setForm((f) => ({ ...f, [name]: value }))
    setErrors((prev) => ({ ...prev, [name]: undefined }))
    setApiError(null)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (submitting || !validate()) return

    setSubmitting(true)
    setApiError(null)
    try {
      await login({ phone_number: form.phone_number.trim(), password: form.password })
      navigate(from, { replace: true })
    } catch (err) {
      setApiError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="auth-logo">🏪</span>
          <h1>Shongkho POS</h1>
          <p className="muted">Sign in to your store account</p>
        </div>

        {apiError && (
          <div className="alert alert-error" role="alert">
            {apiError}
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate>
          <div className="form-group">
            <label htmlFor="phone_number" className="form-label">Phone Number</label>
            <input
              id="phone_number"
              name="phone_number"
              type="tel"
              className={`form-control ${errors.phone_number ? 'is-invalid' : ''}`}
              placeholder="017XXXXXXXX"
              value={form.phone_number}
              onChange={handleChange}
              autoComplete="tel"
              autoFocus
            />
            {errors.phone_number && <div className="form-error">{errors.phone_number}</div>}
          </div>

          <div className="form-group">
            <label htmlFor="password" className="form-label">Password</label>
            <input
              id="password"
              name="password"
              type="password"
              className={`form-control ${errors.password ? 'is-invalid' : ''}`}
              placeholder="••••••••"
              value={form.password}
              onChange={handleChange}
              autoComplete="current-password"
            />
            {errors.password && <div className="form-error">{errors.password}</div>}
          </div>

          <button type="submit" className="btn btn-block" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign In'}
          </button>
        </form>

        <div className="auth-links">
          <Link to="/register">Create an account</Link>
          <span className="muted">·</span>
          <Link to="/register">Forgot password?</Link>
        </div>
      </div>
    </div>
  )
}

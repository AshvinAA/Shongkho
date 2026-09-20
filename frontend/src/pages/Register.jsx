import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import * as authApi from '../api/auth.js'

const initialForm = {
  name: '',
  phone_number: '',
  password: '',
  confirm: '',
  role: 'employee',
  employer_id: '',
  position: '',
  salary: '',
}

/** Registration page for owners (first store bootstrap) and employees. */
export default function Register() {
  const navigate = useNavigate()
  const [form, setForm] = useState(initialForm)
  const [errors, setErrors] = useState({})
  const [apiError, setApiError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  function handleChange(e) {
    const { name, value } = e.target
    setForm((f) => ({ ...f, [name]: value }))
    setErrors((prev) => ({ ...prev, [name]: undefined }))
    setApiError(null)
  }

  function validate() {
    const next = {}
    if (!form.name.trim()) next.name = 'Name is required.'
    if (!/^\d{10,15}$/.test(form.phone_number.trim())) {
      next.phone_number = 'Enter a valid phone number (10–15 digits).'
    }
    if (form.password.length < 4) next.password = 'Password must be at least 4 characters.'
    if (form.confirm !== form.password) next.confirm = 'Passwords do not match.'
    if (form.role === 'employee') {
      const id = Number(form.employer_id)
      if (!form.employer_id || Number.isNaN(id) || id <= 0) {
        next.employer_id = 'Employees need their store owner’s user ID.'
      }
    }
    setErrors(next)
    return Object.keys(next).length === 0
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (submitting || !validate()) return

    setSubmitting(true)
    setApiError(null)
    try {
      const payload = {
        name: form.name.trim(),
        phone_number: form.phone_number.trim(),
        password: form.password,
        role: form.role,
      }
      if (form.role === 'employee') {
        payload.employer_id = Number(form.employer_id)
        if (form.position.trim()) payload.position = form.position.trim()
        if (form.salary) payload.salary = Number(form.salary)
      }
      await authApi.register(payload)
      // Straight to login with the fresh phone number prefilled
      navigate('/login', { replace: true, state: { registeredPhone: payload.phone_number } })
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
          <h1>Create Account</h1>
          <p className="muted">
            Owners bootstrap the store; employees join with their owner’s ID.
          </p>
        </div>

        {apiError && (
          <div className="alert alert-error" role="alert">
            {apiError}
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate>
          <div className="form-group">
            <label className="form-label" htmlFor="reg-name">Full Name</label>
            <input
              id="reg-name"
              name="name"
              type="text"
              className={`form-control ${errors.name ? 'is-invalid' : ''}`}
              value={form.name}
              onChange={handleChange}
              autoComplete="name"
            />
            {errors.name && <div className="form-error">{errors.name}</div>}
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="reg-phone">Phone Number</label>
            <input
              id="reg-phone"
              name="phone_number"
              type="tel"
              className={`form-control ${errors.phone_number ? 'is-invalid' : ''}`}
              placeholder="017XXXXXXXX"
              value={form.phone_number}
              onChange={handleChange}
              autoComplete="tel"
            />
            {errors.phone_number && <div className="form-error">{errors.phone_number}</div>}
          </div>

          <div className="form-row">
            <div className="form-group">
              <label className="form-label" htmlFor="reg-password">Password</label>
              <input
                id="reg-password"
                name="password"
                type="password"
                className={`form-control ${errors.password ? 'is-invalid' : ''}`}
                value={form.password}
                onChange={handleChange}
                autoComplete="new-password"
              />
              {errors.password && <div className="form-error">{errors.password}</div>}
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="reg-confirm">Confirm Password</label>
              <input
                id="reg-confirm"
                name="confirm"
                type="password"
                className={`form-control ${errors.confirm ? 'is-invalid' : ''}`}
                value={form.confirm}
                onChange={handleChange}
                autoComplete="new-password"
              />
              {errors.confirm && <div className="form-error">{errors.confirm}</div>}
            </div>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="reg-role">Account Type</label>
            <select
              id="reg-role"
              name="role"
              className="form-control"
              value={form.role}
              onChange={handleChange}
            >
              <option value="employee">Employee — I work at an existing store</option>
              <option value="owner">Owner — I am setting up my own store</option>
            </select>
          </div>

          {form.role === 'employee' && (
            <>
              <div className="form-group">
                <label className="form-label" htmlFor="reg-employer">Owner’s User ID</label>
                <input
                  id="reg-employer"
                  name="employer_id"
                  type="number"
                  min="1"
                  className={`form-control ${errors.employer_id ? 'is-invalid' : ''}`}
                  placeholder="Ask your store owner for their ID"
                  value={form.employer_id}
                  onChange={handleChange}
                />
                {errors.employer_id && <div className="form-error">{errors.employer_id}</div>}
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label className="form-label" htmlFor="reg-position">Position (optional)</label>
                  <input
                    id="reg-position"
                    name="position"
                    type="text"
                    className="form-control"
                    placeholder="e.g. Cashier"
                    value={form.position}
                    onChange={handleChange}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="reg-salary">Salary ৳ (optional)</label>
                  <input
                    id="reg-salary"
                    name="salary"
                    type="number"
                    min="0"
                    step="0.01"
                    className="form-control"
                    value={form.salary}
                    onChange={handleChange}
                  />
                </div>
              </div>
            </>
          )}

          <button type="submit" className="btn btn-block" disabled={submitting}>
            {submitting ? 'Creating account…' : 'Create Account'}
          </button>
        </form>

        <div className="auth-links">
          <Link to="/login">Already have an account? Sign in</Link>
        </div>

        <details className="forgot-password">
          <summary>Forgot your password?</summary>
          <ForgotPassword />
        </details>
      </div>
    </div>
  )
}

/** Inline two-step reset: verify account, then set a new password. */
function ForgotPassword() {
  const [phone, setPhone] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [stage, setStage] = useState('verify') // 'verify' | 'confirm' | 'done'
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function handleVerify(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const res = await authApi.forgotPassword(phone.trim())
      setMessage(res.detail)
      setStage('confirm')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function handleConfirm(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await authApi.resetPassword(phone.trim(), newPassword)
      setStage('done')
      setMessage('Password reset successful. You can now log in.')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (stage === 'done') {
    return (
      <p className="alert alert-success" style={{ marginTop: '0.75rem' }}>
        {message} <Link to="/login">Go to login</Link>
      </p>
    )
  }

  return (
    <div className="forgot-password-body">
      {stage === 'verify' ? (
        <form onSubmit={handleVerify}>
          <div className="form-group">
            <label className="form-label" htmlFor="fp-phone">Phone Number</label>
            <input
              id="fp-phone"
              type="tel"
              className="form-control"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="017XXXXXXXX"
            />
          </div>
          <button type="submit" className="btn btn-outline btn-block" disabled={busy}>
            {busy ? 'Checking…' : 'Verify account'}
          </button>
        </form>
      ) : (
        <form onSubmit={handleConfirm}>
          {message && <p className="muted">{message}</p>}
          <div className="form-group">
            <label className="form-label" htmlFor="fp-new">New Password</label>
            <input
              id="fp-new"
              type="password"
              className="form-control"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
            />
          </div>
          <button type="submit" className="btn btn-outline btn-block" disabled={busy}>
            {busy ? 'Saving…' : 'Set new password'}
          </button>
        </form>
      )}
      {error && (
        <div className="form-error" role="alert" style={{ marginTop: '0.5rem' }}>
          {error}
        </div>
      )}
    </div>
  )
}

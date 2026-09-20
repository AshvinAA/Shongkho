import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

/**
 * Blocks unauthenticated access. While the session is being hydrated a
 * spinner is shown; after that anonymous users are sent to /login with
 * the original location preserved in state so login can send them back.
 */
export default function ProtectedRoute({ children }) {
  const { isAuthenticated, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div className="page-loading" role="status" aria-label="Loading">
        <div className="spinner" />
        <p className="muted">Loading…</p>
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return children
}

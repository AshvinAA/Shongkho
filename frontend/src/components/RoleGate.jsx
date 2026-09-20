import { useAuth } from '../context/AuthContext.jsx'

/**
 * Conditionally renders children only for the allowed roles.
 *
 *   <RoleGate allowedRoles={['owner']}>…</RoleGate>
 *   <RoleGate allowedRoles={['owner']} fallback={<p>Denied</p>}>…</RoleGate>
 *
 * `fallback` (optional) renders instead of the children when the role
 * doesn't match. When omitted, nothing renders.
 */
export function RoleGate({ allowedRoles, children, fallback = null }) {
  const { user } = useAuth()

  if (!user || !allowedRoles?.includes(user.role)) {
    return fallback
  }
  return children
}

export default RoleGate

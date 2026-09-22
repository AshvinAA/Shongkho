import { Link, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import RoleGate from './RoleGate.jsx'
import Avatar from './Avatar.jsx'

const LINKS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/pos', label: 'POS' },
  { to: '/inventory', label: 'Inventory' },
  { to: '/sales', label: 'Sales' },
  { to: '/customers', label: 'Customers' },
  { to: '/chat', label: '💬 Chat' },
]

/** Top navigation bar with role-aware links, avatar and logout. */
export default function Navbar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <header className="navbar">
      <Link to="/" className="navbar-brand">
        🏪 Shongkho
      </Link>

      <nav className="navbar-links">
        {LINKS.map((link) => (
          <NavLink key={link.to} to={link.to} end={link.end} className={({ isActive }) => (isActive ? 'active' : '')}>
            {link.label}
          </NavLink>
        ))}
        <RoleGate allowedRoles={['owner']}>
          <NavLink to="/staff" className={({ isActive }) => (isActive ? 'active' : '')}>
            Staff
          </NavLink>
          <NavLink to="/analytics" className={({ isActive }) => (isActive ? 'active' : '')}>
            Analytics
          </NavLink>
        </RoleGate>
      </nav>

      <div className="navbar-user">
        <Link to="/profile" className="navbar-avatar-link" title="My Profile">
          <Avatar user={{ name: user?.name, photo: user?.photo }} size="sm" />
          <span className="navbar-user-name">
            {user?.name} · <span className={`role-badge role-${user?.role}`}>{user?.role}</span>
          </span>
        </Link>
        <button type="button" className="btn btn-outline btn-sm" onClick={handleLogout}>
          Logout
        </button>
      </div>
    </header>
  )
}

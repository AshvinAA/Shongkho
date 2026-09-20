import { Outlet } from 'react-router-dom'
import Navbar from './components/Navbar.jsx'
import { useAuth } from './context/AuthContext.jsx'
import { RoleGate } from './components/RoleGate.jsx'

/**
 * App shell for all authenticated pages. ProtectedRoute in main.jsx ensures
 * `user` is hydrated before this renders, so Navbar can rely on it.
 */
export default function App() {
  const { user } = useAuth()

  return (
    <div className="app-shell">
      <Navbar user={user} />
      <main className="app-main">
        <Outlet />
      </main>
      <footer className="app-footer muted">
        Shongkho POS · signed in as <strong>{user?.name}</strong> ({user?.role})
      </footer>
    </div>
  )
}

// Re-export so route definitions in main.jsx can import both from one place.
export { RoleGate }

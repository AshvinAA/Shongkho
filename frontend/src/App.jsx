import AppShell from './components/shell/AppShell.jsx'
import { RoleGate } from './components/RoleGate.jsx'

/**
 * App shell for all authenticated pages. ProtectedRoute in main.jsx ensures
 * `user` is hydrated before this renders, so the shell can rely on it.
 * Layout lives in components/shell/AppShell.jsx (sidebar + topbar + Outlet).
 */
export default function App() {
  return <AppShell />
}

// Re-export so route definitions in main.jsx can import both from one place.
export { RoleGate }

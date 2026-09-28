import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext.jsx'
import Sidebar from './Sidebar.jsx'
import Topbar from './Topbar.jsx'

/**
 * App shell — one layout for every authenticated screen:
 * fixed collapsible sidebar + top bar + max-width content area.
 * State: sidebar collapse (persisted) and mobile drawer (auto-closes on nav).
 */
export default function AppShell() {
  const { user } = useAuth()
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem('shongkho.sidebarCollapsed') === '1'
    } catch {
      return false
    }
  })
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()

  useEffect(() => {
    try {
      localStorage.setItem('shongkho.sidebarCollapsed', collapsed ? '1' : '0')
    } catch {
      /* private mode — non-fatal */
    }
  }, [collapsed])

  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  return (
    <div className={`shell${collapsed ? ' shell-collapsed' : ''}`}>
      <Sidebar
        role={user?.role}
        collapsed={collapsed}
        onToggleCollapsed={() => setCollapsed((c) => !c)}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
      />
      <div className="shell-main">
        <Topbar onOpenMobileNav={() => setMobileOpen(true)} />
        <main className="shell-content" id="main-content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

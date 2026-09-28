import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { LogOut, Menu, UserRound } from 'lucide-react'
import { useAuth } from '../../context/AuthContext.jsx'
import Avatar from '../Avatar.jsx'
import { Badge } from '../ui/index.jsx'

/**
 * Top bar: mobile menu trigger, page title, and the user menu
 * (avatar, name, role badge, profile link, logout).
 */
export default function Topbar({ onOpenMobileNav }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)

  useEffect(() => {
    if (!menuOpen) return undefined
    function onDocClick(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false)
    }
    function onKey(e) {
      if (e.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  async function handleLogout() {
    setMenuOpen(false)
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <header className="shell-topbar">
      <button type="button" className="shell-menu-btn" aria-label="Open menu" onClick={onOpenMobileNav}>
        <Menu size={20} />
      </button>
      <p className="shell-store-name">Shongkho POS</p>

      <div className="shell-user" ref={menuRef}>
        <button type="button" className="shell-user-btn" aria-haspopup="menu" aria-expanded={menuOpen} onClick={() => setMenuOpen((o) => !o)}>
          <Avatar user={{ name: user?.name, photo: user?.photo }} size="sm" />
          <span className="shell-user-name">{user?.name}</span>
          {user?.role ? <Badge variant={user.role === 'owner' ? 'brand' : 'neutral'}>{user.role}</Badge> : null}
        </button>

        {menuOpen ? (
          <div className="shell-user-menu" role="menu">
            <div className="shell-user-menu-head">
              <Avatar user={{ name: user?.name, photo: user?.photo }} size="md" />
              <div>
                <p className="shell-user-menu-name">{user?.name}</p>
                <p className="shell-user-menu-mail">
                  <UserRound size={12} aria-hidden="true" /> {user?.username || user?.user_id}
                </p>
              </div>
            </div>
            <button
              type="button"
              role="menuitem"
              className="shell-user-menu-item"
              onClick={() => {
                setMenuOpen(false)
                navigate('/profile')
              }}
            >
              <UserRound size={15} aria-hidden="true" /> My profile
            </button>
            <button type="button" role="menuitem" className="shell-user-menu-item shell-user-menu-danger" onClick={handleLogout}>
              <LogOut size={15} aria-hidden="true" /> Log out
            </button>
          </div>
        ) : null}
      </div>
    </header>
  )
}

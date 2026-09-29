import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  ScanBarcode,
  Package,
  Receipt,
  Users,
  MessageCircle,
  UserCog,
  ChartColumn,
  PanelLeftClose,
  PanelLeftOpen,
  X,
} from 'lucide-react'
import Logo from '../Logo.jsx'
import ProtikMark from '../assistant/ProtikMark.jsx'

/**
 * Left sidebar — role-based navigation, collapsible to icon rail, active
 * route highlighted. On <900px it becomes a fixed overlay drawer.
 */
const OWNER_SECTIONS = [
  {
    items: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
      { to: '/pos', label: 'POS', icon: ScanBarcode },
    ],
  },
  {
    heading: 'Manage',
    items: [
      { to: '/inventory', label: 'Inventory', icon: Package },
      { to: '/sales', label: 'Sales', icon: Receipt },
      { to: '/customers', label: 'Customers', icon: Users },
      { to: '/staff', label: 'Staff', icon: UserCog },
      { to: '/chat', label: 'Chat', icon: MessageCircle },
    ],
  },
  {
    heading: 'Insights',
    items: [
      { to: '/analytics', label: 'Analytics', icon: ChartColumn },
      { to: '/protik', label: 'Protik প্রতীক', icon: ProtikMark },
    ],
  },
]

const EMPLOYEE_SECTIONS = [
  {
    items: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
      { to: '/pos', label: 'POS', icon: ScanBarcode },
      { to: '/inventory', label: 'Inventory', icon: Package },
      { to: '/sales', label: 'Sales', icon: Receipt },
      { to: '/customers', label: 'Customers', icon: Users },
      { to: '/chat', label: 'Chat', icon: MessageCircle },
    ],
  },
]

export default function Sidebar({ role, collapsed, onToggleCollapsed, mobileOpen, onCloseMobile }) {
  const sections = role === 'owner' ? OWNER_SECTIONS : EMPLOYEE_SECTIONS

  return (
    <>
      {mobileOpen ? <div className="shell-scrim" onClick={onCloseMobile} aria-hidden="true" /> : null}
      <aside className={`shell-sidebar${collapsed ? ' shell-sidebar-collapsed' : ''}${mobileOpen ? ' shell-sidebar-open' : ''}`}>
        <div className="shell-sidebar-brand">
          <Logo size={26} />
          <span className="shell-sidebar-brand-name">Shongkho</span>
          <button
            type="button"
            className="shell-sidebar-toggle shell-sidebar-toggle-desktop"
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!collapsed}
            onClick={onToggleCollapsed}
          >
            {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
          <button type="button" className="shell-sidebar-toggle shell-sidebar-toggle-mobile" aria-label="Close menu" onClick={onCloseMobile}>
            <X size={16} />
          </button>
        </div>

        <nav className="shell-sidebar-nav" aria-label="Main">
          {sections.map((section, i) => (
            <div key={section.heading || i} className="shell-nav-section">
              {section.heading ? <p className="shell-nav-heading">{section.heading}</p> : null}
              {section.items.map((item) => {
                const Icon = item.icon
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) => `shell-nav-link${isActive ? ' shell-nav-active' : ''}`}
                    onClick={onCloseMobile}
                  >
                    <Icon size={18} aria-hidden={item.icon === ProtikMark ? undefined : "true"} />
                    <span className="shell-nav-label">{item.label}</span>
                  </NavLink>
                )
              })}
            </div>
          ))}
        </nav>

        <div className="shell-sidebar-foot">
          <span className="shell-nav-label">v1.0</span>
        </div>
      </aside>
    </>
  )
}

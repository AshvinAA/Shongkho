/**
 * Sidebar navigation regression tests.
 *
 * Guards against nav items silently disappearing during redesigns.
 * Real bug this pins: the UI redesign dropped Chat from the OWNER nav
 * (it stayed on employees only), so the group chat looked "gone" the
 * moment you logged in as the owner. Route + page still existed.
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Sidebar from '../components/shell/Sidebar.jsx'

function renderSidebar(role) {
  return render(
    <MemoryRouter>
      <Sidebar
        role={role}
        collapsed={false}
        onToggleCollapsed={() => {}}
        mobileOpen={false}
        onCloseMobile={() => {}}
      />
    </MemoryRouter>,
  )
}

describe('Sidebar navigation', () => {
  it('shows Chat to the OWNER (regression: redesign dropped it)', () => {
    renderSidebar('owner')
    const link = screen.getByText('Chat').closest('a')
    expect(link).not.toBeNull()
    expect(link).toHaveAttribute('href', '/chat')
  })

  it('shows Chat to employees', () => {
    renderSidebar('employee')
    const link = screen.getByText('Chat').closest('a')
    expect(link).toHaveAttribute('href', '/chat')
  })

  it('owner sees every section including owner-only pages', () => {
    renderSidebar('owner')
    for (const label of ['Dashboard', 'POS', 'Inventory', 'Sales', 'Customers', 'Staff']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(screen.getByText(/Protik/)).toBeInTheDocument()
    expect(screen.getByText('Analytics')).toBeInTheDocument()
  })

  it('employee does NOT see owner-only items (Staff, Analytics, Protik)', () => {
    renderSidebar('employee')
    expect(screen.queryByText('Staff')).not.toBeInTheDocument()
    expect(screen.queryByText('Analytics')).not.toBeInTheDocument()
    expect(screen.queryByText(/Protik/)).not.toBeInTheDocument()
    // Shared pages stay.
    expect(screen.getByText('Inventory')).toBeInTheDocument()
    expect(screen.getByText('Chat')).toBeInTheDocument()
  })
})

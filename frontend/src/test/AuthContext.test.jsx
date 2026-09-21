/**
 * AuthContext + RoleGate tests.
 *
 * Strategy: mock the API layer (src/api/auth.js) so tests stay focused on
 * CONTEXT LOGIC (hydration, error handling, role gating) instead of the
 * network. The backend side of these flows is covered by the pytest suite.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, renderHook, act } from '@testing-library/react'
import { AuthProvider, useAuth } from '../context/AuthContext.jsx'
import { RoleGate } from '../components/RoleGate.jsx'

// Mock the auth API module — AuthContext's only external dependency.
vi.mock('../api/auth.js', () => ({
  fetchMe: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  register: vi.fn(),
  registerEmployee: vi.fn(),
  registerOwner: vi.fn(),
  forgotPassword: vi.fn(),
  resetPassword: vi.fn(),
}))

import * as authApi from '../api/auth.js'

// ---------------------------------------------------------
// Test harness: a probe component exposing the context values as text
// ---------------------------------------------------------
function AuthProbe() {
  const { user, loading, isAuthenticated } = useAuth()
  if (loading) return <div data-testid="state">loading</div>
  return (
    <div data-testid="state">
      {isAuthenticated ? `authed:${user.role}:${user.name}` : 'anonymous'}
    </div>
  )
}

function renderWithProvider() {
  return render(
    <AuthProvider>
      <AuthProbe />
    </AuthProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------
// HYDRATION FROM /auth/me
// ---------------------------------------------------------
describe('AuthContext hydration', () => {
  it('starts in the loading state', () => {
    authApi.fetchMe.mockReturnValue(new Promise(() => {})) // never resolves
    const { getByTestId } = renderWithProvider()
    expect(getByTestId('state')).toHaveTextContent('loading')
  })

  it('hydrates an authenticated user from /auth/me', async () => {
    authApi.fetchMe.mockResolvedValue({
      user_id: 1, role: 'owner', name: 'The Owner', photo: null,
    })
    const { getByTestId } = renderWithProvider()
    await waitFor(() => {
      expect(getByTestId('state')).toHaveTextContent('authed:owner:The Owner')
    })
  })

  it('treats a 401 from /auth/me as anonymous', async () => {
    authApi.fetchMe.mockRejectedValue(new Error('Not logged in'))
    const { getByTestId } = renderWithProvider()
    await waitFor(() => {
      expect(getByTestId('state')).toHaveTextContent('anonymous')
    })
  })

  it('treats a network failure as anonymous (not a crash)', async () => {
    authApi.fetchMe.mockRejectedValue(new TypeError('Failed to fetch'))
    const { getByTestId } = renderWithProvider()
    await waitFor(() => {
      expect(getByTestId('state')).toHaveTextContent('anonymous')
    })
  })

  it('login() stores the returned user', async () => {
    authApi.fetchMe.mockRejectedValue(new Error('Not logged in'))
    authApi.login.mockResolvedValue({ user_id: 2, role: 'employee', name: 'Staff' })

    const { result } = renderHook(() => useAuth(), {
      wrapper: AuthProvider,
    })
    await waitFor(() => expect(result.current.loading).toBe(false))

    await act(() => result.current.login({
      phone_number: '01700000002', password: 'secret123',
    }))
    expect(result.current.isAuthenticated).toBe(true)
    expect(result.current.user.role).toBe('employee')
  })

  it('logout() clears the user even if the API call fails', async () => {
    authApi.fetchMe.mockResolvedValue({ user_id: 1, role: 'owner', name: 'O' })
    authApi.logout.mockRejectedValue(new Error('network down'))

    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider })
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true))

    await act(() => result.current.logout())
    expect(result.current.isAuthenticated).toBe(false)
    expect(result.current.user).toBeNull()
  })
})

// ---------------------------------------------------------
// ROLE GATES
// ---------------------------------------------------------
describe('RoleGate', () => {
  /**
   * Harness: render RoleGate with a user injected through a mocked
   * useAuth — RoleGate reads the context, so we wrap in AuthProvider
   * and drive the user through fetchMe/login mocks.
   */
  async function renderGateWithUser(role) {
    if (role) {
      authApi.fetchMe.mockResolvedValue({ user_id: 9, role, name: 'Tester' })
    } else {
      authApi.fetchMe.mockRejectedValue(new Error('Not logged in'))
    }
    return render(
      <AuthProvider>
        <RoleGate allowedRoles={['owner']}>
          <button>Owner-only button</button>
        </RoleGate>
        <RoleGate allowedRoles={['owner']} fallback={<p>Denied</p>}>
          <p>Secret owner panel</p>
        </RoleGate>
        <RoleGate allowedRoles={['owner', 'employee']}>
          <p>Shared area</p>
        </RoleGate>
      </AuthProvider>,
    )
  }

  it('shows owner-only content to owners', async () => {
    await renderGateWithUser('owner')
    expect(await screen.findByText('Owner-only button')).toBeInTheDocument()
    expect(screen.getByText('Secret owner panel')).toBeInTheDocument()
    expect(screen.getByText('Shared area')).toBeInTheDocument()
  })

  it('hides owner-only content from employees — no fallback leak', async () => {
    await renderGateWithUser('employee')
    await waitFor(() => expect(screen.getByText('Denied')).toBeInTheDocument())
    expect(screen.queryByText('Owner-only button')).not.toBeInTheDocument()
    expect(screen.queryByText('Secret owner panel')).not.toBeInTheDocument()
    // The shared gate (owner + employee) renders for employees.
    expect(screen.getByText('Shared area')).toBeInTheDocument()
  })

  it('renders the fallback for employees', async () => {
    await renderGateWithUser('employee')
    expect(await screen.findByText('Denied')).toBeInTheDocument()
  })

  it('hides everything gated from anonymous visitors', async () => {
    await renderGateWithUser(null)
    // Anonymous users see none of the three gated blocks (the third
    // gate allows owner+employee only — still not anonymous).
    await waitFor(() => {
      expect(screen.queryByText('Shared area')).not.toBeInTheDocument()
    })
    expect(screen.queryByText('Owner-only button')).not.toBeInTheDocument()
    expect(screen.queryByText('Secret owner panel')).not.toBeInTheDocument()
  })
})

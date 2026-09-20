import { createContext, useContext, useEffect, useState, useCallback, useMemo } from 'react'
import * as authApi from '../api/auth.js'

const AuthContext = createContext(null)

/**
 * Auth state for the whole SPA.
 *
 * `user` is null | { user_id, name, role, photo } — hydrated from the server
 * session via /auth/me on first mount (no tokens in localStorage).
 * `loading` is true until that first check resolves.
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    async function hydrate() {
      try {
        const me = await authApi.fetchMe()
        if (!cancelled) setUser(me)
      } catch {
        // 401 or network error — treat as anonymous
        if (!cancelled) setUser(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    hydrate()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (credentials) => {
    const data = await authApi.login(credentials)
    // Backend returns { user_id, role, name }
    setUser(data)
    return data
  }, [])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } finally {
      setUser(null)
    }
  }, [])

  /** Re-hydrate the user from the server session (e.g. after a profile rename). */
  const refreshUser = useCallback(async () => {
    try {
      const me = await authApi.fetchMe()
      setUser(me)
    } catch {
      // Session ended server-side — drop the stale user
      setUser(null)
    }
  }, [])

  const value = useMemo(
    () => ({
      user,
      loading,
      isAuthenticated: !!user,
      login,
      logout,
      refreshUser,
    }),
    [user, loading, login, logout, refreshUser],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used inside <AuthProvider>')
  }
  return ctx
}

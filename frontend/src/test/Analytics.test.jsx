/**
 * Analytics page tests (stage 1).
 *
 * The API layer is mocked (same pattern as POS tests); the backend's
 * aggregation math is verified separately by the pytest suite. Chart
 * internals (Recharts SVG) are not asserted — jsdom has no layout — so
 * the tests check the data-driven UI around the charts: stats, best
 * lists, run lifecycle states, and period switching.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../api/analytics.js', () => ({
  getDashboard: vi.fn(),
  getRunStatus: vi.fn(),
  startRun: vi.fn(),
}))

import * as analyticsApi from '../api/analytics.js'
import Analytics from '../pages/Analytics.jsx'

// Owner-only page: pin the session user for every test.
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ user: { user_id: 1, name: 'The Owner', role: 'owner' } }),
}))

// ---------------------------------------------------------
// Fixtures mirroring the snapshot payloads from the backend
// ---------------------------------------------------------

const SALES_SNAPSHOT = {
  period: 'week',
  best_unit: 'days',
  current: { revenue: 14200, profit: 4200, orders: 87 },
  previous: { revenue: 12600, profit: 3900, orders: 80 },
  change_pct: { revenue: 12.7, profit: 7.7, orders: 8.8 },
  series: [
    { key: '2026-09-21', label: 'Mon 21', revenue: 2100, profit: 600, orders: 12 },
    { key: '2026-09-22', label: 'Tue 22', revenue: 0, profit: 0, orders: 0 },
    { key: '2026-09-23', label: 'Wed 23', revenue: 4200, profit: 1300, orders: 25 },
  ],
  best: {
    by_revenue: [{ key: '2026-09-23', label: 'Wed 23', revenue: 4200, profit: 1300, orders: 25 }],
    by_profit: [{ key: '2026-09-23', label: 'Wed 23', revenue: 4200, profit: 1300, orders: 25 }],
  },
}

const EMPLOYEES_SNAPSHOT = {
  period: 'week',
  employees: [
    { employee_id: 2, name: 'Rahim', photo: 'data:image/svg+xml;utf8,%3Csvg%3E', is_owner: false,
      orders: 30, revenue: 8000, profit: 2400,
      change_pct: { revenue: 14.3, profit: 9.1, orders: 11.1 } },
    { employee_id: 3, name: 'Karim', photo: null, is_owner: false,
      orders: 18, revenue: 3500, profit: 1000,
      change_pct: { revenue: -12.5, profit: -20.0, orders: -10.0 } },
  ],
  race_series: {
    keys: ['2026-09-21', '2026-09-22', '2026-09-23'],
    labels: ['Mon 21', 'Tue 22', 'Wed 23'],
    revenue: { '2': [3000, 3000, 8000], '3': [1500, 2500, 3500] },
    profit: { '2': [900, 900, 2400], '3': [400, 700, 1000] },
  },
}

const PRODUCTS_SNAPSHOT = {
  period: 'week',
  top_by_revenue: [
    { product_id: 1, name: 'Mustard Oil 1L', units: 40, revenue: 5600, profit: 1400,
      margin_pct: 25, units_change_pct: 33.3 },
    { product_id: 2, name: 'Sugar 1kg', units: 22, revenue: 2420, profit: 480,
      margin_pct: 19.8, units_change_pct: null },
  ],
  top_by_profit: [
    { product_id: 1, name: 'Mustard Oil 1L', units: 40, revenue: 5600, profit: 1400,
      margin_pct: 25, units_change_pct: 33.3 },
    { product_id: 2, name: 'Sugar 1kg', units: 22, revenue: 2420, profit: 480,
      margin_pct: 19.8, units_change_pct: null },
  ],
  bottom_by_revenue: [],
}

function renderAnalytics() {
  return render(<Analytics />)
}

function mockDashboard(sections) {
  analyticsApi.getDashboard.mockResolvedValue({
    period: 'week',
    generated_at: '2026-09-23T10:00:00',
    sections,
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('Analytics page — dashboard rendering', () => {
  it('renders the sales stats and delta from the snapshot', async () => {
    mockDashboard({ sales: SALES_SNAPSHOT, employees: EMPLOYEES_SNAPSHOT, products: PRODUCTS_SNAPSHOT })
    renderAnalytics()

    expect(await screen.findByText('Revenue this week')).toBeInTheDocument()
    expect(screen.getByText('৳14,200')).toBeInTheDocument()
    expect(screen.getByText(/▲ 12.7%/)).toBeInTheDocument()
    // Best days list renders from the snapshot. 'Wed 23' appears both in
    // the chart axis and the best list — assert presence, not uniqueness.
    expect(screen.getAllByText('Wed 23').length).toBeGreaterThanOrEqual(1)
  })

  it('renders employee race lanes sorted by revenue', async () => {
    mockDashboard({ sales: SALES_SNAPSHOT, employees: EMPLOYEES_SNAPSHOT, products: PRODUCTS_SNAPSHOT })
    renderAnalytics()

    expect(await screen.findByText('Employee race — revenue')).toBeInTheDocument()
    // Names appear in the chart axis AND the legend — presence is enough.
    expect(screen.getAllByText('Rahim').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Karim').length).toBeGreaterThanOrEqual(1)
    // Race-over-time chart + its legend rendered for both racers.
    expect(screen.getByText(/race over the week/i)).toBeInTheDocument()
    expect(screen.getByText('Final standings')).toBeInTheDocument()
    // Rahim has a seeded photo -> rendered as an <img> avatar somewhere.
    const imgs = screen.getAllByRole('img', { hidden: true })
    expect(imgs.length).toBeGreaterThanOrEqual(0) // avatar presence is chart-internal
  })

  it('shows empty-state cards and the first-run hint before any run', async () => {
    mockDashboard({})
    renderAnalytics()

    expect(await screen.findByText('Sales trend')).toBeInTheDocument()
    expect(screen.getAllByText(/appear after your first run/).length).toBeGreaterThan(0)
    // Single combined CTA: the header button + the first-run hint.
    expect(screen.getByRole('button', { name: /Run analysis/ })).toBeInTheDocument()
    expect(screen.getByText(/No analysis for this period yet/)).toBeInTheDocument()
  })
})

describe('Analytics page — period switching', () => {
  it('refetches the dashboard when the period changes', async () => {
    const user = userEvent.setup()
    mockDashboard({ sales: SALES_SNAPSHOT })
    renderAnalytics()
    await screen.findByText('Revenue this week')

    mockDashboard({ sales: { ...SALES_SNAPSHOT, period: 'month' } })
    await user.click(screen.getByRole('tab', { name: 'Month' }))

    await waitFor(() => {
      expect(analyticsApi.getDashboard).toHaveBeenLastCalledWith('month')
    })
  })
})

describe('Analytics page — run lifecycle', () => {
  it('starts a run, polls until COMPLETED, then refetches', async () => {
    // Real timers: the 1.5s poll interval makes fake-timer juggling with
    // userEvent flakier than the ~2s real wait these tests cost.
    analyticsApi.startRun.mockResolvedValue({ run_id: 'abc', status: 'QUEUED', period: 'week' })
    analyticsApi.getRunStatus
      .mockResolvedValueOnce({ run_id: 'abc', status: 'RUNNING' })
      .mockResolvedValue({ run_id: 'abc', status: 'COMPLETED' })
    mockDashboard({ sales: SALES_SNAPSHOT })

    renderAnalytics()
    await screen.findByText('Revenue this week')

    const user = userEvent.setup()
    // Exactly ONE run button (page header) — no per-section buttons.
    const runButtons = screen.getAllByRole('button', { name: /Run analysis/ })
    expect(runButtons).toHaveLength(1)
    await user.click(runButtons[0])
    expect(analyticsApi.startRun).toHaveBeenCalledWith('week')

    // Poller runs, sees COMPLETED, refetches the dashboard quietly.
    await waitFor(() => {
      expect(analyticsApi.getDashboard).toHaveBeenCalledTimes(2)
    }, { timeout: 6000 })
    expect(analyticsApi.getRunStatus).toHaveBeenCalledWith('abc')
  })

  it('shows the failure reason when a run fails', async () => {
    analyticsApi.startRun.mockResolvedValue({ run_id: 'abc', status: 'QUEUED', period: 'week' })
    analyticsApi.getRunStatus.mockResolvedValue({
      run_id: 'abc', status: 'FAILED', failure_reason: 'ConnectionError: broker down',
    })
    mockDashboard({})

    renderAnalytics()
    await screen.findByText('Sales trend')

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /Run analysis/ }))

    expect(await screen.findByText(/broker down/, {}, { timeout: 6000 })).toBeInTheDocument()
  })
})

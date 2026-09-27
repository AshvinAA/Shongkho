/**
 * Protik page tests — the language switch (docs/PROTIK_BANGLA_PLAN.md §5).
 *
 * API layers are mocked (same pattern as the Analytics tests). The
 * switch must: render three modes, refetch the dashboard with the
 * chosen language, persist the owner's choice, and pass the mode down
 * to the chat panel.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../api/analytics.js', () => ({
  getDashboard: vi.fn(),
  getRunStatus: vi.fn(),
  startRun: vi.fn(),
}))
vi.mock('../api/auth.js', () => ({
  updateMyPreferences: vi.fn(),
}))
vi.mock('../api/assistant.js', () => ({
  sendChat: vi.fn(),
  getChatHistory: vi.fn(),
}))

import * as analyticsApi from '../api/analytics.js'
import * as authApi from '../api/auth.js'
import * as assistantApi from '../api/assistant.js'
import Protik from '../pages/Protik.jsx'

// Owner-only page; the switch seeds from the persisted preference.
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({
    user: { user_id: 1, name: 'The Owner', role: 'owner', assistant_language: 'auto' },
  }),
}))

function mockDashboard(sections = {}) {
  analyticsApi.getDashboard.mockResolvedValue({
    period: 'week',
    generated_at: '2026-09-27T10:00:00',
    sections,
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  mockDashboard({ insights: { summary: 'Steady week.', observations: [], areas_to_watch: [] } })
  assistantApi.getChatHistory.mockResolvedValue({ messages: [] })
})

describe('Protik language switch', () => {
  it('renders the three language modes with the persisted one active', async () => {
    render(<Protik />)
    const tablist = await screen.findByRole('tablist', { name: /protik language/i })
    expect(tablist).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Auto' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'বাংলা' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'EN' })).toBeInTheDocument()
  })

  it('refetches the dashboard with language=bn and persists the choice', async () => {
    const user = userEvent.setup()
    render(<Protik />)
    await screen.findByText('Steady week.')

    await user.click(screen.getByRole('tab', { name: 'বাংলা' }))

    await waitFor(() => {
      expect(analyticsApi.getDashboard).toHaveBeenLastCalledWith('week', 'bn')
    })
    await waitFor(() => {
      expect(authApi.updateMyPreferences).toHaveBeenCalledWith({ assistantLanguage: 'bn' })
    })
  })

  it('labels an English snapshot honestly when no Bangla cache exists', async () => {
    mockDashboard({
      insights: {
        summary: 'English summary.', observations: [], areas_to_watch: [],
        language: 'en', missing_language: 'bn',
      },
    })
    const user = userEvent.setup()
    render(<Protik />)
    await screen.findByText('English summary.')

    await user.click(screen.getByRole('tab', { name: 'বাংলা' }))
    expect(await screen.findByText('English summary.')).toBeInTheDocument()
    expect(await screen.findByText(/বাংলা সংস্করণ এখনো তৈরি হয়নি/)).toBeInTheDocument()
  })

  it('passes the forced mode to the chat panel', async () => {
    assistantApi.sendChat.mockResolvedValue({ message: 'ঠিক আছে', tool_calls: [], meta: {} })
    const user = userEvent.setup()
    render(<Protik />)
    await screen.findByText('Steady week.')

    await user.click(screen.getByRole('tab', { name: 'বাংলা' }))
    const input = await screen.findByLabelText(/message protik/i)
    await user.type(input, 'hello{Enter}')

    await waitFor(() => {
      expect(assistantApi.sendChat).toHaveBeenCalledWith('hello', 'bn')
    })
  })

  it('বাংলা mode relabels the whole panel chrome (plan §5 i18n)', async () => {
    const user = userEvent.setup()
    render(<Protik />)
    await screen.findByText('Steady week.')

    await user.click(screen.getByRole('tab', { name: 'বাংলা' }))

    // Empty-state prose, suggestion chips and placeholder follow the switch.
    expect(await screen.findByText(/দোকান নিয়ে জিজ্ঞেস করুন/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /এই সপ্তাহে কোন পণ্য/ })).toBeInTheDocument()
    expect(await screen.findByPlaceholderText(/বাংলায় বা ইংরেজিতে/)).toBeInTheDocument()
    // Period control relabels too.
    expect(screen.getByRole('tab', { name: 'সপ্তাহ' })).toBeInTheDocument()
  })
})

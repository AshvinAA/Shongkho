/**
 * Assistant panel tests (Part B, text-only).
 *
 * The API layer is mocked (same pattern as the Analytics page tests);
 * backend loop behavior is verified by the pytest suite. The tests
 * check the conversation flow: history reload, send/append, and the
 * honest 429/503 notes. No chart rendering exists anymore — the
 * assistant is a prose advisor.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../api/assistant.js', () => ({
  sendChat: vi.fn(),
  getChatHistory: vi.fn(),
}))

import * as assistantApi from '../api/assistant.js'
import AssistantPanel from '../components/assistant/AssistantPanel.jsx'

vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ user: { user_id: 1, name: 'The Owner', role: 'owner' } }),
}))

beforeEach(() => {
  vi.clearAllMocks()
  assistantApi.getChatHistory.mockResolvedValue({ messages: [] })
})

describe('AssistantPanel', () => {
  it('renders empty state with suggestions when no history', async () => {
    render(<AssistantPanel />)
    expect(await screen.findByText(/Ask me about your store/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /maximise profit this week/i })).toBeInTheDocument()
  })

  it('reloads persisted history on mount (roles + text only)', async () => {
    assistantApi.getChatHistory.mockResolvedValue({
      messages: [
        { role: 'user', message: 'How did today go?' },
        { role: 'assistant', message: 'Revenue was fine — steady day.' },
      ],
    })
    render(<AssistantPanel />)
    expect(await screen.findByText('How did today go?')).toBeInTheDocument()
    expect(screen.getByText('Revenue was fine — steady day.')).toBeInTheDocument()
    // Empty-state suggestions disappear once history exists.
    expect(screen.queryByText(/Ask me about your store/i)).not.toBeInTheDocument()
  })

  it('sends a turn and appends the assistant reply', async () => {
    assistantApi.sendChat.mockResolvedValue({
      message: 'Push Mustard Oil 1L — it earned 780.0 profit this week. Consider a bundle with rice.',
      tool_calls: [{ tool: 'get_top_products', args: {} }],
      meta: {},
    })
    render(<AssistantPanel />)
    const input = screen.getByLabelText(/message the analytics assistant/i)
    await userEvent.type(input, 'What should I push this week?{Enter}')
    await waitFor(() =>
      expect(screen.getByText(/Push Mustard Oil 1L/i)).toBeInTheDocument(),
    )
    expect(screen.getByText('What should I push this week?')).toBeInTheDocument()
  })

  it('shows the honest daily-cap note on 429', async () => {
    const err = new Error('cap')
    err.status = 429
    assistantApi.sendChat.mockRejectedValue(err)
    render(<AssistantPanel />)
    await userEvent.type(
      screen.getByLabelText(/message the analytics assistant/i),
      'hello{Enter}',
    )
    expect(await screen.findByText(/used all your assistant messages/i)).toBeInTheDocument()
  })

  it('shows the not-configured note on 503', async () => {
    const err = new Error('nope')
    err.status = 503
    assistantApi.sendChat.mockRejectedValue(err)
    render(<AssistantPanel />)
    await userEvent.type(
      screen.getByLabelText(/message the analytics assistant/i),
      'hello{Enter}',
    )
    expect(await screen.findByText(/assistant is not configured/i)).toBeInTheDocument()
  })

  it('does not send empty or whitespace-only input', async () => {
    render(<AssistantPanel />)
    await userEvent.type(
      screen.getByLabelText(/message the analytics assistant/i),
      '   {Enter}',
    )
    expect(assistantApi.sendChat).not.toHaveBeenCalled()
  })
})

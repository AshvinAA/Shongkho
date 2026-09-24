/**
 * Assistant panel tests (Part B).
 *
 * The API layer is mocked (same pattern as the Analytics page tests);
 * backend loop behavior is verified by the pytest suite. jsdom has no
 * layout, so chart internals are not asserted — the tests check the
 * conversation flow: history reload, send/append, ui_blocks rendering
 * hand-off, and the honest 429/503 notes.
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
    expect(await screen.findByText(/Ask me anything about your store/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /How did the shop do today\?/i })).toBeInTheDocument()
  })

  it('reloads persisted history on mount (roles + ui_blocks)', async () => {
    assistantApi.getChatHistory.mockResolvedValue({
      messages: [
        { role: 'user', message: 'How did today go?', ui_blocks: [] },
        { role: 'assistant', message: 'Revenue was fine.', ui_blocks: [] },
      ],
    })
    render(<AssistantPanel />)
    expect(await screen.findByText('How did today go?')).toBeInTheDocument()
    expect(screen.getByText('Revenue was fine.')).toBeInTheDocument()
    // Empty-state suggestions disappear once history exists.
    expect(screen.queryByText(/Ask me anything about your store/i)).not.toBeInTheDocument()
  })

  it('sends a turn and appends the envelope (message + ui_blocks)', async () => {
    assistantApi.sendChat.mockResolvedValue({
      message: 'Rahim is on fire today!',
      ui_blocks: [{ type: 'employee_leaderboard', source_tool: 'get_employee_performance', data: { employees: [] } }],
      tool_calls: [],
    })
    const { container } = render(<AssistantPanel />)
    const input = screen.getByLabelText(/message the analytics assistant/i)
    await userEvent.type(input, 'Who is selling the most today?{Enter}')
    await waitFor(() =>
      expect(screen.getByText('Rahim is on fire today!')).toBeInTheDocument(),
    )
    // The user turn echoed back, and the block renderer got the data.
    expect(screen.getByText('Who is selling the most today?')).toBeInTheDocument()
    expect(container.querySelector('.assistant-block')).toBeInTheDocument()
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

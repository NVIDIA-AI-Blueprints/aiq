// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { AgentPrompt } from './AgentPrompt'
import { useChatStore } from '../store'

// Mock MarkdownRenderer
vi.mock('@/shared/components/MarkdownRenderer', () => ({
  MarkdownRenderer: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}))

describe('AgentPrompt', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useChatStore.setState({ respondToInteractionFn: null })
  })

  test('renders prompt content', () => {
    render(
      <AgentPrompt
        id="prompt-1"
        type="clarification"
        content="What programming language would you prefer?"
      />
    )

    expect(screen.getByTestId('markdown')).toHaveTextContent(
      'What programming language would you prefer?'
    )
  })

  test('shows "Agent needs your input" when not responded', () => {
    render(
      <AgentPrompt
        id="prompt-1"
        type="clarification"
        content="Please provide more details"
        isResponded={false}
      />
    )

    expect(screen.getByText('Agent needs your input')).toBeInTheDocument()
  })

  test('shows "Agent received your input" when responded', () => {
    render(
      <AgentPrompt
        id="prompt-1"
        type="clarification"
        content="Please provide more details"
        isResponded={true}
        response="Here are the details"
      />
    )

    expect(screen.getByText('Agent received your input')).toBeInTheDocument()
  })

  test('displays options for choice prompts', () => {
    const options = ['Option A', 'Option B', 'Option C']

    render(<AgentPrompt id="prompt-1" type="choice" content="Choose one:" options={options} />)

    expect(screen.getByText('Option A')).toBeInTheDocument()
    expect(screen.getByText('Option B')).toBeInTheDocument()
    expect(screen.getByText('Option C')).toBeInTheDocument()
  })

  test('hides options when responded', () => {
    const options = ['Option A', 'Option B']

    render(
      <AgentPrompt
        id="prompt-1"
        type="choice"
        content="Choose one:"
        options={options}
        isResponded={true}
        response="Option A"
      />
    )

    // Options list should be hidden when responded
    expect(screen.queryByText('1.')).not.toBeInTheDocument()
  })

  test('displays user response when responded', () => {
    render(
      <AgentPrompt
        id="prompt-1"
        type="clarification"
        content="Question?"
        isResponded={true}
        response="My answer"
      />
    )

    expect(screen.getByText('My answer')).toBeInTheDocument()
  })

  test('displays timestamp when provided', () => {
    const timestamp = new Date('2024-01-15T10:30:00')

    render(
      <AgentPrompt id="prompt-1" type="clarification" content="Question?" timestamp={timestamp} />
    )

    expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
  })

  test('tabs through plan approval actions in DOM order', async () => {
    const user = userEvent.setup()
    useChatStore.setState({ respondToInteractionFn: vi.fn() })

    render(
      <AgentPrompt
        id="prompt-1"
        type="approval"
        content="Reply **approve** to proceed, **reject** to cancel"
      />
    )

    const approveButton = screen.getByRole('button', { name: /approve plan/i })
    const rejectButton = screen.getByRole('button', { name: /reject plan/i })

    expect(approveButton).not.toHaveAttribute('tabindex')
    expect(rejectButton).not.toHaveAttribute('tabindex')

    await user.tab()
    expect(approveButton).toHaveFocus()
    await user.tab()
    expect(rejectButton).toHaveFocus()
  })
})

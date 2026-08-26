// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { AgentPrompt } from './AgentPrompt'
import { useChatStore } from '../store'

vi.mock('@/shared/components/MarkdownRenderer', () => ({
  MarkdownRenderer: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}))

describe('AgentPrompt', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useChatStore.setState({ respondToInteractionFn: null, pendingInteraction: null })
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

  test('shows "Needs your input" when not responded', () => {
    render(
      <AgentPrompt
        id="prompt-1"
        type="clarification"
        content="Please provide more details"
        isResponded={false}
      />
    )

    expect(screen.getByText('Needs your input')).toBeInTheDocument()
  })

  test('shows "Input received" when responded', () => {
    render(
      <AgentPrompt
        id="prompt-1"
        type="clarification"
        content="Please provide more details"
        isResponded={true}
        response="Here are the details"
      />
    )

    expect(screen.getByText('Input received')).toBeInTheDocument()
  })

  test('renders a cancelled response as "Cancelled", not the raw sentinel', () => {
    render(
      <AgentPrompt
        id="prompt-1"
        type="clarification"
        content="Which revenue definition?"
        isResponded={true}
        response="__USER_CANCELLED__"
      />
    )

    expect(screen.getByText('Cancelled')).toBeInTheDocument()
    expect(screen.queryByText('__USER_CANCELLED__')).not.toBeInTheDocument()
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

    expect(screen.queryByText('1.')).not.toBeInTheDocument()
  })

  test('clicking a choice option responds to the agent immediately', async () => {
    const user = userEvent.setup()
    const respond = vi.fn()
    useChatStore.setState({ respondToInteractionFn: respond })

    render(
      <AgentPrompt
        id="prompt-1"
        type="choice"
        content="Choose one:"
        options={['Option A', 'Option B']}
      />
    )

    await user.click(screen.getByRole('button', { name: /choose: option a/i }))

    expect(respond).toHaveBeenCalledWith('Option A')
  })

  test('parses numbered choices from content into cards that respond with the number', async () => {
    const user = userEvent.setup()
    const respond = vi.fn()
    useChatStore.setState({ respondToInteractionFn: respond })

    const content = 'Pick a time window:\n\n1. Last 12 months\n2. Last 24 months\n3. All time'
    render(<AgentPrompt id="prompt-1" type="clarification" content={content} />)

    await user.click(screen.getByRole('button', { name: /choose: last 24 months/i }))

    expect(respond).toHaveBeenCalledWith('2')
  })

  test('submitting the inline input responds with the typed text', async () => {
    const user = userEvent.setup()
    const respond = vi.fn()
    useChatStore.setState({ respondToInteractionFn: respond })

    render(<AgentPrompt id="prompt-1" type="clarification" content="What time window?" />)

    const input = screen.getByRole('textbox', { name: /respond to the agent/i })
    await user.type(input, 'last 12 months{Enter}')

    expect(respond).toHaveBeenCalledWith('last 12 months')
  })

  test('does not render the inline input when there is no interaction handler', () => {
    useChatStore.setState({ respondToInteractionFn: null })

    render(<AgentPrompt id="prompt-1" type="clarification" content="What time window?" />)

    expect(screen.queryByRole('textbox', { name: /respond to the agent/i })).not.toBeInTheDocument()
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

  test('displays selected choice label for numbered prompt responses', () => {
    const content = 'Pick granularity:\n\n1. Daily\n2. Weekly\n3. Monthly\n4. Quarterly'

    render(
      <AgentPrompt
        id="prompt-1"
        type="clarification"
        content={content}
        isResponded={true}
        response="4"
      />
    )

    expect(screen.getByText('Quarterly')).toBeInTheDocument()
    expect(screen.queryByText(/^4$/)).not.toBeInTheDocument()
  })

  test('does not display timestamp for prompts', () => {
    const timestamp = new Date('2024-01-15T10:30:00')

    render(
      <AgentPrompt id="prompt-1" type="clarification" content="Question?" timestamp={timestamp} />
    )

    expect(screen.queryByText(/\d{1,2}:\d{2}/)).not.toBeInTheDocument()
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

  test('only the prompt matching the current pending interaction renders live actions', () => {
    useChatStore.setState({
      respondToInteractionFn: vi.fn(),
      pendingInteraction: {
        id: 'int-new',
        parentId: 'parent-1',
        inputType: 'approval',
        text: 'Approve the plan?',
      },
    })

    render(
      <>
        <AgentPrompt
          id="msg-old"
          interactionId="int-old"
          type="approval"
          content="Reply **approve** to proceed, **reject** to cancel"
        />
        <AgentPrompt
          id="msg-new"
          interactionId="int-new"
          type="approval"
          content="Reply **approve** to proceed, **reject** to cancel"
        />
      </>
    )

    expect(screen.getAllByRole('button', { name: /approve plan/i })).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: /reject plan/i })).toHaveLength(1)
  })

  test('treats type="approval" as an approval prompt even without the approve/reject sentence', () => {
    useChatStore.setState({ respondToInteractionFn: vi.fn() })

    render(<AgentPrompt id="p" type="approval" content="Shall I proceed with this plan?" />)

    expect(screen.getByRole('button', { name: /approve plan/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /reject plan/i })).toBeInTheDocument()
  })

  test('pressing Enter approves when focus is not on an interactive control', async () => {
    const user = userEvent.setup()
    const respond = vi.fn()
    useChatStore.setState({ respondToInteractionFn: respond })

    render(
      <AgentPrompt
        id="p"
        type="approval"
        content="Reply **approve** to proceed, **reject** to cancel"
      />
    )

    await user.keyboard('{Enter}')

    expect(respond).toHaveBeenCalledWith('approve')
  })

  test('pressing Enter while the Reject button is focused rejects instead of approving', async () => {
    const user = userEvent.setup()
    const respond = vi.fn()
    useChatStore.setState({ respondToInteractionFn: respond })

    render(
      <AgentPrompt
        id="p"
        type="approval"
        content="Reply **approve** to proceed, **reject** to cancel"
      />
    )

    await user.tab()
    await user.tab()
    expect(screen.getByRole('button', { name: /reject plan/i })).toHaveFocus()

    await user.keyboard('{Enter}')

    expect(respond).toHaveBeenCalledWith('reject')
    expect(respond).not.toHaveBeenCalledWith('approve')
  })

  test('renders approval plan sections as plan preview, not selectable choices', () => {
    useChatStore.setState({ respondToInteractionFn: vi.fn() })

    const content = [
      'Research Plan Preview',
      '',
      '**Title:** Customer Churn Assessment',
      '',
      '**Sections:**',
      '1. Data Sources and Definitions',
      '2. Customer Base Size Coverage',
      '3. Quarterly Sales Document Trends',
      '',
      'Reply **approve** to proceed, **reject** to cancel',
    ].join('\n')

    render(<AgentPrompt id="prompt-1" type="approval" content={content} />)

    expect(screen.getByText('Research Plan Preview')).toBeInTheDocument()
    expect(screen.getByText('Customer Churn Assessment')).toBeInTheDocument()
    expect(screen.getByText('Quarterly Sales Document Trends')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /choose: quarterly sales document trends/i })
    ).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /approve plan/i })).toHaveClass(
      'agent-action-approve'
    )
    expect(screen.getByRole('button', { name: /reject plan/i })).toHaveClass('agent-action-reject')
  })

  test('keeps the plan expanded and non-collapsible while it needs the user', () => {
    useChatStore.setState({ respondToInteractionFn: vi.fn() })

    const content = [
      'Research Plan Preview',
      '',
      '**Title:** Customer Churn Assessment',
      '',
      '**Sections:**',
      '1. Data Sources and Definitions',
      '2. Quarterly Sales Document Trends',
      '',
      'Reply **approve** to proceed, **reject** to cancel',
    ].join('\n')

    render(<AgentPrompt id="p" type="approval" content={content} />)

    expect(screen.getByText('Research Plan Preview')).toBeInTheDocument()
    expect(screen.getByText('Quarterly Sales Document Trends')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /needs your input/i })).not.toBeInTheDocument()
  })

  test('collapses the whole block to a header with the decision once responded', () => {
    useChatStore.setState({ respondToInteractionFn: vi.fn() })

    const content = [
      'Research Plan Preview',
      '',
      '**Title:** Customer Churn Assessment',
      '',
      '**Sections:**',
      '1. Data Sources and Definitions',
      '2. Quarterly Sales Document Trends',
      '',
      'Reply **approve** to proceed, **reject** to cancel',
    ].join('\n')

    render(<AgentPrompt id="p" type="approval" content={content} isResponded response="approve" />)

    expect(screen.getByText('Input received')).toBeInTheDocument()
    expect(screen.getByText('Plan approved')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /input received/i })).toBeInTheDocument()
    expect(screen.queryByText('Research Plan Preview')).not.toBeInTheDocument()
    expect(screen.queryByText('Quarterly Sales Document Trends')).not.toBeInTheDocument()
    expect(screen.queryByText('Customer Churn Assessment')).not.toBeInTheDocument()
  })

  test('does not treat a responded approval prompt with no response as approved', () => {
    useChatStore.setState({ respondToInteractionFn: vi.fn() })

    const content = [
      'Research Plan Preview',
      '',
      '**Title:** Customer Churn Assessment',
      '',
      '**Sections:**',
      '1. Data Sources and Definitions',
      '',
      'Reply **approve** to proceed, **reject** to cancel',
    ].join('\n')

    render(<AgentPrompt id="p" type="approval" content={content} isResponded />)

    expect(screen.queryByText('Plan approved')).not.toBeInTheDocument()
    expect(screen.queryByText('Plan rejected')).not.toBeInTheDocument()
  })

  test('re-expands the collapsed block when the header toggle is clicked', async () => {
    const user = userEvent.setup()
    useChatStore.setState({ respondToInteractionFn: vi.fn() })

    const content = [
      'Research Plan Preview',
      '',
      '**Title:** Customer Churn Assessment',
      '',
      '**Sections:**',
      '1. Data Sources and Definitions',
      '',
      'Reply **approve** to proceed, **reject** to cancel',
    ].join('\n')

    render(<AgentPrompt id="p" type="approval" content={content} isResponded response="approve" />)

    expect(screen.queryByText('Research Plan Preview')).not.toBeInTheDocument()
    expect(screen.queryByText('Data Sources and Definitions')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /input received/i }))
    expect(screen.getByText('Research Plan Preview')).toBeInTheDocument()
    expect(screen.getByText('Data Sources and Definitions')).toBeInTheDocument()
  })
})

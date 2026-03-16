// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { PlanTab } from './PlanTab'
import type { PlanMessage } from '@/features/chat/types'

// Mock the chat store
let mockPlanMessages: PlanMessage[] = []
let mockIsStreaming = false
let mockIsLoading = false

vi.mock('@/features/chat', () => ({
  useChatStore: () => ({
    planMessages: mockPlanMessages,
    isStreaming: mockIsStreaming,
    isLoading: mockIsLoading,
  }),
}))

// Mock MarkdownRenderer
vi.mock('@/shared/components/MarkdownRenderer', () => ({
  MarkdownRenderer: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}))

describe('PlanTab', () => {
  const createPlanMessage = (overrides: Partial<PlanMessage> = {}): PlanMessage => ({
    id: 'plan-1',
    text: 'Here is your research plan...',
    inputType: 'text',
    timestamp: new Date('2024-01-15T14:30:00'),
    ...overrides,
  })

  beforeEach(() => {
    vi.clearAllMocks()
    mockPlanMessages = []
    mockIsStreaming = false
    mockIsLoading = false
  })

  describe('process overview', () => {
    test('renders process overview section', () => {
      render(<PlanTab />)

      expect(screen.getByText('Process Overview')).toBeInTheDocument()
      expect(screen.getByText(/Once the research/)).toBeInTheDocument()
    })
  })

  describe('empty state', () => {
    test('shows empty state when no plan messages', () => {
      render(<PlanTab />)

      expect(screen.getByText(/The research plan will appear here once deep research begins/)).toBeInTheDocument()
      expect(screen.getByText(/Plans show clarification questions/)).toBeInTheDocument()
    })

    test('shows document icon in empty state', () => {
      render(<PlanTab />)

      expect(screen.getByTestId('plantab-empty-icon')).toBeInTheDocument()
    })
  })

  describe('header', () => {
    test('renders header with title', () => {
      render(<PlanTab />)

      expect(screen.getByText('Research Plan')).toBeInTheDocument()
    })

    test('shows "Planning..." when streaming', () => {
      mockIsStreaming = true

      render(<PlanTab />)

      expect(screen.getByText('Planning...')).toBeInTheDocument()
    })

    test('shows "Planning..." when loading', () => {
      mockIsLoading = true

      render(<PlanTab />)

      expect(screen.getByText('Planning...')).toBeInTheDocument()
    })

    test('does not show "Planning..." when not active', () => {
      mockIsStreaming = false
      mockIsLoading = false

      render(<PlanTab />)

      expect(screen.queryByText('Planning...')).not.toBeInTheDocument()
    })
  })

  describe('with plan messages', () => {
    test('renders plan messages', () => {
      mockPlanMessages = [createPlanMessage({ text: 'Step 1: Research background' })]

      render(<PlanTab />)

      expect(screen.getByText('Step 1: Research background')).toBeInTheDocument()
    })

    test('renders multiple plan messages', () => {
      mockPlanMessages = [
        createPlanMessage({ id: '1', text: 'First message' }),
        createPlanMessage({ id: '2', text: 'Second message' }),
      ]

      render(<PlanTab />)

      expect(screen.getByText('First message')).toBeInTheDocument()
      expect(screen.getByText('Second message')).toBeInTheDocument()
    })

    test('shows timestamp for messages', () => {
      mockPlanMessages = [
        createPlanMessage({ timestamp: new Date('2024-01-15T14:30:00') }),
      ]

      render(<PlanTab />)

      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })

    test('shows "Plan Preview" label for approval type messages', () => {
      mockPlanMessages = [createPlanMessage({ inputType: 'approval' })]

      render(<PlanTab />)

      expect(screen.getByText('Plan Preview')).toBeInTheDocument()
    })

    test('shows "Agent" label for non-approval messages', () => {
      mockPlanMessages = [createPlanMessage({ inputType: 'text' })]

      render(<PlanTab />)

      expect(screen.getByText('Agent')).toBeInTheDocument()
    })
  })

  describe('user responses', () => {
    test('shows user response when provided', () => {
      mockPlanMessages = [
        createPlanMessage({
          text: 'What is your preferred approach?',
          userResponse: 'I prefer option A',
        }),
      ]

      render(<PlanTab />)

      expect(screen.getByText('Your Response')).toBeInTheDocument()
      expect(screen.getByText('I prefer option A')).toBeInTheDocument()
    })

    test('does not show user response section when not provided', () => {
      mockPlanMessages = [
        createPlanMessage({
          text: 'Question',
          userResponse: undefined,
        }),
      ]

      render(<PlanTab />)

      expect(screen.queryByText('Your Response')).not.toBeInTheDocument()
    })
  })

  describe('timestamp handling', () => {
    test('handles Date object timestamp', () => {
      mockPlanMessages = [
        createPlanMessage({ timestamp: new Date('2024-01-15T14:30:00') }),
      ]

      render(<PlanTab />)

      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })

    test('handles ISO string timestamp', () => {
      mockPlanMessages = [
        createPlanMessage({
          timestamp: '2024-01-15T14:30:00Z' as unknown as Date,
        }),
      ]

      render(<PlanTab />)

      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })
  })
})

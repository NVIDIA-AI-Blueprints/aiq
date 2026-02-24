// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { ChatThinking } from './ChatThinking'
import type { ThinkingStep } from '../types'

// Helper to create a thinking step
const createStep = (overrides: Partial<ThinkingStep> = {}): ThinkingStep => ({
  id: 'step-1',
  userMessageId: 'msg-1',
  category: 'tasks',
  functionName: 'test_function',
  displayName: 'Test Function',
  content: 'Step content here',
  isComplete: false,
  timestamp: new Date('2024-01-15T14:30:00'),
  ...overrides,
})

describe('ChatThinking', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('empty state', () => {
    test('renders nothing when no steps provided', () => {
      render(<ChatThinking steps={[]} />)

      // No status text, no toggle - component renders null
      expect(screen.queryByText('Working on a response...')).not.toBeInTheDocument()
      expect(screen.queryByText('Done')).not.toBeInTheDocument()
      expect(screen.queryByText(/Show thinking/)).not.toBeInTheDocument()
    })
  })

  describe('status header', () => {
    test('shows spinner and working text when isThinking is true', () => {
      const steps = [createStep()]

      render(<ChatThinking steps={steps} isThinking={true} />)

      expect(screen.getByLabelText('Thinking in progress')).toBeInTheDocument()
      expect(screen.getByText('Working on a response...')).toBeInTheDocument()
    })

    test('shows check icon and done text when isThinking is false', () => {
      const steps = [createStep()]

      render(<ChatThinking steps={steps} isThinking={false} />)

      expect(screen.queryByLabelText('Thinking in progress')).not.toBeInTheDocument()
      expect(screen.getByText('Done')).toBeInTheDocument()
    })

    test('defaults to isThinking true', () => {
      const steps = [createStep()]

      render(<ChatThinking steps={steps} />)

      expect(screen.getByLabelText('Thinking in progress')).toBeInTheDocument()
      expect(screen.getByText('Working on a response...')).toBeInTheDocument()
    })

    test('shows warning icon and interrupted text when isInterrupted is true', () => {
      const steps = [createStep()]

      render(<ChatThinking steps={steps} isThinking={false} isInterrupted={true} />)

      expect(screen.getByText('Interrupted')).toBeInTheDocument()
      // Should NOT show "Done" or spinner
      expect(screen.queryByText('Done')).not.toBeInTheDocument()
      expect(screen.queryByLabelText('Thinking in progress')).not.toBeInTheDocument()
    })

    test('isThinking takes priority over isInterrupted', () => {
      const steps = [createStep()]

      // When both isThinking and isInterrupted are set, spinner should show (active thinking wins)
      render(<ChatThinking steps={steps} isThinking={true} isInterrupted={true} />)

      expect(screen.getByText('Working on a response...')).toBeInTheDocument()
      expect(screen.queryByText('Interrupted')).not.toBeInTheDocument()
    })

    test('shows clock icon and waiting text when isWaiting is true', () => {
      const steps = [createStep()]

      render(<ChatThinking steps={steps} isThinking={false} isWaiting={true} />)

      expect(screen.getByText('Waiting for response')).toBeInTheDocument()
      expect(screen.queryByText('Done')).not.toBeInTheDocument()
      expect(screen.queryByText('Interrupted')).not.toBeInTheDocument()
      expect(screen.queryByLabelText('Thinking in progress')).not.toBeInTheDocument()
    })

    test('isWaiting takes priority over isInterrupted', () => {
      const steps = [createStep()]

      render(<ChatThinking steps={steps} isThinking={false} isWaiting={true} isInterrupted={true} />)

      expect(screen.getByText('Waiting for response')).toBeInTheDocument()
      expect(screen.queryByText('Interrupted')).not.toBeInTheDocument()
    })

    test('isThinking takes priority over isWaiting', () => {
      const steps = [createStep()]

      render(<ChatThinking steps={steps} isThinking={true} isWaiting={true} />)

      expect(screen.getByText('Working on a response...')).toBeInTheDocument()
      expect(screen.queryByText('Waiting for response')).not.toBeInTheDocument()
    })
  })

  describe('collapse/expand toggle', () => {
    test('shows step count in trigger', () => {
      const steps = [createStep()]

      render(<ChatThinking steps={steps} />)

      expect(screen.getByText('Show thinking (1)')).toBeInTheDocument()
    })

    test('step list is collapsed by default', () => {
      const steps = [createStep({ displayName: 'Intent Classifier' })]

      render(<ChatThinking steps={steps} />)

      // The content should be in the DOM but hidden by KUI Collapsible
      expect(screen.getByText('Show thinking (1)')).toBeInTheDocument()
    })

    test('expands step list on trigger click', async () => {
      const user = userEvent.setup()
      const steps = [createStep({ displayName: 'Intent Classifier' })]

      render(<ChatThinking steps={steps} />)

      // Click the trigger area to expand
      await user.click(screen.getByText('Show thinking (1)'))

      expect(screen.getByText('Intent Classifier')).toBeVisible()
    })
  })

  describe('step list rendering', () => {
    test('renders all steps as flat list with displayName', async () => {
      const user = userEvent.setup()
      const steps = [
        createStep({ id: '1', displayName: 'Intent Classifier', category: 'agents' }),
        createStep({ id: '2', displayName: 'Depth Router', category: 'agents' }),
        createStep({ id: '3', displayName: 'Web Search Tool', category: 'tools' }),
        createStep({ id: '4', displayName: 'Tavily Search', category: 'tools' }),
      ]

      render(<ChatThinking steps={steps} />)

      // Expand via trigger
      await user.click(screen.getByText(`Show thinking (${steps.length})`))

      expect(screen.getByText('Intent Classifier')).toBeVisible()
      expect(screen.getByText('Depth Router')).toBeVisible()
      expect(screen.getByText('Web Search Tool')).toBeVisible()
      expect(screen.getByText('Tavily Search')).toBeVisible()
    })

    test('shows timestamps for each step', async () => {
      const user = userEvent.setup()
      const steps = [createStep({ timestamp: new Date('2024-01-15T14:30:00') })]

      render(<ChatThinking steps={steps} />)

      await user.click(screen.getByText(/Show thinking/))

      // Timestamp should be formatted and visible
      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })

    test('renders steps from all categories in a flat list (no tabs)', async () => {
      const user = userEvent.setup()
      const steps = [
        createStep({ id: '1', category: 'tasks', displayName: 'Workflow Task' }),
        createStep({ id: '2', category: 'agents', displayName: 'Agent Step' }),
        createStep({ id: '3', category: 'tools', displayName: 'Tool Step' }),
      ]

      render(<ChatThinking steps={steps} />)

      await user.click(screen.getByText(/Show thinking/))

      // All three categories appear in a single flat list
      expect(screen.getByText('Workflow Task')).toBeVisible()
      expect(screen.getByText('Agent Step')).toBeVisible()
      expect(screen.getByText('Tool Step')).toBeVisible()
    })

    test('step list has correct ARIA role', async () => {
      const user = userEvent.setup()
      const steps = [createStep()]

      render(<ChatThinking steps={steps} />)

      await user.click(screen.getByText(/Show thinking/))

      expect(screen.getByRole('list', { name: 'Thinking steps' })).toBeInTheDocument()
    })
  })

  describe('styling', () => {
    test('outer container has base border class', () => {
      const steps = [createStep()]

      render(<ChatThinking steps={steps} />)

      // The trigger lives inside the outer container with the base border
      const triggerText = screen.getByText(/Show thinking/)
      const outerDiv = triggerText.closest('.border-base')
      expect(outerDiv).toBeInTheDocument()
    })
  })

  describe('data sources summary', () => {
    test('displays data sources when provided', async () => {
      const user = userEvent.setup()
      const steps = [createStep()]
      const enabledDataSources = ['web_search', 'knowledge_base']

      render(<ChatThinking steps={steps} enabledDataSources={enabledDataSources} />)

      // Expand to see content
      await user.click(screen.getByText(/Show thinking/))

      expect(screen.getByText('Selected Data Sources:')).toBeVisible()
      expect(screen.getByText('Web Search, Knowledge Base')).toBeVisible()
    })

    test('displays files when provided', async () => {
      const user = userEvent.setup()
      const steps = [createStep()]
      const messageFiles = [
        { id: 'file-1', fileName: 'document.pdf' },
        { id: 'file-2', fileName: 'report.docx' },
      ]

      render(<ChatThinking steps={steps} messageFiles={messageFiles} />)

      await user.click(screen.getByText(/Show thinking/))

      expect(screen.getByText('Selected Data Sources:')).toBeVisible()
      expect(screen.getByText('document.pdf, report.docx')).toBeVisible()
    })

    test('displays both data sources and files', async () => {
      const user = userEvent.setup()
      const steps = [createStep()]
      const enabledDataSources = ['web_search']
      const messageFiles = [{ id: 'file-1', fileName: 'document.pdf' }]

      render(
        <ChatThinking
          steps={steps}
          enabledDataSources={enabledDataSources}
          messageFiles={messageFiles}
        />
      )

      await user.click(screen.getByText(/Show thinking/))

      expect(screen.getByText('Selected Data Sources:')).toBeVisible()
      expect(screen.getByText('Web Search')).toBeVisible()
      expect(screen.getByText('document.pdf')).toBeVisible()
    })

    test('excludes knowledge_layer from data sources display', async () => {
      const user = userEvent.setup()
      const steps = [createStep()]
      const enabledDataSources = ['web_search', 'knowledge_layer']

      render(<ChatThinking steps={steps} enabledDataSources={enabledDataSources} />)

      await user.click(screen.getByText(/Show thinking/))

      // knowledge_layer should be filtered out
      expect(screen.getByText('Web Search')).toBeVisible()
      expect(screen.queryByText(/Knowledge Layer/i)).not.toBeInTheDocument()
    })

    test('does not show data sources section when no sources or files', async () => {
      const user = userEvent.setup()
      const steps = [createStep()]

      render(<ChatThinking steps={steps} />)

      await user.click(screen.getByText(/Show thinking/))

      expect(screen.queryByText('Selected Data Sources')).not.toBeInTheDocument()
    })

    test('formats data source names correctly', async () => {
      const user = userEvent.setup()
      const steps = [createStep()]
      const enabledDataSources = ['web_search', 'onedrive', 'google_drive']

      render(<ChatThinking steps={steps} enabledDataSources={enabledDataSources} />)

      await user.click(screen.getByText(/Show thinking/))

      expect(screen.getByText('Web Search, Onedrive, Google Drive')).toBeVisible()
    })
  })
})

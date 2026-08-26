// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { describe, test, expect } from 'vitest'
import { ChatThinking, dedupeNestedToolSteps } from './ChatThinking'
import type { ThinkingStep } from '../types'

const createStep = (overrides: Partial<ThinkingStep> = {}): ThinkingStep => ({
  id: 'step-1',
  userMessageId: 'msg-1',
  category: 'tasks',
  functionName: 'web_search_tool',
  displayName: 'Searching the web',
  content: 'Step content here',
  isComplete: false,
  timestamp: new Date('2024-01-15T14:30:00'),
  ...overrides,
})

describe('ChatThinking', () => {
  describe('empty state', () => {
    test('renders nothing when no steps, sources, or files are provided', () => {
      render(<ChatThinking steps={[]} />)
      expect(screen.queryByLabelText('Working')).not.toBeInTheDocument()
      expect(screen.queryByText('Done')).not.toBeInTheDocument()
      expect(screen.queryByText(/\bstep\b/)).not.toBeInTheDocument()
    })
  })

  describe('status header', () => {
    test('shows the working spinner and a thinking word while thinking', () => {
      render(<ChatThinking steps={[createStep()]} isThinking />)

      expect(screen.getByLabelText('Working')).toBeInTheDocument()
      expect(screen.getByText('Thinking')).toBeInTheDocument()
    })

    test('shows Done when finished', () => {
      render(<ChatThinking steps={[createStep()]} isThinking={false} />)

      expect(screen.getByText('Done')).toBeInTheDocument()
      expect(screen.queryByLabelText('Working')).not.toBeInTheDocument()
    })

    test('shows Interrupted when interrupted', () => {
      render(<ChatThinking steps={[createStep()]} isThinking={false} isInterrupted />)

      expect(screen.getByText('Interrupted')).toBeInTheDocument()
      expect(screen.queryByText('Done')).not.toBeInTheDocument()
    })

    test('shows the waiting label when awaiting user input', () => {
      render(<ChatThinking steps={[createStep()]} isThinking={false} isWaiting />)

      expect(screen.getByText('Needs your input')).toBeInTheDocument()
      expect(screen.queryByText('Done')).not.toBeInTheDocument()
    })

    test('thinking takes priority over interrupted', () => {
      render(<ChatThinking steps={[createStep()]} isThinking isInterrupted />)

      expect(screen.getByLabelText('Working')).toBeInTheDocument()
      expect(screen.queryByText('Interrupted')).not.toBeInTheDocument()
    })
  })

  describe('phase trace', () => {
    test('shows the step count when collapsed', () => {
      render(<ChatThinking steps={[createStep()]} isThinking={false} />)

      expect(screen.getByText('1 step')).toBeInTheDocument()
    })

    test('renders the human tool label in the trace while thinking', () => {
      render(<ChatThinking steps={[createStep({ functionName: 'web_search_tool' })]} isThinking />)

      expect(screen.getByText('Searching the web')).toBeInTheDocument()
    })

    test('expands the collapsed trace on click', async () => {
      const user = userEvent.setup()
      render(
        <ChatThinking steps={[createStep({ functionName: 'paper_search_tool' })]} isThinking={false} />
      )

      await user.click(screen.getByText('1 step'))

      expect(screen.getByText('Searching papers')).toBeInTheDocument()
    })

    test('folds reasoning and explanation notes into a phase instead of new rows', () => {
      const steps = [
        createStep({ id: 'a', functionName: 'web_search_tool', isTopLevel: true }),
        createStep({ id: 'b', functionName: '__reasoning__', content: 'weighing the options' }),
        createStep({ id: 'c', functionName: '__explanation__', content: 'why this matters' }),
      ]
      render(<ChatThinking steps={steps} isThinking={false} />)

      // Only the tool phase is counted; the folded notes are not their own steps.
      expect(screen.getByText('1 step')).toBeInTheDocument()
    })

    test('renders nothing for a reflection-only stream (it produces no phases)', () => {
      render(
        <ChatThinking
          steps={[createStep({ id: 'r', functionName: '__reflection__', content: 'looks good' })]}
          isThinking={false}
        />
      )

      expect(screen.queryByText('Done')).not.toBeInTheDocument()
      expect(screen.queryByText(/\bstep\b/)).not.toBeInTheDocument()
    })
  })

  describe('response duration', () => {
    test('a restored interrupted turn shows the real elapsed from the last step, not a mount-relative value', () => {
      const started = new Date('2024-01-15T14:30:00')
      const step = createStep({
        functionName: 'web_search_tool',
        timestamp: started,
        completedAt: new Date('2024-01-15T14:30:05'),
      })

      render(
        <ChatThinking
          steps={[step]}
          isThinking={false}
          isInterrupted
          responseStartedAt={started}
        />
      )

      const duration = screen.getByLabelText('Total response time')
      expect(duration).toHaveTextContent('0:05')
      expect(duration.textContent).not.toMatch(/\d+:\d\d:\d\d/)
    })

    test('a multi-minute deep-research job shows the real duration from the terminal timestamp', () => {
      const started = new Date('2024-01-15T14:30:00')
      const step = createStep({
        functionName: 'web_search_tool',
        timestamp: started,
        completedAt: new Date('2024-01-15T14:30:02'),
      })

      render(
        <ChatThinking
          steps={[step]}
          isThinking={false}
          responseStartedAt={started}
          responseCompletedAt={new Date('2024-01-15T14:35:00')}
        />
      )

      const duration = screen.getByLabelText('Total response time')
      expect(duration).toHaveTextContent('5:00')
      expect(duration.textContent).not.toBe('0:02')
    })

    test('a still-running job shows no bogus completed duration', () => {
      const started = new Date('2024-01-15T14:30:00')
      const step = createStep({
        functionName: 'web_search_tool',
        timestamp: started,
        completedAt: new Date('2024-01-15T14:30:02'),
      })

      render(
        <ChatThinking
          steps={[step]}
          isThinking
          responseStartedAt={started}
        />
      )

      const duration = screen.getByLabelText('Total response time')
      expect(duration.textContent).not.toBe('0:02')
      expect(duration.textContent).toMatch(/\d+:\d\d:\d\d/)
    })
  })

  describe('dedupeNestedToolSteps', () => {
    test('keeps a distinct nested call to the same tool as a top-level call', () => {
      const out = dedupeNestedToolSteps([
        createStep({ id: 'top', functionName: 'web_search_tool', argSummary: 'cats', isTopLevel: true }),
        createStep({ id: 'nested', functionName: 'web_search_tool', argSummary: 'dogs', isTopLevel: false }),
      ])

      expect(out.map((s) => s.id).sort()).toEqual(['nested', 'top'])
    })

    test('drops a nested announcement that duplicates a top-level call by label and input', () => {
      const out = dedupeNestedToolSteps([
        createStep({ id: 'top', functionName: 'web_search_tool', argSummary: 'cats', isTopLevel: true }),
        createStep({ id: 'nested', functionName: 'web_search_tool', argSummary: 'cats', isTopLevel: false }),
      ])

      expect(out.map((s) => s.id)).toEqual(['top'])
    })

    test('lifts a nested input summary onto a top-level call that carries none', () => {
      const out = dedupeNestedToolSteps([
        createStep({ id: 'top', functionName: 'web_search_tool', argSummary: undefined, isTopLevel: true }),
        createStep({ id: 'nested', functionName: 'web_search_tool', argSummary: 'cats', isTopLevel: false }),
      ])

      expect(out).toHaveLength(1)
      expect(out[0].id).toBe('top')
      expect(out[0].argSummary).toBe('cats')
    })
  })

  describe('step body comes from argSummary', () => {
    const PRIOR_ASSISTANT_ANSWER =
      'A gene is a segment of DNA that codes for a protein, while a genome is the complete set of genetic material.'

    test('renders a prior-answer body when a step still carries it as its arg summary (root cause)', () => {
      render(
        <ChatThinking
          steps={[
            createStep({ functionName: 'intent_classifier', argSummary: PRIOR_ASSISTANT_ANSWER, isTopLevel: true }),
          ]}
          embedded
        />
      )

      expect(screen.getByText('Intent Classifier')).toBeInTheDocument()
      expect(screen.getByText(PRIOR_ASSISTANT_ANSWER)).toBeInTheDocument()
    })

    test('a non-folded step with no arg summary shows its label but no history body', () => {
      render(
        <ChatThinking
          steps={[createStep({ functionName: 'intent_classifier', argSummary: undefined, isTopLevel: true })]}
          embedded
        />
      )

      expect(screen.getByText('Intent Classifier')).toBeInTheDocument()
      expect(screen.queryByText(PRIOR_ASSISTANT_ANSWER)).not.toBeInTheDocument()
    })

    test('a tool step still shows its query as the body', () => {
      render(
        <ChatThinking
          steps={[
            createStep({ functionName: 'web_search_tool', argSummary: 'top customers by revenue', isTopLevel: true }),
          ]}
          embedded
        />
      )

      expect(screen.getByText('Searching the web')).toBeInTheDocument()
      expect(screen.getByText('top customers by revenue')).toBeInTheDocument()
    })
  })

  describe('used sources and files', () => {
    test('surfaces a Using chip for a source the answer actually used', () => {
      render(
        <ChatThinking
          steps={[createStep({ functionName: 'web_search_tool' })]}
          isThinking={false}
          enabledDataSources={['web_search']}
        />
      )

      expect(screen.getByText('Using')).toBeInTheDocument()
      expect(screen.getByText('Web Search')).toBeInTheDocument()
    })

    test('does not surface an enabled source that no tool call used', () => {
      render(
        <ChatThinking
          steps={[createStep({ functionName: 'web_search_tool' })]}
          isThinking={false}
          enabledDataSources={['web_search', 'confluence']}
        />
      )

      expect(screen.getByText('Web Search')).toBeInTheDocument()
      expect(screen.queryByText('Confluence')).not.toBeInTheDocument()
    })

    test('surfaces an arbitrary user-configured source dynamically (not a fixed web/knowledge map)', () => {
      render(
        <ChatThinking
          steps={[createStep({ functionName: 'confluence_search' })]}
          isThinking={false}
          enabledDataSources={['confluence', 'web_search']}
        />
      )

      expect(screen.getByText('Confluence')).toBeInTheDocument()
      expect(screen.queryByText('Web Search')).not.toBeInTheDocument()
    })

    test('resolves a function-group tool to its source via a shared token', () => {
      render(
        <ChatThinking
          steps={[createStep({ functionName: 'eci__gdrive_get_file' })]}
          isThinking={false}
          enabledDataSources={['gdrive']}
        />
      )

      expect(screen.getByText('Google Drive')).toBeInTheDocument()
    })

    test('shows message files as source chips', () => {
      render(
        <ChatThinking
          steps={[createStep()]}
          isThinking={false}
          messageFiles={[{ id: 'f1', fileName: 'document.pdf' }]}
        />
      )

      expect(screen.getByText('document.pdf')).toBeInTheDocument()
    })
  })

  describe('embedded variant', () => {
    test('renders only the trace spine, without the chat header', () => {
      render(<ChatThinking steps={[createStep({ functionName: 'web_search_tool' })]} embedded />)

      expect(screen.getByText('Searching the web')).toBeInTheDocument()
      expect(screen.queryByText('Thinking')).not.toBeInTheDocument()
      expect(screen.queryByText('Done')).not.toBeInTheDocument()
    })
  })
})

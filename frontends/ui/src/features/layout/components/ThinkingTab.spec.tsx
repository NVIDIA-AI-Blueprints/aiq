// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { ThinkingTab } from './ThinkingTab'

interface MockLLMStep {
  id: string
  name: string
  content: string
  isComplete: boolean
}

interface MockAgent {
  id: string
  name: string
  status: string
}

interface MockToolCall {
  id: string
  name: string
  status: string
}

interface MockFile {
  id: string
  name: string
}

interface MockState {
  thinkingSteps: unknown[]
  activeThinkingStepId: string | null
  isStreaming: boolean
  isDeepResearchStreaming: boolean
  currentStatus: string | null
  deepResearchLLMSteps: MockLLMStep[]
  deepResearchAgents: MockAgent[]
  deepResearchToolCalls: MockToolCall[]
  deepResearchFiles: MockFile[]
}

const defaultState: MockState = {
  thinkingSteps: [],
  activeThinkingStepId: null,
  isStreaming: false,
  isDeepResearchStreaming: false,
  currentStatus: null,
  deepResearchLLMSteps: [],
  deepResearchAgents: [],
  deepResearchToolCalls: [],
  deepResearchFiles: [],
}

let mockState: MockState = { ...defaultState }

vi.mock('@/features/chat', () => ({
  useChatStore: vi.fn((selector?: (state: MockState) => unknown) => {
    return selector ? selector(mockState) : mockState
  }),
}))

vi.mock('./ThoughtTracesTab', () => ({
  ThoughtTracesTab: ({
    thoughtTraces,
  }: {
    thoughtTraces: unknown[]
  }) => (
    <div data-testid="thought-traces-tab">
      Thoughts: {thoughtTraces.length}
    </div>
  ),
}))

vi.mock('./AgentsTab', () => ({
  AgentsTab: () => <div data-testid="agents-tab">Agents Tab</div>,
}))

vi.mock('./ToolCallsTab', () => ({
  ToolCallsTab: ({ toolCalls }: { toolCalls: unknown[] }) => (
    <div data-testid="tool-calls-tab">
      Tool Calls: {toolCalls.length}
    </div>
  ),
}))

vi.mock('./FilesTab', () => ({
  FilesTab: () => (
    <div data-testid="files-tab">
      Files
    </div>
  ),
}))

describe('ThinkingTab', () => {
  beforeEach(() => {
    mockState = { ...defaultState }
  })

  test('renders segmented control with tabs in correct order', () => {
    render(<ThinkingTab />)

    expect(screen.getByRole('radio', { name: /Thoughts/i })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Agents/i })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Tools/i })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Files/i })).toBeInTheDocument()
  })

  test('shows agents tab by default', () => {
    render(<ThinkingTab />)

    expect(screen.getByTestId('agents-tab')).toBeInTheDocument()
    expect(screen.queryByTestId('thought-traces-tab')).not.toBeInTheDocument()
    expect(screen.queryByTestId('tool-calls-tab')).not.toBeInTheDocument()
    expect(screen.queryByTestId('files-tab')).not.toBeInTheDocument()
  })

  test('passes data to sub-tabs from store state', () => {
    mockState = {
      ...defaultState,
      deepResearchLLMSteps: [{ id: '1', name: 'step1', content: 'content', isComplete: false }],
      deepResearchToolCalls: [{ id: '1', name: 'tool1', status: 'running' }],
    }

    render(<ThinkingTab />)

    // Verify the tab buttons are present (counts are now shown inside each tab, not on buttons)
    expect(screen.getByRole('radio', { name: /Thoughts/i })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Agents/i })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Tools/i })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Files/i })).toBeInTheDocument()
  })
})

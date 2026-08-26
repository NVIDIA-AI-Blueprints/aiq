// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { ThinkingTab } from './ThinkingTab'

interface MockFile {
  id: string
  filename: string
  content: string
}

interface MockCitation {
  id: string
  url: string
  content: string
  timestamp: Date
  isCited?: boolean
}

interface MockState {
  deepResearchCitations: MockCitation[]
  deepResearchFiles: MockFile[]
}

const defaultState: MockState = {
  deepResearchCitations: [],
  deepResearchFiles: [],
}

let mockState: MockState = { ...defaultState }

vi.mock('@/features/chat', () => ({
  useChatStore: vi.fn((selector?: (state: MockState) => unknown) => {
    return selector ? selector(mockState) : mockState
  }),
}))

vi.mock('./AgentsTab', () => ({
  AgentsTab: () => <div data-testid="agents-tab">Steps Content</div>,
}))

vi.mock('./FileCard', () => ({
  FileCard: ({ file }: { file: MockFile }) => (
    <div data-testid="file-card">{file.filename}</div>
  ),
}))

vi.mock('./CitationCard', () => ({
  CitationCard: ({ citation }: { citation: MockCitation }) => (
    <article data-testid="citation-card">{citation.url}</article>
  ),
}))

describe('ThinkingTab', () => {
  beforeEach(() => {
    mockState = { ...defaultState }
  })

  test('collapses to exactly two sub-tabs: Steps and Sources', () => {
    render(<ThinkingTab />)

    expect(screen.getAllByRole('radio').map((radio) => radio.textContent)).toEqual([
      'Steps',
      'Sources',
    ])
  })

  test('shows the Steps view by default', () => {
    render(<ThinkingTab />)

    expect(screen.getByTestId('agents-tab')).toBeInTheDocument()
  })

  test('switches to Sources on demand', async () => {
    const user = userEvent.setup()
    render(<ThinkingTab />)

    await user.click(screen.getByRole('radio', { name: /Sources/i }))

    expect(screen.getByText('Sources the agent reads will appear here.')).toBeInTheDocument()
  })

  test('merges read + cited into one list with All / Cited filter', async () => {
    const user = userEvent.setup()
    mockState = {
      ...defaultState,
      deepResearchCitations: [
        {
          id: 'read-source',
          url: 'https://read.example',
          content: 'Source read during research',
          timestamp: new Date('2026-05-01T00:00:00Z'),
          isCited: false,
        },
        {
          id: 'cited-source',
          url: 'https://cited.example',
          content: 'Source cited in final report',
          timestamp: new Date('2026-05-02T00:00:00Z'),
          isCited: true,
        },
      ],
    }

    render(<ThinkingTab />)
    await user.click(screen.getByRole('radio', { name: /Sources/i }))

    expect(screen.getByText('Cited in report')).toBeInTheDocument()
    expect(screen.getByText('Other sources found')).toBeInTheDocument()
    expect(screen.getByText('https://read.example')).toBeInTheDocument()
    expect(screen.getByText('https://cited.example')).toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: /Cited \(1\)/i }))

    expect(screen.getByText('https://cited.example')).toBeInTheDocument()
    expect(screen.queryByText('https://read.example')).not.toBeInTheDocument()
  })

  test('shows a cited-specific empty state when sources exist but none are cited', async () => {
    const user = userEvent.setup()
    mockState = {
      ...defaultState,
      deepResearchCitations: [
        {
          id: 'read-only',
          url: 'https://read.example',
          content: 'Source read but not cited',
          timestamp: new Date('2026-05-01T00:00:00Z'),
          isCited: false,
        },
      ],
    }

    render(<ThinkingTab />)
    await user.click(screen.getByRole('radio', { name: /Sources/i }))
    await user.click(screen.getByRole('radio', { name: /Cited \(0\)/i }))

    expect(screen.getByText('No sources were cited in the report.')).toBeInTheDocument()
    expect(
      screen.queryByText('Sources the agent reads will appear here.')
    ).not.toBeInTheDocument()
  })

  test('shows clear empty-state copy for Sources', async () => {
    const user = userEvent.setup()
    render(<ThinkingTab />)

    await user.click(screen.getByRole('radio', { name: /Sources/i }))

    expect(screen.getByText('Sources the agent reads will appear here.')).toBeInTheDocument()
    expect(
      screen.getByText(
        'These details appear during active research and may not be available for completed reports.'
      )
    ).toBeInTheDocument()
  })

  test('folds generated files into a thin disclosure only when files exist', async () => {
    const user = userEvent.setup()
    mockState = {
      ...defaultState,
      deepResearchFiles: [{ id: 'f1', filename: 'report.md', content: 'body' }],
    }

    render(<ThinkingTab />)

    expect(screen.getByText('Generated files (1)')).toBeInTheDocument()
    expect(screen.queryByTestId('file-card')).not.toBeInTheDocument()

    await user.click(screen.getByText('Generated files (1)'))
    expect(screen.getByTestId('file-card')).toBeInTheDocument()
  })

  test('hides the generated-files section when there are no files', () => {
    render(<ThinkingTab />)

    expect(screen.queryByText(/Generated files/i)).not.toBeInTheDocument()
  })
})

// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { FilesTab } from './FilesTab'

// Mock the chat store
let mockDeepResearchFiles: Array<{ id: string; filename: string; content: string }> = []

vi.mock('@/features/chat/store', () => ({
  useChatStore: (selector: (state: { deepResearchFiles: typeof mockDeepResearchFiles }) => unknown) =>
    selector({ deepResearchFiles: mockDeepResearchFiles }),
}))

// Mock FileCard
vi.mock('./FileCard', () => ({
  FileCard: ({ file }: { file: { id: string; filename: string } }) => (
    <div data-testid="file-card">{file.filename}</div>
  ),
}))

describe('FilesTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockDeepResearchFiles = []
  })

  describe('empty state', () => {
    test('shows empty state when no files', () => {
      render(<FilesTab />)

      expect(screen.getByText('Generated files will appear here during research.')).toBeInTheDocument()
      expect(screen.getByText(/Shows drafts, reports/)).toBeInTheDocument()
    })
  })

  describe('with files', () => {
    test('renders header', () => {
      mockDeepResearchFiles = [{ id: '1', filename: 'report.md', content: 'content' }]

      render(<FilesTab />)

      expect(screen.getByText('Files')).toBeInTheDocument()
    })

    test('renders file cards', () => {
      mockDeepResearchFiles = [
        { id: '1', filename: 'report.md', content: 'Report content' },
        { id: '2', filename: 'draft.txt', content: 'Draft content' },
      ]

      render(<FilesTab />)

      expect(screen.getByText('report.md')).toBeInTheDocument()
      expect(screen.getByText('draft.txt')).toBeInTheDocument()
    })

    test('renders correct number of file cards', () => {
      mockDeepResearchFiles = [
        { id: '1', filename: 'file1.md', content: '' },
        { id: '2', filename: 'file2.md', content: '' },
        { id: '3', filename: 'file3.md', content: '' },
      ]

      render(<FilesTab />)

      expect(screen.getAllByTestId('file-card')).toHaveLength(3)
    })
  })
})

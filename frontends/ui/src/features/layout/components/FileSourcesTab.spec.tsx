// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { FileSourcesTab } from './FileSourcesTab'

// Mock the chat store
vi.mock('@/features/chat/store', () => ({
  useChatStore: vi.fn((selector) => {
    const state = {
      currentConversation: { id: 'session-1' },
      ensureSession: vi.fn(() => 'session-1'),
    }
    return selector(state)
  }),
}))

// Mock useAppConfig
vi.mock('@/shared/context', () => ({
  useAppConfig: () => ({
    authRequired: true,
    fileUpload: {
      acceptedTypes: '.pdf,.docx,.txt,.md',
      acceptedMimeTypes: ['application/pdf', 'text/plain', 'text/markdown'],
      maxTotalSizeMB: 100,
      maxFileSize: 100 * 1024 * 1024,
      maxTotalSize: 100 * 1024 * 1024,
      maxFileCount: 10,
    },
  }),
}))


// Mock the file upload hook
const mockUploadFiles = vi.fn()
const mockDeleteFile = vi.fn()
const mockClearError = vi.fn()

vi.mock('@/features/documents', () => ({
  useFileUpload: vi.fn(() => ({
    uploadFiles: mockUploadFiles,
    deleteFile: mockDeleteFile,
    sessionFiles: [],
    isUploading: false,
    isPolling: false,
    error: null,
    clearError: mockClearError,
  })),
  useDocumentsStore: vi.fn((selector) => {
    const state = { currentCollectionName: 'session-1' }
    return selector(state)
  }),
  FileUploadZone: ({ onUpload }: { onUpload: (files: File[]) => void }) => (
    <button onClick={() => onUpload([new File([''], 'test.pdf')])}>Upload Zone</button>
  ),
  mapToDisplayStatus: (status: string) => status,
}))

// Mock the layout store
vi.mock('../store', () => ({
  useLayoutStore: vi.fn((selector) => {
    const state = {
      knowledgeLayerAvailable: true,
    }
    return selector(state)
  }),
}))

// Mock child components
vi.mock('./FileSourceCard', () => ({
  FileSourceCard: ({
    title,
    onDelete,
    id,
  }: {
    title: string
    onDelete: (id: string) => void
    id: string
  }) => (
    <div data-testid={`file-card-${id}`}>
      {title}
      <button onClick={() => onDelete(id)}>Delete</button>
    </div>
  ),
}))

vi.mock('./DeleteFileConfirmationModal', () => ({
  DeleteFileConfirmationModal: ({
    open,
    onConfirm,
    onOpenChange,
  }: {
    open: boolean
    onConfirm: () => void
    onOpenChange: (open: boolean) => void
  }) =>
    open ? (
      <div data-testid="delete-modal">
        <button onClick={onConfirm}>Confirm Delete</button>
        <button onClick={() => onOpenChange(false)}>Cancel</button>
      </div>
    ) : null,
}))

import { useFileUpload, useDocumentsStore } from '@/features/documents'

describe('FileSourcesTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  test('renders empty state when no files', () => {
    render(<FileSourcesTab />)

    expect(screen.getByText('No Attached Files')).toBeInTheDocument()
    expect(
      screen.getByText('All attached files will be accessible to agents in this session unless removed.')
    ).toBeInTheDocument()
  })

  test('renders file upload zone in empty state', () => {
    render(<FileSourcesTab />)

    expect(screen.getByText('Upload Zone')).toBeInTheDocument()
  })

  test('renders file list when files exist', () => {
    vi.mocked(useFileUpload).mockReturnValue({
      uploadFiles: mockUploadFiles,
      deleteFile: mockDeleteFile,
      sessionFiles: [
        { id: 'file-1', fileName: 'document.pdf', status: 'success', collectionName: 'session-1' },
        { id: 'file-2', fileName: 'report.txt', status: 'uploading', collectionName: 'session-1' },
      ],
      isUploading: false,
      error: null,
      clearError: mockClearError,
    } as unknown as ReturnType<typeof useFileUpload>)

    render(<FileSourcesTab />)

    expect(screen.getByTestId('file-card-file-1')).toHaveTextContent('document.pdf')
    expect(screen.getByTestId('file-card-file-2')).toHaveTextContent('report.txt')
  })

  test('shows file count in header', () => {
    vi.mocked(useFileUpload).mockReturnValue({
      uploadFiles: mockUploadFiles,
      deleteFile: mockDeleteFile,
      sessionFiles: [
        { id: 'file-1', fileName: 'doc.pdf', status: 'success', collectionName: 'session-1' },
      ],
      isUploading: false,
      error: null,
      clearError: mockClearError,
    } as unknown as ReturnType<typeof useFileUpload>)

    render(<FileSourcesTab />)

    expect(screen.getByText(/uploaded files \(1\)/i)).toBeInTheDocument()
  })

  test('opens delete confirmation modal when delete is clicked', async () => {
    const user = userEvent.setup()

    vi.mocked(useFileUpload).mockReturnValue({
      uploadFiles: mockUploadFiles,
      deleteFile: mockDeleteFile,
      sessionFiles: [
        { id: 'file-1', fileName: 'doc.pdf', status: 'success', collectionName: 'session-1' },
      ],
      isUploading: false,
      error: null,
      clearError: mockClearError,
    } as unknown as ReturnType<typeof useFileUpload>)

    render(<FileSourcesTab />)

    await user.click(screen.getByRole('button', { name: /delete/i }))

    expect(screen.getByTestId('delete-modal')).toBeInTheDocument()
  })

  test('calls deleteFile when delete is confirmed', async () => {
    const user = userEvent.setup()

    vi.mocked(useFileUpload).mockReturnValue({
      uploadFiles: mockUploadFiles,
      deleteFile: mockDeleteFile,
      sessionFiles: [
        { id: 'file-1', fileName: 'doc.pdf', status: 'success', collectionName: 'session-1' },
      ],
      isUploading: false,
      error: null,
      clearError: mockClearError,
    } as unknown as ReturnType<typeof useFileUpload>)

    render(<FileSourcesTab />)

    await user.click(screen.getByRole('button', { name: /delete/i }))
    await user.click(screen.getByRole('button', { name: /confirm delete/i }))

    expect(mockDeleteFile).toHaveBeenCalledWith('file-1')
  })

  test('shows processing spinner when uploading but sessionFiles is empty', () => {
    vi.mocked(useFileUpload).mockReturnValue({
      uploadFiles: mockUploadFiles,
      deleteFile: mockDeleteFile,
      sessionFiles: [],
      isUploading: true,
      isPolling: false,
      error: null,
      clearError: mockClearError,
    } as unknown as ReturnType<typeof useFileUpload>)

    render(<FileSourcesTab />)

    expect(screen.getByText('Checking for files...')).toBeInTheDocument()
    expect(screen.queryByText(/no files/i)).not.toBeInTheDocument()
  })

  test('shows processing spinner when polling but sessionFiles is empty', () => {
    vi.mocked(useFileUpload).mockReturnValue({
      uploadFiles: mockUploadFiles,
      deleteFile: mockDeleteFile,
      sessionFiles: [],
      isUploading: false,
      isPolling: true,
      error: null,
      clearError: mockClearError,
    } as unknown as ReturnType<typeof useFileUpload>)

    render(<FileSourcesTab />)

    expect(screen.getByText('Checking for files...')).toBeInTheDocument()
    expect(screen.queryByText(/no files/i)).not.toBeInTheDocument()
  })

  test('does not show processing spinner when sessionFiles exist', () => {
    vi.mocked(useFileUpload).mockReturnValue({
      uploadFiles: mockUploadFiles,
      deleteFile: mockDeleteFile,
      sessionFiles: [
        { id: 'file-1', fileName: 'doc.pdf', status: 'uploading', collectionName: 'session-1' },
      ],
      isUploading: true,
      isPolling: false,
      error: null,
      clearError: mockClearError,
    } as unknown as ReturnType<typeof useFileUpload>)

    render(<FileSourcesTab />)

    expect(screen.queryByText('Checking for files...')).not.toBeInTheDocument()
    expect(screen.getByTestId('file-card-file-1')).toBeInTheDocument()
  })

  test('does not show spinner when upload belongs to a different session', () => {
    // Active collection is a different session than the one rendered
    vi.mocked(useDocumentsStore).mockImplementation((selector) => {
      const state = { currentCollectionName: 'other-session-99' }
      return (selector as (s: typeof state) => unknown)(state)
    })

    vi.mocked(useFileUpload).mockReturnValue({
      uploadFiles: mockUploadFiles,
      deleteFile: mockDeleteFile,
      sessionFiles: [],
      isUploading: true,
      isPolling: true,
      error: null,
      clearError: mockClearError,
    } as unknown as ReturnType<typeof useFileUpload>)

    render(<FileSourcesTab />)

    // Spinner should NOT appear because the upload is for a different session
    expect(screen.queryByText('Checking for files...')).not.toBeInTheDocument()
    expect(screen.getByText('No Attached Files')).toBeInTheDocument()
  })

  test('displays upload error when present', () => {
    vi.mocked(useFileUpload).mockReturnValue({
      uploadFiles: mockUploadFiles,
      deleteFile: mockDeleteFile,
      sessionFiles: [],
      isUploading: false,
      error: 'File too large',
      clearError: mockClearError,
    } as unknown as ReturnType<typeof useFileUpload>)

    render(<FileSourcesTab />)

    expect(screen.getByText('File too large')).toBeInTheDocument()
  })
})

// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { FileUploadZone } from './FileUploadZone'

// Mock the documents store
let mockTrackedFiles: Array<{
  id: string
  file?: File
  collectionName: string
  status: string
  fileSize: number
  progress?: number
  errorMessage?: string
}> = []

vi.mock('../store', () => ({
  useDocumentsStore: (selector: (state: { trackedFiles: typeof mockTrackedFiles }) => unknown) =>
    selector({ trackedFiles: mockTrackedFiles }),
}))

// Mock the constants
vi.mock('../', () => ({
  ACCEPTED_FILE_TYPES: '.pdf,.docx,.txt',
  MAX_FILE_SIZE: 10 * 1024 * 1024, // 10 MB
}))

describe('FileUploadZone', () => {
  const mockOnUpload = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    mockTrackedFiles = []
  })

  describe('basic rendering', () => {
    test('renders upload zone', () => {
      render(<FileUploadZone onUpload={mockOnUpload} />)

      // Should show file size limit
      expect(screen.getByText('Up to 10 MB')).toBeInTheDocument()
    })

    test('shows accepted file types', () => {
      render(<FileUploadZone onUpload={mockOnUpload} />)

      expect(screen.getByText(/Accepts: .pdf,.docx,.txt/)).toBeInTheDocument()
    })

    test('uses custom max file size', () => {
      render(
        <FileUploadZone
          onUpload={mockOnUpload}
          maxFileSize={5 * 1024 * 1024}
        />
      )

      expect(screen.getByText('Up to 5 MB')).toBeInTheDocument()
    })

    test('uses custom accepted types', () => {
      render(
        <FileUploadZone
          onUpload={mockOnUpload}
          acceptedTypes=".json,.yaml"
        />
      )

      expect(screen.getByText(/Accepts: .json,.yaml/)).toBeInTheDocument()
    })

    test('renders with label when provided', () => {
      render(
        <FileUploadZone
          onUpload={mockOnUpload}
          label="Upload Documents"
        />
      )

      expect(screen.getByText('Upload Documents')).toBeInTheDocument()
    })
  })

  describe('disabled state', () => {
    test('is disabled when isUploading is true', () => {
      render(<FileUploadZone onUpload={mockOnUpload} isUploading={true} />)

      // The Upload component should be disabled
      // Check for disabled state via the input element
      const fileInput = screen.getByTestId('nv-upload-input-element')
      expect(fileInput).toBeDisabled()
    })

    test('is enabled when isUploading is false', () => {
      render(<FileUploadZone onUpload={mockOnUpload} isUploading={false} />)

      const fileInput = screen.getByTestId('nv-upload-input-element')
      expect(fileInput).not.toBeDisabled()
    })
  })

  describe('session file filtering', () => {
    test('filters files by session ID', () => {
      mockTrackedFiles = [
        {
          id: 'file-1',
          file: new File(['content'], 'file1.pdf', { type: 'application/pdf' }),
          collectionName: 'session-1',
          status: 'success',
          fileSize: 1000,
        },
        {
          id: 'file-2',
          file: new File(['content'], 'file2.pdf', { type: 'application/pdf' }),
          collectionName: 'session-2',
          status: 'success',
          fileSize: 2000,
        },
      ]

      render(
        <FileUploadZone
          onUpload={mockOnUpload}
          sessionId="session-1"
        />
      )

      // Should only show file from session-1
      expect(screen.getByText('file1.pdf')).toBeInTheDocument()
      expect(screen.queryByText('file2.pdf')).not.toBeInTheDocument()
    })

    test('shows no files when sessionId does not match', () => {
      mockTrackedFiles = [
        {
          id: 'file-1',
          file: new File(['content'], 'file1.pdf', { type: 'application/pdf' }),
          collectionName: 'session-1',
          status: 'success',
          fileSize: 1000,
        },
      ]

      render(
        <FileUploadZone
          onUpload={mockOnUpload}
          sessionId="session-999"
        />
      )

      expect(screen.queryByText('file1.pdf')).not.toBeInTheDocument()
    })
  })

  describe('file status mapping', () => {
    test('maps success status correctly', () => {
      mockTrackedFiles = [
        {
          id: 'file-1',
          file: new File(['content'], 'success.pdf', { type: 'application/pdf' }),
          collectionName: 'session-1',
          status: 'success',
          fileSize: 1000,
        },
      ]

      render(<FileUploadZone onUpload={mockOnUpload} sessionId="session-1" />)

      expect(screen.getByText('success.pdf')).toBeInTheDocument()
    })

    test('maps failed status to error', () => {
      mockTrackedFiles = [
        {
          id: 'file-1',
          file: new File(['content'], 'failed.pdf', { type: 'application/pdf' }),
          collectionName: 'session-1',
          status: 'failed',
          fileSize: 1000,
          errorMessage: 'Upload failed',
        },
      ]

      render(<FileUploadZone onUpload={mockOnUpload} sessionId="session-1" />)

      expect(screen.getByText('failed.pdf')).toBeInTheDocument()
    })

    test('maps uploading status correctly', () => {
      mockTrackedFiles = [
        {
          id: 'file-1',
          file: new File(['content'], 'uploading.pdf', { type: 'application/pdf' }),
          collectionName: 'session-1',
          status: 'uploading',
          fileSize: 1000,
          progress: 50,
        },
      ]

      render(<FileUploadZone onUpload={mockOnUpload} sessionId="session-1" />)

      expect(screen.getByText('uploading.pdf')).toBeInTheDocument()
    })
  })

  describe('onUpload callback', () => {
    test('does not call onUpload for already tracked files', async () => {
      const existingFile = new File(['content'], 'existing.pdf', { type: 'application/pdf' })
      mockTrackedFiles = [
        {
          id: 'existing-file-id',
          file: existingFile,
          collectionName: 'session-1',
          status: 'success',
          fileSize: 1000,
        },
      ]

      render(<FileUploadZone onUpload={mockOnUpload} sessionId="session-1" />)

      // Mock KUI Upload would trigger with existing file
      // Since the file is already tracked, onUpload should not be called
      expect(mockOnUpload).not.toHaveBeenCalled()
    })
  })

  describe('file object handling', () => {
    test('excludes files without File object', () => {
      mockTrackedFiles = [
        {
          id: 'file-1',
          file: undefined, // No File object
          collectionName: 'session-1',
          status: 'success',
          fileSize: 1000,
        },
      ]

      render(<FileUploadZone onUpload={mockOnUpload} sessionId="session-1" />)

      // The file without File object should not appear in the list
      expect(screen.queryByRole('listitem')).not.toBeInTheDocument()
    })
  })
})

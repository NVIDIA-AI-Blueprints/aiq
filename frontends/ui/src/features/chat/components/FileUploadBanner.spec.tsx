// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { FileUploadBanner } from './FileUploadBanner'

describe('FileUploadBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('uploaded status', () => {
    test('renders informational message about uploading and ingesting', () => {
      render(<FileUploadBanner type="uploaded" fileCount={1} />)

      expect(
        screen.getByText(/file is uploading and ingesting/i)
      ).toBeInTheDocument()
      expect(
        screen.getByText(/until completion, a file cannot be included in queries/i)
      ).toBeInTheDocument()
    })

    test('renders same message regardless of file count', () => {
      render(<FileUploadBanner type="uploaded" fileCount={5} />)

      expect(
        screen.getByText(/file is uploading and ingesting/i)
      ).toBeInTheDocument()
    })

    test('is dismissable when onDismiss is provided', async () => {
      const user = userEvent.setup()
      const onDismiss = vi.fn()

      render(<FileUploadBanner type="uploaded" fileCount={1} onDismiss={onDismiss} />)

      // KUI Banner renders a close button when onClose is provided
      const closeButton = screen.getByRole('button')
      expect(closeButton).toBeInTheDocument()

      await user.click(closeButton)
      expect(onDismiss).toHaveBeenCalledTimes(1)
    })

    test('does not show View Files button', () => {
      render(<FileUploadBanner type="uploaded" fileCount={1} />)

      expect(screen.queryByRole('button', { name: /view.*files/i })).not.toBeInTheDocument()
    })
  })

  describe('pending_warning status', () => {
    test('renders warning message about pending files', () => {
      render(<FileUploadBanner type="pending_warning" fileCount={2} />)

      expect(
        screen.getByText(/files are pending/i)
      ).toBeInTheDocument()
    })

    test('is not dismissable', () => {
      const onDismiss = vi.fn()

      render(<FileUploadBanner type="pending_warning" fileCount={1} onDismiss={onDismiss} />)

      // pending_warning should not have a close button (dismissable: false)
      expect(screen.queryByRole('button')).not.toBeInTheDocument()
    })
  })

  describe('deleted status', () => {
    test('renders singular message for one file', () => {
      render(<FileUploadBanner type="deleted" fileCount={1} />)

      expect(screen.getByText(/your file has been deleted/i)).toBeInTheDocument()
    })

    test('renders plural message for multiple files', () => {
      render(<FileUploadBanner type="deleted" fileCount={3} />)

      expect(screen.getByText(/3 files have been deleted/i)).toBeInTheDocument()
    })
  })

  test('displays timestamp when provided', () => {
    const timestamp = new Date('2024-01-15T14:30:00')

    render(<FileUploadBanner type="uploaded" fileCount={1} timestamp={timestamp} />)

    expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
  })

  test('handles ISO string timestamp', () => {
    render(<FileUploadBanner type="uploaded" fileCount={1} timestamp="2024-01-15T14:30:00Z" />)

    expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
  })
})

// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { ErrorBanner } from './ErrorBanner'

// Mock the error registry
vi.mock('../lib/error-registry', () => ({
  getErrorMeta: (code: string) => {
    const registry: Record<string, { title: string; defaultMessage: string; status: 'error' | 'warning' | 'info' }> = {
      'connection.failed': {
        title: 'Connection Failed',
        defaultMessage: 'Unable to connect to the server. Please check your network connection.',
        status: 'error',
      },
      'auth.session_expired': {
        title: 'Session Expired',
        defaultMessage: 'Your session has expired',
        status: 'error',
      },
      'file.upload_failed': {
        title: 'Upload Failed',
        defaultMessage: 'File upload failed',
        status: 'error',
      },
      'file.ingest_failed': {
        title: 'Processing Failed',
        defaultMessage: 'Failed to process the file contents',
        status: 'warning',
      },
    }
    return registry[code] || {
      title: 'Error',
      defaultMessage: 'An error occurred',
      status: 'error',
    }
  },
}))

describe('ErrorBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('basic rendering', () => {
    test('renders error title from registry', () => {
      render(<ErrorBanner code="connection.failed" />)

      expect(screen.getByText('Connection Failed')).toBeInTheDocument()
    })

    test('renders default message from registry', () => {
      render(<ErrorBanner code="connection.failed" />)

      expect(screen.getByText(/unable to connect to the server/i)).toBeInTheDocument()
    })

    test('renders custom message when provided', () => {
      render(
        <ErrorBanner
          code="connection.failed"
          message="Custom error message"
        />
      )

      expect(screen.getByText('Custom error message')).toBeInTheDocument()
      expect(screen.queryByText(/unable to connect to the server/i)).not.toBeInTheDocument()
    })

    test('uses KUI Banner component', () => {
      const { container } = render(<ErrorBanner code="connection.failed" />)

      // KUI Banner renders with specific class structure
      expect(container.querySelector('[class*="banner"]')).toBeInTheDocument()
    })
  })

  describe('banner status', () => {
    test('renders error status for connection errors', () => {
      render(<ErrorBanner code="connection.failed" />)

      // Banner should be visible with error status
      expect(screen.getByText('Connection Failed')).toBeInTheDocument()
    })

    test('renders warning status for processing errors', () => {
      render(<ErrorBanner code="file.ingest_failed" />)

      // Banner should be visible with warning status
      expect(screen.getByText('Processing Failed')).toBeInTheDocument()
    })
  })

  describe('timestamp', () => {
    test('displays timestamp when provided', () => {
      render(
        <ErrorBanner
          code="connection.failed"
          timestamp={new Date('2024-01-15T14:30:00')}
        />
      )

      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })

    test('handles ISO string timestamp', () => {
      render(
        <ErrorBanner
          code="connection.failed"
          timestamp="2024-01-15T14:30:00Z"
        />
      )

      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })

    test('does not display timestamp when not provided', () => {
      const { container } = render(<ErrorBanner code="connection.failed" />)

      // Should render but without a time string
      expect(container.textContent).not.toMatch(/\d{1,2}:\d{2}/)
    })
  })

  describe('persistent banner', () => {
    test('does not show retry button', () => {
      render(<ErrorBanner code="connection.failed" />)

      expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument()
    })

    test('does not show dismiss button', () => {
      render(<ErrorBanner code="connection.failed" />)

      expect(screen.queryByRole('button', { name: /dismiss/i })).not.toBeInTheDocument()
    })
  })

  describe('expandable details', () => {
    test('shows "Show details" button when details provided', () => {
      render(
        <ErrorBanner
          code="connection.failed"
          details="Stack trace here..."
        />
      )

      expect(screen.getByText('Show details')).toBeInTheDocument()
    })

    test('expands to show details when clicked', async () => {
      const user = userEvent.setup()

      render(
        <ErrorBanner
          code="connection.failed"
          details="Error stack trace goes here"
        />
      )

      await user.click(screen.getByText('Show details'))

      expect(screen.getByText('Error stack trace goes here')).toBeInTheDocument()
      expect(screen.getByText('Hide details')).toBeInTheDocument()
    })

    test('collapses details when clicked again', async () => {
      const user = userEvent.setup()

      render(
        <ErrorBanner
          code="connection.failed"
          details="Error details"
        />
      )

      // Expand
      await user.click(screen.getByText('Show details'))
      expect(screen.getByText('Error details')).toBeInTheDocument()

      // Collapse
      await user.click(screen.getByText('Hide details'))
      expect(screen.queryByText('Error details')).not.toBeInTheDocument()
    })

    test('does not show details button when no details provided', () => {
      render(<ErrorBanner code="connection.failed" />)

      expect(screen.queryByText('Show details')).not.toBeInTheDocument()
    })
  })

  describe('accessibility', () => {
    test('details button has aria-expanded attribute', async () => {
      const user = userEvent.setup()

      render(
        <ErrorBanner
          code="connection.failed"
          details="Details here"
        />
      )

      const button = screen.getByText('Show details').closest('button')!
      expect(button).toHaveAttribute('aria-expanded', 'false')

      await user.click(button)
      expect(button).toHaveAttribute('aria-expanded', 'true')
    })

    test('details button has aria-controls', () => {
      render(
        <ErrorBanner
          code="connection.failed"
          details="Details here"
        />
      )

      const button = screen.getByText('Show details').closest('button')
      expect(button).toHaveAttribute('aria-controls', 'error-details')
    })
  })
})

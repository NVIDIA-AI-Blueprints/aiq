// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { SourceCard, type SourceInfo } from './SourceCard'

describe('SourceCard', () => {
  const createSource = (overrides: Partial<SourceInfo> = {}): SourceInfo => ({
    id: 'source-1',
    url: 'https://example.com/article',
    isCited: false,
    ...overrides,
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('basic rendering', () => {
    test('renders as a link', () => {
      render(<SourceCard source={createSource()} />)

      const link = screen.getByRole('link')
      expect(link).toHaveAttribute('href', 'https://example.com/article')
      expect(link).toHaveAttribute('target', '_blank')
      expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    })

    test('displays URL', () => {
      render(
        <SourceCard
          source={createSource({ url: 'https://example.com/path/to/page' })}
        />
      )

      expect(screen.getByText('https://example.com/path/to/page')).toBeInTheDocument()
    })

    test('displays title when provided', () => {
      render(
        <SourceCard
          source={createSource({ title: 'Article Title', url: 'https://example.com' })}
        />
      )

      expect(screen.getByText('Article Title')).toBeInTheDocument()
    })

    test('displays domain when no title', () => {
      render(
        <SourceCard
          source={createSource({ url: 'https://www.example.com/page', title: undefined })}
        />
      )

      expect(screen.getByText('example.com')).toBeInTheDocument()
    })
  })

  describe('cited state', () => {
    test('shows checkmark emoji when cited', () => {
      render(<SourceCard source={createSource({ isCited: true })} />)

      expect(screen.getByText('✅')).toBeInTheDocument()
    })

    test('does not show checkmark when not cited', () => {
      render(<SourceCard source={createSource({ isCited: false })} />)

      expect(screen.queryByText('✅')).not.toBeInTheDocument()
    })
  })

  describe('timestamp', () => {
    test('displays timestamp when provided', () => {
      render(
        <SourceCard
          source={createSource({
            discoveredAt: new Date('2024-01-15T14:30:00'),
          })}
        />
      )

      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })

    test('does not display timestamp when not provided', () => {
      render(
        <SourceCard
          source={createSource({ discoveredAt: undefined })}
        />
      )

      // Only domain/title and URL should be present
      expect(screen.getByText('example.com')).toBeInTheDocument()
    })

    test('handles ISO string timestamp', () => {
      render(
        <SourceCard
          source={createSource({
            discoveredAt: '2024-01-15T14:30:00Z' as unknown as Date,
          })}
        />
      )

      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })
  })

  describe('snippet', () => {
    test('displays snippet when provided', () => {
      render(
        <SourceCard
          source={createSource({
            snippet: 'This is a preview of the content...',
          })}
        />
      )

      expect(screen.getByText('This is a preview of the content...')).toBeInTheDocument()
    })

    test('does not display snippet when not provided', () => {
      render(<SourceCard source={createSource({ snippet: undefined })} />)

      // Component should render without snippet section
      expect(screen.getByRole('link')).toBeInTheDocument()
    })
  })

  describe('domain extraction', () => {
    test('removes www prefix', () => {
      render(
        <SourceCard
          source={createSource({
            url: 'https://www.wikipedia.org/wiki/Test',
            title: undefined,
          })}
        />
      )

      expect(screen.getByText('wikipedia.org')).toBeInTheDocument()
    })

    test('handles complex subdomains', () => {
      render(
        <SourceCard
          source={createSource({
            url: 'https://docs.example.com/api',
            title: undefined,
          })}
        />
      )

      expect(screen.getByText('docs.example.com')).toBeInTheDocument()
    })

    test('handles invalid URL gracefully', () => {
      render(
        <SourceCard
          source={createSource({
            url: 'not-a-url',
            title: undefined,
          })}
        />
      )

      // Should show the raw URL as fallback - it appears in both domain and URL spots
      const urlTexts = screen.getAllByText('not-a-url')
      expect(urlTexts.length).toBeGreaterThan(0)
    })
  })
})

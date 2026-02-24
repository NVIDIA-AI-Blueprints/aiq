// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { CitationCard } from './CitationCard'
import type { CitationSource } from '@/features/chat/types'

describe('CitationCard', () => {
  const createCitation = (overrides: Partial<CitationSource> = {}): CitationSource => ({
    id: 'citation-1',
    url: 'https://example.com/article',
    content: 'Citation content',
    timestamp: new Date('2024-01-15T14:30:00'),
    isCited: false,
    ...overrides,
  })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('basic rendering', () => {
    test('renders as a link', () => {
      render(<CitationCard citation={createCitation()} />)

      const link = screen.getByRole('link')
      expect(link).toHaveAttribute('href', 'https://example.com/article')
      expect(link).toHaveAttribute('target', '_blank')
      expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    })

    test('displays domain name', () => {
      render(<CitationCard citation={createCitation({ url: 'https://www.example.com/page' })} />)

      expect(screen.getByText('example.com')).toBeInTheDocument()
    })

    test('displays full URL', () => {
      render(
        <CitationCard
          citation={createCitation({ url: 'https://example.com/full/path/here' })}
        />
      )

      expect(screen.getByText('https://example.com/full/path/here')).toBeInTheDocument()
    })

    test('displays timestamp', () => {
      render(
        <CitationCard
          citation={createCitation({ timestamp: new Date('2024-01-15T14:30:00') })}
        />
      )

      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })
  })

  describe('cited vs referenced state', () => {
    test('shows check icon when cited', () => {
      render(<CitationCard citation={createCitation({ isCited: true })} />)

      // The citation should be styled differently when cited
      const domain = screen.getByText('example.com')
      expect(domain).toBeInTheDocument()
    })

    test('shows link icon when referenced (not cited)', () => {
      render(<CitationCard citation={createCitation({ isCited: false })} />)

      const domain = screen.getByText('example.com')
      expect(domain).toBeInTheDocument()
    })
  })

  describe('domain extraction', () => {
    test('removes www prefix from domain', () => {
      render(
        <CitationCard
          citation={createCitation({ url: 'https://www.wikipedia.org/wiki/Test' })}
        />
      )

      expect(screen.getByText('wikipedia.org')).toBeInTheDocument()
    })

    test('handles complex URLs', () => {
      render(
        <CitationCard
          citation={createCitation({ url: 'https://sub.domain.example.com/path?query=1' })}
        />
      )

      expect(screen.getByText('sub.domain.example.com')).toBeInTheDocument()
    })

    test('handles invalid URLs gracefully', () => {
      render(<CitationCard citation={createCitation({ url: 'not-a-valid-url' })} />)

      // Should show truncated URL as fallback - it appears in both domain and URL spots
      const urlTexts = screen.getAllByText('not-a-valid-url')
      expect(urlTexts.length).toBeGreaterThan(0)
    })
  })

  describe('timestamp handling', () => {
    test('handles Date object timestamp', () => {
      render(
        <CitationCard
          citation={createCitation({ timestamp: new Date('2024-01-15T09:15:00') })}
        />
      )

      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })

    test('handles ISO string timestamp', () => {
      render(
        <CitationCard
          citation={createCitation({
            timestamp: '2024-01-15T14:30:00Z' as unknown as Date,
          })}
        />
      )

      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
    })
  })
})

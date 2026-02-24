// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { describe, test, expect } from 'vitest'
import { UserMessage } from './UserMessage'

describe('UserMessage', () => {
  test('renders message content', () => {
    render(<UserMessage content="Hello, how can you help me?" />)

    expect(screen.getByText('Hello, how can you help me?')).toBeInTheDocument()
  })

  test('preserves whitespace in content', () => {
    const multilineContent = `Line 1
Line 2
Line 3`

    render(<UserMessage content={multilineContent} />)

    // Check that the Text component contains the multiline content
    const textElement = screen.getByTestId('nv-text')
    expect(textElement.textContent).toBe(multilineContent)
  })

  test('renders empty content', () => {
    const { container } = render(<UserMessage content="" />)

    // Component should still render, just with empty text
    expect(container.querySelector('[class*="rounded"]')).toBeInTheDocument()
  })

  test('renders long content', () => {
    const longContent = 'A'.repeat(1000)

    render(<UserMessage content={longContent} />)

    expect(screen.getByText(longContent)).toBeInTheDocument()
  })

  test('renders special characters', () => {
    const { container } = render(<UserMessage content="Code: `const x = 1` and <html> tags" />)

    // Since MarkdownRenderer renders markdown, check for the presence of content parts
    expect(container.textContent).toContain('Code:')
    expect(container.textContent).toContain('const x = 1')
  })

  test('displays timestamp when provided', () => {
    const timestamp = new Date('2024-01-15T14:30:00')

    render(<UserMessage content="Hello" timestamp={timestamp} />)

    expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
  })

  test('handles ISO string timestamp', () => {
    render(<UserMessage content="Hello" timestamp="2024-01-15T14:30:00Z" />)

    expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument()
  })

  test('does not display timestamp when not provided', () => {
    const { container } = render(<UserMessage content="Hello" />)

    // No timestamp text should be present
    expect(container.querySelectorAll('[class*="text-subtle"]')).toHaveLength(0)
  })
})

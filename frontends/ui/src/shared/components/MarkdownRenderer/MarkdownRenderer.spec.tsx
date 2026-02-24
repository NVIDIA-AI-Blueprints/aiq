// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { describe, test, expect } from 'vitest'
import { MarkdownRenderer } from './MarkdownRenderer'

describe('MarkdownRenderer', () => {
  describe('basic rendering', () => {
    test('renders plain text content', () => {
      render(<MarkdownRenderer content="Hello, world!" />)

      expect(screen.getByText('Hello, world!')).toBeInTheDocument()
    })

    test('renders empty content without error', () => {
      const { container } = render(<MarkdownRenderer content="" />)

      expect(container.querySelector('.markdown-content')).toBeInTheDocument()
    })

    test('applies custom className', () => {
      const { container } = render(
        <MarkdownRenderer content="Test" className="custom-class" />
      )

      expect(container.querySelector('.custom-class')).toBeInTheDocument()
    })
  })

  describe('headings', () => {
    test('renders h1 heading', () => {
      render(<MarkdownRenderer content="# Heading 1" />)

      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Heading 1')
    })

    test('renders h2 heading', () => {
      render(<MarkdownRenderer content="## Heading 2" />)

      expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Heading 2')
    })

    test('renders h3 heading', () => {
      render(<MarkdownRenderer content="### Heading 3" />)

      expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('Heading 3')
    })

    test('renders h4 heading', () => {
      render(<MarkdownRenderer content="#### Heading 4" />)

      expect(screen.getByRole('heading', { level: 4 })).toHaveTextContent('Heading 4')
    })
  })

  describe('paragraphs', () => {
    test('renders paragraph text', () => {
      render(<MarkdownRenderer content="This is a paragraph." />)

      expect(screen.getByText('This is a paragraph.')).toBeInTheDocument()
    })

    test('renders multiple paragraphs', () => {
      render(<MarkdownRenderer content={`Paragraph 1.

Paragraph 2.`} />)

      expect(screen.getByText('Paragraph 1.')).toBeInTheDocument()
      expect(screen.getByText('Paragraph 2.')).toBeInTheDocument()
    })
  })

  describe('lists', () => {
    test('renders unordered list', () => {
      render(<MarkdownRenderer content={`- Item 1
- Item 2
- Item 3`} />)

      expect(screen.getByText('Item 1')).toBeInTheDocument()
      expect(screen.getByText('Item 2')).toBeInTheDocument()
      expect(screen.getByText('Item 3')).toBeInTheDocument()
    })

    test('renders ordered list', () => {
      render(<MarkdownRenderer content={`1. First
2. Second
3. Third`} />)

      expect(screen.getByText('First')).toBeInTheDocument()
      expect(screen.getByText('Second')).toBeInTheDocument()
      expect(screen.getByText('Third')).toBeInTheDocument()
    })
  })

  describe('inline formatting', () => {
    test('renders bold text', () => {
      render(<MarkdownRenderer content="This is **bold** text." />)

      expect(screen.getByText('bold')).toHaveClass('font-semibold')
    })

    test('renders italic text', () => {
      render(<MarkdownRenderer content="This is *italic* text." />)

      const italicElement = screen.getByText('italic')
      expect(italicElement.tagName).toBe('EM')
    })

    test('renders inline code', () => {
      render(<MarkdownRenderer content="Use the `console.log()` function." />)

      const codeElement = screen.getByText('console.log()')
      expect(codeElement.tagName).toBe('CODE')
      expect(codeElement).toHaveClass('font-mono')
    })
  })

  describe('links', () => {
    test('renders links with correct href', () => {
      render(<MarkdownRenderer content="Visit [Example](https://example.com)" />)

      const link = screen.getByRole('link', { name: 'Example' })
      expect(link).toHaveAttribute('href', 'https://example.com')
    })

    test('links open in new tab', () => {
      render(<MarkdownRenderer content="[Link](https://example.com)" />)

      const link = screen.getByRole('link', { name: 'Link' })
      expect(link).toHaveAttribute('target', '_blank')
      expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    })
  })

  describe('code blocks', () => {
    test('renders code block with language', () => {
      const code = '```javascript\nconst x = 1;\n```'

      render(<MarkdownRenderer content={code} />)

      // CodeSnippet component should be rendered
      expect(screen.getByText('const x = 1;')).toBeInTheDocument()
    })

    test('renders code block without language', () => {
      const code = '```\nplain code\n```'

      render(<MarkdownRenderer content={code} />)

      expect(screen.getByText('plain code')).toBeInTheDocument()
    })

    test('renders Python code block', () => {
      const code = '```python\ndef hello():\n    print("Hello")\n```'

      render(<MarkdownRenderer content={code} />)

      expect(screen.getByText(/def hello/)).toBeInTheDocument()
    })
  })

  describe('blockquotes', () => {
    test('renders blockquote', () => {
      render(<MarkdownRenderer content="> This is a quote" />)

      const blockquote = screen.getByText('This is a quote').closest('blockquote')
      expect(blockquote).toBeInTheDocument()
    })
  })

  describe('horizontal rules', () => {
    test('renders horizontal rule', () => {
      const { container } = render(<MarkdownRenderer content={`Above

---

Below`} />)

      expect(container.querySelector('hr')).toBeInTheDocument()
    })
  })

  describe('tables (GFM)', () => {
    test('renders table with headers', () => {
      const tableMarkdown = `
| Header 1 | Header 2 |
|----------|----------|
| Cell 1   | Cell 2   |
| Cell 3   | Cell 4   |
`
      render(<MarkdownRenderer content={tableMarkdown} />)

      expect(screen.getByText('Header 1')).toBeInTheDocument()
      expect(screen.getByText('Header 2')).toBeInTheDocument()
      expect(screen.getByText('Cell 1')).toBeInTheDocument()
      expect(screen.getByText('Cell 4')).toBeInTheDocument()
    })
  })

  describe('compact mode', () => {
    test('uses default text size when compact is false', () => {
      render(<MarkdownRenderer content="Normal text" compact={false} />)

      // Text should be rendered (we can't easily check the exact kind prop)
      expect(screen.getByText('Normal text')).toBeInTheDocument()
    })

    test('uses smaller text size when compact is true', () => {
      render(<MarkdownRenderer content="Compact text" compact={true} />)

      // Text should be rendered
      expect(screen.getByText('Compact text')).toBeInTheDocument()
    })
  })

  describe('complex content', () => {
    test('renders mixed content correctly', () => {
      const content = `
# Main Title

This is a paragraph with **bold** and *italic* text.

## Code Example

\`\`\`javascript
const greeting = "Hello";
\`\`\`

### List of Items

- Item one
- Item two
- Item three

> A thoughtful quote

Visit [our site](https://example.com) for more.
`
      render(<MarkdownRenderer content={content} />)

      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Main Title')
      expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Code Example')
      expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('List of Items')
      expect(screen.getByText('bold')).toBeInTheDocument()
      expect(screen.getByText('Item one')).toBeInTheDocument()
      expect(screen.getByRole('link', { name: 'our site' })).toBeInTheDocument()
    })
  })

  describe('memoization', () => {
    test('component has displayName set', () => {
      expect(MarkdownRenderer.displayName).toBe('MarkdownRenderer')
    })
  })

  describe('edge cases', () => {
    test('handles special characters', () => {
      render(<MarkdownRenderer content={'Special chars: < > & " \''} />)

      expect(screen.getByText(/Special chars/)).toBeInTheDocument()
    })

    test('handles very long content', () => {
      const longContent = 'Word '.repeat(1000)

      const { container } = render(<MarkdownRenderer content={longContent} />)

      expect(container.querySelector('.markdown-content')).toBeInTheDocument()
    })

    test('handles nested formatting', () => {
      render(<MarkdownRenderer content="**Bold with *italic* inside**" />)

      // Should render without errors
      expect(screen.getByText(/Bold with/)).toBeInTheDocument()
    })
  })
})

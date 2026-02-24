// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client'

import { type FC, memo, useMemo } from 'react'
import ReactMarkdown, { type Components, type ExtraProps } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Text, CodeSnippet, Anchor } from '@/adapters/ui'
import type { MarkdownRendererProps } from './types'
import { getLanguageFromClassName } from './utils'

/**
 * MarkdownRenderer - Renders markdown content with KUI styling
 *
 * @param content - Markdown string to render
 * @param isStreaming - Whether content is still streaming (disables memoization)
 * @param className - Additional CSS classes
 * @param compact - Use smaller text sizes for chat bubbles
 */
export const MarkdownRenderer: FC<MarkdownRendererProps> = memo(
  ({ content, className = '', compact = false }) => {
    // Custom component mappings
    const components: Components = useMemo(
      () => ({
        code: ({
          children,
          className: codeClassName,
          ...props
        }: React.ComponentPropsWithoutRef<'code'> & ExtraProps) => {
          // Check if this is a block code (has language class) vs inline
          const isBlock = codeClassName?.startsWith('language-')
          const codeContent = String(children).replace(/\n$/, '')

          if (isBlock) {
            const language = getLanguageFromClassName(codeClassName)
            const lineCount = codeContent.split('\n').length

            return (
              <CodeSnippet
                value={codeContent}
                language={language}
                kind="block"
                collapsible={lineCount > 15}
                rows={15}
              />
            )
          }

          // Inline code
          return (
            <code
              className="bg-surface-raised text-primary rounded px-1.5 py-0.5 font-mono text-sm"
              {...props}
            >
              {children}
            </code>
          )
        },

        // Skip default pre rendering since CodeSnippet handles it
        pre: ({ children }) => <>{children}</>,

        // Headings
        h1: ({ children }) => (
          <Text asChild kind="title/xl" className="text-primary mb-3 mt-6 block">
            <h1>{children}</h1>
          </Text>
        ),
        h2: ({ children }) => (
          <Text asChild kind="title/lg" className="text-primary mb-2 mt-5 block">
            <h2>{children}</h2>
          </Text>
        ),
        h3: ({ children }) => (
          <Text asChild kind="title/md" className="text-primary mb-2 mt-4 block">
            <h3>{children}</h3>
          </Text>
        ),
        h4: ({ children }) => (
          <Text asChild kind="title/sm" className="text-primary mb-1 mt-3 block">
            <h4>{children}</h4>
          </Text>
        ),

        // Paragraphs
        p: ({ children }) => (
          <Text
            asChild
            kind={compact ? 'body/regular/sm' : 'body/regular/md'}
            className="text-primary mb-3 block leading-relaxed"
          >
            <p>{children}</p>
          </Text>
        ),

        // Lists
        ul: ({ children }) => (
          <ul className="text-primary mb-3 list-outside list-disc space-y-1 pl-5">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="text-primary mb-3 list-outside list-decimal space-y-1 pl-5">{children}</ol>
        ),
        li: ({ children }) => (
          <Text asChild kind={compact ? 'body/regular/sm' : 'body/regular/md'}>
            <li className="text-primary">{children}</li>
          </Text>
        ),

        // Links
        a: ({ href, children }) => (
          <Anchor href={href ?? '#'} target="_blank" rel="noopener noreferrer" kind="inline">
            {children}
          </Anchor>
        ),

        // Emphasis
        strong: ({ children }) => (
          <strong className="text-primary font-semibold">{children}</strong>
        ),
        em: ({ children }) => <em className="text-primary italic">{children}</em>,

        // Blockquotes
        blockquote: ({ children }) => (
          <blockquote className="border-info text-subtle my-3 border-l-4 pl-4 italic">
            {children}
          </blockquote>
        ),

        // Horizontal rule
        hr: () => <hr className="border-base my-4" />,

        // Tables (GFM)
        table: ({ children }) => (
          <div className="my-4 overflow-x-auto">
            <table className="border-base min-w-full rounded border">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead className="bg-surface-raised">{children}</thead>,
        tbody: ({ children }) => <tbody>{children}</tbody>,
        tr: ({ children }) => <tr className="border-base border-b">{children}</tr>,
        th: ({ children }) => (
          <Text asChild kind="label/semibold/sm">
            <th className="text-primary px-3 py-2 text-left">{children}</th>
          </Text>
        ),
        td: ({ children }) => (
          <Text asChild kind="body/regular/sm">
            <td className="text-primary px-3 py-2">{children}</td>
          </Text>
        ),
      }),
      [compact]
    )

    return (
      <div className={`markdown-content break-words [overflow-wrap:anywhere] [&>*:last-child]:mb-0 ${className}`}>
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {content}
        </ReactMarkdown>
      </div>
    )
  }
)

MarkdownRenderer.displayName = 'MarkdownRenderer'

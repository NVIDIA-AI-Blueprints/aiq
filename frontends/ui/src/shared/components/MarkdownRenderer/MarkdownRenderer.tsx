// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client'

import { type FC, type ReactNode, memo, useMemo } from 'react'
import ReactMarkdown, { type Components, type ExtraProps, defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import { Text, CodeSnippet, Anchor } from '@/adapters/ui'
import { cn } from '@/shared/lib/cn'
import type { MarkdownRendererProps } from './types'
import { getLanguageFromClassName } from './utils'
import { rehypeCitations } from './rehype-citations'
import { Citation } from './Citation'
import { MermaidBlock } from '@/shared/components/Mermaid'
import { ARTIFACT_SCHEME, isArtifactRef, resolveArtifactUrl } from '@/shared/utils/artifact-url'
import { ChartBlock, fenceBareSpecs } from '@/shared/components/ResultChart'

// Fenced languages the agent uses for declarative result charts, routed to ChartBlock.
const CHART_LANGUAGES = new Set(['chart', 'chart-carousel'])

// react-markdown's default sanitizer strips non-standard URL schemes, which would blank the
// src of `artifact://<id>` images before the `img` renderer can resolve them. Preserve that
// scheme and defer to the default transform for everything else (keeps XSS protection).
const urlTransform = (url: string): string =>
  url.startsWith(ARTIFACT_SCHEME) ? url : defaultUrlTransform(url)

function getTextFromChildren(node: ReactNode): string {
  if (typeof node === 'string') return node
  if (typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(getTextFromChildren).join('')
  if (node && typeof node === 'object' && 'props' in node) {
    return getTextFromChildren((node as React.ReactElement).props.children)
  }
  return ''
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, '')
    .replace(/[\s_]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

/**
 * MarkdownRenderer - Renders markdown content with KUI styling
 *
 * @param content - Markdown string to render
 * @param isStreaming - Whether content is still streaming (disables memoization)
 * @param className - Additional CSS classes
 * @param compact - Use smaller text sizes for chat bubbles
 * @param artifactJobId - Job id used to resolve `artifact://` image refs
 * @param variant - `answer` applies the answer-prose scale and citation chips
 * @param sources - Cited sources used to resolve inline `[n]` citation chips
 */
export const MarkdownRenderer: FC<MarkdownRendererProps> = memo(
  ({ content, className = '', compact = false, artifactJobId, variant = 'default', sources }) => {
    // Wrap any bare chart-spec line the agent forgot to fence so it still renders.
    const prepared = useMemo(() => fenceBareSpecs(content), [content])
    const isAnswer = variant === 'answer'
    const hasCitations = isAnswer && Array.isArray(sources) && sources.length > 0
    const components: Components = useMemo(
      () => ({
        cite: ({ children }) => (
          <Citation n={parseInt(getTextFromChildren(children) || '0', 10)} sources={sources ?? []} />
        ),
        code: ({
          children,
          className: codeClassName,
          node: _node,
          ...props
        }: React.ComponentPropsWithoutRef<'code'> & ExtraProps) => {
          // Block code (has a language class) vs inline
          const isBlock = codeClassName?.startsWith('language-')
          const codeContent = String(children).replace(/\n$/, '')

          if (isBlock) {
            const lineCount = codeContent.split('\n').length
            const fallback = (
              <CodeSnippet
                value={codeContent}
                language={getLanguageFromClassName(codeClassName)}
                kind="block"
                collapsible={lineCount > 15}
                rows={15}
              />
            )

            const rawLang = codeClassName?.replace(/^language-/, '') ?? ''
            if (CHART_LANGUAGES.has(rawLang)) {
              return <ChartBlock raw={codeContent} fallback={fallback} />
            }

            // A fenced ```mermaid block renders as an interactive diagram; every
            // other fence (including ```chart) falls through to the code block.
            if (/language-mermaid\b/.test(codeClassName ?? '')) {
              return <MermaidBlock code={codeContent} fallback={fallback} />
            }

            return fallback
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

        // Headings: include id for in-page anchor navigation
        h1: ({ children }) => {
          const id = slugify(getTextFromChildren(children))
          return (
            <Text asChild kind="title/xl" className="text-primary mb-3 mt-6 block scroll-mt-4">
              <h1 id={id}>{children}</h1>
            </Text>
          )
        },
        h2: ({ children }) => {
          const id = slugify(getTextFromChildren(children))
          return (
            <Text asChild kind="title/lg" className="text-primary mb-2 mt-5 block scroll-mt-4">
              <h2 id={id}>{children}</h2>
            </Text>
          )
        },
        h3: ({ children }) => {
          const id = slugify(getTextFromChildren(children))
          return (
            <Text asChild kind="title/md" className="text-primary mb-2 mt-4 block scroll-mt-4">
              <h3 id={id}>{children}</h3>
            </Text>
          )
        },
        h4: ({ children }) => {
          const id = slugify(getTextFromChildren(children))
          return (
            <Text asChild kind="title/sm" className="text-primary mb-1 mt-3 block scroll-mt-4">
              <h4 id={id}>{children}</h4>
            </Text>
          )
        },

        // Paragraphs
        p: ({ children }) =>
          isAnswer ? (
            <p className="text-primary mb-3 leading-relaxed">{children}</p>
          ) : (
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
        ol: ({ children, start }) => (
          <ol start={start} className="text-primary mb-3 list-outside list-decimal space-y-1 pl-5">
            {children}
          </ol>
        ),
        li: ({ children }) =>
          isAnswer ? (
            <li className="text-primary">{children}</li>
          ) : (
            <Text asChild kind={compact ? 'body/regular/sm' : 'body/regular/md'}>
              <li className="text-primary">{children}</li>
            </Text>
          ),

        // Links: anchor hrefs scroll in-page; external hrefs open new tabs
        a: ({ href, children }) => {
          if (href?.startsWith('#')) {
            return (
              <Anchor
                href={href}
                kind="inline"
                onClick={(e: React.MouseEvent) => {
                  e.preventDefault()
                  const el = document.getElementById(href.slice(1))
                  el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                }}
              >
                {children}
              </Anchor>
            )
          }
          return (
            <Anchor href={href ?? '#'} target="_blank" rel="noopener noreferrer" kind="inline">
              {children}
            </Anchor>
          )
        },

        // Images: resolve durable artifact:// refs to the content endpoint and render
        // as a captioned figure; pass other images through with responsive styling.
        img: ({ src, alt }) => {
          const rawSrc = typeof src === 'string' ? src : ''
          const resolved = isArtifactRef(rawSrc)
            ? resolveArtifactUrl(rawSrc, artifactJobId)
            : rawSrc
          // An unresolved artifact ref (no job id) would be a broken image, so skip it.
          if (!resolved || isArtifactRef(resolved)) return null
          const caption = alt ?? ''
          return (
            // react-markdown renders images inside a <p>, so use phrasing-content spans
            // (not <figure>/<figcaption>, which are invalid inside <p>).
            <span className="my-4 flex flex-col items-center">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={resolved}
                alt={caption}
                loading="lazy"
                className="border-base max-w-full rounded-md border"
              />
              {caption && (
                <Text asChild kind="body/regular/sm" className="text-subtle mt-2 block text-center">
                  <span>{caption}</span>
                </Text>
              )}
            </span>
          )
        },

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
      [compact, isAnswer, sources, artifactJobId]
    )

    return (
      <div
        className={cn(
          'markdown-content [overflow-wrap:anywhere] break-words [&>*:last-child]:mb-0',
          isAnswer && 'answer-prose',
          className,
        )}
      >
        <ReactMarkdown
          remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: false }]]}
          rehypePlugins={hasCitations ? [rehypeCitations, rehypeKatex] : [rehypeKatex]}
          components={components}
          urlTransform={urlTransform}
        >
          {prepared}
        </ReactMarkdown>
      </div>
    )
  }
)

MarkdownRenderer.displayName = 'MarkdownRenderer'

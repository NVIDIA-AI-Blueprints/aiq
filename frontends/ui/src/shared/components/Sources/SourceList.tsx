// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from 'react'
import { cn } from '@/shared/lib/cn'
import { SourceKindIcon } from './SourceKindIcon'
import { prettyDomain } from './source-utils'
import type { SourceRef } from './types'

interface SourceListProps {
  sources: SourceRef[]
  className?: string
  title?: string
}

/**
 * Compact, vertical references list for an agent answer: one {@link SourceRef}
 * per line (origin icon, superscript-style index, label, and an optional domain
 * link for web sources), rendered smaller than the body text so sources stay
 * present but subordinate to the answer.
 */
export function SourceList({ sources, className, title = 'Sources' }: SourceListProps): ReactNode {
  if (sources.length === 0) return null

  return (
    <section className={cn('mt-3 space-y-1', className)} aria-label={title}>
      <h3 className="text-subtle text-xs font-medium">{title}</h3>
      <ul className="text-secondary space-y-0.5 text-xs">
        {sources.map((s) => {
          const domain = s.url ? prettyDomain(s.url) : ''
          const showDomain = Boolean(domain) && domain !== s.label
          return (
            <li key={s.id} className="flex items-start gap-1.5 leading-snug">
              <sup className="text-subtle mt-0.5 align-super text-[0.6rem] leading-none">
                {s.index}
              </sup>
              <span className="text-subtle mt-px shrink-0">
                <SourceKindIcon kind={s.kind} className="h-3 w-3" />
              </span>
              {s.url ? (
                <a
                  href={s.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-[color:var(--color-green-500)] min-w-0 break-words underline-offset-2 hover:underline"
                >
                  {s.label}
                </a>
              ) : (
                <span className="min-w-0 break-words">{s.label}</span>
              )}
              {s.url && showDomain && (
                <a
                  href={s.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-subtle hover:text-[color:var(--color-green-500)] min-w-0 truncate underline-offset-2 hover:underline"
                >
                  {domain}
                </a>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

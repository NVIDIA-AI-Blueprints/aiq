// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client'

import { type ReactNode } from 'react'
import { cn } from '@/shared/lib/cn'
import { SourceKindIcon } from './SourceKindIcon'
import type { SourceRef } from './types'

interface SourceRowProps {
  source: SourceRef
}

/**
 * One source rendered as a compact row: an origin icon, its title, a subtle
 * domain, and the citation index. Becomes a link when the source has a real URL,
 * opening it in a new tab.
 */
function SourceRow({ source }: SourceRowProps): ReactNode {
  const showLabel = Boolean(source.label) && source.label !== source.title
  const inner = (
    <>
      <span className="text-subtle mt-0.5 shrink-0">
        <SourceKindIcon kind={source.kind} className="h-3.5 w-3.5" />
      </span>
      <span className="text-primary min-w-0 flex-1 truncate text-sm">{source.title}</span>
      {showLabel && <span className="text-subtle shrink-0 text-xs">{source.label}</span>}
      <span className="text-subtle shrink-0 text-xs" aria-hidden="true">
        [{source.index}]
      </span>
    </>
  )
  if (source.url) {
    return (
      <a
        href={source.url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-secondary hover:bg-surface-sunken hover:text-primary flex items-baseline gap-2 rounded-md px-2 py-1.5 no-underline transition-colors"
      >
        {inner}
      </a>
    )
  }
  return <div className="text-secondary flex items-baseline gap-2 px-2 py-1.5">{inner}</div>
}

interface SourceStripProps {
  sources: SourceRef[]
  className?: string
}

/**
 * Report-attached list of cited sources. Renders every source as a compact row
 * so the full list stays scannable instead of hiding most of it behind a "more"
 * control; the parent panel scrolls when the list is long.
 */
export function SourceStrip({ sources, className }: SourceStripProps): ReactNode {
  if (sources.length === 0) return null

  return (
    <section className={cn('space-y-1', className)} aria-label="Sources">
      <h3 className="text-secondary flex items-center gap-1.5 text-sm font-medium">
        <SourceKindIcon kind="doc" /> Sources
      </h3>
      <div className="flex flex-col">
        {sources.map((s) => (
          <SourceRow key={s.id} source={s} />
        ))}
      </div>
    </section>
  )
}

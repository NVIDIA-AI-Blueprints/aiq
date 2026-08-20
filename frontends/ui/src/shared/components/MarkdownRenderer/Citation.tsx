// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client'

import { type ReactNode, useId, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { SourceKindIcon } from '@/shared/components/Sources/SourceKindIcon'
import type { SourceRef } from '@/shared/components/Sources/types'

interface CitationProps {
  n: number
  sources: SourceRef[]
}

const MARK =
  'text-secondary hover:text-[color:var(--color-green-500)] ml-px cursor-pointer align-super text-[0.8rem] font-medium leading-none no-underline transition-colors'

/**
 * Inline numbered citation, rendered as a true superscript reference mark.
 * Resolves to a source by its real `[N]` marker index and, when found, reveals a
 * hover/focus popover with the source kind, title, and snippet. A citation
 * number with no matching source degrades to a bare mark; a non-numeric value
 * renders the original bracketed text unchanged.
 */
export function Citation({ n, sources }: CitationProps): ReactNode {
  const [open, setOpen] = useState(false)
  const tooltipId = useId()

  if (!Number.isFinite(n) || n < 1) return <>[{Number.isFinite(n) ? n : ''}]</>

  const src = sources.find((s) => s.index === n)
  const chip = (
    <a
      href={src?.url}
      target={src?.url ? '_blank' : undefined}
      rel={src?.url ? 'noopener noreferrer' : undefined}
      tabIndex={src?.url ? undefined : 0}
      className={MARK}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      aria-label={src ? `Source ${n}: ${src.label}` : `Source ${n}`}
      aria-describedby={src && open ? tooltipId : undefined}
    >
      <sup>{n}</sup>
    </a>
  )

  if (!src) return chip

  return (
    <span className="relative inline-block">
      {chip}
      <AnimatePresence>
        {open && (
          <motion.span
            id={tooltipId}
            role="tooltip"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            transition={{ duration: 0.15 }}
            className="bg-surface-raised border-base absolute bottom-full left-0 z-50 mb-1 block w-72 rounded-lg border p-3 shadow-lg"
          >
            <span className="text-secondary flex items-center gap-1.5 text-xs">
              <SourceKindIcon kind={src.kind} /> {src.label}
            </span>
            <span className="text-primary mt-1 line-clamp-2 block text-sm font-medium">{src.title}</span>
            {src.snippet && <span className="text-subtle mt-1 line-clamp-4 block text-xs">{src.snippet}</span>}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  )
}

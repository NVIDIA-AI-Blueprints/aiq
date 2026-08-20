// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * CollapsibleBlock
 *
 * The shared header + body disclosure used by agent surfaces (thinking trace,
 * plan/approval blocks). A header button toggles an AnimatePresence height /
 * opacity body so every block opens and closes with the same motion and reads
 * uniform regardless of which surface renders it. Controlled: the parent owns
 * the `open` state and is notified via `onOpenChange`.
 */

'use client'

import type { FC, ReactNode } from 'react'
import { useId } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Flex, AnimatedChevron } from '@/adapters/ui'
import { useReducedMotion } from '@/hooks/use-reduced-motion'

export interface CollapsibleBlockProps {
  /** Leading glyph rendered before the title (status atom, source icon, etc.). */
  icon?: ReactNode
  /** Primary header label. */
  title: ReactNode
  /** Trailing header content (counts, durations, the collapse affordance). */
  meta?: ReactNode
  /** Controlled open state. */
  open: boolean
  /** Notified when the header toggles (only when `collapsible`). */
  onOpenChange?: (open: boolean) => void
  /** When false the block renders static (no toggle, body always shown). */
  collapsible?: boolean
  children: ReactNode
}

export const CollapsibleBlock: FC<CollapsibleBlockProps> = ({
  icon,
  title,
  meta,
  open,
  onOpenChange,
  collapsible = true,
  children,
}) => {
  const regionId = useId()
  const prefersReducedMotion = useReducedMotion()
  const header = (
    <>
      <Flex align="center" gap="2" className="min-w-0">
        {icon != null && <span className="grid h-7 w-7 shrink-0 place-items-center">{icon}</span>}
        {title}
      </Flex>
      {(meta != null || collapsible) && (
        <Flex align="center" gap="1" className="shrink-0">
          {meta}
          {collapsible && <AnimatedChevron />}
        </Flex>
      )}
    </>
  )

  return (
    <div className="w-full py-1">
      {collapsible ? (
        <button
          type="button"
          onClick={() => onOpenChange?.(!open)}
          aria-expanded={open}
          aria-controls={open ? regionId : undefined}
          className="group flex w-full items-center justify-between rounded-[var(--radius-card)] py-1.5 text-left transition-colors"
        >
          {header}
        </button>
      ) : (
        <div className="flex w-full items-center justify-between py-1.5">{header}</div>
      )}

      <AnimatePresence initial={false}>
        {(open || !collapsible) && (
          <motion.div
            id={regionId}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={prefersReducedMotion ? { duration: 0 } : { duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            {children}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

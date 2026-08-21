// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/shared/lib/cn'

/**
 * Visual tone of a {@link Card}. Status tones (`active`/`success`/`error`) and
 * source tones (`web`/`doc`) add an accent without changing the base surface, so
 * every card in the chat UI shares one shape and radius.
 */
export type CardTone = 'default' | 'active' | 'success' | 'error' | 'web' | 'doc'

const TONE_CLASS: Record<CardTone, string> = {
  default: 'border-base',
  active: 'border-[color:var(--color-brand)]',
  success: 'border-[color:var(--color-green-500)]',
  error: 'border-[color:var(--border-color-feedback-danger)]',
  web: 'border-base border-l-2 border-l-[color:var(--text-color-subtle)]',
  doc: 'border-base border-l-2 border-l-[color:var(--text-color-base)]',
}

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  tone?: CardTone
}

/**
 * Single surface primitive used across the chat UI. Replaces the ad-hoc
 * `rounded-lg border bg-surface-*` blocks so cards are visually consistent.
 */
export function Card({ tone = 'default', className, children, ...rest }: CardProps): ReactNode {
  return (
    <div
      className={cn('bg-surface-raised rounded-[var(--radius-card)] border p-4', TONE_CLASS[tone], className)}
      {...rest}
    >
      {children}
    </div>
  )
}

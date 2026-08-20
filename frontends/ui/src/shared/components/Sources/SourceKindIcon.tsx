// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from 'react'
import type { SourceKind } from './types'

interface Props {
  kind: SourceKind
  className?: string
}

/**
 * Compact inline icon for a source's origin. Uses `currentColor` so callers
 * control the accent. Self-contained SVGs to keep source typing free of external
 * icon dependencies.
 */
export function SourceKindIcon({ kind, className = 'h-3.5 w-3.5' }: Props): ReactNode {
  const common = { className, viewBox: '0 0 16 16', fill: 'none', stroke: 'currentColor', strokeWidth: 1.4 }
  if (kind === 'web') {
    return (
      <svg {...common} aria-hidden="true">
        <circle cx="8" cy="8" r="5.5" />
        <path d="M2.5 8h11M8 2.5c1.8 1.8 1.8 9.2 0 11M8 2.5c-1.8 1.8-1.8 9.2 0 11" />
      </svg>
    )
  }
  return (
    <svg {...common} aria-hidden="true">
      <path d="M4 2.5h5l3 3V13a.5.5 0 0 1-.5.5h-7A.5.5 0 0 1 4 13z" />
      <path d="M9 2.5v3h3" />
    </svg>
  )
}

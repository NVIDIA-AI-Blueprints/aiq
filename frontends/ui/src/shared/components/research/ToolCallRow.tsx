// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { FC } from 'react'
import { Text } from '@/adapters/ui'
import { SourceKindIcon } from '@/shared/components/Sources/SourceKindIcon'
import { StatusDot, type NodeState } from './StatusDot'
import { getToolLabel } from './research-labels'

/**
 * One tool / model call in an agent trace: a status atom, the source-kind glyph,
 * the human label, and an optional truncated summary of the call's input. Shared
 * verbatim by the inline chat trace and the research panel so a tool call reads
 * the same wherever it shows up. `label` overrides the derived human label (used
 * by group headers that summarize several calls under one family name) while
 * keeping the source-kind glyph driven by `name`.
 */
export const ToolCallRow: FC<{
  name: string
  status: NodeState
  args?: string
  size?: 'sm' | 'xs'
  label?: string
}> = ({ name, status, args, size = 'sm', label: labelOverride }) => {
  const { label: derivedLabel, kind } = getToolLabel(name)
  const label = labelOverride ?? derivedLabel
  return (
    <div className="tool-call-row grid min-w-0 grid-cols-[1.25rem_1rem_minmax(0,1fr)] items-start gap-x-2">
      <span className="tool-call-row-dot grid place-items-center">
        <StatusDot state={status} size={size} />
      </span>
      <span className="text-secondary mt-px shrink-0">
        <SourceKindIcon kind={kind} />
      </span>
      <div className="flex min-w-0 flex-col">
        <Text
          kind="body/regular/sm"
          className="tool-call-row-label text-primary truncate font-medium"
        >
          {label}
        </Text>
        {args && (
          <Text kind="body/regular/xs" className="tool-call-row-args break-words">
            {args}
          </Text>
        )}
      </div>
    </div>
  )
}

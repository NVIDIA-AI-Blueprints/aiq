// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { FC } from 'react'
import { cn } from '@/shared/lib/cn'

/**
 * Lifecycle state of an agent-trace node. Drives the single status atom used by
 * both the inline chat trace and the research panel, so a node looks identical
 * wherever it appears.
 */
export type NodeState = 'running' | 'done' | 'pending' | 'waiting' | 'interrupted' | 'error'

/** A single status atom: the only source of truth for every node's look. */
export const StatusDot: FC<{ state: NodeState; size?: 'sm' | 'xs' }> = ({ state, size = 'sm' }) => (
  <span
    className={cn('status-dot', `status-dot-${state}`, size === 'xs' && 'status-dot-xs')}
    aria-hidden="true"
  />
)

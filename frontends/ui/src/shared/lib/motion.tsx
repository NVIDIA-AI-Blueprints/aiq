// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client'

import type { ReactNode } from 'react'
import { MotionConfig } from 'motion/react'
import { useReducedMotion } from '@/hooks/use-reduced-motion'

/**
 * Centralizes Motion configuration so every animation honors the user's
 * `prefers-reduced-motion` setting. Mount once near the application root.
 */
export function AppMotionConfig({ children }: { children: ReactNode }): ReactNode {
  const reduce = useReducedMotion()

  return <MotionConfig reducedMotion={reduce ? 'always' : 'never'}>{children}</MotionConfig>
}

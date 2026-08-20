// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from 'react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { render, screen } from '@/test-utils'
import { AppMotionConfig } from './motion'

const useReducedMotion = vi.hoisted(() => vi.fn(() => false))
vi.mock('@/hooks/use-reduced-motion', () => ({ useReducedMotion }))

const captured = vi.hoisted(() => ({ reducedMotion: undefined as string | undefined }))
vi.mock('motion/react', () => ({
  MotionConfig: ({ reducedMotion, children }: { reducedMotion?: string; children: ReactNode }) => {
    captured.reducedMotion = reducedMotion
    return children
  },
}))

describe('AppMotionConfig', () => {
  afterEach(() => {
    vi.clearAllMocks()
    captured.reducedMotion = undefined
  })

  test('maps allowed motion to reducedMotion="never"', () => {
    useReducedMotion.mockReturnValue(false)
    render(
      <AppMotionConfig>
        <span>content</span>
      </AppMotionConfig>,
    )
    expect(screen.getByText('content')).toBeInTheDocument()
    expect(captured.reducedMotion).toBe('never')
  })

  test('maps a reduced-motion preference to reducedMotion="always"', () => {
    useReducedMotion.mockReturnValue(true)
    render(
      <AppMotionConfig>
        <span>reduced</span>
      </AppMotionConfig>,
    )
    expect(screen.getByText('reduced')).toBeInTheDocument()
    expect(captured.reducedMotion).toBe('always')
  })
})

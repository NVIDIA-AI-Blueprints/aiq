// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest'

import { STICK_TO_BOTTOM_THRESHOLD_PX, isPinnedToBottom } from './scroll'

describe('isPinnedToBottom', () => {
  it('is pinned when scrolled exactly to the bottom', () => {
    // scrollTop at its max (scrollHeight - clientHeight) => distance 0
    expect(isPinnedToBottom(800, 1000, 200)).toBe(true)
  })

  it('is pinned when within the default threshold of the bottom', () => {
    // distance = 1000 - 700 - 200 = 100 <= 120
    expect(isPinnedToBottom(700, 1000, 200)).toBe(true)
  })

  it('is NOT pinned when scrolled up beyond the threshold', () => {
    // distance = 1000 - 600 - 200 = 200 > 120
    expect(isPinnedToBottom(600, 1000, 200)).toBe(false)
  })

  it('is pinned when content does not overflow the viewport', () => {
    // scrollHeight <= clientHeight => distance is non-positive
    expect(isPinnedToBottom(0, 200, 200)).toBe(true)
    expect(isPinnedToBottom(0, 150, 200)).toBe(true)
  })

  it('treats the boundary at exactly the threshold as pinned', () => {
    // distance = 1000 - 680 - 200 = 120 === threshold
    expect(isPinnedToBottom(680, 1000, 200, STICK_TO_BOTTOM_THRESHOLD_PX)).toBe(true)
    // one pixel further up => not pinned
    expect(isPinnedToBottom(679, 1000, 200, STICK_TO_BOTTOM_THRESHOLD_PX)).toBe(false)
  })

  it('honors a custom threshold', () => {
    // distance = 50; not pinned with a tight 10px threshold, pinned with 60px
    expect(isPinnedToBottom(750, 1000, 200, 10)).toBe(false)
    expect(isPinnedToBottom(750, 1000, 200, 60)).toBe(true)
  })
})

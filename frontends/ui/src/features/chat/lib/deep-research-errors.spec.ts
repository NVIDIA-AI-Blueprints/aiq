// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'
import {
  getDeepResearchJobLoadFailureKind,
  isUnavailableDeepResearchJobError,
} from './deep-research-errors'

describe('deep research error classification', () => {
  test.each([
    'Failed to get job status: 404',
    'Failed to get job status: 410',
    'Job expired',
    'Job deleted',
    'Job not found',
  ])('classifies unavailable jobs as expired or deleted: %s', (message) => {
    const error = new Error(message)

    expect(getDeepResearchJobLoadFailureKind(error)).toBe('unavailable')
    expect(isUnavailableDeepResearchJobError(error)).toBe(true)
  })

  test.each([
    'Failed to get job status: 500 - PROXY_ERROR: fetch failed',
    'TypeError: Failed to fetch',
    'fetch failed',
    'ECONNREFUSED 127.0.0.1:8000',
    'NetworkError when attempting to fetch resource.',
  ])('classifies proxy and network failures as backend unreachable: %s', (message) => {
    const error = new Error(message)

    expect(getDeepResearchJobLoadFailureKind(error)).toBe('backend_unreachable')
    expect(isUnavailableDeepResearchJobError(error)).toBe(false)
  })

  test('keeps generic 500 errors distinct from unreachable backend failures', () => {
    expect(getDeepResearchJobLoadFailureKind(new Error('Failed to get job status: 500'))).toBe(
      'other'
    )
  })
})

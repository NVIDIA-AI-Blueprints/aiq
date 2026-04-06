// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, test } from 'vitest'

import {
  isLikelyAuthRelatedTransportError,
  isDeepResearchReplayCompleteMode,
} from './transport-auth-signals'

describe('isLikelyAuthRelatedTransportError', () => {
  test.each([
    ['HTTP 401 response', 'Upstream returned 401 Unauthorized'],
    ['unauthorized keyword', 'Request was unauthorized'],
    ['token expired', 'token has expired'],
    ['token invalid', 'token is invalid'],
    ['token missing', 'token missing from request'],
    ['session expired', 'session expired'],
    ['session invalid', 'session invalid or revoked'],
    ['authentication keyword', 'authentication failed'],
    ['mixed case', 'Token Expired due to timeout'],
    ['401 in longer message', 'WebSocket closed: 401 Unauthorized - check credentials'],
  ])('returns true for auth-shaped error: %s', (_label, text) => {
    expect(isLikelyAuthRelatedTransportError(text)).toBe(true)
  })

  test.each([
    ['network error', 'Network connection timed out'],
    ['generic server error', 'Internal server error 500'],
    ['DNS failure', 'ENOTFOUND backend.example.com'],
    ['connection refused', 'Connection refused'],
    ['SSE retry', 'SSE connection failed after retries'],
    ['empty string', ''],
    ['random text', 'Something went wrong, please try again'],
    ['403 forbidden (RBAC, not auth)', 'HTTP 403 Forbidden'],
    ['permission denied', 'You do not have permission to access this resource'],
  ])('returns false for non-auth error: %s', (_label, text) => {
    expect(isLikelyAuthRelatedTransportError(text)).toBe(false)
  })
})

describe('isDeepResearchReplayCompleteMode', () => {
  test('returns true for live mode', () => {
    expect(isDeepResearchReplayCompleteMode('live')).toBe(true)
  })

  test('returns true for pubsub mode', () => {
    expect(isDeepResearchReplayCompleteMode('pubsub')).toBe(true)
  })

  test('returns false for polling mode', () => {
    expect(isDeepResearchReplayCompleteMode('polling')).toBe(false)
  })

  test('returns false for unknown mode', () => {
    expect(isDeepResearchReplayCompleteMode('unknown')).toBe(false)
  })

  test('returns false for empty string', () => {
    expect(isDeepResearchReplayCompleteMode('')).toBe(false)
  })
})

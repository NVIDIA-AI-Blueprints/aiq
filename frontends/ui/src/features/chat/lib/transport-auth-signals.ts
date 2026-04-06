// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Heuristics for detecting auth-related transport failures.
 *
 * WebSocket and SSE transports surface opaque errors when the backend
 * rejects a request due to missing or invalid auth. These helpers let
 * the UI hooks distinguish "backend is down" from "auth drifted" so
 * users see an actionable "session expired" message instead of silence.
 */

const AUTH_ERROR_PATTERNS = [
  /\b401\b/i,
  /\bunauthorized\b/i,
  /\btoken.*(expired|invalid|missing)\b/i,
  /\bsession.*(expired|invalid)\b/i,
  /\bauthenticat/i,
]

/**
 * Returns true if the error text looks like it was caused by an
 * authentication or authorization failure rather than a network issue.
 */
export const isLikelyAuthRelatedTransportError = (text: string): boolean => {
  return AUTH_ERROR_PATTERNS.some((pattern) => pattern.test(text))
}

/**
 * Returns true if the given stream.mode value indicates that SSE replay
 * catch-up is complete and the stream has switched to live events.
 */
export const isDeepResearchReplayCompleteMode = (mode: string): boolean => {
  return mode === 'live' || mode === 'pubsub'
}

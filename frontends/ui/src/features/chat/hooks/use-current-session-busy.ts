// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * useIsCurrentSessionBusy Hook
 *
 * Hook to check if the CURRENT session has active operations.
 * Used to disable file operations, data source changes, exports, and session
 * management during:
 * - Shallow thinking (WebSocket streaming)
 * - Deep research (SSE streaming or non-terminal job status)
 * - HITL interactions (pending user response)
 *
 * This hook checks BOTH ephemeral state (fast path for normal operation) AND
 * persisted state from message history (safety net for page refresh recovery).
 *
 * For per-session checks (e.g., session deletion), use store.isSessionBusy() instead.
 */

'use client'

import { useChatStore } from '../store'
import { hasActiveDeepResearchJob } from '../lib/session-activity'

/**
 * Check if the current session has active operations.
 * Returns true if any of the following are true:
 *
 * Ephemeral state (fast path — covers normal operation):
 * 1. WebSocket is streaming (shallow thinking)
 * 2. Deep research SSE is actively streaming AND owned by the current session
 * 3. Deep research job is in a non-terminal ephemeral state AND owned by the current session
 *
 * Persisted state (safety net — covers page refresh gap):
 * 4. Message history has an in-progress deep research job
 * 5. A HITL interaction is pending user response
 *
 * @returns true if current session is busy with operations
 */
export const useIsCurrentSessionBusy = (): boolean => {
  // --- Ephemeral state (fast path, covers normal operation) ---
  const isStreaming = useChatStore((state) => state.isStreaming)
  const isDeepResearchStreaming = useChatStore((state) => state.isDeepResearchStreaming)
  const deepResearchStatus = useChatStore((state) => state.deepResearchStatus)

  // Deep research streams in the background owned by the session that started
  // it, and its streaming flag / status are global store values, so scope them
  // to the owning session before counting them as current-session activity.
  const ownsDeepResearch = useChatStore(
    (state) =>
      state.deepResearchOwnerConversationId !== null &&
      state.deepResearchOwnerConversationId === state.currentConversation?.id
  )

  // --- Persisted state (safety net, covers page refresh) ---

  // Check persisted message history for active deep research jobs.
  // Returns boolean — Zustand only re-renders when the value changes.
  const hasActiveJobInHistory = useChatStore((state) => {
    if (!state.currentConversation) return false
    return hasActiveDeepResearchJob(state.currentConversation.messages)
  })

  // Check persisted HITL pending interaction (already in partialize)
  const hasPendingInteraction = useChatStore((state) => state.pendingInteraction !== null)

  return (
    // Ephemeral: WebSocket streaming (shallow thinking)
    isStreaming ||
    // Ephemeral: this session's own deep research SSE is actively streaming
    (ownsDeepResearch && isDeepResearchStreaming) ||
    // Ephemeral: this session's own deep research job in a non-terminal state
    (ownsDeepResearch &&
      deepResearchStatus !== null &&
      ['submitted', 'running'].includes(deepResearchStatus)) ||
    // Persisted: Deep research job detected in message history (covers refresh gap)
    hasActiveJobInHistory ||
    // Persisted: HITL prompt waiting for user response
    hasPendingInteraction
  )
}

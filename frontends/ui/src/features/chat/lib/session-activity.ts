// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Session Activity Utilities
 *
 * Pure functions to derive session activity state from PERSISTED data.
 * These survive page refresh because they read from localStorage-backed
 * conversation message history rather than ephemeral store fields.
 *
 * Used by:
 * - useIsCurrentSessionBusy hook (current session check)
 * - isSessionBusy store method (per-session check)
 * - hasAnyBusySession store method (global check)
 */

import type { ChatMessage, DeepResearchJobStatus } from '../types'

/** Non-terminal deep research statuses that indicate an active server-side job */
const ACTIVE_JOB_STATUSES: readonly DeepResearchJobStatus[] = ['submitted', 'running']

/**
 * Check if a conversation has an in-progress deep research job in its message history.
 *
 * Scans messages in reverse (most recent first) to find the latest agent_response
 * with a deep research job. Returns true if that job is in a non-terminal state.
 *
 * Performance: O(1) in practice since job messages are always near the end.
 *
 * @param messages - The conversation's message array (from persisted state)
 * @returns true if the most recent deep research job is still running
 */
export const hasActiveDeepResearchJob = (messages: ChatMessage[]): boolean => {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (
      m.messageType === 'agent_response' &&
      m.deepResearchJobId &&
      m.deepResearchJobStatus
    ) {
      return (ACTIVE_JOB_STATUSES as readonly string[]).includes(m.deepResearchJobStatus)
    }
  }
  return false
}

/**
 * Activity flags derived entirely from persisted data.
 * All flags survive page refresh.
 */
export interface SessionActivityFlags {
  /** Server-side deep research job is running (derived from message history) */
  hasActiveDeepResearch: boolean
  /** HITL prompt is waiting for user response (from persisted pendingInteraction) */
  hasPendingHITL: boolean
}

/**
 * Derive all activity flags for the current session from persisted state.
 * This is the single source of truth for "is this session busy" after a page refresh.
 *
 * @param messages - Current conversation's message array
 * @param pendingInteraction - The persisted pending HITL interaction (or null)
 * @returns Activity flags derived from persisted data
 */
export const getPersistedActivityFlags = (
  messages: ChatMessage[],
  pendingInteraction: unknown | null
): SessionActivityFlags => ({
  hasActiveDeepResearch: hasActiveDeepResearchJob(messages),
  hasPendingHITL: pendingInteraction !== null,
})

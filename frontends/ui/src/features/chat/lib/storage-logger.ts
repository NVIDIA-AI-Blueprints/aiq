// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Storage Logger
 *
 * Centralized logging utilities for localStorage operations in chat store.
 * Helps debug intermittent session clearing issues.
 */

import type { Conversation } from '../types'

const LOG_PREFIX = '[SessionsStore]'

/**
 * Calculate approximate size of data in KB
 */
const calculateDataSize = (data: unknown): number => {
  try {
    const jsonString = JSON.stringify(data)
    return Math.round((jsonString.length * 2) / 1024) // UTF-16 uses 2 bytes per char
  } catch {
    return 0
  }
}

/**
 * Format timestamp for logs
 */
const getTimestamp = (): string => {
  return new Date().toISOString()
}

/**
 * Log successful localStorage write (dev-only)
 */
export const logStorageWrite = (conversations: Conversation[], userId: string | null): void => {
  if (process.env.NODE_ENV !== 'development') return

  const sizeKB = calculateDataSize(conversations)
  const sessionCount = conversations.length

  console.debug(`${LOG_PREFIX} localStorage write: ${sessionCount} sessions, ${sizeKB}KB`, {
    userId,
    sessionIds: conversations.map((c) => c.id),
    timestamp: getTimestamp(),
  })
}

/**
 * Log quota exceeded error with pruning attempt (dev-only)
 */
export const logQuotaExceededPruning = (
  beforeCount: number,
  afterCount: number,
  beforeSizeKB: number,
  afterSizeKB: number
): void => {
  if (process.env.NODE_ENV !== 'development') return

  console.warn(
    `${LOG_PREFIX} ⚠️ QUOTA EXCEEDED - Pruning sessions`,
    {
      before: { sessions: beforeCount, sizeKB: beforeSizeKB },
      after: { sessions: afterCount, sizeKB: afterSizeKB },
      timestamp: getTimestamp(),
    }
  )
}

/**
 * Log successful pruning (dev-only)
 */
export const logPruningSuccess = (
  beforeCount: number,
  afterCount: number,
  beforeSizeKB: number,
  afterSizeKB: number
): void => {
  if (process.env.NODE_ENV !== 'development') return

  console.debug(
    `${LOG_PREFIX} Pruned sessions: ${beforeCount} → ${afterCount}, ${beforeSizeKB}KB → ${afterSizeKB}KB`,
    {
      timestamp: getTimestamp(),
    }
  )
}

/**
 * Log critical error: all sessions cleared (ALWAYS logged, even in production)
 */
export const logCriticalSessionsClear = (
  userId: string | null,
  lostSessionIds: string[],
  error: unknown
): void => {
  // ALWAYS log this - it's a critical data loss event
  console.error(`${LOG_PREFIX} ❌ CRITICAL: All sessions cleared due to quota exceeded`, {
    userId,
    lostSessions: lostSessionIds,
    sessionCount: lostSessionIds.length,
    timestamp: getTimestamp(),
    error: error instanceof Error ? error.message : String(error),
  })
}

/**
 * Log storage event from another tab or extension (dev-only)
 */
export const logExternalStorageEvent = (
  key: string | null,
  oldValue: string | null,
  newValue: string | null
): void => {
  if (process.env.NODE_ENV !== 'development') return

  console.warn(`${LOG_PREFIX} 🔍 Storage event detected: external modification`, {
    key,
    cleared: oldValue !== null && newValue === null,
    modified: oldValue !== null && newValue !== null,
    timestamp: getTimestamp(),
  })
}

/**
 * Log store hydration on initialization (dev-only)
 */
export const logStoreHydration = (
  success: boolean,
  sessionCount: number,
  userId: string | null
): void => {
  if (process.env.NODE_ENV !== 'development') return

  if (success) {
    console.debug(`${LOG_PREFIX} Store hydrated from localStorage: ${sessionCount} sessions`, {
      userId,
      timestamp: getTimestamp(),
    })
  } else {
    console.warn(`${LOG_PREFIX} Store hydration failed - starting with empty state`, {
      timestamp: getTimestamp(),
    })
  }
}

/**
 * Log localStorage availability check (dev-only)
 */
export const logStorageAvailability = (available: boolean): void => {
  if (process.env.NODE_ENV !== 'development') return

  if (!available) {
    console.warn(`${LOG_PREFIX} localStorage not available - persistence disabled`, {
      timestamp: getTimestamp(),
    })
  }
}

/**
 * Log when pruning fails and we have to clear everything (ALWAYS logged)
 */
export const logPruningFailure = (error: unknown): void => {
  // ALWAYS log - this leads to data loss
  console.error(`${LOG_PREFIX} ❌ Pruning failed - will attempt to clear all sessions`, {
    timestamp: getTimestamp(),
    error: error instanceof Error ? error.message : String(error),
  })
}

/**
 * Log automatic session cleanup (ALWAYS logged - important for debugging)
 */
export const logStorageCleanup = (
  deletedSessions: string[],
  freedMB: number,
  beforeMB: number,
  afterMB: number
): void => {
  // ALWAYS log - this helps diagnose unexpected session loss
  console.warn(`${LOG_PREFIX} 🧹 Auto-cleanup: Deleted ${deletedSessions.length} old sessions`, {
    deletedSessionIds: deletedSessions,
    freedSpaceMB: freedMB.toFixed(2),
    beforeStorageMB: beforeMB.toFixed(2),
    afterStorageMB: afterMB.toFixed(2),
    timestamp: getTimestamp(),
  })
}

/**
 * Log storage capacity check (dev-only)
 */
export const logStorageCapacity = (
  currentMB: number,
  quotaMB: number,
  percentUsed: number,
  isHealthy: boolean
): void => {
  if (process.env.NODE_ENV !== 'development') return

  const emoji = isHealthy ? '✓' : '⚠️'
  console.debug(
    `${LOG_PREFIX} ${emoji} Storage: ${currentMB.toFixed(2)}MB / ${quotaMB}MB (${percentUsed.toFixed(0)}%)`,
    {
      timestamp: getTimestamp(),
    }
  )
}

/**
 * Log storage capacity warning (ALWAYS logged when over threshold)
 */
export const logStorageWarning = (
  currentMB: number,
  thresholdMB: number,
  sessionCount: number
): void => {
  // ALWAYS log - helps users understand why cleanup is happening
  console.warn(
    `${LOG_PREFIX} ⚠️ Storage approaching limit: ${currentMB.toFixed(2)}MB (threshold: ${thresholdMB}MB)`,
    {
      currentStorageMB: currentMB.toFixed(2),
      thresholdMB,
      sessionCount,
      message: 'Oldest sessions will be auto-deleted to free space',
      timestamp: getTimestamp(),
    }
  )
}

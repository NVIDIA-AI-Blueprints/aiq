// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Storage Manager
 *
 * Manages localStorage capacity by tracking size and automatically cleaning up
 * old sessions when approaching quota limits (5MB in most browsers).
 */

import type { Conversation } from '../types'
import { logStorageCapacity, logStorageWarning, logStorageCleanup } from './storage-logger'

/** localStorage quota limit in MB (conservative estimate across browsers) */
const STORAGE_QUOTA_MB = 4.8

/** Warning threshold in MB — triggers cleanup when exceeded (0.6 MB headroom to quota) */
const WARNING_THRESHOLD_MB = 4.2

/** Target size after cleanup in MB */
const TARGET_SIZE_MB = 3.5

/** Storage key for chat store */
const STORAGE_KEY = 'aiq-chat-store'

/**
 * Calculate the size of a specific localStorage key in bytes
 */
const getKeySize = (key: string): number => {
  try {
    const value = localStorage.getItem(key)
    if (!value) return 0
    // UTF-16 uses 2 bytes per character
    return value.length * 2
  } catch {
    return 0
  }
}

/**
 * Calculate total localStorage usage in bytes
 */
export const calculateTotalStorageSize = (): number => {
  try {
    let total = 0
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (key) {
        total += getKeySize(key)
      }
    }
    return total
  } catch {
    return 0
  }
}

/**
 * Calculate the size of the chat store in bytes
 */
export const calculateChatStoreSize = (): number => {
  return getKeySize(STORAGE_KEY)
}

/**
 * Convert bytes to megabytes
 */
const bytesToMB = (bytes: number): number => {
  return bytes / (1024 * 1024)
}

/**
 * Check if storage is healthy (below warning threshold)
 */
export const checkStorageHealth = (): {
  isHealthy: boolean
  currentMB: number
  percentUsed: number
} => {
  const totalBytes = calculateTotalStorageSize()
  const currentMB = bytesToMB(totalBytes)
  const percentUsed = (currentMB / STORAGE_QUOTA_MB) * 100

  return {
    isHealthy: currentMB < WARNING_THRESHOLD_MB,
    currentMB,
    percentUsed,
  }
}

/**
 * Get chat store data from localStorage
 */
const getChatStoreData = (): { conversations: Conversation[]; currentConversationId: string | null } | null => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (!stored) return null

    const parsed = JSON.parse(stored)
    return {
      conversations: parsed.state?.conversations ?? [],
      currentConversationId: parsed.state?.currentConversation?.id ?? null,
    }
  } catch {
    return null
  }
}

/**
 * Save chat store data back to localStorage
 */
const saveChatStoreData = (
  conversations: Conversation[],
  currentConversationId: string | null
): void => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (!stored) return

    const parsed = JSON.parse(stored)
    const currentConversation = conversations.find((c) => c.id === currentConversationId) ?? null

    parsed.state = {
      ...parsed.state,
      conversations,
      currentConversation,
    }

    localStorage.setItem(STORAGE_KEY, JSON.stringify(parsed))
  } catch (error) {
    console.error('[SessionsStore] Failed to save after cleanup:', error)
  }
}

/**
 * Get the oldest session by updatedAt timestamp (excluding current session)
 */
export const getOldestSession = (
  conversations: Conversation[],
  currentConversationId: string | null
): Conversation | null => {
  const eligibleSessions = conversations.filter((c) => c.id !== currentConversationId)

  if (eligibleSessions.length === 0) return null

  return eligibleSessions.reduce((oldest, current) => {
    const oldestTime = new Date(oldest.updatedAt as unknown as string).getTime()
    const currentTime = new Date(current.updatedAt as unknown as string).getTime()
    return currentTime < oldestTime ? current : oldest
  })
}

/**
 * Clean up old sessions until storage is below target size
 *
 * @param currentConversationId - ID of current session to protect from deletion
 * @returns Number of sessions deleted
 */
export const cleanupOldSessions = (currentConversationId: string | null): number => {
  const data = getChatStoreData()
  if (!data) return 0

  let { conversations } = data
  const deletedSessionIds: string[] = []
  const beforeMB = bytesToMB(calculateTotalStorageSize())

  // Keep deleting oldest sessions until we're below target size
  while (bytesToMB(calculateTotalStorageSize()) > TARGET_SIZE_MB) {
    const oldestSession = getOldestSession(conversations, currentConversationId)

    // No more sessions to delete (only current session remains or no sessions)
    if (!oldestSession) break

    // Delete the oldest session
    conversations = conversations.filter((c) => c.id !== oldestSession.id)
    deletedSessionIds.push(oldestSession.id)

    // Save updated conversations back to localStorage
    saveChatStoreData(conversations, currentConversationId)

    // Safety: don't delete more than 10 sessions in one cleanup
    if (deletedSessionIds.length >= 10) break
  }

  // Log cleanup if any sessions were deleted
  if (deletedSessionIds.length > 0) {
    const afterMB = bytesToMB(calculateTotalStorageSize())
    const freedMB = beforeMB - afterMB
    logStorageCleanup(deletedSessionIds, freedMB, beforeMB, afterMB)
  }

  return deletedSessionIds.length
}

/**
 * Ensure storage capacity before creating a new session.
 * Automatically cleans up old sessions if storage is approaching limits.
 *
 * Call this at the start of ensureSession() in the store.
 *
 * @param currentConversationId - ID of current session to protect
 */
export const ensureStorageCapacity = (currentConversationId: string | null): void => {
  const health = checkStorageHealth()

  // Log current capacity (dev-only)
  logStorageCapacity(health.currentMB, STORAGE_QUOTA_MB, health.percentUsed, health.isHealthy)

  // If storage is healthy, nothing to do
  if (health.isHealthy) return

  // Storage is over threshold - warn and cleanup
  const data = getChatStoreData()
  const sessionCount = data?.conversations.length ?? 0

  logStorageWarning(health.currentMB, WARNING_THRESHOLD_MB, sessionCount)

  // Trigger cleanup
  const deletedCount = cleanupOldSessions(currentConversationId)

  // If no sessions were deleted but storage is still over threshold,
  // this means the current session itself is too large
  if (deletedCount === 0 && !checkStorageHealth().isHealthy) {
    console.warn(
      '[SessionsStore] ⚠️ Current session is too large - message pruning will occur on next save',
      {
        currentMB: health.currentMB,
        sessionCount,
      }
    )
  }
}

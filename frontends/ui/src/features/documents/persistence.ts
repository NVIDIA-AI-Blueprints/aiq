// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * File Upload Persistence
 *
 * Utilities for persisting active file upload jobs to localStorage
 * so progress can survive page refreshes.
 */

import type { TrackedFile } from './types'

const STORAGE_KEY = 'documents_active_jobs'

/** Persisted job info for resuming polling after refresh */
export interface PersistedJob {
  /** Ingestion job ID */
  jobId: string
  /** Collection/session this job belongs to */
  collectionName: string
  /** Files being tracked for this job */
  files: Omit<TrackedFile, 'file'>[]
  /** When this job was started (for cleanup of stale jobs) */
  startedAt: number
}

/** Max age for persisted jobs (30 minutes) - older jobs are considered stale */
const MAX_JOB_AGE_MS = 30 * 60 * 1000

/**
 * Get all persisted active jobs
 */
export const getPersistedJobs = (): PersistedJob[] => {
  try {
    const data = localStorage.getItem(STORAGE_KEY)
    if (!data) return []

    const jobs: PersistedJob[] = JSON.parse(data)

    // Filter out stale jobs (older than MAX_JOB_AGE_MS)
    const now = Date.now()
    const activeJobs = jobs.filter((job) => now - job.startedAt < MAX_JOB_AGE_MS)

    // Clean up stale jobs from storage
    if (activeJobs.length !== jobs.length) {
      savePersistedJobs(activeJobs)
    }

    return activeJobs
  } catch {
    return []
  }
}

/**
 * Get persisted job for a specific collection
 */
export const getPersistedJobForCollection = (collectionName: string): PersistedJob | null => {
  const jobs = getPersistedJobs()
  return jobs.find((job) => job.collectionName === collectionName) || null
}

/**
 * Save all persisted jobs
 */
const savePersistedJobs = (jobs: PersistedJob[]): void => {
  try {
    if (jobs.length === 0) {
      localStorage.removeItem(STORAGE_KEY)
    } else {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs))
    }
  } catch {
    // Silently fail if localStorage is not available
  }
}

/**
 * Add or update a persisted job
 */
export const persistJob = (
  jobId: string,
  collectionName: string,
  files: TrackedFile[]
): void => {
  const jobs = getPersistedJobs()

  // Remove File objects (not serializable) and create persisted version
  const persistedFiles: Omit<TrackedFile, 'file'>[] = files.map(({ file: _file, ...rest }) => rest)

  const newJob: PersistedJob = {
    jobId,
    collectionName,
    files: persistedFiles,
    startedAt: Date.now(),
  }

  // Replace existing job for this collection or add new
  const existingIndex = jobs.findIndex((j) => j.collectionName === collectionName)
  if (existingIndex >= 0) {
    jobs[existingIndex] = newJob
  } else {
    jobs.push(newJob)
  }

  savePersistedJobs(jobs)
}

/**
 * Update files for a persisted job (called during polling)
 */
export const updatePersistedJobFiles = (jobId: string, files: TrackedFile[]): void => {
  const jobs = getPersistedJobs()
  const jobIndex = jobs.findIndex((j) => j.jobId === jobId)

  if (jobIndex >= 0) {
    const persistedFiles: Omit<TrackedFile, 'file'>[] = files.map(({ file: _file, ...rest }) => rest)
    jobs[jobIndex].files = persistedFiles
    savePersistedJobs(jobs)
  }
}

/**
 * Remove a persisted job (called when polling completes)
 */
export const removePersistedJob = (jobId: string): void => {
  const jobs = getPersistedJobs()
  const filtered = jobs.filter((j) => j.jobId !== jobId)
  savePersistedJobs(filtered)
}

/**
 * Remove persisted job for a collection
 */
export const removePersistedJobForCollection = (collectionName: string): void => {
  const jobs = getPersistedJobs()
  const filtered = jobs.filter((j) => j.collectionName !== collectionName)
  savePersistedJobs(filtered)
}

/**
 * Clear all persisted jobs (for cleanup/debugging)
 */
export const clearAllPersistedJobs = (): void => {
  localStorage.removeItem(STORAGE_KEY)
}

// ============================================================================
// Session Collection Tracking
// ============================================================================
//
// Tracks which sessions are known to have backend collections.
// Prevents unnecessary GET /collections/{sessionId} calls (and 404 errors)
// for sessions that have never had files uploaded.

const COLLECTIONS_STORAGE_KEY = 'documents_sessions_with_collections'

/** Max tracked sessions to prevent unbounded localStorage growth */
const MAX_TRACKED_SESSIONS = 200

/**
 * Get all session IDs known to have backend collections
 */
const getTrackedSessions = (): string[] => {
  try {
    const data = localStorage.getItem(COLLECTIONS_STORAGE_KEY)
    if (!data) return []
    return JSON.parse(data) as string[]
  } catch {
    return []
  }
}

/**
 * Save tracked sessions to localStorage
 */
const saveTrackedSessions = (sessions: string[]): void => {
  try {
    if (sessions.length === 0) {
      localStorage.removeItem(COLLECTIONS_STORAGE_KEY)
    } else {
      localStorage.setItem(COLLECTIONS_STORAGE_KEY, JSON.stringify(sessions))
    }
  } catch {
    // Silently fail if localStorage is not available
  }
}

/**
 * Check if a session is known to have a backend collection.
 * Returns false for sessions that have never had files uploaded.
 */
export const sessionHasKnownCollection = (sessionId: string): boolean => {
  return getTrackedSessions().includes(sessionId)
}

/**
 * Mark a session as having a backend collection.
 * Called when a collection is successfully created or found via API.
 */
export const markSessionHasCollection = (sessionId: string): void => {
  const sessions = getTrackedSessions()

  // Already tracked
  if (sessions.includes(sessionId)) return

  // Add to end (most recent)
  sessions.push(sessionId)

  // Cap at MAX_TRACKED_SESSIONS by removing oldest (front of array)
  while (sessions.length > MAX_TRACKED_SESSIONS) {
    sessions.shift()
  }

  saveTrackedSessions(sessions)
}

/**
 * Remove a session's collection marker.
 * Called when a collection returns 404 (e.g., TTL-expired on backend).
 */
export const unmarkSessionCollection = (sessionId: string): void => {
  const sessions = getTrackedSessions()
  const filtered = sessions.filter((id) => id !== sessionId)
  saveTrackedSessions(filtered)
}

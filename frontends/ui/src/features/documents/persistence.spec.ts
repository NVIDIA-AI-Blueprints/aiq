// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, test, expect, beforeEach, vi, afterEach } from 'vitest'
import {
  getPersistedJobs,
  getPersistedJobForCollection,
  persistJob,
  updatePersistedJobFiles,
  removePersistedJob,
  removePersistedJobForCollection,
  clearAllPersistedJobs,
  sessionHasKnownCollection,
  markSessionHasCollection,
  unmarkSessionCollection,
  type PersistedJob,
} from './persistence'
import type { TrackedFile } from './types'

const STORAGE_KEY = 'documents_active_jobs'

describe('persistence', () => {
  beforeEach(() => {
    // Clear localStorage before each test
    localStorage.clear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  const createTrackedFile = (overrides: Partial<TrackedFile> = {}): TrackedFile => ({
    id: 'file-1',
    fileName: 'test.pdf',
    fileSize: 1024,
    status: 'uploading',
    progress: 0,
    collectionName: 'session-1',
    ...overrides,
  })

  const createPersistedJob = (overrides: Partial<PersistedJob> = {}): PersistedJob => ({
    jobId: 'job-1',
    collectionName: 'session-1',
    files: [{ id: 'file-1', fileName: 'test.pdf', fileSize: 1024, status: 'uploading', progress: 0 }],
    startedAt: Date.now(),
    ...overrides,
  })

  describe('getPersistedJobs', () => {
    test('returns empty array when no jobs stored', () => {
      const jobs = getPersistedJobs()
      expect(jobs).toEqual([])
    })

    test('returns stored jobs', () => {
      const job = createPersistedJob()
      localStorage.setItem(STORAGE_KEY, JSON.stringify([job]))

      const jobs = getPersistedJobs()

      expect(jobs).toHaveLength(1)
      expect(jobs[0].jobId).toBe('job-1')
    })

    test('filters out stale jobs older than 30 minutes', () => {
      const now = Date.now()
      const staleJob = createPersistedJob({
        jobId: 'stale-job',
        startedAt: now - 31 * 60 * 1000, // 31 minutes ago
      })
      const freshJob = createPersistedJob({
        jobId: 'fresh-job',
        startedAt: now - 5 * 60 * 1000, // 5 minutes ago
      })
      localStorage.setItem(STORAGE_KEY, JSON.stringify([staleJob, freshJob]))

      const jobs = getPersistedJobs()

      expect(jobs).toHaveLength(1)
      expect(jobs[0].jobId).toBe('fresh-job')
    })

    test('cleans up stale jobs from storage', () => {
      const now = Date.now()
      const staleJob = createPersistedJob({
        jobId: 'stale-job',
        startedAt: now - 31 * 60 * 1000,
      })
      localStorage.setItem(STORAGE_KEY, JSON.stringify([staleJob]))

      getPersistedJobs()

      // Storage should be cleared since no active jobs remain
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
    })

    test('returns empty array on invalid JSON', () => {
      localStorage.setItem(STORAGE_KEY, 'invalid json')

      const jobs = getPersistedJobs()

      expect(jobs).toEqual([])
    })
  })

  describe('getPersistedJobForCollection', () => {
    test('returns null when no job for collection', () => {
      const job = getPersistedJobForCollection('nonexistent')
      expect(job).toBeNull()
    })

    test('returns job for matching collection', () => {
      const job = createPersistedJob({ collectionName: 'session-123' })
      localStorage.setItem(STORAGE_KEY, JSON.stringify([job]))

      const result = getPersistedJobForCollection('session-123')

      expect(result).not.toBeNull()
      expect(result?.jobId).toBe('job-1')
    })

    test('returns null for non-matching collection', () => {
      const job = createPersistedJob({ collectionName: 'session-123' })
      localStorage.setItem(STORAGE_KEY, JSON.stringify([job]))

      const result = getPersistedJobForCollection('session-456')

      expect(result).toBeNull()
    })
  })

  describe('persistJob', () => {
    test('adds new job to storage', () => {
      const file = createTrackedFile()

      persistJob('job-1', 'session-1', [file])

      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
      expect(stored).toHaveLength(1)
      expect(stored[0].jobId).toBe('job-1')
      expect(stored[0].collectionName).toBe('session-1')
    })

    test('replaces existing job for same collection', () => {
      const existingJob = createPersistedJob({ jobId: 'old-job', collectionName: 'session-1' })
      localStorage.setItem(STORAGE_KEY, JSON.stringify([existingJob]))

      const file = createTrackedFile()
      persistJob('new-job', 'session-1', [file])

      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
      expect(stored).toHaveLength(1)
      expect(stored[0].jobId).toBe('new-job')
    })

    test('removes File objects from tracked files', () => {
      const mockFile = new File(['content'], 'test.pdf', { type: 'application/pdf' })
      const file = createTrackedFile({ file: mockFile })

      persistJob('job-1', 'session-1', [file])

      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
      expect(stored[0].files[0]).not.toHaveProperty('file')
      expect(stored[0].files[0].fileName).toBe('test.pdf')
    })

    test('adds to existing jobs for different collections', () => {
      const existingJob = createPersistedJob({ collectionName: 'session-1' })
      localStorage.setItem(STORAGE_KEY, JSON.stringify([existingJob]))

      const file = createTrackedFile({ collectionName: 'session-2' })
      persistJob('job-2', 'session-2', [file])

      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
      expect(stored).toHaveLength(2)
    })
  })

  describe('updatePersistedJobFiles', () => {
    test('updates files for existing job', () => {
      const job = createPersistedJob()
      localStorage.setItem(STORAGE_KEY, JSON.stringify([job]))

      const updatedFile = createTrackedFile({ progress: 50, status: 'ingesting' })
      updatePersistedJobFiles('job-1', [updatedFile])

      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
      expect(stored[0].files[0].progress).toBe(50)
      expect(stored[0].files[0].status).toBe('ingesting')
    })

    test('does nothing if job not found', () => {
      const job = createPersistedJob({ jobId: 'job-1' })
      localStorage.setItem(STORAGE_KEY, JSON.stringify([job]))

      const updatedFile = createTrackedFile({ progress: 50 })
      updatePersistedJobFiles('nonexistent-job', [updatedFile])

      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
      expect(stored[0].files[0].progress).toBe(0) // Unchanged
    })
  })

  describe('removePersistedJob', () => {
    test('removes job by jobId', () => {
      const jobs = [
        createPersistedJob({ jobId: 'job-1' }),
        createPersistedJob({ jobId: 'job-2', collectionName: 'session-2' }),
      ]
      localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs))

      removePersistedJob('job-1')

      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
      expect(stored).toHaveLength(1)
      expect(stored[0].jobId).toBe('job-2')
    })

    test('clears storage when last job removed', () => {
      const job = createPersistedJob()
      localStorage.setItem(STORAGE_KEY, JSON.stringify([job]))

      removePersistedJob('job-1')

      expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
    })
  })

  describe('removePersistedJobForCollection', () => {
    test('removes job by collectionName', () => {
      const jobs = [
        createPersistedJob({ jobId: 'job-1', collectionName: 'session-1' }),
        createPersistedJob({ jobId: 'job-2', collectionName: 'session-2' }),
      ]
      localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs))

      removePersistedJobForCollection('session-1')

      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
      expect(stored).toHaveLength(1)
      expect(stored[0].collectionName).toBe('session-2')
    })
  })

  describe('clearAllPersistedJobs', () => {
    test('removes all jobs from storage', () => {
      const jobs = [createPersistedJob(), createPersistedJob({ jobId: 'job-2' })]
      localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs))

      clearAllPersistedJobs()

      expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
    })
  })

  describe('session collection tracking', () => {
    const COLLECTIONS_KEY = 'documents_sessions_with_collections'

    describe('sessionHasKnownCollection', () => {
      test('returns false when no sessions are tracked', () => {
        expect(sessionHasKnownCollection('session-1')).toBe(false)
      })

      test('returns true when session is tracked', () => {
        localStorage.setItem(COLLECTIONS_KEY, JSON.stringify(['session-1']))

        expect(sessionHasKnownCollection('session-1')).toBe(true)
      })

      test('returns false for untracked session', () => {
        localStorage.setItem(COLLECTIONS_KEY, JSON.stringify(['session-1']))

        expect(sessionHasKnownCollection('session-2')).toBe(false)
      })

      test('returns false on invalid JSON', () => {
        localStorage.setItem(COLLECTIONS_KEY, 'not json')

        expect(sessionHasKnownCollection('session-1')).toBe(false)
      })
    })

    describe('markSessionHasCollection', () => {
      test('adds session to tracked list', () => {
        markSessionHasCollection('session-1')

        const stored = JSON.parse(localStorage.getItem(COLLECTIONS_KEY) || '[]')
        expect(stored).toEqual(['session-1'])
      })

      test('does not duplicate an already-tracked session', () => {
        markSessionHasCollection('session-1')
        markSessionHasCollection('session-1')

        const stored = JSON.parse(localStorage.getItem(COLLECTIONS_KEY) || '[]')
        expect(stored).toEqual(['session-1'])
      })

      test('tracks multiple sessions', () => {
        markSessionHasCollection('session-1')
        markSessionHasCollection('session-2')

        const stored = JSON.parse(localStorage.getItem(COLLECTIONS_KEY) || '[]')
        expect(stored).toEqual(['session-1', 'session-2'])
      })

      test('caps at 200 sessions with FIFO eviction', () => {
        // Pre-fill with 200 sessions
        const sessions = Array.from({ length: 200 }, (_, i) => `session-${i}`)
        localStorage.setItem(COLLECTIONS_KEY, JSON.stringify(sessions))

        markSessionHasCollection('session-new')

        const stored = JSON.parse(localStorage.getItem(COLLECTIONS_KEY) || '[]')
        expect(stored).toHaveLength(200)
        // Oldest session (session-0) should be evicted
        expect(stored).not.toContain('session-0')
        // Newest should be present
        expect(stored).toContain('session-new')
        // Second oldest should still be present
        expect(stored).toContain('session-1')
      })
    })

    describe('unmarkSessionCollection', () => {
      test('removes session from tracked list', () => {
        localStorage.setItem(COLLECTIONS_KEY, JSON.stringify(['session-1', 'session-2']))

        unmarkSessionCollection('session-1')

        const stored = JSON.parse(localStorage.getItem(COLLECTIONS_KEY) || '[]')
        expect(stored).toEqual(['session-2'])
      })

      test('does nothing if session not tracked', () => {
        localStorage.setItem(COLLECTIONS_KEY, JSON.stringify(['session-1']))

        unmarkSessionCollection('session-999')

        const stored = JSON.parse(localStorage.getItem(COLLECTIONS_KEY) || '[]')
        expect(stored).toEqual(['session-1'])
      })

      test('clears storage when last session removed', () => {
        localStorage.setItem(COLLECTIONS_KEY, JSON.stringify(['session-1']))

        unmarkSessionCollection('session-1')

        expect(localStorage.getItem(COLLECTIONS_KEY)).toBeNull()
      })
    })
  })
})

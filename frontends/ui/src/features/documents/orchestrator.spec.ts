// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { UploadOrchestrator } from './orchestrator'

// Mock the documents client
const mockClient = {
  getCollection: vi.fn(),
  listFiles: vi.fn(),
  getJobStatus: vi.fn(),
  createCollection: vi.fn(),
  uploadFiles: vi.fn(),
  deleteFiles: vi.fn(),
}

vi.mock('@/adapters/api', () => ({
  createDocumentsClient: () => mockClient,
}))

// Mock the stores
const mockDocumentsStore = {
  clearFilesForCollection: vi.fn(),
  setFilesFromServer: vi.fn(),
  setCurrentCollection: vi.fn(),
  setCollectionInfo: vi.fn(),
  setPolling: vi.fn(),
  setActiveJobId: vi.fn(),
  setError: vi.fn(),
  clearError: vi.fn(),
  updateFilesFromJobStatus: vi.fn(),
  trackedFiles: [],
  isUploading: false,
  isPolling: false,
  shownBannersForJobs: {},
  markBannerShown: vi.fn(),
}

vi.mock('./store', () => ({
  useDocumentsStore: {
    getState: () => mockDocumentsStore,
  },
}))

const mockLayoutStore = {
  openRightPanel: vi.fn(),
  setDataSourcesPanelTab: vi.fn(),
  knowledgeLayerAvailable: true,
}

vi.mock('@/features/layout/store', () => ({
  useLayoutStore: {
    getState: () => mockLayoutStore,
  },
}))

vi.mock('@/features/chat', () => ({
  useChatStore: {
    getState: () => ({}),
  },
}))

// Mock persistence - use typed wrapper fns to allow per-test mock control
const mockSessionHasKnownCollection = vi.fn((_sessionId: string): boolean => false)
const mockMarkSessionHasCollection = vi.fn((_sessionId: string): void => undefined)
const mockUnmarkSessionCollection = vi.fn((_sessionId: string): void => undefined)
const mockGetPersistedJobForCollection = vi.fn(
  (_collectionName: string): ReturnType<typeof import('./persistence').getPersistedJobForCollection> => null
)

vi.mock('./persistence', () => ({
  persistJob: vi.fn(),
  removePersistedJob: vi.fn(),
  getPersistedJobForCollection: (name: string) => mockGetPersistedJobForCollection(name),
  updatePersistedJobFiles: vi.fn(),
  sessionHasKnownCollection: (id: string) => mockSessionHasKnownCollection(id),
  markSessionHasCollection: (id: string) => mockMarkSessionHasCollection(id),
  unmarkSessionCollection: (id: string) => mockUnmarkSessionCollection(id),
}))

describe('UploadOrchestrator', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    // Reset mock return values to defaults
    // (clearAllMocks only clears calls/instances, not implementations or return values)
    mockSessionHasKnownCollection.mockReturnValue(false)
    mockMarkSessionHasCollection.mockReturnValue(undefined)
    mockUnmarkSessionCollection.mockReturnValue(undefined)
    mockGetPersistedJobForCollection.mockReturnValue(null)
    UploadOrchestrator.cleanup()
  })

  afterEach(() => {
    vi.useRealTimers()
    UploadOrchestrator.cleanup()
  })

  describe('setAuthToken', () => {
    test('sets auth token for client creation', () => {
      UploadOrchestrator.setAuthToken('test-token')
      // Token is stored internally and used when creating clients
    })

    test('handles undefined token', () => {
      UploadOrchestrator.setAuthToken(undefined)
    })
  })

  describe('setCallbacks', () => {
    test('sets callbacks for upload events', () => {
      const onComplete = vi.fn()
      const onError = vi.fn()

      UploadOrchestrator.setCallbacks({ onComplete, onError })
    })
  })

  describe('handleSessionChange', () => {
    test('does nothing when session is the same', async () => {
      await UploadOrchestrator.handleSessionChange('session-1')
      mockDocumentsStore.clearFilesForCollection.mockClear()

      await UploadOrchestrator.handleSessionChange('session-1')

      expect(mockDocumentsStore.clearFilesForCollection).not.toHaveBeenCalled()
    })

    test('clears files when switching sessions', async () => {
      await UploadOrchestrator.handleSessionChange('session-1')
      mockDocumentsStore.clearFilesForCollection.mockClear()

      await UploadOrchestrator.handleSessionChange('session-2')

      expect(mockDocumentsStore.clearFilesForCollection).toHaveBeenCalledWith('session-1')
      expect(mockDocumentsStore.clearFilesForCollection).toHaveBeenCalledWith('session-2')
    })

    test('loads files for new session when session has known collection', async () => {
      mockSessionHasKnownCollection.mockReturnValue(true)
      mockClient.getCollection.mockResolvedValue({
        name: 'session-1',
        description: 'Test session',
      })
      mockClient.listFiles.mockResolvedValue([
        { file_id: 'file-1', file_name: 'test.pdf', status: 'completed' },
      ])

      await UploadOrchestrator.handleSessionChange('session-1')
      await vi.runAllTimersAsync()

      expect(mockClient.getCollection).toHaveBeenCalledWith('session-1')
    })

    test('skips loading files for new session without known collection', async () => {
      mockSessionHasKnownCollection.mockReturnValue(false)

      await UploadOrchestrator.handleSessionChange('session-1')
      await vi.runAllTimersAsync()

      expect(mockClient.getCollection).not.toHaveBeenCalled()
    })

    test('handles undefined session', async () => {
      await UploadOrchestrator.handleSessionChange('session-1')
      await UploadOrchestrator.handleSessionChange(undefined)

      expect(mockDocumentsStore.clearFilesForCollection).toHaveBeenCalledWith('session-1')
    })
  })

  describe('loadFilesForSession', () => {
    test('loads files from server when session has known collection', async () => {
      mockSessionHasKnownCollection.mockReturnValue(true)
      mockClient.getCollection.mockResolvedValue({
        name: 'session-1',
        description: 'Test session',
      })
      mockClient.listFiles.mockResolvedValue([
        { file_id: 'file-1', file_name: 'test.pdf', status: 'completed' },
      ])

      // Set up session first via handleSessionChange (sets currentSessionId)
      await UploadOrchestrator.handleSessionChange('session-1')

      expect(mockClient.getCollection).toHaveBeenCalledWith('session-1')
      expect(mockClient.listFiles).toHaveBeenCalledWith('session-1')
      expect(mockDocumentsStore.setFilesFromServer).toHaveBeenCalled()
      expect(mockMarkSessionHasCollection).toHaveBeenCalledWith('session-1')
    })

    test('skips API call when session has no known collection', async () => {
      mockSessionHasKnownCollection.mockReturnValue(false)

      await UploadOrchestrator.loadFilesForSession('session-1')

      expect(mockClient.getCollection).not.toHaveBeenCalled()
      expect(mockClient.listFiles).not.toHaveBeenCalled()
    })

    test('calls API when session has persisted job even without known collection', async () => {
      // First set up currentSessionId without triggering API calls
      mockSessionHasKnownCollection.mockReturnValue(false)
      await UploadOrchestrator.handleSessionChange('session-1')
      // handleSessionChange sets currentSessionId and calls loadFilesForSession
      // which skips due to no known collection. Now switch away and back.
      await UploadOrchestrator.handleSessionChange('session-2')

      // Now set up: session-1 has no known collection but has a persisted job
      mockSessionHasKnownCollection.mockReturnValue(false)
      // getPersistedJobForCollection returns null for handleSessionChange check (first call)
      // but returns a job for loadFilesForSession check (second call in same flow)
      // First call from handleSessionChange returns null (so it falls through to loadFilesForSession)
      // Second call from loadFilesForSession guard returns a persisted job
      mockGetPersistedJobForCollection
        .mockReturnValueOnce(null)
        .mockReturnValueOnce({
          jobId: 'job-1',
          collectionName: 'session-1',
          files: [],
          startedAt: Date.now(),
        })
      mockClient.getCollection.mockResolvedValue({
        name: 'session-1',
        description: 'Test session',
      })
      mockClient.listFiles.mockResolvedValue([])

      await UploadOrchestrator.handleSessionChange('session-1')

      expect(mockClient.getCollection).toHaveBeenCalledWith('session-1')
    })

    test('unmarks session when collection returns 404 (TTL expired)', async () => {
      mockSessionHasKnownCollection.mockReturnValue(true)
      mockClient.getCollection.mockResolvedValue(null)

      // Set up session first via handleSessionChange (sets currentSessionId)
      await UploadOrchestrator.handleSessionChange('session-1')

      expect(mockUnmarkSessionCollection).toHaveBeenCalledWith('session-1')
    })

    test('handles non-existent collection', async () => {
      mockSessionHasKnownCollection.mockReturnValue(true)
      mockClient.getCollection.mockResolvedValue(null)

      // Set currentSessionId via handleSessionChange
      await UploadOrchestrator.handleSessionChange('session-1')

      expect(mockClient.listFiles).not.toHaveBeenCalled()
    })

    test('skips if already loaded for same session', async () => {
      mockSessionHasKnownCollection.mockReturnValue(true)
      mockClient.getCollection.mockResolvedValue({
        name: 'session-1',
        description: 'Test session',
      })
      mockClient.listFiles.mockResolvedValue([])

      // Set currentSessionId first
      await UploadOrchestrator.handleSessionChange('session-1')
      mockClient.getCollection.mockClear()

      await UploadOrchestrator.loadFilesForSession('session-1')

      expect(mockClient.getCollection).not.toHaveBeenCalled()
    })

    test('skips if currently uploading', async () => {
      mockSessionHasKnownCollection.mockReturnValue(true)
      mockDocumentsStore.isUploading = true

      await UploadOrchestrator.loadFilesForSession('session-1')

      expect(mockClient.getCollection).not.toHaveBeenCalled()
      mockDocumentsStore.isUploading = false
    })

    test('skips if currently polling', async () => {
      mockSessionHasKnownCollection.mockReturnValue(true)
      mockDocumentsStore.isPolling = true

      await UploadOrchestrator.loadFilesForSession('session-1')

      expect(mockClient.getCollection).not.toHaveBeenCalled()
      mockDocumentsStore.isPolling = false
    })

    test('handles errors gracefully without unmarking session', async () => {
      mockSessionHasKnownCollection.mockReturnValue(true)
      mockClient.getCollection.mockRejectedValue(new Error('Network error'))

      // Set currentSessionId via handleSessionChange first with a clean session
      // (need to bypass the loadFilesForSession that handleSessionChange calls)
      mockSessionHasKnownCollection.mockReturnValueOnce(false)
      await UploadOrchestrator.handleSessionChange('session-1')

      // Now call directly with known collection
      mockSessionHasKnownCollection.mockReturnValue(true)
      await UploadOrchestrator.loadFilesForSession('session-1')

      // Should not unmark on network errors (backend may be temporarily unavailable)
      expect(mockUnmarkSessionCollection).not.toHaveBeenCalled()
    })
  })

  describe('refreshFilesForSession', () => {
    test('forces re-fetch by resetting cache for current session', async () => {
      mockSessionHasKnownCollection.mockReturnValue(true)
      mockClient.getCollection.mockResolvedValue({
        name: 'session-1',
        description: 'Test session',
      })
      mockClient.listFiles.mockResolvedValue([
        { file_id: 'file-1', file_name: 'test.pdf', status: 'completed' },
      ])

      // Initial load via handleSessionChange
      await UploadOrchestrator.handleSessionChange('session-1')
      expect(mockClient.getCollection).toHaveBeenCalledTimes(1)
      mockClient.getCollection.mockClear()
      mockClient.listFiles.mockClear()

      // Normal loadFilesForSession would skip (already loaded)
      await UploadOrchestrator.loadFilesForSession('session-1')
      expect(mockClient.getCollection).not.toHaveBeenCalled()

      // refreshFilesForSession should bypass the cache and re-fetch
      await UploadOrchestrator.refreshFilesForSession('session-1')
      expect(mockClient.getCollection).toHaveBeenCalledWith('session-1')
      expect(mockClient.listFiles).toHaveBeenCalledWith('session-1')
    })

    test('does nothing for a different session than current', async () => {
      mockSessionHasKnownCollection.mockReturnValue(true)
      mockClient.getCollection.mockResolvedValue({
        name: 'session-1',
        description: 'Test session',
      })
      mockClient.listFiles.mockResolvedValue([])

      await UploadOrchestrator.handleSessionChange('session-1')
      mockClient.getCollection.mockClear()

      // Refresh for a different session should be ignored
      await UploadOrchestrator.refreshFilesForSession('session-2')
      expect(mockClient.getCollection).not.toHaveBeenCalled()
    })

    test('detects backend-side removal (404) and unmarks session', async () => {
      mockSessionHasKnownCollection.mockReturnValue(true)
      mockClient.getCollection.mockResolvedValue({
        name: 'session-1',
        description: 'Test session',
      })
      mockClient.listFiles.mockResolvedValue([
        { file_id: 'file-1', file_name: 'test.pdf', status: 'completed' },
      ])

      // Initial load succeeds
      await UploadOrchestrator.handleSessionChange('session-1')
      mockUnmarkSessionCollection.mockClear()

      // Backend TTL cleanup happened - collection now returns 404
      mockClient.getCollection.mockResolvedValue(null)

      await UploadOrchestrator.refreshFilesForSession('session-1')
      expect(mockUnmarkSessionCollection).toHaveBeenCalledWith('session-1')
    })
  })

  describe('startPolling', () => {
    test('starts polling for job status', () => {
      UploadOrchestrator.startPolling('job-1', 'session-1')

      expect(mockDocumentsStore.setPolling).toHaveBeenCalledWith(true)
      expect(mockDocumentsStore.setActiveJobId).toHaveBeenCalledWith('job-1')
    })

    test('stops existing polling before starting new one', () => {
      UploadOrchestrator.startPolling('job-1', 'session-1')
      UploadOrchestrator.startPolling('job-2', 'session-1')

      // Second call should have set up new polling
      expect(mockDocumentsStore.setActiveJobId).toHaveBeenLastCalledWith('job-2')
    })
  })

  describe('stopPolling', () => {
    test('stops current polling', () => {
      UploadOrchestrator.startPolling('job-1', 'session-1')
      UploadOrchestrator.stopPolling()

      expect(mockDocumentsStore.setPolling).toHaveBeenCalledWith(false)
      expect(mockDocumentsStore.setActiveJobId).toHaveBeenCalledWith(null)
    })

    test('handles stop when not polling', () => {
      UploadOrchestrator.stopPolling()

      expect(mockDocumentsStore.setPolling).toHaveBeenCalledWith(false)
    })
  })

  describe('cleanup', () => {
    test('stops polling and clears state', () => {
      UploadOrchestrator.startPolling('job-1', 'session-1')
      UploadOrchestrator.cleanup()

      expect(mockDocumentsStore.setPolling).toHaveBeenCalledWith(false)
    })
  })

  describe('polling behavior', () => {
    test('polls job status on interval', async () => {
      mockClient.getJobStatus.mockResolvedValue({
        job_id: 'job-1',
        status: 'in_progress',
        file_details: [{ file_id: 'file-1', file_name: 'test.pdf', status: 'processing' }],
      })

      UploadOrchestrator.startPolling('job-1', 'session-1')

      await vi.advanceTimersByTimeAsync(5000)

      expect(mockClient.getJobStatus).toHaveBeenCalledWith('job-1', expect.any(AbortSignal))
    })

    test('stops polling when job completes', async () => {
      mockClient.getJobStatus.mockResolvedValue({
        job_id: 'job-1',
        status: 'completed',
        file_details: [
          { file_id: 'file-1', file_name: 'test.pdf', status: 'completed', progress_percent: 100 },
        ],
      })
      mockClient.listFiles.mockResolvedValue([])

      UploadOrchestrator.startPolling('job-1', 'session-1')
      await vi.advanceTimersByTimeAsync(5000)

      expect(mockDocumentsStore.setPolling).toHaveBeenLastCalledWith(false)
    })

    test('stops polling when job fails', async () => {
      mockClient.getJobStatus.mockResolvedValue({
        job_id: 'job-1',
        status: 'failed',
        error_message: 'Upload failed',
        file_details: [],
      })

      UploadOrchestrator.startPolling('job-1', 'session-1')
      await vi.advanceTimersByTimeAsync(5000)

      expect(mockDocumentsStore.setError).toHaveBeenCalledWith('Upload failed')
    })

    test('stops polling when job not found', async () => {
      mockClient.getJobStatus.mockResolvedValue(null)

      UploadOrchestrator.startPolling('job-1', 'session-1')
      await vi.advanceTimersByTimeAsync(5000)

      expect(mockDocumentsStore.setError).toHaveBeenCalledWith('Job not found')
    })

    test('handles polling errors', async () => {
      mockClient.getJobStatus.mockRejectedValue(new Error('Network error'))

      UploadOrchestrator.startPolling('job-1', 'session-1')

      // Should not throw
      await vi.advanceTimersByTimeAsync(5000)
    })

    test('handles abort errors silently', async () => {
      const abortError = new Error('Aborted')
      abortError.name = 'AbortError'
      mockClient.getJobStatus.mockRejectedValue(abortError)

      UploadOrchestrator.startPolling('job-1', 'session-1')
      await vi.advanceTimersByTimeAsync(5000)

      expect(mockDocumentsStore.setError).not.toHaveBeenCalled()
    })
  })
})

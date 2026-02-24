// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

// Use vi.hoisted for mocks that need to be available before vi.mock
const { mockClient, mockDocumentsStoreState, mockOrchestratorFns } = vi.hoisted(() => ({
  mockClient: {
    getCollection: vi.fn(),
    createCollection: vi.fn(),
    uploadFiles: vi.fn(),
    deleteFiles: vi.fn(),
    listFiles: vi.fn(),
  },
  mockDocumentsStoreState: {
    trackedFiles: [] as unknown[],
    isUploading: false,
    isPolling: false,
    error: null as string | null,
    setCurrentCollection: vi.fn(),
    setCollectionInfo: vi.fn(),
    addTrackedFile: vi.fn(),
    updateTrackedFile: vi.fn(),
    removeTrackedFile: vi.fn(),
    setUploading: vi.fn(),
    setError: vi.fn(),
    clearError: vi.fn(),
  },
  mockOrchestratorFns: {
    setAuthToken: vi.fn(),
    setCallbacks: vi.fn(),
    handleSessionChange: vi.fn(),
    startPolling: vi.fn(),
    stopPolling: vi.fn(),
  },
}))

// Mock modules
vi.mock('@/adapters/api', () => ({
  createDocumentsClient: () => mockClient,
}))

vi.mock('@/adapters/auth', () => ({
  useAuth: () => ({ idToken: 'test-token' }),
}))

vi.mock('@/shared/context', () => ({
  useAppConfig: () => ({
    authRequired: true,
    fileUpload: {
      acceptedTypes: '.pdf,.md,.docx,.html,.txt',
      acceptedMimeTypes: ['application/pdf', 'text/plain', 'text/markdown'],
      maxTotalSizeMB: 100,
      maxFileSize: 100 * 1024 * 1024,
      maxTotalSize: 100 * 1024 * 1024,
      maxFileCount: 10,
    },
  }),
}))

vi.mock('../store', () => ({
  useDocumentsStore: () => mockDocumentsStoreState,
}))

vi.mock('@/features/chat', () => {
  const mockChatState = { addFileUploadStatusCard: vi.fn() }
  const useChatStore = (selector: (state: typeof mockChatState) => unknown) =>
    selector(mockChatState)
  useChatStore.getState = () => mockChatState
  return { useChatStore }
})

vi.mock('../orchestrator', () => ({
  UploadOrchestrator: mockOrchestratorFns,
}))

const mockMarkSessionHasCollection = vi.fn()
vi.mock('../persistence', () => ({
  markSessionHasCollection: (...args: unknown[]) => mockMarkSessionHasCollection(...args),
}))

vi.mock('../validation', () => ({
  validateFileUpload: vi.fn((files: File[]) => ({
    validFiles: files,
    batchErrors: [],
    fileErrors: [],
    summary: '',
  })),
}))

vi.mock('uuid', () => ({
  v4: () => 'mock-uuid',
}))

import { useFileUpload } from './use-file-upload'

describe('useFileUpload', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockDocumentsStoreState.trackedFiles = []
    mockDocumentsStoreState.isUploading = false
    mockDocumentsStoreState.isPolling = false
    mockDocumentsStoreState.error = null
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  describe('initialization', () => {
    test('returns initial state', () => {
      const { result } = renderHook(() => useFileUpload())

      expect(result.current.trackedFiles).toEqual([])
      expect(result.current.isUploading).toBe(false)
      expect(result.current.isPolling).toBe(false)
      expect(result.current.error).toBeNull()
    })

    test('sets auth token on mount', () => {
      renderHook(() => useFileUpload())

      expect(mockOrchestratorFns.setAuthToken).toHaveBeenCalledWith('test-token')
    })

    test('sets callbacks on mount', () => {
      const onComplete = vi.fn()
      const onError = vi.fn()

      renderHook(() => useFileUpload({ onComplete, onError }))

      expect(mockOrchestratorFns.setCallbacks).toHaveBeenCalledWith({
        onComplete,
        onError,
      })
    })

    test('handles session change when sessionId changes', async () => {
      const { rerender } = renderHook(({ sessionId }) => useFileUpload({ sessionId }), {
        initialProps: { sessionId: 'session-1' },
      })

      // Initial render doesn't call handleSessionChange since previousSessionIdRef starts undefined
      // and the effect checks for sessionId !== previousSessionId

      rerender({ sessionId: 'session-2' })

      expect(mockOrchestratorFns.handleSessionChange).toHaveBeenCalledWith('session-2')
    })
  })

  describe('sessionFiles', () => {
    test('filters tracked files by session', () => {
      mockDocumentsStoreState.trackedFiles = [
        { id: '1', fileName: 'file1.pdf', collectionName: 'session-1', fileSize: 1000 },
        { id: '2', fileName: 'file2.pdf', collectionName: 'session-2', fileSize: 2000 },
        { id: '3', fileName: 'file3.pdf', collectionName: 'session-1', fileSize: 3000 },
      ] as unknown[]

      const { result } = renderHook(() => useFileUpload({ sessionId: 'session-1' }))

      expect(result.current.sessionFiles).toHaveLength(2)
      expect(result.current.sessionFiles[0].fileName).toBe('file1.pdf')
      expect(result.current.sessionFiles[1].fileName).toBe('file3.pdf')
    })

    test('returns empty array when no session', () => {
      mockDocumentsStoreState.trackedFiles = [
        { id: '1', fileName: 'file1.pdf', collectionName: 'session-1', fileSize: 1000 },
      ] as unknown[]

      const { result } = renderHook(() => useFileUpload())

      expect(result.current.sessionFiles).toHaveLength(0)
    })
  })

  describe('validationContext', () => {
    test('computes validation context from session files', () => {
      mockDocumentsStoreState.trackedFiles = [
        { id: '1', fileName: 'file1.pdf', collectionName: 'session-1', fileSize: 1000 },
        { id: '2', fileName: 'file2.pdf', collectionName: 'session-1', fileSize: 2000 },
      ] as unknown[]

      const { result } = renderHook(() => useFileUpload({ sessionId: 'session-1' }))

      expect(result.current.validationContext).toEqual({
        existingTotalSize: 3000,
        existingFileCount: 2,
        existingFileNames: new Set(['file1.pdf', 'file2.pdf']),
      })
    })
  })

  describe('uploadFiles', () => {
    test('does nothing when files array is empty', async () => {
      const { result } = renderHook(() => useFileUpload({ sessionId: 'session-1' }))

      await act(async () => {
        await result.current.uploadFiles([])
      })

      expect(mockClient.uploadFiles).not.toHaveBeenCalled()
    })

    test('sets error when no session ID', async () => {
      const onError = vi.fn()
      const { result } = renderHook(() => useFileUpload({ onError }))

      await act(async () => {
        await result.current.uploadFiles([new File(['test'], 'test.pdf', { type: 'application/pdf' })])
      })

      expect(mockDocumentsStoreState.setError).toHaveBeenCalledWith('Session ID required for upload')
      expect(onError).toHaveBeenCalled()
    })

    test('uploads files successfully', async () => {
      mockClient.getCollection.mockResolvedValue({ name: 'session-1' })
      mockClient.uploadFiles.mockResolvedValue({
        job_id: 'job-1',
        file_ids: ['file-id-1'],
      })

      const { result } = renderHook(() => useFileUpload({ sessionId: 'session-1' }))

      await act(async () => {
        await result.current.uploadFiles([
          new File(['test'], 'test.pdf', { type: 'application/pdf' }),
        ])
      })

      expect(mockDocumentsStoreState.setUploading).toHaveBeenCalledWith(true)
      expect(mockClient.uploadFiles).toHaveBeenCalled()
      expect(mockOrchestratorFns.startPolling).toHaveBeenCalledWith(
        'job-1',
        'session-1',
        expect.any(Array)
      )
    })

    test('creates collection if not exists', async () => {
      mockClient.getCollection.mockResolvedValue(null)
      mockClient.createCollection.mockResolvedValue({ name: 'session-1' })
      mockClient.uploadFiles.mockResolvedValue({
        job_id: 'job-1',
        file_ids: ['file-id-1'],
      })

      const { result } = renderHook(() => useFileUpload({ sessionId: 'session-1' }))

      await act(async () => {
        await result.current.uploadFiles([
          new File(['test'], 'test.pdf', { type: 'application/pdf' }),
        ])
      })

      expect(mockClient.createCollection).toHaveBeenCalledWith(
        'session-1',
        'Documents for session session-1'
      )
    })

    test('marks session as having collection after ensureCollectionExists', async () => {
      mockClient.getCollection.mockResolvedValue({ name: 'session-1' })
      mockClient.uploadFiles.mockResolvedValue({
        job_id: 'job-1',
        file_ids: ['file-id-1'],
      })

      const { result } = renderHook(() => useFileUpload({ sessionId: 'session-1' }))

      await act(async () => {
        await result.current.uploadFiles([
          new File(['test'], 'test.pdf', { type: 'application/pdf' }),
        ])
      })

      expect(mockMarkSessionHasCollection).toHaveBeenCalledWith('session-1')
    })

    test('uses targetSessionId when provided', async () => {
      mockClient.getCollection.mockResolvedValue({ name: 'target-session' })
      mockClient.uploadFiles.mockResolvedValue({
        job_id: 'job-1',
        file_ids: ['file-id-1'],
      })

      const { result } = renderHook(() => useFileUpload({ sessionId: 'session-1' }))

      await act(async () => {
        await result.current.uploadFiles(
          [new File(['test'], 'test.pdf', { type: 'application/pdf' })],
          'target-session'
        )
      })

      expect(mockClient.getCollection).toHaveBeenCalledWith('target-session')
    })

    test('handles upload errors', async () => {
      mockClient.getCollection.mockResolvedValue({ name: 'session-1' })
      mockClient.uploadFiles.mockRejectedValue(new Error('Upload failed'))

      const onError = vi.fn()
      const { result } = renderHook(() => useFileUpload({ sessionId: 'session-1', onError }))

      await act(async () => {
        await result.current.uploadFiles([
          new File(['test'], 'test.pdf', { type: 'application/pdf' }),
        ])
      })

      expect(mockDocumentsStoreState.setError).toHaveBeenCalledWith('Upload failed')
      expect(onError).toHaveBeenCalled()
    })

    test('ignores abort errors', async () => {
      const abortError = new Error('Aborted')
      abortError.name = 'AbortError'
      mockClient.getCollection.mockResolvedValue({ name: 'session-1' })
      mockClient.uploadFiles.mockRejectedValue(abortError)

      const onError = vi.fn()
      const { result } = renderHook(() => useFileUpload({ sessionId: 'session-1', onError }))

      await act(async () => {
        await result.current.uploadFiles([
          new File(['test'], 'test.pdf', { type: 'application/pdf' }),
        ])
      })

      expect(onError).not.toHaveBeenCalled()
    })
  })

  describe('cancelUpload', () => {
    test('stops orchestrator polling', () => {
      const { result } = renderHook(() => useFileUpload())

      act(() => {
        result.current.cancelUpload()
      })

      expect(mockOrchestratorFns.stopPolling).toHaveBeenCalled()
      expect(mockDocumentsStoreState.setUploading).toHaveBeenCalledWith(false)
    })
  })

  describe('deleteFile', () => {
    test('removes file that has no collection', async () => {
      mockDocumentsStoreState.trackedFiles = [
        { id: 'file-1', fileName: 'test.pdf', collectionName: null, fileSize: 1000 },
      ] as unknown[]

      const { result } = renderHook(() => useFileUpload())

      await act(async () => {
        await result.current.deleteFile('file-1')
      })

      expect(mockDocumentsStoreState.removeTrackedFile).toHaveBeenCalledWith('file-1')
      expect(mockClient.deleteFiles).not.toHaveBeenCalled()
    })

    test('deletes file from server and removes tracked file', async () => {
      mockDocumentsStoreState.trackedFiles = [
        { id: 'file-1', fileName: 'test.pdf', collectionName: 'session-1', fileSize: 1000 },
      ] as unknown[]
      mockClient.deleteFiles.mockResolvedValue(undefined)

      const { result } = renderHook(() => useFileUpload())

      await act(async () => {
        await result.current.deleteFile('file-1')
      })

      expect(mockClient.deleteFiles).toHaveBeenCalledWith('session-1', ['test.pdf'])
      expect(mockDocumentsStoreState.removeTrackedFile).toHaveBeenCalledWith('file-1')
    })

    test('handles delete errors', async () => {
      mockDocumentsStoreState.trackedFiles = [
        { id: 'file-1', fileName: 'test.pdf', collectionName: 'session-1', fileSize: 1000 },
      ] as unknown[]
      mockClient.deleteFiles.mockRejectedValue(new Error('Delete failed'))

      const { result } = renderHook(() => useFileUpload())

      await act(async () => {
        await result.current.deleteFile('file-1')
      })

      expect(mockDocumentsStoreState.setError).toHaveBeenCalledWith('Delete failed')
    })
  })

  describe('retryFile', () => {
    test('does nothing when file not found', async () => {
      mockDocumentsStoreState.trackedFiles = []

      const { result } = renderHook(() => useFileUpload({ sessionId: 'session-1' }))

      await act(async () => {
        await result.current.retryFile('file-1')
      })

      expect(mockDocumentsStoreState.removeTrackedFile).not.toHaveBeenCalled()
    })

    test('sets error when file has no File object', async () => {
      mockDocumentsStoreState.trackedFiles = [
        { id: 'file-1', fileName: 'test.pdf', collectionName: 'session-1', fileSize: 1000 },
      ] as unknown[]

      const { result } = renderHook(() => useFileUpload({ sessionId: 'session-1' }))

      await act(async () => {
        await result.current.retryFile('file-1')
      })

      expect(mockDocumentsStoreState.setError).toHaveBeenCalledWith(
        'Cannot retry server-loaded files. Please upload the file again.'
      )
    })

    test('removes and re-uploads file', async () => {
      const testFile = new File(['test'], 'test.pdf', { type: 'application/pdf' })
      mockDocumentsStoreState.trackedFiles = [
        {
          id: 'file-1',
          fileName: 'test.pdf',
          collectionName: 'session-1',
          fileSize: 1000,
          file: testFile,
        },
      ] as unknown[]

      mockClient.getCollection.mockResolvedValue({ name: 'session-1' })
      mockClient.uploadFiles.mockResolvedValue({
        job_id: 'job-1',
        file_ids: ['file-id-1'],
      })

      const { result } = renderHook(() => useFileUpload({ sessionId: 'session-1' }))

      await act(async () => {
        await result.current.retryFile('file-1')
      })

      expect(mockDocumentsStoreState.removeTrackedFile).toHaveBeenCalledWith('file-1')
    })
  })

  describe('clearError', () => {
    test('clears error state', () => {
      const { result } = renderHook(() => useFileUpload())

      act(() => {
        result.current.clearError()
      })

      expect(mockDocumentsStoreState.clearError).toHaveBeenCalled()
    })
  })
})

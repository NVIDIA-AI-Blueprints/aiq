// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, test, expect, beforeEach } from 'vitest'
import {
  useDocumentsStore,
  selectFilesInProgress,
  selectCompletedFiles,
  selectFailedFiles,
  selectIsProcessing,
} from './store'
import type { TrackedFile, CollectionInfo, IngestionJobStatus, FileInfo } from './types'

describe('useDocumentsStore', () => {
  beforeEach(() => {
    // Reset store to initial state before each test
    useDocumentsStore.setState({
      currentCollectionName: null,
      collectionInfo: null,
      trackedFiles: [],
      activeJobId: null,
      isCreatingCollection: false,
      isUploading: false,
      isPolling: false,
      error: null,
      shownBannersForJobs: {},
    })
  })

  describe('initial state', () => {
    test('has correct default values', () => {
      const state = useDocumentsStore.getState()

      expect(state.currentCollectionName).toBeNull()
      expect(state.collectionInfo).toBeNull()
      expect(state.trackedFiles).toEqual([])
      expect(state.activeJobId).toBeNull()
      expect(state.isCreatingCollection).toBe(false)
      expect(state.isUploading).toBe(false)
      expect(state.isPolling).toBe(false)
      expect(state.error).toBeNull()
      expect(state.shownBannersForJobs).toEqual({})
    })
  })

  describe('collection management', () => {
    test('setCurrentCollection sets collection name', () => {
      useDocumentsStore.getState().setCurrentCollection('test-collection')

      expect(useDocumentsStore.getState().currentCollectionName).toBe('test-collection')
    })

    test('setCurrentCollection sets to null', () => {
      useDocumentsStore.setState({ currentCollectionName: 'existing' })

      useDocumentsStore.getState().setCurrentCollection(null)

      expect(useDocumentsStore.getState().currentCollectionName).toBeNull()
    })

    test('setCollectionInfo sets collection info', () => {
      const info: CollectionInfo = {
        name: 'test-collection',
        file_count: 5,
        chunk_count: 10,
        backend: 'milvus',
        metadata: {},
      }

      useDocumentsStore.getState().setCollectionInfo(info)

      expect(useDocumentsStore.getState().collectionInfo).toEqual(info)
    })

    test('setCollectionInfo sets to null', () => {
      useDocumentsStore.setState({
        collectionInfo: { name: 'existing', file_count: 3, chunk_count: 6, backend: 'milvus', metadata: {} },
      })

      useDocumentsStore.getState().setCollectionInfo(null)

      expect(useDocumentsStore.getState().collectionInfo).toBeNull()
    })
  })

  describe('file tracking', () => {
    const createTrackedFile = (overrides: Partial<TrackedFile> = {}): TrackedFile => ({
      id: 'file-1',
      fileName: 'test.pdf',
      fileSize: 1024,
      status: 'uploading',
      progress: 0,
      ...overrides,
    })

    test('addTrackedFile adds file to list', () => {
      const file = createTrackedFile()

      useDocumentsStore.getState().addTrackedFile(file)

      expect(useDocumentsStore.getState().trackedFiles).toHaveLength(1)
      expect(useDocumentsStore.getState().trackedFiles[0]).toEqual(file)
    })

    test('addTrackedFile appends to existing files', () => {
      const file1 = createTrackedFile({ id: 'file-1' })
      const file2 = createTrackedFile({ id: 'file-2', fileName: 'test2.pdf' })

      useDocumentsStore.getState().addTrackedFile(file1)
      useDocumentsStore.getState().addTrackedFile(file2)

      expect(useDocumentsStore.getState().trackedFiles).toHaveLength(2)
    })

    test('updateTrackedFile updates specific file', () => {
      const file = createTrackedFile()
      useDocumentsStore.setState({ trackedFiles: [file] })

      useDocumentsStore.getState().updateTrackedFile('file-1', {
        status: 'ingesting',
        progress: 50,
      })

      const updated = useDocumentsStore.getState().trackedFiles[0]
      expect(updated.status).toBe('ingesting')
      expect(updated.progress).toBe(50)
      expect(updated.fileName).toBe('test.pdf') // unchanged
    })

    test('updateTrackedFile does not affect other files', () => {
      const file1 = createTrackedFile({ id: 'file-1' })
      const file2 = createTrackedFile({ id: 'file-2', fileName: 'other.pdf' })
      useDocumentsStore.setState({ trackedFiles: [file1, file2] })

      useDocumentsStore.getState().updateTrackedFile('file-1', { progress: 100 })

      const files = useDocumentsStore.getState().trackedFiles
      expect(files[0].progress).toBe(100)
      expect(files[1].progress).toBe(0) // unchanged
    })

    test('removeTrackedFile removes specific file', () => {
      const file1 = createTrackedFile({ id: 'file-1' })
      const file2 = createTrackedFile({ id: 'file-2' })
      useDocumentsStore.setState({ trackedFiles: [file1, file2] })

      useDocumentsStore.getState().removeTrackedFile('file-1')

      const files = useDocumentsStore.getState().trackedFiles
      expect(files).toHaveLength(1)
      expect(files[0].id).toBe('file-2')
    })

    test('clearTrackedFiles removes all files', () => {
      const file1 = createTrackedFile({ id: 'file-1' })
      const file2 = createTrackedFile({ id: 'file-2' })
      useDocumentsStore.setState({ trackedFiles: [file1, file2] })

      useDocumentsStore.getState().clearTrackedFiles()

      expect(useDocumentsStore.getState().trackedFiles).toEqual([])
    })

    test('clearFilesForCollection removes only files for specific collection', () => {
      const file1 = createTrackedFile({ id: 'file-1', collectionName: 'session-1' })
      const file2 = createTrackedFile({ id: 'file-2', collectionName: 'session-1' })
      const file3 = createTrackedFile({ id: 'file-3', collectionName: 'session-2' })
      useDocumentsStore.setState({ trackedFiles: [file1, file2, file3] })

      useDocumentsStore.getState().clearFilesForCollection('session-1')

      const files = useDocumentsStore.getState().trackedFiles
      expect(files).toHaveLength(1)
      expect(files[0].id).toBe('file-3')
      expect(files[0].collectionName).toBe('session-2')
    })

    test('clearFilesForCollection does nothing if no matching files', () => {
      const file1 = createTrackedFile({ id: 'file-1', collectionName: 'session-1' })
      useDocumentsStore.setState({ trackedFiles: [file1] })

      useDocumentsStore.getState().clearFilesForCollection('nonexistent-session')

      expect(useDocumentsStore.getState().trackedFiles).toHaveLength(1)
    })

    test('clearFilesForCollection handles files without collectionName', () => {
      const file1 = createTrackedFile({ id: 'file-1', collectionName: 'session-1' })
      const file2 = createTrackedFile({ id: 'file-2', collectionName: undefined })
      useDocumentsStore.setState({ trackedFiles: [file1, file2] })

      useDocumentsStore.getState().clearFilesForCollection('session-1')

      const files = useDocumentsStore.getState().trackedFiles
      expect(files).toHaveLength(1)
      expect(files[0].id).toBe('file-2')
    })
  })

  describe('job tracking', () => {
    test('setActiveJobId sets job ID', () => {
      useDocumentsStore.getState().setActiveJobId('job-123')

      expect(useDocumentsStore.getState().activeJobId).toBe('job-123')
    })

    test('setActiveJobId clears job ID', () => {
      useDocumentsStore.setState({ activeJobId: 'existing-job' })

      useDocumentsStore.getState().setActiveJobId(null)

      expect(useDocumentsStore.getState().activeJobId).toBeNull()
    })
  })

  describe('loading states', () => {
    test('setCreatingCollection sets loading state', () => {
      useDocumentsStore.getState().setCreatingCollection(true)
      expect(useDocumentsStore.getState().isCreatingCollection).toBe(true)

      useDocumentsStore.getState().setCreatingCollection(false)
      expect(useDocumentsStore.getState().isCreatingCollection).toBe(false)
    })

    test('setUploading sets loading state', () => {
      useDocumentsStore.getState().setUploading(true)
      expect(useDocumentsStore.getState().isUploading).toBe(true)

      useDocumentsStore.getState().setUploading(false)
      expect(useDocumentsStore.getState().isUploading).toBe(false)
    })

    test('setPolling sets polling state', () => {
      useDocumentsStore.getState().setPolling(true)
      expect(useDocumentsStore.getState().isPolling).toBe(true)

      useDocumentsStore.getState().setPolling(false)
      expect(useDocumentsStore.getState().isPolling).toBe(false)
    })
  })

  describe('error handling', () => {
    test('setError sets error message', () => {
      useDocumentsStore.getState().setError('Upload failed')

      expect(useDocumentsStore.getState().error).toBe('Upload failed')
    })

    test('setError clears error with null', () => {
      useDocumentsStore.setState({ error: 'Previous error' })

      useDocumentsStore.getState().setError(null)

      expect(useDocumentsStore.getState().error).toBeNull()
    })

    test('clearError clears error', () => {
      useDocumentsStore.setState({ error: 'Some error' })

      useDocumentsStore.getState().clearError()

      expect(useDocumentsStore.getState().error).toBeNull()
    })
  })

  describe('updateFilesFromJobStatus', () => {
    test('updates files based on job status by serverFileId', () => {
      const trackedFile: TrackedFile = {
        id: 'local-1',
        fileName: 'test.pdf',
        fileSize: 1024,
        status: 'uploading',
        progress: 0,
        serverFileId: 'server-file-1',
        jobId: 'job-1',
      }
      useDocumentsStore.setState({ trackedFiles: [trackedFile] })

      const jobStatus: IngestionJobStatus = {
        job_id: 'job-1',
        status: 'processing',
        submitted_at: '2024-01-01T00:00:00Z',
        total_files: 1,
        processed_files: 0,
        collection_name: 'test-collection',
        backend: 'milvus',
        metadata: {},
        file_details: [
          {
            file_id: 'server-file-1',
            file_name: 'test.pdf',
            status: 'ingesting',
            progress_percent: 75,
          },
        ],
      }

      useDocumentsStore.getState().updateFilesFromJobStatus(jobStatus)

      const updated = useDocumentsStore.getState().trackedFiles[0]
      expect(updated.status).toBe('ingesting')
      expect(updated.progress).toBe(75)
    })

    test('updates files based on job status by filename', () => {
      const trackedFile: TrackedFile = {
        id: 'local-1',
        fileName: 'test.pdf',
        fileSize: 1024,
        status: 'uploading',
        progress: 0,
        jobId: 'job-1',
      }
      useDocumentsStore.setState({ trackedFiles: [trackedFile] })

      const jobStatus: IngestionJobStatus = {
        job_id: 'job-1',
        status: 'completed',
        submitted_at: '2024-01-01T00:00:00Z',
        total_files: 1,
        processed_files: 1,
        collection_name: 'test-collection',
        backend: 'milvus',
        metadata: {},
        file_details: [
          {
            file_id: 'server-file-1',
            file_name: 'test.pdf',
            status: 'success',
            progress_percent: 100,
          },
        ],
      }

      useDocumentsStore.getState().updateFilesFromJobStatus(jobStatus)

      const updated = useDocumentsStore.getState().trackedFiles[0]
      expect(updated.status).toBe('success')
      expect(updated.progress).toBe(100)
      expect(updated.serverFileId).toBe('server-file-1')
    })

    test('updates error message from job status', () => {
      const trackedFile: TrackedFile = {
        id: 'local-1',
        fileName: 'test.pdf',
        fileSize: 1024,
        status: 'ingesting',
        progress: 50,
        serverFileId: 'server-file-1',
      }
      useDocumentsStore.setState({ trackedFiles: [trackedFile] })

      const jobStatus: IngestionJobStatus = {
        job_id: 'job-1',
        status: 'failed',
        submitted_at: '2024-01-01T00:00:00Z',
        total_files: 1,
        processed_files: 0,
        collection_name: 'test-collection',
        backend: 'milvus',
        metadata: {},
        file_details: [
          {
            file_id: 'server-file-1',
            file_name: 'test.pdf',
            status: 'failed',
            progress_percent: 50,
            error_message: 'Parsing failed',
          },
        ],
      }

      useDocumentsStore.getState().updateFilesFromJobStatus(jobStatus)

      const updated = useDocumentsStore.getState().trackedFiles[0]
      expect(updated.status).toBe('failed')
      expect(updated.errorMessage).toBe('Parsing failed')
    })

    test('leaves unmatched files unchanged', () => {
      const trackedFile: TrackedFile = {
        id: 'local-1',
        fileName: 'unmatched.pdf',
        fileSize: 1024,
        status: 'uploading',
        progress: 0,
      }
      useDocumentsStore.setState({ trackedFiles: [trackedFile] })

      const jobStatus: IngestionJobStatus = {
        job_id: 'job-1',
        status: 'completed',
        submitted_at: '2024-01-01T00:00:00Z',
        total_files: 1,
        processed_files: 1,
        collection_name: 'test-collection',
        backend: 'milvus',
        metadata: {},
        file_details: [
          {
            file_id: 'other-file',
            file_name: 'other.pdf',
            status: 'success',
            progress_percent: 100,
          },
        ],
      }

      useDocumentsStore.getState().updateFilesFromJobStatus(jobStatus)

      const file = useDocumentsStore.getState().trackedFiles[0]
      expect(file.status).toBe('uploading')
      expect(file.progress).toBe(0)
    })
  })

  describe('setFilesFromServer', () => {
    test('replaces files for collection from server', () => {
      useDocumentsStore.setState({
        trackedFiles: [
          {
            id: 'local-1',
            fileName: 'old.pdf',
            fileSize: 1024,
            status: 'success',
            progress: 100,
            collectionName: 'session-1',
          },
        ],
      })

      const serverFiles: FileInfo[] = [
        {
          file_id: 'server-1',
          file_name: 'new.pdf',
          file_size: 2048,
          collection_name: 'session-1',
          status: 'success',
          chunk_count: 5,
          metadata: {},
        },
        {
          file_id: 'server-2',
          file_name: 'new2.pdf',
          file_size: 4096,
          collection_name: 'session-1',
          status: 'ingesting',
          chunk_count: 0,
          metadata: {},
        },
      ]

      useDocumentsStore.getState().setFilesFromServer('session-1', serverFiles)

      const files = useDocumentsStore.getState().trackedFiles
      expect(files).toHaveLength(2)
      expect(files[0].id).toBe('server-1')
      expect(files[0].fileName).toBe('new.pdf')
      expect(files[0].status).toBe('success')
      expect(files[1].id).toBe('server-2')
      expect(files[1].status).toBe('ingesting')
    })

    test('preserves files from other collections', () => {
      useDocumentsStore.setState({
        trackedFiles: [
          {
            id: 'local-1',
            fileName: 'other.pdf',
            fileSize: 1024,
            status: 'success',
            progress: 100,
            collectionName: 'other-session',
          },
        ],
      })

      const serverFiles: FileInfo[] = [
        {
          file_id: 'server-1',
          file_name: 'new.pdf',
          file_size: 2048,
          collection_name: 'session-1',
          status: 'success',
          chunk_count: 5,
          metadata: {},
        },
      ]

      useDocumentsStore.getState().setFilesFromServer('session-1', serverFiles)

      const files = useDocumentsStore.getState().trackedFiles
      expect(files).toHaveLength(2)
      expect(files.find((f) => f.collectionName === 'other-session')).toBeDefined()
    })

    test('preserves jobId from existing tracked files', () => {
      useDocumentsStore.setState({
        trackedFiles: [
          {
            id: 'local-1',
            fileName: 'test.pdf',
            fileSize: 1024,
            status: 'ingesting',
            progress: 50,
            collectionName: 'session-1',
            serverFileId: 'server-1',
            jobId: 'job-123',
          },
        ],
      })

      const serverFiles: FileInfo[] = [
        {
          file_id: 'server-1',
          file_name: 'test.pdf',
          file_size: 1024,
          collection_name: 'session-1',
          status: 'success',
          chunk_count: 5,
          metadata: {},
        },
      ]

      useDocumentsStore.getState().setFilesFromServer('session-1', serverFiles)

      const files = useDocumentsStore.getState().trackedFiles
      expect(files[0].jobId).toBe('job-123')
    })

    test('preserves uploadedAt from existing tracked files over server value', () => {
      const clientTimestamp = '2025-02-12T14:30:00.000Z'
      useDocumentsStore.setState({
        trackedFiles: [
          {
            id: 'local-1',
            fileName: 'test.pdf',
            fileSize: 1024,
            status: 'ingesting',
            progress: 50,
            collectionName: 'session-1',
            serverFileId: 'server-1',
            uploadedAt: clientTimestamp,
          },
        ],
      })

      const serverFiles: FileInfo[] = [
        {
          file_id: 'server-1',
          file_name: 'test.pdf',
          file_size: 1024,
          collection_name: 'session-1',
          status: 'success',
          chunk_count: 5,
          metadata: {},
          uploaded_at: '2025-02-12', // date-only from server (midnight bug)
        },
      ]

      useDocumentsStore.getState().setFilesFromServer('session-1', serverFiles)

      const files = useDocumentsStore.getState().trackedFiles
      expect(files[0].uploadedAt).toBe(clientTimestamp)
    })

    test('uses server uploadedAt when no existing tracked file', () => {
      useDocumentsStore.setState({ trackedFiles: [] })

      const serverFiles: FileInfo[] = [
        {
          file_id: 'server-1',
          file_name: 'test.pdf',
          file_size: 1024,
          collection_name: 'session-1',
          status: 'success',
          chunk_count: 5,
          metadata: {},
          uploaded_at: '2025-02-12',
        },
      ]

      useDocumentsStore.getState().setFilesFromServer('session-1', serverFiles)

      const files = useDocumentsStore.getState().trackedFiles
      expect(files[0].uploadedAt).toBe('2025-02-12')
    })
  })

  describe('banner tracking', () => {
    test('markBannerShown marks uploaded banner', () => {
      useDocumentsStore.getState().markBannerShown('job-1', 'uploaded')

      const banners = useDocumentsStore.getState().shownBannersForJobs['job-1']
      expect(banners.uploaded).toBe(true)
      expect(banners.ingested).toBe(false)
    })

    test('markBannerShown marks ingested banner', () => {
      useDocumentsStore.getState().markBannerShown('job-1', 'ingested')

      const banners = useDocumentsStore.getState().shownBannersForJobs['job-1']
      expect(banners.uploaded).toBe(false)
      expect(banners.ingested).toBe(true)
    })

    test('markBannerShown preserves existing banner state', () => {
      useDocumentsStore.getState().markBannerShown('job-1', 'uploaded')
      useDocumentsStore.getState().markBannerShown('job-1', 'ingested')

      const banners = useDocumentsStore.getState().shownBannersForJobs['job-1']
      expect(banners.uploaded).toBe(true)
      expect(banners.ingested).toBe(true)
    })

    test('markBannerShown tracks multiple jobs', () => {
      useDocumentsStore.getState().markBannerShown('job-1', 'uploaded')
      useDocumentsStore.getState().markBannerShown('job-2', 'ingested')

      const state = useDocumentsStore.getState().shownBannersForJobs
      expect(state['job-1'].uploaded).toBe(true)
      expect(state['job-2'].ingested).toBe(true)
    })
  })

  describe('selectors', () => {
    test('selectFilesInProgress returns uploading and ingesting files', () => {
      const state = {
        trackedFiles: [
          { id: '1', fileName: 'a.pdf', fileSize: 100, status: 'uploading' as const, progress: 50 },
          { id: '2', fileName: 'b.pdf', fileSize: 100, status: 'ingesting' as const, progress: 75 },
          { id: '3', fileName: 'c.pdf', fileSize: 100, status: 'success' as const, progress: 100 },
          { id: '4', fileName: 'd.pdf', fileSize: 100, status: 'failed' as const, progress: 0 },
        ],
      }

      const inProgress = selectFilesInProgress(state as any)

      expect(inProgress).toHaveLength(2)
      expect(inProgress.map((f) => f.id)).toEqual(['1', '2'])
    })

    test('selectCompletedFiles returns success files', () => {
      const state = {
        trackedFiles: [
          { id: '1', fileName: 'a.pdf', fileSize: 100, status: 'success' as const, progress: 100 },
          { id: '2', fileName: 'b.pdf', fileSize: 100, status: 'success' as const, progress: 100 },
          { id: '3', fileName: 'c.pdf', fileSize: 100, status: 'ingesting' as const, progress: 50 },
        ],
      }

      const completed = selectCompletedFiles(state as any)

      expect(completed).toHaveLength(2)
      expect(completed.map((f) => f.id)).toEqual(['1', '2'])
    })

    test('selectFailedFiles returns failed files', () => {
      const state = {
        trackedFiles: [
          { id: '1', fileName: 'a.pdf', fileSize: 100, status: 'failed' as const, progress: 0 },
          { id: '2', fileName: 'b.pdf', fileSize: 100, status: 'success' as const, progress: 100 },
        ],
      }

      const failed = selectFailedFiles(state as any)

      expect(failed).toHaveLength(1)
      expect(failed[0].id).toBe('1')
    })

    test('selectIsProcessing returns true when uploading', () => {
      const state = { isUploading: true, isPolling: false }

      expect(selectIsProcessing(state as any)).toBe(true)
    })

    test('selectIsProcessing returns true when polling', () => {
      const state = { isUploading: false, isPolling: true }

      expect(selectIsProcessing(state as any)).toBe(true)
    })

    test('selectIsProcessing returns false when idle', () => {
      const state = { isUploading: false, isPolling: false }

      expect(selectIsProcessing(state as any)).toBe(false)
    })
  })
})

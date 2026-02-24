// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { renderHook } from '@testing-library/react'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { useFileUploadBanners } from './use-file-upload-banners'

// Mock the stores
const mockMarkBannerShown = vi.fn()
const mockOpenRightPanel = vi.fn()
const mockSetDataSourcesPanelTab = vi.fn()

vi.mock('../store', () => ({
  useDocumentsStore: vi.fn((selector) => {
    const state = {
      currentCollectionName: null,
      collectionInfo: null,
      trackedFiles: [],
      activeJobId: null,
      isCreatingCollection: false,
      isUploading: false,
      isPolling: false,
      error: null,
      shownBannersForJobs: {},
      markBannerShown: mockMarkBannerShown,
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return selector ? (selector as any)(state) : state
  }),
}))

vi.mock('@/features/layout/store', () => ({
  useLayoutStore: () => ({
    openRightPanel: mockOpenRightPanel,
    setDataSourcesPanelTab: mockSetDataSourcesPanelTab,
  }),
}))

import { useDocumentsStore } from '../store'
import type { TrackedFile } from '../types'

/**
 * Helper to create tracked file objects for testing
 */
function createTrackedFile(
  overrides: Partial<TrackedFile> & { id: string; fileName: string; status: TrackedFile['status'] }
): TrackedFile {
  return {
    fileSize: 1024,
    progress: 0,
    ...overrides,
  }
}

describe('useFileUploadBanners', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  test('does not open panel when no tracked files', () => {
    renderHook(() => useFileUploadBanners())

    expect(mockOpenRightPanel).not.toHaveBeenCalled()
    expect(mockMarkBannerShown).not.toHaveBeenCalled()
  })

  test('does not open panel for files without jobId', () => {
    vi.mocked(useDocumentsStore).mockImplementation((selector) => {
      const state = {
        currentCollectionName: null,
        collectionInfo: null,
        trackedFiles: [
          createTrackedFile({
            id: 'file-1',
            fileName: 'test.pdf',
            status: 'success',
            collectionName: 'session-1',
            // No jobId
          }),
        ],
        activeJobId: null,
        isCreatingCollection: false,
        isUploading: false,
        isPolling: false,
        error: null,
        shownBannersForJobs: {},
        markBannerShown: mockMarkBannerShown,
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return selector ? (selector as any)(state) : state
    })

    renderHook(() => useFileUploadBanners())

    expect(mockOpenRightPanel).not.toHaveBeenCalled()
  })

  test('opens Data Sources panel when all files complete successfully', () => {
    vi.mocked(useDocumentsStore).mockImplementation((selector) => {
      const state = {
        currentCollectionName: null,
        collectionInfo: null,
        trackedFiles: [
          createTrackedFile({
            id: 'file-1',
            fileName: 'test1.pdf',
            status: 'success',
            jobId: 'job-1',
            collectionName: 'session-1',
          }),
          createTrackedFile({
            id: 'file-2',
            fileName: 'test2.pdf',
            status: 'success',
            jobId: 'job-1',
            collectionName: 'session-1',
          }),
        ],
        activeJobId: null,
        isCreatingCollection: false,
        isUploading: false,
        isPolling: false,
        error: null,
        shownBannersForJobs: {},
        markBannerShown: mockMarkBannerShown,
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return selector ? (selector as any)(state) : state
    })

    renderHook(() => useFileUploadBanners())

    expect(mockSetDataSourcesPanelTab).toHaveBeenCalledWith('files')
    expect(mockOpenRightPanel).toHaveBeenCalledWith('data-sources')
    expect(mockMarkBannerShown).toHaveBeenCalledWith('job-1', 'ingested')
  })

  test('does not open panel if already handled for this job', () => {
    vi.mocked(useDocumentsStore).mockImplementation((selector) => {
      const state = {
        currentCollectionName: null,
        collectionInfo: null,
        trackedFiles: [
          createTrackedFile({
            id: 'file-1',
            fileName: 'test.pdf',
            status: 'success',
            jobId: 'job-1',
            collectionName: 'session-1',
          }),
        ],
        activeJobId: null,
        isCreatingCollection: false,
        isUploading: false,
        isPolling: false,
        error: null,
        shownBannersForJobs: {
          'job-1': { uploaded: true, ingested: true },
        },
        markBannerShown: mockMarkBannerShown,
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return selector ? (selector as any)(state) : state
    })

    renderHook(() => useFileUploadBanners())

    expect(mockOpenRightPanel).not.toHaveBeenCalled()
    expect(mockMarkBannerShown).not.toHaveBeenCalled()
  })

  test('does not open panel while files are still ingesting', () => {
    vi.mocked(useDocumentsStore).mockImplementation((selector) => {
      const state = {
        currentCollectionName: null,
        collectionInfo: null,
        trackedFiles: [
          createTrackedFile({
            id: 'file-1',
            fileName: 'test1.pdf',
            status: 'success',
            jobId: 'job-1',
            collectionName: 'session-1',
          }),
          createTrackedFile({
            id: 'file-2',
            fileName: 'test2.pdf',
            status: 'ingesting',
            jobId: 'job-1',
            collectionName: 'session-1',
          }),
        ],
        activeJobId: null,
        isCreatingCollection: false,
        isUploading: false,
        isPolling: false,
        error: null,
        shownBannersForJobs: {},
        markBannerShown: mockMarkBannerShown,
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return selector ? (selector as any)(state) : state
    })

    renderHook(() => useFileUploadBanners())

    expect(mockOpenRightPanel).not.toHaveBeenCalled()
  })

  test('handles multiple jobs independently', () => {
    vi.mocked(useDocumentsStore).mockImplementation((selector) => {
      const state = {
        currentCollectionName: null,
        collectionInfo: null,
        trackedFiles: [
          // Job 1 - still ingesting
          createTrackedFile({
            id: 'file-1',
            fileName: 'test1.pdf',
            status: 'ingesting',
            jobId: 'job-1',
            collectionName: 'session-1',
          }),
          // Job 2 - complete
          createTrackedFile({
            id: 'file-2',
            fileName: 'test2.pdf',
            status: 'success',
            jobId: 'job-2',
            collectionName: 'session-2',
          }),
        ],
        activeJobId: null,
        isCreatingCollection: false,
        isUploading: false,
        isPolling: false,
        error: null,
        shownBannersForJobs: {},
        markBannerShown: mockMarkBannerShown,
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return selector ? (selector as any)(state) : state
    })

    renderHook(() => useFileUploadBanners())

    // Job 2 should trigger panel open
    expect(mockSetDataSourcesPanelTab).toHaveBeenCalledWith('files')
    expect(mockOpenRightPanel).toHaveBeenCalledWith('data-sources')
    expect(mockMarkBannerShown).toHaveBeenCalledWith('job-2', 'ingested')

    // Only one call (for job-2), not for job-1
    expect(mockMarkBannerShown).toHaveBeenCalledTimes(1)
  })

  test('opens Data Sources panel when all files have failed', () => {
    vi.mocked(useDocumentsStore).mockImplementation((selector) => {
      const state = {
        currentCollectionName: null,
        collectionInfo: null,
        trackedFiles: [
          createTrackedFile({
            id: 'file-1',
            fileName: 'test1.pdf',
            status: 'failed',
            jobId: 'job-1',
            collectionName: 'session-1',
            errorMessage: 'Ingestion failed',
          }),
        ],
        activeJobId: null,
        isCreatingCollection: false,
        isUploading: false,
        isPolling: false,
        error: null,
        shownBannersForJobs: {},
        markBannerShown: mockMarkBannerShown,
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return selector ? (selector as any)(state) : state
    })

    renderHook(() => useFileUploadBanners())

    expect(mockSetDataSourcesPanelTab).toHaveBeenCalledWith('files')
    expect(mockOpenRightPanel).toHaveBeenCalledWith('data-sources')
    expect(mockMarkBannerShown).toHaveBeenCalledWith('job-1', 'ingested')
  })

  test('opens Data Sources panel when files are a mix of success and failed', () => {
    vi.mocked(useDocumentsStore).mockImplementation((selector) => {
      const state = {
        currentCollectionName: null,
        collectionInfo: null,
        trackedFiles: [
          createTrackedFile({
            id: 'file-1',
            fileName: 'test1.pdf',
            status: 'success',
            jobId: 'job-1',
            collectionName: 'session-1',
          }),
          createTrackedFile({
            id: 'file-2',
            fileName: 'test2.pdf',
            status: 'failed',
            jobId: 'job-1',
            collectionName: 'session-1',
            errorMessage: 'Unsupported format',
          }),
        ],
        activeJobId: null,
        isCreatingCollection: false,
        isUploading: false,
        isPolling: false,
        error: null,
        shownBannersForJobs: {},
        markBannerShown: mockMarkBannerShown,
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return selector ? (selector as any)(state) : state
    })

    renderHook(() => useFileUploadBanners())

    expect(mockSetDataSourcesPanelTab).toHaveBeenCalledWith('files')
    expect(mockOpenRightPanel).toHaveBeenCalledWith('data-sources')
    expect(mockMarkBannerShown).toHaveBeenCalledWith('job-1', 'ingested')
  })

  test('does not open panel when some files are still ingesting alongside failures', () => {
    vi.mocked(useDocumentsStore).mockImplementation((selector) => {
      const state = {
        currentCollectionName: null,
        collectionInfo: null,
        trackedFiles: [
          createTrackedFile({
            id: 'file-1',
            fileName: 'test1.pdf',
            status: 'failed',
            jobId: 'job-1',
            collectionName: 'session-1',
          }),
          createTrackedFile({
            id: 'file-2',
            fileName: 'test2.pdf',
            status: 'ingesting',
            jobId: 'job-1',
            collectionName: 'session-1',
          }),
        ],
        activeJobId: null,
        isCreatingCollection: false,
        isUploading: false,
        isPolling: false,
        error: null,
        shownBannersForJobs: {},
        markBannerShown: mockMarkBannerShown,
      }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return selector ? (selector as any)(state) : state
    })

    renderHook(() => useFileUploadBanners())

    expect(mockOpenRightPanel).not.toHaveBeenCalled()
  })
})

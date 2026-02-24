// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Documents Store
 *
 * Zustand store for managing document/file upload state.
 * Tracks files across upload → ingestion → success/failure lifecycle.
 */

import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import type { DocumentsStore, DocumentsState, TrackedFile } from './types'
import { DEFAULT_JOB_BANNER_STATE } from './types'

const initialState: DocumentsState = {
  currentCollectionName: null,
  collectionInfo: null,
  trackedFiles: [],
  activeJobId: null,
  isCreatingCollection: false,
  isUploading: false,
  isPolling: false,
  error: null,
  shownBannersForJobs: {},
}

import { mapBackendStatus } from './utils'

export const useDocumentsStore = create<DocumentsStore>()(
  devtools(
    (set) => ({
      ...initialState,

      // --------------------------------------------------------------------------
      // Collection Management
      // --------------------------------------------------------------------------

      setCurrentCollection: (name) => {
        set({ currentCollectionName: name }, false, 'setCurrentCollection')
      },

      setCollectionInfo: (info) => {
        set({ collectionInfo: info }, false, 'setCollectionInfo')
      },

      // --------------------------------------------------------------------------
      // File Tracking
      // --------------------------------------------------------------------------

      addTrackedFile: (file) => {
        set(
          (state) => ({
            trackedFiles: [...state.trackedFiles, file],
          }),
          false,
          'addTrackedFile'
        )
      },

      updateTrackedFile: (id, updates) => {
        set(
          (state) => ({
            trackedFiles: state.trackedFiles.map((f) => (f.id === id ? { ...f, ...updates } : f)),
          }),
          false,
          'updateTrackedFile'
        )
      },

      removeTrackedFile: (id) => {
        set(
          (state) => ({
            trackedFiles: state.trackedFiles.filter((f) => f.id !== id),
          }),
          false,
          'removeTrackedFile'
        )
      },

      clearTrackedFiles: () => {
        set({ trackedFiles: [] }, false, 'clearTrackedFiles')
      },

      clearFilesForCollection: (collectionName) => {
        set(
          (state) => ({
            trackedFiles: state.trackedFiles.filter((f) => f.collectionName !== collectionName),
          }),
          false,
          'clearFilesForCollection'
        )
      },

      // --------------------------------------------------------------------------
      // Job Tracking
      // --------------------------------------------------------------------------

      setActiveJobId: (jobId) => {
        set({ activeJobId: jobId }, false, 'setActiveJobId')
      },

      // --------------------------------------------------------------------------
      // Loading States
      // --------------------------------------------------------------------------

      setCreatingCollection: (loading) => {
        set({ isCreatingCollection: loading }, false, 'setCreatingCollection')
      },

      setUploading: (loading) => {
        set({ isUploading: loading }, false, 'setUploading')
      },

      setPolling: (polling) => {
        set({ isPolling: polling }, false, 'setPolling')
      },

      // --------------------------------------------------------------------------
      // Error Handling
      // --------------------------------------------------------------------------

      setError: (error) => {
        set({ error }, false, 'setError')
      },

      clearError: () => {
        set({ error: null }, false, 'clearError')
      },

      // --------------------------------------------------------------------------
      // Bulk Operations
      // --------------------------------------------------------------------------

      updateFilesFromJobStatus: (jobStatus) => {
        set(
          (state) => {
            const updatedFiles = state.trackedFiles.map((file) => {
              // Find matching file in job details by server ID or filename
              const jobFile = jobStatus.file_details.find(
                (jf) => jf.file_id === file.serverFileId || jf.file_name === file.fileName
              )

              if (!jobFile) return file

              return {
                ...file,
                status: mapBackendStatus(jobFile.status),
                progress: jobFile.progress_percent,
                errorMessage: jobFile.error_message,
                serverFileId: jobFile.file_id,
              }
            })

            return { trackedFiles: updatedFiles }
          },
          false,
          'updateFilesFromJobStatus'
        )
      },

      setFilesFromServer: (collectionName, files) => {
        set(
          (state) => {
            // Get existing files for this collection to preserve jobId
            const existingFilesMap = new Map(
              state.trackedFiles
                .filter((f) => f.collectionName === collectionName)
                .map((f) => [f.serverFileId || f.id, f])
            )

            // Remove any existing files for this collection
            const otherFiles = state.trackedFiles.filter((f) => f.collectionName !== collectionName)

            // Convert FileInfo to TrackedFile, preserving jobId from existing files
            // Use the collectionName parameter (sessionId) for consistency with sessionFiles filtering
            const serverFiles: TrackedFile[] = files.map((file) => {
              const existingFile = existingFilesMap.get(file.file_id)
              return {
                id: file.file_id, // Use server ID as local ID
                fileName: file.file_name,
                fileSize: file.file_size || 0,
                status: file.status,
                progress: file.status === 'success' ? 100 : 0,
                errorMessage: file.error_message,
                serverFileId: file.file_id,
                collectionName, // Use parameter, not file.collection_name, for consistent filtering
                // Preserve jobId and uploadedAt from existing tracked file if available.
                // The client sets uploadedAt with full time precision on upload;
                // the server may return a date-only string (midnight) from ChromaDB metadata.
                jobId: existingFile?.jobId,
                uploadedAt: existingFile?.uploadedAt || file.uploaded_at,
              }
            })

            return {
              trackedFiles: [...otherFiles, ...serverFiles],
            }
          },
          false,
          'setFilesFromServer'
        )
      },

      // --------------------------------------------------------------------------
      // Banner Tracking (for deduplication)
      // --------------------------------------------------------------------------

      markBannerShown: (jobId, type) => {
        set(
          (state) => {
            const existing = state.shownBannersForJobs[jobId] || DEFAULT_JOB_BANNER_STATE
            return {
              shownBannersForJobs: {
                ...state.shownBannersForJobs,
                [jobId]: {
                  ...existing,
                  [type]: true,
                },
              },
            }
          },
          false,
          'markBannerShown'
        )
      },
    }),
    { name: 'DocumentsStore' }
  )
)

// --------------------------------------------------------------------------
// Selectors
// --------------------------------------------------------------------------

/**
 * Get files that are currently in progress (uploading or ingesting)
 */
export const selectFilesInProgress = (state: DocumentsState): TrackedFile[] =>
  state.trackedFiles.filter((f) => f.status === 'uploading' || f.status === 'ingesting')

/**
 * Get files that have completed successfully
 */
export const selectCompletedFiles = (state: DocumentsState): TrackedFile[] =>
  state.trackedFiles.filter((f) => f.status === 'success')

/**
 * Get files that have failed
 */
export const selectFailedFiles = (state: DocumentsState): TrackedFile[] =>
  state.trackedFiles.filter((f) => f.status === 'failed')

/**
 * Check if any upload/ingestion is in progress
 */
export const selectIsProcessing = (state: DocumentsState): boolean =>
  state.isUploading || state.isPolling

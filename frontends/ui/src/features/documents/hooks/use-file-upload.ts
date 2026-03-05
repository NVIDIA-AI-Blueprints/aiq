// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * useFileUpload Hook
 *
 * Simplified hook for file upload operations.
 * Delegates complex orchestration (polling, persistence, session management)
 * to the UploadOrchestrator service.
 */

'use client'

import { useCallback, useEffect, useMemo, useRef } from 'react'
import { v4 as uuidv4 } from 'uuid'
import { createDocumentsClient } from '@/adapters/api'
import { useDocumentsStore } from '../store'
import { useAuth } from '@/adapters/auth'
import { useAppConfig } from '@/shared/context'
import { useLayoutStore } from '@/features/layout/store'
import type { TrackedFile } from '../types'
import { validateFileUpload, type ValidationContext } from '../validation'
import { UploadOrchestrator } from '../orchestrator'
import { markSessionHasCollection } from '../persistence'
import { useChatStore } from '@/features/chat'

interface UseFileUploadOptions {
  sessionId?: string
  onComplete?: () => void
  onError?: (error: Error) => void
}

interface UseFileUploadReturn {
  uploadFiles: (files: File[], targetSessionId?: string) => Promise<void>
  cancelUpload: () => void
  deleteFile: (fileId: string) => Promise<void>
  retryFile: (fileId: string) => Promise<void>
  trackedFiles: TrackedFile[]
  sessionFiles: TrackedFile[]
  validationContext: ValidationContext
  isUploading: boolean
  isPolling: boolean
  error: string | null
  clearError: () => void
}

export const useFileUpload = (options: UseFileUploadOptions = {}): UseFileUploadReturn => {
  const { sessionId, onComplete, onError } = options

  const { idToken } = useAuth()
  const { fileUpload: fileUploadConfig } = useAppConfig()
  const clientRef = useRef(createDocumentsClient({ authToken: idToken }))
  const previousSessionIdRef = useRef<string | undefined>(undefined)

  const {
    trackedFiles,
    isUploading,
    isPolling,
    error,
    setCurrentCollection,
    setCollectionInfo,
    addTrackedFile,
    updateTrackedFile,
    removeTrackedFile,
    unmarkRecentlyDeleted,
    setUploading,
    setError,
    clearError,
  } = useDocumentsStore()

  const sessionFiles = useMemo(
    () => (sessionId ? trackedFiles.filter((f) => f.collectionName === sessionId) : []),
    [trackedFiles, sessionId]
  )

  const validationContext: ValidationContext = useMemo(
    () => ({
      existingTotalSize: sessionFiles.reduce((sum, f) => sum + f.fileSize, 0),
      existingFileCount: sessionFiles.length,
      existingFileNames: new Set(sessionFiles.map((f) => f.fileName)),
    }),
    [sessionFiles]
  )

  useEffect(() => {
    clientRef.current = createDocumentsClient({ authToken: idToken })
    UploadOrchestrator.setAuthToken(idToken)
  }, [idToken])

  useEffect(() => {
    UploadOrchestrator.setCallbacks({ onComplete, onError })
  }, [onComplete, onError])

  useEffect(() => {
    const previousSessionId = previousSessionIdRef.current

    if (sessionId !== previousSessionId) {
      UploadOrchestrator.handleSessionChange(sessionId)
      previousSessionIdRef.current = sessionId
    }
  }, [sessionId])

  // Retry file loading when knowledgeLayerAvailable becomes true.
  // On browser refresh, the initial loadFilesForSession call may fire before
  // fetchDataSources completes, causing it to skip because
  // knowledgeLayerAvailable is still false. This effect ensures we retry
  // once the knowledge layer is confirmed available.
  const knowledgeLayerAvailable = useLayoutStore((state) => state.knowledgeLayerAvailable)
  useEffect(() => {
    if (knowledgeLayerAvailable && sessionId) {
      UploadOrchestrator.loadFilesForSession(sessionId)
    }
  }, [knowledgeLayerAvailable, sessionId])

  // Note: We intentionally don't cleanup the orchestrator on unmount.
  // The orchestrator is a singleton that manages polling across component lifecycles.
  // Cleanup happens via session changes (handleSessionChange) when user switches sessions.

  const ensureCollectionExists = useCallback(
    async (collectionName: string): Promise<void> => {
      let collection = await clientRef.current.getCollection(collectionName)

      if (!collection) {
        collection = await clientRef.current.createCollection(
          collectionName,
          `Documents for session ${collectionName}`
        )
      }

      // Mark this session as having a collection so future session switches
      // know to check the backend for files (prevents unnecessary 404s)
      markSessionHasCollection(collectionName)

      setCurrentCollection(collectionName)
      setCollectionInfo(collection)
    },
    [setCurrentCollection, setCollectionInfo]
  )

  const uploadFiles = useCallback(
    async (files: File[], targetSessionId?: string) => {
      if (files.length === 0) return

      const collectionName = targetSessionId || sessionId
      if (!collectionName) {
        const uploadError = new Error('Session ID required for upload')
        setError(uploadError.message)
        onError?.(uploadError)
        return
      }

      const validationResult = validateFileUpload(files, validationContext, fileUploadConfig)

      if (validationResult.batchErrors.length > 0) {
        setError(validationResult.summary)
        return
      }

      if (validationResult.validFiles.length === 0) {
        setError(validationResult.summary)
        return
      }

      const validFiles = validationResult.validFiles
      setUploading(true)

      if (validationResult.fileErrors.length > 0) {
        const skippedCount = validationResult.fileErrors.length
        const uploadingCount = validFiles.length
        setError(
          `Uploading ${uploadingCount} file${uploadingCount > 1 ? 's' : ''}, skipped ${skippedCount} (${validationResult.summary})`
        )
      } else {
        clearError()
      }

      const trackedFileMap: Map<string, TrackedFile> = new Map()

      // Add tracked files to the store immediately so uploading cards appear
      // in the UI before any network calls (collection creation, upload POST)
      for (const file of validFiles) {
        const trackedFile: TrackedFile = {
          id: uuidv4(),
          file,
          fileName: file.name,
          fileSize: file.size,
          status: 'uploading',
          progress: 0,
          collectionName,
          uploadedAt: new Date().toISOString(),
        }
        addTrackedFile(trackedFile)
        trackedFileMap.set(file.name, trackedFile)
      }

      // Show informational banner in chat as soon as upload starts
      const chatStore = useChatStore.getState()
      chatStore.addFileUploadStatusCard(
        'uploaded',
        validFiles.length,
        `upload-${Date.now()}`,
        collectionName
      )

      try {
        await ensureCollectionExists(collectionName)

        const { job_id, file_ids } = await clientRef.current.uploadFiles(collectionName, validFiles)

        // Upload POST response means upload is complete and ingestion has started
        // Set status to 'ingesting' immediately
        const filesToPersist: TrackedFile[] = []

        validFiles.forEach((file, index) => {
          const trackedFile = trackedFileMap.get(file.name)
          if (trackedFile) {
            const updatedFile: TrackedFile = {
              ...trackedFile,
              status: 'ingesting',
              serverFileId: file_ids[index],
              jobId: job_id,
            }
            updateTrackedFile(trackedFile.id, {
              status: 'ingesting',
              serverFileId: file_ids[index],
              jobId: job_id,
            })
            filesToPersist.push(updatedFile)
          }
        })

        UploadOrchestrator.startPolling(job_id, collectionName, filesToPersist)
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') {
          return
        }
        const message = err instanceof Error ? err.message : 'Upload failed'
        setError(message)
        onError?.(err instanceof Error ? err : new Error(message))

        // Update all files that were added to 'failed' status
        for (const trackedFile of trackedFileMap.values()) {
          updateTrackedFile(trackedFile.id, {
            status: 'failed',
            errorMessage: message,
          })
        }
      } finally {
        setUploading(false)
      }
    },
    [
      sessionId,
      validationContext,
      fileUploadConfig,
      ensureCollectionExists,
      addTrackedFile,
      updateTrackedFile,
      setUploading,
      clearError,
      setError,
      onError,
    ]
  )

  const cancelUpload = useCallback(() => {
    UploadOrchestrator.stopPolling()
    setUploading(false)
  }, [setUploading])

  const deleteFile = useCallback(
    async (fileId: string) => {
      const file = trackedFiles.find((f) => f.id === fileId)
      if (!file || !file.collectionName) {
        removeTrackedFile(fileId)
        return
      }

      const collectionName = file.collectionName
      const deleteId = file.serverFileId || file.fileName

      // Optimistic delete: remove from UI immediately, call API in background.
      // This prevents the file from reappearing if a concurrent server reload
      // returns stale data before the backend processes the delete.
      removeTrackedFile(fileId)

      try {
        await clientRef.current.deleteFiles(collectionName, [deleteId])
      } catch (err) {
        // Restore the file on failure so the user can retry.
        // Also undo the recentlyDeletedIds entry so the file isn't
        // filtered out on the next server sync.
        addTrackedFile(file)
        unmarkRecentlyDeleted(file)
        const message = err instanceof Error ? err.message : 'Delete failed'
        setError(message)
      }
    },
    [trackedFiles, addTrackedFile, removeTrackedFile, unmarkRecentlyDeleted, setError]
  )

  const retryFile = useCallback(
    async (fileId: string) => {
      const file = trackedFiles.find((f) => f.id === fileId)
      if (!file) return

      if (!file.file) {
        setError('Cannot retry server-loaded files. Please upload the file again.')
        return
      }

      removeTrackedFile(fileId)
      await uploadFiles([file.file])
    },
    [trackedFiles, removeTrackedFile, uploadFiles, setError]
  )

  return {
    uploadFiles,
    cancelUpload,
    deleteFile,
    retryFile,
    trackedFiles,
    sessionFiles,
    validationContext,
    isUploading,
    isPolling,
    error,
    clearError,
  }
}

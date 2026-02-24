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
  const previousSessionIdRef = useRef<string | undefined>(sessionId)

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

      try {
        await ensureCollectionExists(collectionName)

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

  const addFileUploadStatusCard = useChatStore((state) => state.addFileUploadStatusCard)

  const deleteFile = useCallback(
    async (fileId: string) => {
      const file = trackedFiles.find((f) => f.id === fileId)
      if (!file || !file.collectionName) {
        removeTrackedFile(fileId)
        return
      }

      const collectionName = file.collectionName

      try {
        await clientRef.current.deleteFiles(collectionName, [file.fileName])
        removeTrackedFile(fileId)

        // File deletion is handled silently - no status message needed
        // (removed 'deleted' status type from FileUploadStatusType)
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Delete failed'
        setError(message)
      }
    },
    [trackedFiles, removeTrackedFile, setError, addFileUploadStatusCard]
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

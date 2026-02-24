// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * FileSourcesTab Component
 *
 * Content for the "File Sources" tab in the DataSourcePanel.
 * Displays a list of uploaded file sources with their status.
 * Integrates with file upload system for real-time progress tracking.
 */

'use client'

import { type FC, useCallback, useRef, useState } from 'react'
import { Flex, Text, Button, StatusMessage, Banner } from '@/adapters/ui'
import { LoadingSpinner } from '@/adapters/ui/icons'
import { FileSourceCard } from './FileSourceCard'
import { DeleteFileConfirmationModal } from './DeleteFileConfirmationModal'
import { useFileUpload, useDocumentsStore, FileUploadZone, mapToDisplayStatus } from '@/features/documents'
import { useChatStore } from '@/features/chat/store'
import { useLayoutStore } from '../store'
import { useAppConfig } from '@/shared/context'

interface FileSourcesTabProps {
  /** Callback when a file is deleted */
  onDeleteFile?: (id: string) => void
}

/**
 * Tab content showing list of uploaded file sources.
 * Connected to the file upload store for real-time updates.
 */
export const FileSourcesTab: FC<FileSourcesTabProps> = ({ onDeleteFile }) => {
  // Get current conversation and ensureSession for session management
  const currentConversation = useChatStore((state) => state.currentConversation)
  const ensureSession = useChatStore((state) => state.ensureSession)

  // Check if file uploads are available (knowledge layer)
  const knowledgeLayerAvailable = useLayoutStore((state) => state.knowledgeLayerAvailable)

  // Get file upload configuration from app config
  const { fileUpload: fileUploadConfig } = useAppConfig()

  // File upload hook - provides session files and handles validation internally
  const {
    uploadFiles,
    deleteFile,
    sessionFiles,
    isUploading,
    isPolling,
    error: uploadError,
    clearError,
  } = useFileUpload({
    sessionId: currentConversation?.id,
  })

  // The documents store's currentCollectionName tells us WHICH session is actively being processed.
  // isUploading/isPolling are global flags, so we must scope to the current session to avoid
  // showing a spinner for uploads belonging to a different session.
  const activeCollection = useDocumentsStore((state) => state.currentCollectionName)
  const isThisSessionProcessing =
    activeCollection === currentConversation?.id && (isUploading || isPolling)

  // Show loading spinner when THIS session's files are being processed but haven't appeared yet
  const isFileProcessing = isThisSessionProcessing && sessionFiles.length === 0

  // Delete confirmation modal state
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false)
  const [fileIdToDelete, setFileIdToDelete] = useState<string | null>(null)

  /**
   * Handle file upload with session auto-creation.
   * Validation is handled internally by uploadFiles.
   */
  const handleUpload = useCallback(
    async (files: File[]) => {
      const sessionId = ensureSession()
      if (!sessionId) {
        console.error('Failed to create session for upload')
        return
      }
      // uploadFiles validates internally and sets error if invalid
      await uploadFiles(files, sessionId)
    },
    [ensureSession, uploadFiles]
  )

  // Hidden file input ref
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Handle Add File button click
  const handleAddFileClick = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  // Handle file input change
  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || [])
      if (files.length > 0) {
        handleUpload(files)
      }
      // Reset input so same file can be selected again
      e.target.value = ''
    },
    [handleUpload]
  )

  // Opens the delete confirmation modal
  const handleDeleteClick = useCallback((id: string) => {
    setFileIdToDelete(id)
    setIsDeleteModalOpen(true)
  }, [])

  // Actually performs the delete after confirmation
  const handleConfirmDelete = useCallback(async () => {
    if (fileIdToDelete) {
      await deleteFile(fileIdToDelete)
      onDeleteFile?.(fileIdToDelete)
      setFileIdToDelete(null)
    }
  }, [fileIdToDelete, deleteFile, onDeleteFile])

  // Handles modal close/cancel
  const handleModalOpenChange = useCallback((open: boolean) => {
    setIsDeleteModalOpen(open)
    if (!open) {
      setFileIdToDelete(null)
    }
  }, [])

  if (sessionFiles.length === 0) {
    return (
      <Flex direction="col" gap="4" className="flex-1">
        {/* Show info banner when file upload is not available */}
        {!knowledgeLayerAvailable && (
          <Banner kind="inline" status="info" className="mb-6 px-4 py-3">
            Setup backend to enable files.
          </Banner>
        )}

        {/* Show loading spinner when files are being processed but API hasn't updated yet */}
        {isFileProcessing && (
          <Flex direction="col" align="center" justify="center" gap="2" className="py-8">
            <LoadingSpinner size="medium" aria-label="Processing files" />
            <Text kind="body/regular/sm" className="text-subtle">
              Checking for files...
            </Text>
          </Flex>
        )}

        {/* Show empty state message when file upload is available and not processing */}
        {knowledgeLayerAvailable && !isFileProcessing && (
          <StatusMessage
            size="small"
            slotHeading="No Files"
            slotSubheading="You have not added any files to this session. Once you do they will appear here."
          />
        )}

        {/* Upload Error Display */}
        {uploadError && (
          <Banner kind="inline" status="error" onClose={clearError}>
            {uploadError}
          </Banner>
        )}

        {/* File Upload Zone for empty state - only show when knowledge layer is available and not processing */}
        {knowledgeLayerAvailable && !isFileProcessing && (
          <FileUploadZone
            sessionId={currentConversation?.id}
            acceptedTypes={fileUploadConfig.acceptedTypes}
            maxFileSize={fileUploadConfig.maxFileSize}
            onUpload={handleUpload}
            isUploading={isUploading}
          />
        )}
      </Flex>
    )
  }

  return (
    <Flex direction="col" gap="2" className="flex-1 overflow-y-auto">
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={fileUploadConfig.acceptedTypes}
        className="hidden"
        onChange={handleFileChange}
      />

      {/* Upload Error Display */}
      {uploadError && (
        <Banner kind="inline" status="error" onClose={clearError}>
          {uploadError}
        </Banner>
      )}

      {/* Header with count and add button */}
      <Flex align="center" justify="between" className="mb-1">
        <Text kind="label/semibold/xs" className="text-subtle uppercase">
          Uploaded Files ({sessionFiles.length})
        </Text>
        <Button
          kind="tertiary"
          size="small"
          onClick={handleAddFileClick}
          disabled={isUploading || !knowledgeLayerAvailable}
          title={knowledgeLayerAvailable ? "Add files" : "File upload not available"}
        >
          + Add File
        </Button>
      </Flex>

      {/* File list */}
      {sessionFiles.map((file) => (
        <FileSourceCard
          key={file.id}
          id={file.id}
          title={file.fileName}
          fileSize={file.fileSize}
          uploadedAt={file.uploadedAt}
          status={mapToDisplayStatus(file.status)}
          errorMessage={file.errorMessage ?? undefined}
          expirationIntervalHours={fileUploadConfig.fileExpirationCheckIntervalHours}
          onDelete={handleDeleteClick}
        />
      ))}

      {/* Delete Confirmation Modal */}
      <DeleteFileConfirmationModal
        open={isDeleteModalOpen}
        onOpenChange={handleModalOpenChange}
        onConfirm={handleConfirmDelete}
      />
    </Flex>
  )
}

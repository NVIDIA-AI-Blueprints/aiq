// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * FileUploadZone Component
 *
 * Drag-and-drop file upload zone using KUI Upload component.
 * Integrates with useFileUpload hook for handling uploads.
 */

'use client'

import { type FC, useCallback, useState, useEffect, useMemo } from 'react'
import { Upload, FormField } from '@/adapters/ui'
import { useDocumentsStore } from '../store'
import { useIsCurrentSessionBusy } from '@/features/chat'
import { ACCEPTED_FILE_TYPES, MAX_FILE_SIZE } from '../'

// ============================================================================
// Types
// ============================================================================

interface UploadedFile {
  id: string
  file: File
  status: 'uploading' | 'success' | 'error'
  errorMessage?: string
  uploadedBytes?: number
}

interface FileUploadZoneProps {
  /** Session ID for filtering displayed files */
  sessionId?: string
  /** Max file size in bytes (for display only) */
  maxFileSize?: number
  /** Accepted file types (MIME types or extensions) */
  acceptedTypes?: string
  /** Handler for uploading files (parent handles validation via hook) */
  onUpload?: (files: File[]) => void
  /** Whether upload is in progress */
  isUploading?: boolean
  /** Label for the form field */
  label?: string
}

// ============================================================================
// Component
// ============================================================================

export const FileUploadZone: FC<FileUploadZoneProps> = ({
  sessionId,
  maxFileSize = MAX_FILE_SIZE,
  acceptedTypes = ACCEPTED_FILE_TYPES,
  onUpload,
  isUploading = false,
  label,
}) => {
  // Check if current session is busy with operations
  const isBusy = useIsCurrentSessionBusy()

  // Get files for current session
  const trackedFiles = useDocumentsStore((state) => state.trackedFiles)
  const sessionFiles = useMemo(
    () => (sessionId ? trackedFiles.filter((f) => f.collectionName === sessionId) : []),
    [trackedFiles, sessionId]
  )

  // Map sessionFiles to KUI Upload value format
  const [uploadValue, setUploadValue] = useState<UploadedFile[]>([])

  // Sync sessionFiles to uploadValue
  useEffect(() => {
    const mapped = sessionFiles
      .filter((tf) => tf.file) // Only include files with File object (can be displayed in Upload)
      .map((tf) => ({
        id: tf.id,
        file: tf.file!,
        status:
          tf.status === 'failed'
            ? ('error' as const)
            : tf.status === 'success'
              ? ('success' as const)
              : ('uploading' as const),
        errorMessage: tf.errorMessage ?? undefined,
        uploadedBytes: tf.progress ? Math.floor((tf.progress / 100) * tf.fileSize) : undefined,
      }))
    setUploadValue(mapped)
  }, [sessionFiles])

  const handleValueChange = useCallback(
    (files: UploadedFile | UploadedFile[]) => {
      const fileArray = Array.isArray(files) ? files : [files]

      // Find truly new files (not already tracked in this session)
      const existingIds = new Set(sessionFiles.map((tf) => tf.id))
      const newFiles = fileArray.filter((f) => !existingIds.has(f.id)).map((f) => f.file)

      if (newFiles.length === 0) return

      // Pass files to parent - validation happens in uploadFiles hook
      onUpload?.(newFiles)
    },
    [sessionFiles, onUpload]
  )

  const uploadDisabled = isUploading || isBusy

  return (
    <Upload
      accept={acceptedTypes}
      multiple
      value={uploadValue}
      onValueChange={handleValueChange}
      disabled={uploadDisabled}
      listKind="card"
      renderInput={(trigger) => <FormField slotLabel={label}>{trigger}</FormField>}
    >
      <span>Up to {Math.round(maxFileSize / (1024 * 1024))} MB</span>
      <span> · </span>
      <span>Accepts: {acceptedTypes}</span>
    </Upload>
  )
}

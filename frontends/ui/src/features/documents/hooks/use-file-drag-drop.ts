// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * useFileDragDrop Hook
 *
 * Handles drag-and-drop file upload.
 * Provides drag state and event handlers.
 * Note: File validation happens in uploadFiles hook, not here.
 */

import { useCallback, useRef, useState } from 'react'
import { useAppConfig } from '@/shared/context'
import { checkDraggedFilesSupported } from '../validation'

interface UseFileDragDropOptions {
  /** Callback when files are dropped */
  onDrop: (files: File[]) => void
  /** Whether drag-drop is disabled */
  disabled?: boolean
}

interface UseFileDragDropReturn {
  /** Whether files are being dragged over the drop zone */
  isDragging: boolean
  /** Whether dragged files contain unsupported types */
  isUnsupportedDrag: boolean
  /** Event handlers to spread on the drop zone element */
  dragHandlers: {
    onDragEnter: (e: React.DragEvent) => void
    onDragLeave: (e: React.DragEvent) => void
    onDragOver: (e: React.DragEvent) => void
    onDrop: (e: React.DragEvent) => void
  }
}

/**
 * Hook for handling drag-and-drop file uploads.
 * Provides drag state for UI feedback and passes dropped files to onDrop callback.
 */
export function useFileDragDrop({
  onDrop,
  disabled = false,
}: UseFileDragDropOptions): UseFileDragDropReturn {
  const [isDragging, setIsDragging] = useState(false)
  const [isUnsupportedDrag, setIsUnsupportedDrag] = useState(false)
  const dragCounterRef = useRef(0)
  const { fileUpload: fileUploadConfig } = useAppConfig()

  const handleDragEnter = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      if (disabled) return

      dragCounterRef.current++
      if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
        setIsDragging(true)
        // Check if files are supported (quick MIME type check for UI feedback)
        const allSupported = checkDraggedFilesSupported(e.dataTransfer, fileUploadConfig)
        setIsUnsupportedDrag(!allSupported)
      }
    },
    [disabled, fileUploadConfig]
  )

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounterRef.current--
    if (dragCounterRef.current === 0) {
      setIsDragging(false)
      setIsUnsupportedDrag(false)
    }
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      setIsDragging(false)
      setIsUnsupportedDrag(false)
      dragCounterRef.current = 0

      if (disabled) return

      const files = Array.from(e.dataTransfer.files)
      if (files.length === 0) return

      // Pass files to callback - validation happens in uploadFiles
      onDrop(files)
    },
    [disabled, onDrop]
  )

  return {
    isDragging,
    isUnsupportedDrag,
    dragHandlers: {
      onDragEnter: handleDragEnter,
      onDragLeave: handleDragLeave,
      onDragOver: handleDragOver,
      onDrop: handleDrop,
    },
  }
}

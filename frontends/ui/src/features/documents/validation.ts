// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * File Upload Validation
 *
 * Centralized validation logic for all file upload entry points.
 * Provides detailed error information rather than silent filtering.
 *
 * Validation Rules (configurable via AppConfig):
 * - Max file size per individual file (default: 100MB)
 * - Max total size including existing session files (default: 100MB)
 * - Max files total including existing session files (default: 10)
 * - Accepted types (default: .pdf, .docx, .txt, .md)
 *
 * Behavior:
 * - File-level errors (duplicates, invalid types, oversized): Skip those files, upload others
 * - Batch-level errors (total size/count exceeded): Reject entire batch
 */

import type { FileUploadConfig } from '@/shared/context'
import {
  DEFAULT_MAX_FILE_SIZE,
  DEFAULT_MAX_TOTAL_SIZE,
  DEFAULT_MAX_FILE_COUNT,
  DEFAULT_ACCEPTED_FILE_TYPES,
  DEFAULT_ACCEPTED_MIME_TYPES,
} from './constants'

// ============================================================================
// Types
// ============================================================================

/** Error codes for file validation failures */
export type FileValidationErrorCode = 'FILE_TOO_LARGE' | 'INVALID_TYPE' | 'DUPLICATE_FILE'

/** Error codes for batch-level validation failures */
export type BatchValidationErrorCode = 'TOTAL_SIZE_EXCEEDED' | 'MAX_FILES_EXCEEDED'

/** Detailed error information for a single file */
export interface FileValidationError {
  file: File
  code: FileValidationErrorCode
  message: string
}

/** Batch-level error (affects the whole batch) */
export interface BatchValidationError {
  code: BatchValidationErrorCode
  message: string
}

/** Result of validating a batch of files */
export interface BatchValidationResult {
  /** Whether all files passed validation and batch constraints are met */
  valid: boolean
  /** Whether there is at least one uploadable file and no batch-level blockers */
  canUpload: boolean
  /** Files that would be valid (empty if batch is invalid) */
  validFiles: File[]
  /** Individual file errors */
  fileErrors: FileValidationError[]
  /** Batch-level errors (size/count limits) */
  batchErrors: BatchValidationError[]
  /** Human-readable summary for UI display */
  summary: string | null
}

/** Context for validation (existing files in session) */
export interface ValidationContext {
  /** Total size of files already in the session (bytes) */
  existingTotalSize: number
  /** Number of files already in the session */
  existingFileCount: number
  /** Names of files already in the session (for duplicate detection) */
  existingFileNames: Set<string>
}

/** Default file upload configuration (used when AppConfig is not available) */
const DEFAULT_CONFIG: FileUploadConfig = {
  acceptedTypes: DEFAULT_ACCEPTED_FILE_TYPES,
  acceptedMimeTypes: DEFAULT_ACCEPTED_MIME_TYPES,
  maxTotalSizeMB: 100,
  maxFileSize: DEFAULT_MAX_FILE_SIZE,
  maxTotalSize: DEFAULT_MAX_TOTAL_SIZE,
  maxFileCount: DEFAULT_MAX_FILE_COUNT,
  fileExpirationCheckIntervalHours: 0,
}

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Check if a file has a valid extension
 * @param fileName - Name of the file to check
 * @param config - Optional file upload configuration (uses defaults if not provided)
 */
export function isValidFileExtension(
  fileName: string,
  config: FileUploadConfig = DEFAULT_CONFIG
): boolean {
  const parts = fileName.split('.')
  if (parts.length < 2) return false
  const acceptedExtensions = config.acceptedTypes.split(',').map((ext) => ext.toLowerCase().trim())
  const extension = '.' + parts.pop()?.toLowerCase()
  return acceptedExtensions.includes(extension)
}

/**
 * Check if a MIME type is valid (used during drag operations)
 * @param mimeType - MIME type to check
 * @param config - Optional file upload configuration (uses defaults if not provided)
 */
export function isValidMimeType(
  mimeType: string,
  config: FileUploadConfig = DEFAULT_CONFIG
): boolean {
  // Empty MIME type is allowed (some files like .md may not have one)
  if (!mimeType) return true
  const normalized = mimeType.toLowerCase()
  return config.acceptedMimeTypes.some((m) => m.toLowerCase() === normalized)
}

/**
 * Format bytes to human-readable string
 */
export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

/**
 * Create default validation context (empty session)
 */
export function createEmptyValidationContext(): ValidationContext {
  return {
    existingTotalSize: 0,
    existingFileCount: 0,
    existingFileNames: new Set(),
  }
}

// ============================================================================
// Main Validation Function
// ============================================================================

/**
 * Validate a batch of files for upload.
 *
 * Performs the following checks:
 * 1. Individual file type validation (extension-based)
 * 2. Individual file size (configurable, default 100MB)
 * 3. Duplicate file detection
 * 4. Total size including existing files (configurable, default 100MB)
 * 5. File count including existing files (configurable, default 10)
 *
 * File-level errors (duplicates, invalid types, oversized) will skip those files
 * but allow other valid files to proceed. Batch-level errors (total size/count
 * exceeded) will reject the entire batch.
 *
 * @param files - Array of files to validate
 * @param context - Optional context with existing session files info
 * @param config - Optional file upload configuration (uses defaults if not provided)
 * @returns Detailed validation result
 */
export function validateFileUpload(
  files: File[],
  context: ValidationContext = createEmptyValidationContext(),
  config: FileUploadConfig = DEFAULT_CONFIG
): BatchValidationResult {
  const fileErrors: FileValidationError[] = []
  const batchErrors: BatchValidationError[] = []
  const potentiallyValidFiles: File[] = []

  // Track new files for batch calculations
  let newFilesTotalSize = 0
  const newFileNames = new Set<string>()

  // -------------------------------------------------------------------------
  // Pass 1: Validate individual files
  // -------------------------------------------------------------------------

  for (const file of files) {
    // Check for duplicates within the new batch
    if (newFileNames.has(file.name)) {
      fileErrors.push({
        file,
        code: 'DUPLICATE_FILE',
        message: `"${file.name}" is included multiple times`,
      })
      continue
    }

    // Check for duplicates against existing session files
    if (context.existingFileNames.has(file.name)) {
      fileErrors.push({
        file,
        code: 'DUPLICATE_FILE',
        message: `"${file.name}" already exists in this session`,
      })
      continue
    }

    // Check file type (extension)
    if (!isValidFileExtension(file.name, config)) {
      fileErrors.push({
        file,
        code: 'INVALID_TYPE',
        message: `"${file.name}" is not a supported file type. Accepted: ${config.acceptedTypes}`,
      })
      continue
    }

    // Check individual file size
    if (file.size > config.maxFileSize) {
      fileErrors.push({
        file,
        code: 'FILE_TOO_LARGE',
        message: `"${file.name}" is ${formatBytes(file.size)}, exceeds ${formatBytes(config.maxFileSize)} limit`,
      })
      continue
    }

    // File passed individual validation
    potentiallyValidFiles.push(file)
    newFilesTotalSize += file.size
    newFileNames.add(file.name)
  }

  // -------------------------------------------------------------------------
  // Pass 2: Validate batch constraints (including existing files)
  // -------------------------------------------------------------------------

  const totalSize = context.existingTotalSize + newFilesTotalSize
  const totalCount = context.existingFileCount + potentiallyValidFiles.length

  // Check total size constraint
  if (totalSize > config.maxTotalSize) {
    const availableSpace = Math.max(0, config.maxTotalSize - context.existingTotalSize)
    batchErrors.push({
      code: 'TOTAL_SIZE_EXCEEDED',
      message:
        context.existingTotalSize > 0
          ? `Total size would be ${formatBytes(totalSize)}. Only ${formatBytes(availableSpace)} available (${formatBytes(config.maxTotalSize)} limit).`
          : `Total size ${formatBytes(totalSize)} exceeds ${formatBytes(config.maxTotalSize)} limit.`,
    })
  }

  // Check file count constraint
  if (totalCount > config.maxFileCount) {
    const availableSlots = Math.max(0, config.maxFileCount - context.existingFileCount)
    batchErrors.push({
      code: 'MAX_FILES_EXCEEDED',
      message:
        context.existingFileCount > 0
          ? `Would have ${totalCount} files. Only ${availableSlots} more allowed (${config.maxFileCount} max).`
          : `${totalCount} files exceeds the ${config.maxFileCount} file limit.`,
    })
  }

  // -------------------------------------------------------------------------
  // Build result
  // -------------------------------------------------------------------------

  // Batch errors block the entire upload; file errors just skip those files
  const hasBatchErrors = batchErrors.length > 0
  const hasFileErrors = fileErrors.length > 0
  const isValid = !hasBatchErrors && !hasFileErrors && potentiallyValidFiles.length > 0
  const canUpload = !hasBatchErrors && potentiallyValidFiles.length > 0

  // Generate human-readable summary
  let summary: string | null = null
  if (hasFileErrors || hasBatchErrors) {
    const parts: string[] = []

    if (hasFileErrors) {
      const fileErrorSummary =
        fileErrors.length === 1 ? fileErrors[0].message : `${fileErrors.length} files have issues`
      parts.push(fileErrorSummary)
    }

    if (hasBatchErrors) {
      parts.push(...batchErrors.map((e) => e.message))
    }

    summary = parts.join(' ')
  }

  return {
    valid: isValid,
    canUpload,
    // Return valid files unless there are batch-level errors
    // File-level errors just skip those files, allowing partial uploads
    validFiles: hasBatchErrors ? [] : potentiallyValidFiles,
    fileErrors,
    batchErrors,
    summary,
  }
}

// ============================================================================
// Drag-Drop Helper
// ============================================================================

/**
 * Quick check if dragged files are potentially supported (for drag state feedback).
 * Only checks MIME types - not full validation.
 * Used to show "unsupported file type" indicator during drag.
 *
 * @param dataTransfer - DataTransfer object from drag event
 * @param config - Optional file upload configuration (uses defaults if not provided)
 */
export function checkDraggedFilesSupported(
  dataTransfer: DataTransfer,
  config: FileUploadConfig = DEFAULT_CONFIG
): boolean {
  const items = Array.from(dataTransfer.items)
  for (const item of items) {
    if (item.kind === 'file') {
      if (!isValidMimeType(item.type, config)) {
        return false
      }
    }
  }
  return true
}

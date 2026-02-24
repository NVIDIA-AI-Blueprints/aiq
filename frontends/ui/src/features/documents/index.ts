// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Documents Feature Exports
 *
 * Central export point for the documents/file upload feature.
 * Features should import from '@/features/documents' only.
 */

// Store
export { useDocumentsStore } from './store'
export {
  selectFilesInProgress,
  selectCompletedFiles,
  selectFailedFiles,
  selectIsProcessing,
} from './store'

// Hooks
export { useFileUpload, useFileDragDrop, useFileUploadBanners } from './hooks'

// Persistence (for debugging/testing)
export {
  getPersistedJobs,
  clearAllPersistedJobs,
  type PersistedJob,
} from './persistence'

// Orchestrator (singleton for managing upload lifecycle)
export { UploadOrchestrator } from './orchestrator'

// Utils
export { mapBackendStatus, mapToDisplayStatus, normalizeFileName } from './utils'

// Validation
export {
  validateFileUpload,
  checkDraggedFilesSupported,
  isValidFileExtension,
  isValidMimeType,
  formatBytes,
  createEmptyValidationContext,
} from './validation'

// Constants (use AppConfig.fileUpload for runtime configuration)
export {
  // Default values (for fallback when AppConfig is not available)
  DEFAULT_MAX_FILE_SIZE,
  DEFAULT_MAX_TOTAL_SIZE,
  DEFAULT_MAX_FILE_COUNT,
  DEFAULT_ACCEPTED_FILE_TYPES,
  DEFAULT_ACCEPTED_MIME_TYPES,
  // Legacy exports (deprecated, use AppConfig.fileUpload instead)
  MAX_FILE_SIZE,
  MAX_TOTAL_SIZE,
  MAX_FILE_COUNT,
  ACCEPTED_FILE_TYPES,
  ACCEPTED_MIME_TYPES,
} from './constants'

// Components
export { FileUploadZone } from './components'

// Types
export type {
  DocumentFileStatus,
  JobState,
  CollectionInfo,
  FileInfo,
  FileProgress,
  IngestionJobStatus,
  TrackedFile,
  JobBannerState,
  BannerType,
  DocumentsState,
  DocumentsActions,
  DocumentsStore,
} from './types'

// Banner state constant
export { DEFAULT_JOB_BANNER_STATE } from './types'

export type {
  FileValidationErrorCode,
  BatchValidationErrorCode,
  FileValidationError,
  BatchValidationError,
  BatchValidationResult,
  ValidationContext,
} from './validation'

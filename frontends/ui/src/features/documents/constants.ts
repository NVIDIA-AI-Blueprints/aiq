// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Documents Feature Constants
 *
 * Default values for file upload limits and accepted types.
 * These are used as fallbacks when AppConfig is not available.
 * Runtime configuration is provided via AppConfigContext from environment variables.
 */

/** Default maximum file size in bytes per individual file (100MB) */
export const DEFAULT_MAX_FILE_SIZE = 100 * 1024 * 1024

/** Default maximum total size for all files including existing session files (100MB) */
export const DEFAULT_MAX_TOTAL_SIZE = 100 * 1024 * 1024

/** Default maximum number of files per session */
export const DEFAULT_MAX_FILE_COUNT = 10

/** Default accepted file extensions for upload (used by file inputs) */
export const DEFAULT_ACCEPTED_FILE_TYPES = '.pdf,.md,.docx,.html,.txt'

/** Default accepted MIME types for upload (used for drag-drop validation) */
export const DEFAULT_ACCEPTED_MIME_TYPES = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'text/plain',
  'text/markdown',
  'text/x-markdown',
  'text/html',
]

// Legacy exports for backward compatibility (use AppConfig where possible)
/** @deprecated Use AppConfig.fileUpload.maxFileSize instead */
export const MAX_FILE_SIZE = DEFAULT_MAX_FILE_SIZE
/** @deprecated Use AppConfig.fileUpload.maxTotalSize instead */
export const MAX_TOTAL_SIZE = DEFAULT_MAX_TOTAL_SIZE
/** @deprecated Use AppConfig.fileUpload.maxFileCount instead */
export const MAX_FILE_COUNT = DEFAULT_MAX_FILE_COUNT
/** @deprecated Use AppConfig.fileUpload.acceptedTypes instead */
export const ACCEPTED_FILE_TYPES = DEFAULT_ACCEPTED_FILE_TYPES
/** @deprecated Use AppConfig.fileUpload.acceptedMimeTypes instead */
export const ACCEPTED_MIME_TYPES = new Set(DEFAULT_ACCEPTED_MIME_TYPES)

// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Document Feature Utilities
 *
 * Shared utility functions for status mapping and other common operations.
 */

import type { DocumentFileStatus } from './types'
import type { FileSourceStatus } from '@/features/layout/components/FileSourceCard'

/**
 * Map backend file status string to DocumentFileStatus
 */
export const mapBackendStatus = (backendStatus: string): DocumentFileStatus => {
  const statusMap: Record<string, DocumentFileStatus> = {
    uploading: 'uploading',
    ingesting: 'ingesting',
    success: 'success',
    failed: 'failed',
  }
  return statusMap[backendStatus] || 'uploading'
}

/**
 * Map DocumentFileStatus to FileSourceCard display status
 */
export const mapToDisplayStatus = (status: DocumentFileStatus): FileSourceStatus => {
  switch (status) {
    case 'uploading':
      return 'uploading'
    case 'ingesting':
      return 'ingesting'
    case 'success':
      return 'available'
    case 'failed':
      return 'error'
    default:
      return 'uploading'
  }
}

/**
 * Normalize backend filename to display name.
 * Backend returns filenames like "tmp_m04en5b_original-file.pdf"
 * This extracts "original-file.pdf" for display.
 *
 * Pattern: tmp_{random_id}_{original_filename}
 */
export const normalizeFileName = (backendFileName: string): string => {
  // Match pattern: tmp_{alphanumeric_id}_{rest}
  const match = backendFileName.match(/^tmp_[a-z0-9]+_(.+)$/i)
  if (match) {
    return match[1]
  }
  return backendFileName
}

// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Document Feature Types
 *
 * Re-exports API types from schemas and defines frontend-specific types.
 */

import type {
  DocumentFileStatus,
  CollectionInfo,
  FileInfo,
  IngestionJobStatus,
} from '@/adapters/api/documents-schemas'

// Re-export API types from schemas (single source of truth)
export type {
  DocumentFileStatus,
  JobState,
  CollectionInfo,
  FileInfo,
  FileProgress,
  IngestionJobStatus,
} from '@/adapters/api/documents-schemas'

// ============================================================================
// Request Types
// ============================================================================

export interface CreateCollectionRequest {
  name: string
  description?: string
  metadata?: Record<string, unknown>
}

export interface DeleteFilesRequest {
  file_ids: string[]
}

// ============================================================================
// Frontend State Types
// ============================================================================

/** Tracked file in the upload queue (client-side) */
export interface TrackedFile {
  /** Client-generated ID */
  id: string
  /** Original File object (only available for locally uploaded files) */
  file?: File
  /** File name */
  fileName: string
  /** File size in bytes */
  fileSize: number
  /** Current status */
  status: DocumentFileStatus
  /** Progress percentage (0-100) */
  progress: number
  /** Error message if failed */
  errorMessage?: string | null
  /** Backend file_id once uploaded */
  serverFileId?: string
  /** Ingestion job ID */
  jobId?: string
  /** Collection this file belongs to */
  collectionName?: string
  /** When the file was uploaded (from server) */
  uploadedAt?: string | null
}

/** Tracks which banners have been shown for a job */
export interface JobBannerState {
  uploaded: boolean
  ingested: boolean
}

/** Banner type derived from JobBannerState keys */
export type BannerType = keyof JobBannerState

/** Default state for job banners (none shown) */
export const DEFAULT_JOB_BANNER_STATE: JobBannerState = {
  uploaded: false,
  ingested: false,
}

/** Document store state */
export interface DocumentsState {
  /** Current session's collection name (same as sessionId) */
  currentCollectionName: string | null
  /** Collection info if exists */
  collectionInfo: CollectionInfo | null
  /** Files being tracked (uploading, processing, complete) */
  trackedFiles: TrackedFile[]
  /** Active ingestion job ID for polling */
  activeJobId: string | null
  /** Loading states */
  isCreatingCollection: boolean
  isUploading: boolean
  isPolling: boolean
  /** Error message */
  error: string | null
  /** Tracks which banners have been shown for each job (NOT persisted) */
  shownBannersForJobs: Record<string, JobBannerState>
}

/** Document store actions */
export interface DocumentsActions {
  // Collection management
  setCurrentCollection: (name: string | null) => void
  setCollectionInfo: (info: CollectionInfo | null) => void

  // File tracking
  addTrackedFile: (file: TrackedFile) => void
  updateTrackedFile: (id: string, updates: Partial<TrackedFile>) => void
  removeTrackedFile: (id: string) => void
  clearTrackedFiles: () => void
  /** Clear files for a specific collection (used when switching sessions) */
  clearFilesForCollection: (collectionName: string) => void

  // Job tracking
  setActiveJobId: (jobId: string | null) => void

  // Loading states
  setCreatingCollection: (loading: boolean) => void
  setUploading: (loading: boolean) => void
  setPolling: (polling: boolean) => void

  // Error handling
  setError: (error: string | null) => void
  clearError: () => void

  // Bulk operations
  updateFilesFromJobStatus: (jobStatus: IngestionJobStatus) => void
  /** Load files from server for a collection (used when switching sessions) */
  setFilesFromServer: (collectionName: string, files: FileInfo[]) => void

  // Banner tracking (for deduplication)
  /** Mark a banner as shown for a job */
  markBannerShown: (jobId: string, type: BannerType) => void
}

export type DocumentsStore = DocumentsState & DocumentsActions

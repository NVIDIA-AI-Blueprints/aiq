// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * useFileUploadBanners Hook
 *
 * Monitors file upload status and opens the Data Sources panel
 * when files finish ingesting, so the user can see their files are ready.
 *
 * The "uploaded" info banner is triggered earlier, directly in the
 * uploadFiles flow (use-file-upload.ts), when the upload starts.
 */

'use client'

import { useEffect } from 'react'
import { useDocumentsStore } from '../store'
import { DEFAULT_JOB_BANNER_STATE } from '../types'
import { useLayoutStore } from '@/features/layout/store'

/**
 * Hook that watches file upload status and opens the Data Sources panel
 * when all files in a job reach a terminal state (success or failed).
 */
export const useFileUploadBanners = () => {
  const trackedFiles = useDocumentsStore((state) => state.trackedFiles)
  const shownBannersForJobs = useDocumentsStore((state) => state.shownBannersForJobs)
  const markBannerShown = useDocumentsStore((state) => state.markBannerShown)
  const { openRightPanel, setDataSourcesPanelTab } = useLayoutStore()

  useEffect(() => {
    // Group files by jobId (each upload batch has its own job)
    const filesByJob = new Map<string, typeof trackedFiles>()
    for (const file of trackedFiles) {
      if (!file.jobId) continue
      const existing = filesByJob.get(file.jobId) || []
      filesByJob.set(file.jobId, [...existing, file])
    }

    // Check each job for terminal state (available or error)
    for (const [jobId, jobFiles] of filesByJob) {
      const jobBanners = shownBannersForJobs[jobId] || DEFAULT_JOB_BANNER_STATE

      // Count files in terminal states
      const terminalCount = jobFiles.filter(
        (f) => f.status === 'success' || f.status === 'failed'
      ).length

      // All files in this job reached a terminal state → open Data Sources panel
      const allTerminal = terminalCount === jobFiles.length
      if (allTerminal && !jobBanners.ingested) {
        setDataSourcesPanelTab('files')
        openRightPanel('data-sources')
        markBannerShown(jobId, 'ingested')
      }
    }
  }, [trackedFiles, shownBannersForJobs, markBannerShown, openRightPanel, setDataSourcesPanelTab])
}

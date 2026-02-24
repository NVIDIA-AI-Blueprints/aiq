// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * NoSourcesBanner Component
 *
 * Displays a warning banner when no data sources are enabled and no files
 * are available for the current session. This alerts users that responses
 * may be less accurate without external data sources.
 *
 * Auto-hides when:
 * - Any data source is enabled (e.g., web search)
 * - At least one file is available (status === 'success')
 *
 * Dismissable by user. Dismiss state resets when conditions improve
 * (sources/files become available) so the banner can reappear if the
 * user later removes all sources and files.
 */

'use client'

import { type FC, useState, useEffect, useRef } from 'react'
import { Banner } from '@/adapters/ui'
import { useLayoutStore } from '@/features/layout/store'
import { useDocumentsStore } from '@/features/documents'
import { useChatStore } from '../store'

const WARNING_MESSAGE =
  'No data sources selected and no files are available. Responses are more likely to be inaccurate or outdated unless external data sources are added.'

/**
 * Warning banner shown when no data sources or files are available.
 * Self-contained: reads state from layout, documents, and chat stores.
 */
export const NoSourcesBanner: FC = () => {
  const [isDismissedByUser, setIsDismissedByUser] = useState(false)

  const enabledDataSourceIds = useLayoutStore((state) => state.enabledDataSourceIds)
  const sessionId = useChatStore((state) => state.currentConversation?.id)

  // Get completed files for the current session from the documents store
  const hasAvailableFiles = useDocumentsStore((state) =>
    state.trackedFiles.some(
      (f) => f.collectionName === sessionId && f.status === 'success'
    )
  )

  const hasAnySources = enabledDataSourceIds.length > 0
  const shouldShow = !hasAnySources && !hasAvailableFiles

  // Track previous shouldShow to detect when conditions improve.
  // When the warning condition clears (sources/files become available),
  // reset the dismiss state so the banner can reappear if conditions worsen again.
  const prevShouldShowRef = useRef(shouldShow)

  useEffect(() => {
    const prev = prevShouldShowRef.current
    // Conditions improved: was showing (or would show) -> now resolved
    if (prev && !shouldShow) {
      setIsDismissedByUser(false)
    }
    prevShouldShowRef.current = shouldShow
  }, [shouldShow])

  const handleDismiss = () => {
    setIsDismissedByUser(true)
  }

  if (!shouldShow || isDismissedByUser) return null

  return (
    <div className="mx-auto w-full max-w-3xl px-4">
      <Banner status="warning" kind="inline" onClose={handleDismiss}>
        {WARNING_MESSAGE}
      </Banner>
    </div>
  )
}

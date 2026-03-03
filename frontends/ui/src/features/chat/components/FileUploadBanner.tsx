// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * FileUploadBanner Component
 *
 * Displays status banners for file upload progress in the chat area.
 * Variants:
 * - "uploaded": Informational banner shown when files start uploading/ingesting
 * - "pending_warning": Warning when user submits with pending files
 */

'use client'

import { type FC } from 'react'
import { Banner, Flex, Text } from '@/adapters/ui'
import { formatTime } from '@/shared/utils/format-time'
import type { FileUploadStatusType } from '../types'

export interface FileUploadBannerProps {
  /** Type of status: uploaded or pending_warning */
  type: FileUploadStatusType
  /** Number of files in the batch */
  fileCount: number
  /** Timestamp of the status update (Date or ISO string from persisted state) */
  timestamp?: Date | string
  /** Callback when the banner is dismissed (removes message from chat) */
  onDismiss?: () => void
}

interface BannerContent {
  message: string
  status: 'info' | 'warning'
  dismissable: boolean
}

/**
 * Banner content configuration for each status type.
 * Returns null for unknown/legacy types (e.g. 'ingested' from persisted conversations)
 * so the component can skip rendering them.
 */
const getBannerContent = (type: FileUploadStatusType): BannerContent | null => {
  switch (type) {
    case 'uploaded':
      return {
        message:
          'File is uploading and ingesting. Until completion, a file cannot be included in queries.',
        status: 'info',
        dismissable: true,
      }
    case 'pending_warning':
      return {
        message:
          'Files are pending! Wait until they are ready or send your query again to continue WITHOUT those files.',
        status: 'warning',
        dismissable: false,
      }
    default:
      // Legacy/unknown types from persisted conversations — skip silently
      return null
  }
}

/**
 * File upload status banner displayed in the chat area
 */
export const FileUploadBanner: FC<FileUploadBannerProps> = ({
  type,
  timestamp,
  onDismiss,
}) => {
  const content = getBannerContent(type)

  // Skip rendering for unknown/legacy types
  if (!content) return null

  return (
    <Flex direction="col" gap="1" className="w-full">
      <Banner
        status={content.status}
        kind="inline"
        onClose={content.dismissable ? onDismiss : undefined}
      >
        {content.message}
      </Banner>
      {timestamp && (
        <Text kind="body/regular/xs" className="text-subtle mr-3 self-end">
          {formatTime(timestamp)}
        </Text>
      )}
    </Flex>
  )
}

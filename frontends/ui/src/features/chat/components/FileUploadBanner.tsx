// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * FileUploadBanner Component
 *
 * Displays status banners for file upload progress in the chat area.
 * Variants:
 * - "uploaded": Informational banner shown when files start uploading/ingesting
 * - "pending_warning": Warning when user submits with pending files
 * - "deleted": Confirmation when files are deleted
 */

'use client'

import { type FC } from 'react'
import { Banner, Flex, Text } from '@/adapters/ui'
import { formatTime } from '@/shared/utils/format-time'
import type { FileUploadStatusType } from '../types'

export interface FileUploadBannerProps {
  /** Type of status: uploaded, pending_warning, or deleted */
  type: FileUploadStatusType
  /** Number of files in the batch */
  fileCount: number
  /** Timestamp of the status update (Date or ISO string from persisted state) */
  timestamp?: Date | string
  /** Callback when the banner is dismissed (removes message from chat) */
  onDismiss?: () => void
}

/** Banner status type for KUI Banner component */
type BannerStatus = 'success' | 'info' | 'warning' | 'error'

interface BannerContent {
  message: string
  status: BannerStatus
  dismissable: boolean
}

/**
 * Banner content configuration for each status type.
 * Returns null for unknown/legacy types (e.g. 'ingested' from persisted conversations)
 * so the component can skip rendering them.
 */
const getBannerContent = (type: FileUploadStatusType, _fileCount: number): BannerContent | null => {
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
    case 'deleted':
      return {
        message:
          _fileCount === 1
            ? 'Your file has been deleted.'
            : `${_fileCount} files have been deleted.`,
        status: 'info',
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
  fileCount,
  timestamp,
  onDismiss,
}) => {
  const content = getBannerContent(type, fileCount)

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

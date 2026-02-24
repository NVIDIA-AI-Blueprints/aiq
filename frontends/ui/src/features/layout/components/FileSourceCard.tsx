// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * FileSourceCard Component
 *
 * Displays a single uploaded file source with status and delete action.
 * Shows file title, upload time, description, and current status.
 */

'use client'

import { type FC, useState, useEffect } from 'react'
import { Flex, Text, Button, Spinner } from '@/adapters/ui'
import { Document, Trash } from '@/adapters/ui/icons'
import { useIsCurrentSessionBusy } from '@/features/chat'

/** File source status types */
export type FileSourceStatus = 'uploading' | 'ingesting' | 'available' | 'error'

export interface FileSourceCardProps {
  /** Unique identifier for the file */
  id: string
  /** File title/name */
  title: string
  /** File size in bytes */
  fileSize?: number | null
  /** When the file was uploaded (optional - not displayed if null/undefined) */
  uploadedAt?: Date | string | null
  /** Optional description of the file */
  description?: string
  /** Current status of the file */
  status: FileSourceStatus
  /** Error message when status is 'error' */
  errorMessage?: string
  /** Hours after upload before the file may expire (0 = no expiry shown) */
  expirationIntervalHours?: number
  /** Callback when delete is clicked */
  onDelete: (id: string) => void
}

/** Status configuration for styling */
const STATUS_CONFIG: Record<
  FileSourceStatus,
  { label: string; color: string; showSpinner: boolean }
> = {
  uploading: {
    label: 'Uploading...',
    color: 'var(--text-color-feedback-info)',
    showSpinner: true,
  },
  ingesting: {
    label: 'Ingesting...',
    color: 'var(--text-color-feedback-info)',
    showSpinner: true,
  },
  available: {
    label: 'Available',
    color: 'var(--text-color-feedback-success)',
    showSpinner: false,
  },
  error: {
    label: 'Error',
    color: 'var(--text-color-feedback-danger)',
    showSpinner: false,
  },
}

/**
 * Format byte count into a human-readable size string.
 */
const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / Math.pow(1024, exponent)
  return `${value % 1 === 0 ? value : value.toFixed(1)} ${units[exponent]}`
}

/**
 * Format upload timestamp for display
 */
const formatDateTime = (date: Date | string): string => {
  const dateObj = typeof date === 'string' ? new Date(date) : date
  return dateObj.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * Compute the milliseconds remaining until expiration.
 * Returns null if inputs are invalid or interval is 0.
 */
const computeMsRemaining = (
  uploadedAt: Date | string | null | undefined,
  intervalHours: number
): number | null => {
  if (!uploadedAt || intervalHours <= 0) return null
  const dateObj = typeof uploadedAt === 'string' ? new Date(uploadedAt) : uploadedAt
  if (isNaN(dateObj.getTime())) return null
  const expiresAtMs = dateObj.getTime() + intervalHours * 60 * 60 * 1000
  return expiresAtMs - Date.now()
}

/**
 * Format milliseconds remaining into "Expires in H:MM" or the expired label.
 * Returns null when expiration doesn't apply.
 */
const formatExpiryLabel = (msRemaining: number | null): { text: string; expired: boolean } | null => {
  if (msRemaining === null) return null
  if (msRemaining <= 0) return { text: 'Deletion Pending - Reupload', expired: true }

  const totalMinutes = Math.max(1, Math.ceil(msRemaining / 60_000))
  return { text: `Expires in ${totalMinutes} min`, expired: false }
}

/**
 * Hook that returns a live expiry label, re-evaluated every minute.
 */
const useExpiryLabel = (
  uploadedAt: Date | string | null | undefined,
  intervalHours: number,
  active: boolean
): { text: string; expired: boolean } | null => {
  const [label, setLabel] = useState<{ text: string; expired: boolean } | null>(() =>
    active ? formatExpiryLabel(computeMsRemaining(uploadedAt, intervalHours)) : null
  )

  useEffect(() => {
    if (!active) {
      setLabel(null)
      return
    }

    // Compute immediately
    setLabel(formatExpiryLabel(computeMsRemaining(uploadedAt, intervalHours)))

    // Re-evaluate every 60 seconds
    const id = setInterval(() => {
      setLabel(formatExpiryLabel(computeMsRemaining(uploadedAt, intervalHours)))
    }, 60_000)

    return () => clearInterval(id)
  }, [uploadedAt, intervalHours, active])

  return label
}

/**
 * Card component for displaying an uploaded file source.
 */
export const FileSourceCard: FC<FileSourceCardProps> = ({
  id,
  title,
  fileSize,
  uploadedAt,
  description,
  status,
  errorMessage,
  expirationIntervalHours = 0,
  onDelete,
}) => {
  const config = STATUS_CONFIG[status]
  const isBusy = useIsCurrentSessionBusy()
  const expiryLabel = useExpiryLabel(uploadedAt, expirationIntervalHours, status === 'available')

  const handleDelete = () => {
    onDelete(id)
  }

  const deleteDisabled = isBusy

  return (
    <Flex
      align="start"
      justify="between"
      className={`
        bg-surface-raised border-base rounded-lg border
        p-3 transition-colors
        ${status === 'error' ? 'border-error/50' : ''}
        group
      `}
    >
      <Flex align="center" gap="3" className="min-w-0 flex-1">
        {/* File Icon or Spinner */}
        {config.showSpinner ? (
          <Spinner size="small" aria-label={config.label} />
        ) : (
          <Document
            width={32}
            height={32}
            className={status === 'error' ? 'text-error' : 'text-secondary'}
          />
        )}

        {/* Content */}
        <Flex direction="col" gap="1" className="min-w-0 flex-1">
          {/* Title, file size, and timestamp */}
          <Flex align="center" gap="2" className="min-w-0">
            <Text kind="label/semibold/sm" className="text-primary truncate">
              {title}
            </Text>
            {fileSize != null && fileSize > 0 && (
              <Text kind="body/regular/xs" className="text-subtle shrink-0">
                {formatFileSize(fileSize)}
              </Text>
            )}
            {uploadedAt && (
              <>
                <span className="text-subtle shrink-0">•</span>
                <Text kind="body/regular/xs" className="text-subtle shrink-0">
                  {formatDateTime(uploadedAt)}
                </Text>
              </>
            )}
          </Flex>

          {/* Description (if provided) */}
          {description && (
            <Text kind="body/regular/xs" className="text-subtle line-clamp-2">
              {description}
            </Text>
          )}

          {/* Status and expiration row */}
          <Flex align="center" gap="2" className="mt-1">
            {/* Status indicator */}
            <Flex align="center" gap="1">
              {status === 'available' && <span className="text-success text-xs">✓</span>}
              {status === 'error' && <span className="text-error text-xs">✕</span>}
              <Text 
                kind={config.showSpinner ? "body/regular/sm" : "body/regular/xs"}
                style={{ color: config.color }}
              >
                {config.label}
              </Text>
            </Flex>

            {/* Expiration countdown */}
            {expiryLabel && (
              <>
                <span className="text-subtle">•</span>
                <Text
                  kind="body/regular/xs"
                  className={expiryLabel.expired ? 'text-warning' : 'text-orange-400'}
                >
                  {expiryLabel.text}
                </Text>
              </>
            )}
          </Flex>

          {/* Error message */}
          {status === 'error' && errorMessage && (
            <Text kind="body/regular/xs" className="text-error mt-1">
              {errorMessage}
            </Text>
          )}
        </Flex>

        {/* Delete button */}
        <Button
          kind="tertiary"
          size="small"
          color="danger"
          onClick={handleDelete}
          disabled={deleteDisabled}
          aria-label={deleteDisabled ? `Delete ${title} (disabled)` : `Delete ${title}`}
          title={deleteDisabled ? "Cannot delete files during active operations" : "Delete file"}
          className="ml-2 flex-shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
        >
          <Trash width={16} height={16} className="text-subtle hover:text-error" />
        </Button>
      </Flex>
    </Flex>
  )
}

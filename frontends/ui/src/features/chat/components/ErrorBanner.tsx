// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * ErrorBanner Component
 *
 * Displays persistent error messages in the chat area using KUI Banner.
 * Uses the error registry for consistent error metadata across the application.
 */

'use client'

import { type FC, useState } from 'react'
import { Banner, Flex, Text } from '@/adapters/ui'
import { formatTime } from '@/shared/utils/format-time'
import { ChevronDown, ChevronUp } from '@/adapters/ui/icons'
import type { ErrorCode } from '../types'
import { getErrorMeta } from '../lib/error-registry'

export type { ErrorCode }

export interface ErrorBannerProps {
  /** Error code from the error registry */
  code: ErrorCode
  /** Optional custom message (overrides default from registry) */
  message?: string
  /** Optional expandable details */
  details?: string
  /** Timestamp of the error */
  timestamp?: Date | string
  /** Optional callback when banner is dismissed */
  onDismiss?: () => void
}

/**
 * Error banner for displaying connection, file, auth, and system errors
 */
export const ErrorBanner: FC<ErrorBannerProps> = ({
  code,
  message,
  details,
  timestamp,
  onDismiss,
}) => {
  const [isExpanded, setIsExpanded] = useState(false)
  const errorMeta = getErrorMeta(code)

  // Use custom message if provided, otherwise use default from registry
  const displayMessage = message || errorMeta.defaultMessage

  const subheading = (
    <>
      {displayMessage}
      {details && (
        <>
          {' '}
          <button
            type="button"
            onClick={() => setIsExpanded(!isExpanded)}
            aria-expanded={isExpanded}
            aria-controls="error-details"
            className="inline-flex cursor-pointer items-center gap-1 border-none bg-transparent p-0 text-xs font-medium no-underline"
          >
            {isExpanded ? 'Hide details' : 'Show details'}
            {isExpanded ? (
              <ChevronUp className="h-3 w-3" aria-hidden="true" />
            ) : (
              <ChevronDown className="h-3 w-3" aria-hidden="true" />
            )}
          </button>
          {isExpanded && (
            <pre
              id="error-details"
              className="text-error bg-surface-raised mt-2 whitespace-pre-wrap rounded p-2 font-mono text-xs"
            >
              {details}
            </pre>
          )}
        </>
      )}
    </>
  )

  return (
    <Flex direction="col" gap="1" className="w-full">
      <Banner
        status={errorMeta.status}
        kind="header"
        slotSubheading={subheading}
        onClose={onDismiss}
      >
        {errorMeta.title}
      </Banner>

      {timestamp && (
        <Text kind="body/regular/xs" className="text-subtle mr-2 self-end">
          {formatTime(timestamp)}
        </Text>
      )}
    </Flex>
  )
}

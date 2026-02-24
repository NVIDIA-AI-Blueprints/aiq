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
import { Banner, Button, Flex, Text } from '@/adapters/ui'
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

  return (
    <Flex direction="col" gap="1" className="w-full">
      <Flex direction="col" gap="2">
        <Banner
          status={errorMeta.status}
          kind="header"
          slotSubheading={displayMessage}
          onClose={onDismiss}
        >
          {errorMeta.title}
        </Banner>

        {/* Expandable Details */}
        {details && (
          <Flex direction="col" gap="1" className="pl-4">
            <Button
              kind="tertiary"
              size="small"
              onClick={() => setIsExpanded(!isExpanded)}
              aria-expanded={isExpanded}
              aria-controls="error-details"
              title={isExpanded ? 'Hide details' : 'Show details'}
            >
              <Flex align="center" gap="1">
                <Text kind="label/regular/xs">{isExpanded ? 'Hide details' : 'Show details'}</Text>
                {isExpanded ? (
                  <ChevronUp className="h-3 w-3" aria-hidden="true" />
                ) : (
                  <ChevronDown className="h-3 w-3" aria-hidden="true" />
                )}
              </Flex>
            </Button>
            {isExpanded && (
              <Text
                id="error-details"
                kind="body/regular/sm"
                className="text-error bg-surface-raised whitespace-pre-wrap rounded p-2 font-mono text-xs"
              >
                {details}
              </Text>
            )}
          </Flex>
        )}
      </Flex>

      {/* Timestamp outside banner, right-aligned */}
      {timestamp && (
        <Text kind="body/regular/xs" className="text-subtle mr-2 self-end">
          {formatTime(timestamp)}
        </Text>
      )}
    </Flex>
  )
}

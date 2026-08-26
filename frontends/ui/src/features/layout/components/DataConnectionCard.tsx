// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * DataConnectionCard Component
 *
 * Displays a single data connection source with enable/disable toggle.
 * Supports disabled state for unavailable sources (permission issues).
 */

'use client'

import { type FC, useCallback, useState } from 'react'
import { Flex, Text, Switch, Button } from '@/adapters/ui'
import { SourceKindIcon } from '@/shared/components/Sources/SourceKindIcon'
import { cn } from '@/shared/lib/cn'
import { type DataSource, getDataSourceKind } from '../data-sources'

interface DataConnectionCardProps {
  /** Data source configuration */
  source: DataSource
  /** Whether the source is currently enabled */
  isEnabled: boolean
  /** Whether the source is available (user has permission). Default: true */
  isAvailable?: boolean
  /** Whether the current session is busy with operations. Default: false */
  isBusy?: boolean
  /** Custom reason for why the source is unavailable (shown in tooltip) */
  unavailableReason?: string
  /** Callback when toggle state changes */
  onToggle: (id: string, enabled: boolean) => void
  /** Start the per-user OAuth connect flow for a protected source */
  onConnect?: (id: string) => void | Promise<void>
}

/** Human-readable status line for a protected MCP source. */
const STATUS_LABELS: Record<string, string> = {
  connected: 'Connected',
  not_connected: 'Not connected',
  expired: 'Session expired',
  error: 'Connection error',
}

/**
 * Card component for displaying and controlling a data connection.
 * Shows source info with toggle switch, and handles unavailable state.
 */
export const DataConnectionCard: FC<DataConnectionCardProps> = ({
  source,
  isEnabled,
  isAvailable = true,
  isBusy = false,
  unavailableReason,
  onToggle,
  onConnect,
}) => {
  const [connecting, setConnecting] = useState(false)

  // Per-user MCP auth state (present only for protected sources).
  const perUserAuth = source.perUserAuth
  const isProtected = !!perUserAuth?.required
  const authStatus = perUserAuth?.status ?? undefined
  // A protected source must be connected before it can be enabled.
  const needsConnect = isProtected && authStatus !== 'connected'

  // Combine availability and busy state. A protected-but-unconnected source
  // cannot be toggled — the Connect action replaces the switch.
  const isDisabled = !isAvailable || isBusy
  const canToggle = !isDisabled && !needsConnect

  const handleToggle = () => {
    if (canToggle) {
      onToggle(source.id, !isEnabled)
    }
  }

  const handleConnect = useCallback(async () => {
    if (connecting || !onConnect) return
    setConnecting(true)
    try {
      await onConnect(source.id)
    } finally {
      setConnecting(false)
    }
  }, [connecting, onConnect, source.id])

  const handleCardClick = () => {
    handleToggle()
  }

  const handleCardKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      handleToggle()
    }
  }

  const handleSwitchClick = (e: React.MouseEvent) => {
    // Stop propagation to prevent double-toggle when clicking the switch directly
    e.stopPropagation()
  }

  const cardContent = (
    <Flex
      align="center"
      justify="between"
      role="button"
      tabIndex={canToggle ? 0 : -1}
      onClick={handleCardClick}
      onKeyDown={handleCardKeyDown}
      className={cn(
        'surface-card group flex items-center justify-between border p-3',
        isDisabled
          ? 'border-base cursor-not-allowed opacity-50'
          : isEnabled
            ? 'brand-tint cursor-pointer border'
            : canToggle
              ? 'border-base hover:bg-surface-raised-50 cursor-pointer'
              : 'border-base'
      )}
      aria-pressed={isEnabled}
      aria-disabled={!canToggle}
      aria-label={`${source.name}: ${isEnabled ? 'enabled' : 'disabled'}${!canToggle ? ' (disabled)' : ''}`}
      title={
        isBusy
          ? 'Data source changes disabled during active operations'
          : !isAvailable
            ? unavailableReason || "You don't have permission to access this data source"
            : undefined
      }
    >
      <Flex align="center" gap="3" className="min-w-0 flex-1">
        <span
          className={cn(
            'grid h-9 w-9 flex-shrink-0 place-items-center rounded-lg transition-colors',
            isDisabled
              ? 'bg-surface-sunken text-subtle'
              : isEnabled
                ? 'brand-chip'
                : 'bg-surface-raised text-secondary'
          )}
        >
          <SourceKindIcon kind={getDataSourceKind(source.id)} className="h-5 w-5" />
        </span>
        <Flex direction="col" className="min-w-0">
          <Text kind="label/semibold/sm" className={isDisabled ? 'text-subtle' : 'text-primary'}>
            {source.name}
          </Text>
          <Text kind="body/regular/xs" className="text-subtle truncate">
            {source.description}
          </Text>
          {isProtected && (
            <Text
              kind="body/regular/xs"
              className={authStatus === 'connected' ? 'text-success' : authStatus === 'error' ? 'text-error' : 'text-subtle'}
            >
              {perUserAuth?.lastError && authStatus === 'error'
                ? perUserAuth.lastError
                : STATUS_LABELS[authStatus ?? 'not_connected']}
            </Text>
          )}
        </Flex>
      </Flex>
      {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions */}
      <div className="ml-3 flex-shrink-0" onClick={handleSwitchClick}>
        {needsConnect ? (
          <Button
            size="small"
            kind="secondary"
            onClick={handleConnect}
            disabled={connecting || !isAvailable || isBusy}
            aria-label={`Connect ${source.name}`}
          >
            {connecting
              ? 'Connecting…'
              : authStatus === 'expired' || authStatus === 'error'
                ? 'Reconnect'
                : 'Connect'}
          </Button>
        ) : (
          <Switch
            size="small"
            checked={isEnabled && isAvailable}
            onCheckedChange={handleToggle}
            disabled={isDisabled}
            aria-label={isDisabled ? `${source.name} (disabled)` : `${isEnabled ? 'Disable' : 'Enable'} ${source.name}`}
          />
        )}
      </div>
    </Flex>
  )

  return cardContent
}

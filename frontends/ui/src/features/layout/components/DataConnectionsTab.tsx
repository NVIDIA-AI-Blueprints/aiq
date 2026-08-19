// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * DataConnectionsTab Component
 *
 * Tab displaying all available data connection sources (e.g., web search, knowledge base, document store).
 * Each source can be enabled/disabled for the current session.
 * Sources are fetched from the Data Sources API on mount.
 */

'use client'

import { type FC, useMemo } from 'react'
import { Flex, Text, Button } from '@/adapters/ui'
import { useShallow } from 'zustand/react/shallow'
import { LoadingSpinner } from '@/adapters/ui/icons'
import { type DataSource, getDataSourceDisplay } from '../data-sources'
import { DataConnectionCard } from './DataConnectionCard'
import { useLayoutStore } from '../store'

interface DataConnectionsTabProps {
  /** Set of enabled source IDs */
  enabledSourceIds: Set<string>
  /** Callback when source toggle state changes */
  onToggle: (sourceId: string, enabled: boolean) => void
}

/**
 * Tab content for managing data connections.
 * Displays available data sources with enable/disable toggles.
 */
export const DataConnectionsTab: FC<DataConnectionsTabProps> = ({ enabledSourceIds, onToggle }) => {
  const { availableDataSources, dataSourcesLoading, dataSourcesError } = useLayoutStore(
    useShallow((s) => ({
      availableDataSources: s.availableDataSources,
      dataSourcesLoading: s.dataSourcesLoading,
      dataSourcesError: s.dataSourcesError,
    }))
  )
  const fetchDataSources = useLayoutStore((s) => s.fetchDataSources)

  const displaySources: DataSource[] = useMemo(() => {
    if (!availableDataSources || availableDataSources.length === 0) {
      return []
    }
    return availableDataSources.map((source) => {
      const display = getDataSourceDisplay(source)
      return {
        id: source.id,
        name: display.name,
        description: display.description,
        category: source.category ?? 'enterprise',
        defaultEnabled: true,
        requiresAuth: source.requires_auth ?? false,
        perUserAuth: source.per_user_auth
          ? {
              required: source.per_user_auth.required,
              provider: source.per_user_auth.provider,
              mcpServerId: source.per_user_auth.mcp_server_id,
              status: source.per_user_auth.status,
              connectUrl: source.per_user_auth.connect_url,
              expiresAt: source.per_user_auth.expires_at,
              lastError: source.per_user_auth.last_error,
            }
          : undefined,
      }
    })
  }, [availableDataSources])

  if (dataSourcesLoading) {
    return (
      <Flex direction="col" align="center" justify="center" className="flex-1">
        <LoadingSpinner size="medium" aria-label="Loading data sources" />
        <Text kind="body/regular/sm" className="text-subtle mt-2">
          Loading data sources...
        </Text>
      </Flex>
    )
  }

  if (dataSourcesError) {
    return (
      <Flex direction="col" align="center" justify="center" className="flex-1 py-8">
        <Text kind="body/regular/sm" className="text-error mb-2">
          Unable to load data sources
        </Text>
        <Text kind="body/regular/xs" className="text-subtle mb-4 text-center">
          {dataSourcesError}
        </Text>
        <Button
          kind="secondary"
          size="small"
          onClick={() => fetchDataSources()}
          aria-label="Retry loading data sources"
        >
          Retry
        </Button>
      </Flex>
    )
  }

  if (displaySources.length === 0) {
    return (
      <Flex direction="col" align="center" justify="center" className="flex-1 py-8">
        <Text kind="body/regular/sm" className="text-subtle">
          No data sources available
        </Text>
      </Flex>
    )
  }

  return (
    <Flex direction="col" className="flex-1 overflow-y-auto">
      <Text
        kind="label/semibold/xs"
        className="text-subtle mb-3 font-mono uppercase tracking-widest"
      >
        Available Sources ({displaySources.length})
      </Text>

      <Flex direction="col" gap="2">
        {displaySources.map((source) => (
          <DataConnectionCard
            key={source.id}
            source={source}
            isEnabled={enabledSourceIds.has(source.id)}
            isAvailable={true}
            onToggle={onToggle}
          />
        ))}
      </Flex>
    </Flex>
  )
}

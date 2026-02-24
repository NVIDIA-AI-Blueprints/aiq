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
import { LoadingSpinner } from '@/adapters/ui/icons'
import { type DataSource } from '../data-sources'
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
export const DataConnectionsTab: FC<DataConnectionsTabProps> = ({
  enabledSourceIds,
  onToggle,
}) => {
  const { availableDataSources, dataSourcesLoading, dataSourcesError, fetchDataSources } =
    useLayoutStore()

  // Convert API data sources to UI format - no fallback
  const displaySources: DataSource[] = useMemo(() => {
    if (!availableDataSources || availableDataSources.length === 0) {
      return []
    }
    return availableDataSources.map((source) => ({
      id: source.id,
      name: source.name,
      description: source.description ?? '',
      category: source.category ?? 'enterprise',
      defaultEnabled: true,
    }))
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

  // Show error state when API fails - no fallback to hardcoded sources
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

  // Show empty state if no sources available
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
      <Text kind="label/semibold/xs" className="text-subtle mb-3 uppercase">
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

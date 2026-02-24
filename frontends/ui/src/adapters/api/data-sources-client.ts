// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Data Sources API Client
 *
 * Handles fetching available data sources from the backend.
 * Returns dynamic data sources and knowledge layer availability.
 */

import { apiConfig } from './config'

const getBaseUrl = (): string => {
  const isBrowser = typeof window !== 'undefined'
  return isBrowser ? '' : apiConfig.baseUrl
}

// ============================================================================
// Types
// ============================================================================

export interface DataSourceFromAPI {
  /** Unique identifier for the data source */
  id: string
  /** Display name for the source */
  name: string
  /** Brief description of the source */
  description?: string
  /** Category for grouping/filtering */
  category?: 'web' | 'enterprise' | 'storage' | 'collaboration'
  /** Whether the source is enabled by default */
  default_enabled?: boolean
}

export interface DataSourcesResponse {
  /** List of available data sources from API (objects with id, name, description) */
  data_sources: DataSourceFromAPI[]
  /** Whether the knowledge layer (file upload) is available */
  knowledge_layer: boolean
}

export interface DataSourcesClientOptions {
  /** Auth token for API requests */
  authToken?: string
}

// ============================================================================
// Helpers
// ============================================================================

/**
 * Parse API error response and throw a consistent error
 */
async function handleApiError(response: Response, context: string): Promise<never> {
  const error = await response.json().catch(() => ({}))
  throw new Error(error?.error?.message || `${context}: ${response.statusText}`)
}

// ============================================================================
// Client Factory
// ============================================================================

/**
 * Create a data sources API client
 *
 * @param options - Client options including auth token
 * @returns Data sources client with API methods
 *
 * @example
 * ```typescript
 * const { idToken } = useAuth()
 * const client = createDataSourcesClient({ authToken: idToken })
 *
 * // Fetch data sources
 * const { data_sources, knowledge_layer } = await client.getDataSources()
 * ```
 */
export const createDataSourcesClient = (options: DataSourcesClientOptions = {}) => {
  const { authToken } = options

  // Helper to create headers
  const getHeaders = (): Record<string, string> => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`
    }
    return headers
  }

  return {
    /**
     * Get available data sources from the backend
     *
     * @param signal - Optional AbortSignal for cancellation
     * @returns Data sources list and knowledge layer availability
     */
    async getDataSources(signal?: AbortSignal): Promise<DataSourcesResponse> {
      const baseUrl = getBaseUrl()
      const url = baseUrl ? `${baseUrl}/v1/data_sources` : '/api/v1/data_sources'
      const response = await fetch(url, {
        method: 'GET',
        headers: getHeaders(),
        signal,
      })

      if (!response.ok) {
        await handleApiError(response, 'Failed to fetch data sources')
      }

      const data = await response.json()

      // API might return array directly OR wrapped in {data_sources: [...]}
      // Handle both cases
      const rawDataSources: DataSourceFromAPI[] = Array.isArray(data)
        ? data
        : (data.data_sources ?? [])

      // Check if knowledge_layer is in the array - if present, file uploads are available
      const hasKnowledgeLayer = rawDataSources.some((source) => source.id === 'knowledge_layer')

      // Filter out knowledge_layer from the data sources list (it's not displayed)
      const filteredDataSources = rawDataSources.filter((source) => source.id !== 'knowledge_layer')

      return {
        data_sources: filteredDataSources,
        knowledge_layer: hasKnowledgeLayer,
      }
    },
  }
}

export type DataSourcesClient = ReturnType<typeof createDataSourcesClient>

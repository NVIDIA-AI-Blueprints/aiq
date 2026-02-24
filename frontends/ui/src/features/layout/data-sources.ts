// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Data Sources Type Definitions
 *
 * Type definitions for data sources returned by the backend API.
 * Data sources are fetched dynamically from GET /v1/data_sources.
 */

/** Category types for organizing data sources */
export type DataSourceCategory = 'web' | 'enterprise' | 'storage' | 'collaboration'

/** Data source configuration interface */
export interface DataSource {
  /** Unique identifier matching backend source IDs */
  id: string
  /** Display name for the source */
  name: string
  /** Brief description of the source */
  description: string
  /** Category for grouping/filtering */
  category: DataSourceCategory
  /** Whether the source is enabled by default */
  defaultEnabled: boolean
}

/**
 * Default data source ID that works without authentication.
 * Web search uses backend API keys (Tavily), not user tokens.
 */
export const WEB_SEARCH_SOURCE_ID = 'web_search'

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

/** Per-user MCP auth status for a protected source. */
export type PerUserAuthStatus = 'connected' | 'not_connected' | 'expired' | 'error'

/** Per-user MCP OAuth state attached to a protected data source (UI shape). */
export interface PerUserAuth {
  required: boolean
  provider?: string | null
  mcpServerId?: string | null
  status?: PerUserAuthStatus | null
  connectUrl?: string | null
  expiresAt?: string | null
  lastError?: string | null
}

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
  /** Whether the source requires user authentication */
  requiresAuth: boolean
  /** Per-user MCP OAuth state (present only for protected MCP sources) */
  perUserAuth?: PerUserAuth
}

// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Data Sources Type Definitions
 *
 * Type definitions for data sources returned by the backend API.
 * Data sources are fetched dynamically from GET /v1/data_sources.
 */

import type { SourceKind } from '@/shared/components/Sources/types'

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

/**
 * Presentation-only label overrides keyed by source id.
 *
 * Some backend sources carry intentionally verbose `name`/`description` copy
 * because that text doubles as the agent's tool-routing instruction. These
 * overrides keep the sidebar labels short and scannable without altering the
 * backend copy the agent depends on.
 */
const DATA_SOURCE_DISPLAY_OVERRIDES: Record<
  string,
  { name?: string; description?: string; kind?: SourceKind }
> = {}

/**
 * Returns the short, sidebar-friendly name and description for a source,
 * preferring a presentation override when one exists for the source id.
 */
export function getDataSourceDisplay(source: {
  id: string
  name: string
  description?: string | null
}): { name: string; description: string } {
  const override = DATA_SOURCE_DISPLAY_OVERRIDES[source.id]
  return {
    name: override?.name ?? source.name,
    description: override?.description ?? source.description ?? '',
  }
}

const BASE_DATA_SOURCE_LABELS: Record<string, string> = {
  web_search: 'Web Search',
  knowledge_layer: 'Files',
  benefits: 'Benefits',
  confluence: 'Confluence',
  gdrive: 'Google Drive',
  jira: 'Jira',
  nvbugs: 'NVBugs',
  nvidiablogs: 'NVIDIA Blogs',
  nvidiadocs: 'NVIDIA Documentation',
  nvidianews: 'NVIDIA News',
  o365onedrive: 'Microsoft OneDrive (O365)',
  o365sharepoint: 'Microsoft SharePoint (O365)',
  onedrive: 'Microsoft OneDrive',
  people: 'People Directory',
  servicenow: 'ServiceNow',
}

/**
 * Returns the short, human-readable label for a source id (e.g. `web_search` ->
 * "Web Search"). Prefers a display override, then a known base label, then a
 * title-cased fallback, so chips and footers show clean headings instead of raw
 * ids.
 */
export function getDataSourceLabel(id: string): string {
  const override = DATA_SOURCE_DISPLAY_OVERRIDES[id]
  if (override?.name) return override.name
  if (BASE_DATA_SOURCE_LABELS[id]) return BASE_DATA_SOURCE_LABELS[id]
  return id
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ')
}

/**
 * Maps a data source to a typed icon kind so each connection shows a glyph that
 * matches what it does (a globe for web/search sources) instead of a single
 * generic icon for every source.
 */
export function getDataSourceKind(id: string): SourceKind {
  const override = DATA_SOURCE_DISPLAY_OVERRIDES[id]
  if (override?.kind) return override.kind
  const name = id.toLowerCase()
  if (name.includes('web') || name.includes('search') || name.includes('glean')) {
    return 'web'
  }
  return 'doc'
}

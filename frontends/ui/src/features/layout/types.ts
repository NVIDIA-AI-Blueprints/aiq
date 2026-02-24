// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Layout Feature Types
 *
 * Type definitions for the main app layout including sidebars and panels.
 */

import type { DataSourceFromAPI } from '@/adapters/api'

/** Theme mode options */
export type ThemeMode = 'light' | 'dark' | 'system'

/** Panels that can be opened on the right side */
export type RightPanelType = 'research' | 'data-sources' | 'settings' | null

/** Tabs within the Research panel */
export type ResearchPanelTab = 'plan' | 'tasks' | 'thinking' | 'citations' | 'report'

/** Tabs within the DataSources panel */
export type DataSourcesPanelTab = 'connections' | 'files'

/** Layout state for managing panels */
export interface LayoutState {
  /** Whether the sessions panel is open (left side) */
  isSessionsPanelOpen: boolean
  /** Currently open right panel (null = closed) */
  rightPanel: RightPanelType
  /** Active tab in the research panel */
  researchPanelTab: ResearchPanelTab
  /** Active tab in the data sources panel */
  dataSourcesPanelTab: DataSourcesPanelTab
  /** IDs of enabled data sources (array for zustand serialization) */
  enabledDataSourceIds: string[]
  /** Current theme mode */
  theme: ThemeMode
  /** Dynamic data sources from API (null = not loaded yet) */
  availableDataSources: DataSourceFromAPI[] | null
  /** Whether the knowledge layer (file upload) is available */
  knowledgeLayerAvailable: boolean
  /** Whether data sources are being fetched */
  dataSourcesLoading: boolean
  /** Error message if data sources fetch failed */
  dataSourcesError: string | null
  /**
   * @deprecated Use researchPanelTab instead
   */
  detailsPanelTab: ResearchPanelTab
  /**
   * @deprecated Use dataSourcesPanelTab instead
   */
  dataSourcePanelTab: DataSourcesPanelTab
}

/** Layout actions for state management */
export interface LayoutActions {
  /** Toggle sessions panel open/closed */
  toggleSessionsPanel: () => void
  /** Set sessions panel state */
  setSessionsPanelOpen: (open: boolean) => void
  /** Open a specific right panel (closes any existing) */
  openRightPanel: (panel: RightPanelType) => void
  /** Close the right panel */
  closeRightPanel: () => void
  /** Set the active research panel tab */
  setResearchPanelTab: (tab: ResearchPanelTab) => void
  /** Set the active data sources panel tab */
  setDataSourcesPanelTab: (tab: DataSourcesPanelTab) => void
  /** Toggle a data source enabled/disabled by ID */
  toggleDataSource: (id: string) => void
  /** Set all enabled data sources */
  setEnabledDataSources: (ids: string[]) => void
  /** Set the theme mode */
  setTheme: (theme: ThemeMode) => void
  /** Fetch data sources from API. Only web_search is enabled by default */
  fetchDataSources: (authToken?: string) => Promise<void>
  /** Disable all non-web sources (keep only web_search enabled) */
  disableNonWebSources: () => void
  /** Set available data sources (from API) */
  setAvailableDataSources: (sources: DataSourceFromAPI[]) => void
  /** Set knowledge layer availability */
  setKnowledgeLayerAvailable: (available: boolean) => void
  /**
   * @deprecated Use setResearchPanelTab instead
   */
  setDetailsPanelTab: (tab: ResearchPanelTab) => void
  /**
   * @deprecated Use setDataSourcesPanelTab instead
   */
  setDataSourcePanelTab: (tab: DataSourcesPanelTab) => void
}

/** Combined layout store type */
export type LayoutStore = LayoutState & LayoutActions

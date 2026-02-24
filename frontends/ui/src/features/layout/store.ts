// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Layout Store
 *
 * Zustand store for managing the main app layout state.
 * Controls sidebar visibility and panel states.
 */

import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import type {
  LayoutState,
  LayoutStore,
  RightPanelType,
  ResearchPanelTab,
  DataSourcesPanelTab,
  ThemeMode,
} from './types'
import { createDataSourcesClient, type DataSourceFromAPI } from '@/adapters/api'
import { WEB_SEARCH_SOURCE_ID } from './data-sources'

const initialState: LayoutState = {
  isSessionsPanelOpen: false,
  rightPanel: null,
  researchPanelTab: 'report',
  dataSourcesPanelTab: 'connections',
  enabledDataSourceIds: [], // Start empty, populated when data sources are fetched
  theme: 'system',
  availableDataSources: null,
  knowledgeLayerAvailable: false, // Default to false until API confirms availability
  dataSourcesLoading: false,
  dataSourcesError: null,
  // Deprecated aliases for backwards compatibility
  detailsPanelTab: 'report',
  dataSourcePanelTab: 'connections',
}

export const useLayoutStore = create<LayoutStore>()(
  devtools(
    (set) => ({
      ...initialState,

      toggleSessionsPanel: () =>
        set(
          (state) => ({ isSessionsPanelOpen: !state.isSessionsPanelOpen }),
          false,
          'toggleSessionsPanel'
        ),

      setSessionsPanelOpen: (open: boolean) =>
        set({ isSessionsPanelOpen: open }, false, 'setSessionsPanelOpen'),

      openRightPanel: (panel: RightPanelType) =>
        set({ rightPanel: panel }, false, 'openRightPanel'),

      closeRightPanel: () => set({ rightPanel: null }, false, 'closeRightPanel'),

      setResearchPanelTab: (tab: ResearchPanelTab) =>
        set({ researchPanelTab: tab }, false, 'setResearchPanelTab'),

      setDataSourcesPanelTab: (tab: DataSourcesPanelTab) =>
        set({ dataSourcesPanelTab: tab }, false, 'setDataSourcesPanelTab'),

      toggleDataSource: (id: string) =>
        set(
          (state) => {
            const isEnabled = state.enabledDataSourceIds.includes(id)
            return {
              enabledDataSourceIds: isEnabled
                ? state.enabledDataSourceIds.filter((sourceId) => sourceId !== id)
                : [...state.enabledDataSourceIds, id],
            }
          },
          false,
          'toggleDataSource'
        ),

      setEnabledDataSources: (ids: string[]) =>
        set({ enabledDataSourceIds: ids }, false, 'setEnabledDataSources'),

      setTheme: (theme: ThemeMode) => set({ theme }, false, 'setTheme'),

      fetchDataSources: async (authToken?: string) => {
        set({ dataSourcesLoading: true, dataSourcesError: null }, false, 'fetchDataSources/start')

        try {
          const client = createDataSourcesClient({ authToken })
          const response = await client.getDataSources()

          // data_sources is already filtered (knowledge_layer removed) by the client
          // Only enable web_search by default - user must manually enable other sources
          const enabledIds = response.data_sources
            .filter((source) => source.id === WEB_SEARCH_SOURCE_ID)
            .map((source) => source.id)

          set(
            {
              availableDataSources: response.data_sources,
              knowledgeLayerAvailable: response.knowledge_layer,
              enabledDataSourceIds: enabledIds,
              dataSourcesLoading: false,
              dataSourcesError: null,
            },
            false,
            'fetchDataSources/success'
          )
        } catch (error) {
          const errorMessage = error instanceof Error ? error.message : 'Failed to fetch data sources'
          set(
            {
              dataSourcesLoading: false,
              dataSourcesError: errorMessage,
            },
            false,
            'fetchDataSources/error'
          )
        }
      },

      disableNonWebSources: () =>
        set(
          (state) => ({
            enabledDataSourceIds: state.enabledDataSourceIds.filter(
              (id) => id === WEB_SEARCH_SOURCE_ID
            ),
          }),
          false,
          'disableNonWebSources'
        ),

      setAvailableDataSources: (sources: DataSourceFromAPI[]) =>
        set({ availableDataSources: sources }, false, 'setAvailableDataSources'),

      setKnowledgeLayerAvailable: (available: boolean) =>
        set({ knowledgeLayerAvailable: available }, false, 'setKnowledgeLayerAvailable'),

      // Deprecated actions - delegate to new ones
      setDetailsPanelTab: (tab: ResearchPanelTab) =>
        set(
          { researchPanelTab: tab, detailsPanelTab: tab },
          false,
          'setDetailsPanelTab'
        ),

      setDataSourcePanelTab: (tab: DataSourcesPanelTab) =>
        set(
          { dataSourcesPanelTab: tab, dataSourcePanelTab: tab },
          false,
          'setDataSourcePanelTab'
        ),
    }),
    { name: 'LayoutStore' }
  )
)

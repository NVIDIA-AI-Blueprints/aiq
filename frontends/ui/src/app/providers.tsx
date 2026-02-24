// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Application Providers
 *
 * Wraps the application with necessary providers:
 * - AppConfigProvider (runtime server-side config)
 * - ThemeProvider (KUI dark/light mode)
 * - SessionProvider (NextAuth)
 * - DeepResearchRestorer (checks for active deep research jobs on mount)
 */

'use client'

import { type ReactNode, useEffect, useRef, useState } from 'react'
import { SessionProvider } from 'next-auth/react'
import { ThemeProvider } from '@/adapters/ui'
import { AppConfigProvider, type AppConfig } from '@/shared/context'
import { useLayoutStore } from '@/features/layout'
import { useChatStore } from '@/features/chat/store'
import type { ThemeMode } from '@/features/layout'

interface ProvidersProps {
  children: ReactNode
  /** Runtime configuration from server-side environment variables */
  config: AppConfig
}

/**
 * Applies theme classes directly to the document element.
 * This ensures theme changes happen without remounting the component tree.
 * Defers application until after hydration to prevent SSR mismatches.
 */
const useThemeEffect = (theme: ThemeMode): void => {
  const [mounted, setMounted] = useState(false)

  // Mark as mounted after first render (client-side only)
  useEffect(() => {
    setMounted(true)
  }, [])

  useEffect(() => {
    // Skip during SSR and initial hydration
    if (!mounted) return

    const root = document.documentElement

    // Remove existing theme classes
    root.classList.remove('nv-light', 'nv-dark')

    if (theme === 'system') {
      // Check system preference
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
      root.classList.add(prefersDark ? 'nv-dark' : 'nv-light')

      // Listen for system theme changes
      const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
      const handleChange = (e: MediaQueryListEvent): void => {
        root.classList.remove('nv-light', 'nv-dark')
        root.classList.add(e.matches ? 'nv-dark' : 'nv-light')
      }
      mediaQuery.addEventListener('change', handleChange)
      return () => mediaQuery.removeEventListener('change', handleChange)
    } else {
      // Apply explicit theme
      root.classList.add(theme === 'dark' ? 'nv-dark' : 'nv-light')
    }
  }, [theme, mounted])
}

/**
 * Hook to fetch data sources on app initialization.
 * Loads available data sources from the API and updates the layout store.
 * Only web_search is enabled by default - users must manually enable other sources.
 */
const useDataSourcesInit = (): void => {
  const fetchDataSources = useLayoutStore((state) => state.fetchDataSources)
  const availableDataSources = useLayoutStore((state) => state.availableDataSources)

  useEffect(() => {
    // Only fetch if not already loaded
    if (availableDataSources === null) {
      fetchDataSources()
    }
  }, [fetchDataSources, availableDataSources])
}

/**
 * Restores per-session data source toggles after the initial API fetch.
 * On page refresh, fetchDataSources sets enabledDataSourceIds to [web_search].
 * This hook overrides that default with the stored per-session selection.
 * Waits for both availableDataSources and a hydrated conversation before restoring.
 */
const useDataSourceSessionRestore = (): void => {
  const availableDataSources = useLayoutStore((state) => state.availableDataSources)
  const setEnabledDataSources = useLayoutStore((state) => state.setEnabledDataSources)
  const conversationId = useChatStore((state) => state.currentConversation?.id)
  const restoredRef = useRef(false)

  useEffect(() => {
    if (restoredRef.current || !availableDataSources) return

    const conversation = useChatStore.getState().currentConversation
    if (!conversation) return

    const savedIds = conversation.enabledDataSourceIds
    if (savedIds) {
      const availableIds = new Set(availableDataSources.map((s) => s.id))
      const validIds = savedIds.filter((id) => availableIds.has(id))
      setEnabledDataSources(validIds)
    }

    restoredRef.current = true
  }, [availableDataSources, conversationId, setEnabledDataSources])
}

/**
 * Theme wrapper that syncs with layout store.
 * Applies theme classes directly to document for instant updates.
 * Uses defer prop to prevent hydration mismatches.
 */
const ThemeWrapper = ({ children }: { children: ReactNode }): ReactNode => {
  const theme = useLayoutStore((state) => state.theme)

  // Apply theme classes directly to document
  useThemeEffect(theme)

  // Initialize data sources
  useDataSourcesInit()

  // Restore per-session data source toggles after initial fetch
  useDataSourceSessionRestore()

  return (
    <ThemeProvider theme={theme} global defer>
      {children}
    </ThemeProvider>
  )
}

/**
 * Restores deep research state on conversation load.
 * - Reconnects to running/submitted jobs for page refresh recovery.
 * - Cleans up orphaned 'starting' banners by polling job status via REST.
 * Completed jobs are loaded on-demand via "View Report" click.
 */
const DeepResearchRestorer = ({ children }: { children: ReactNode }): ReactNode => {
  const [mounted, setMounted] = useState(false)
  const reconnectToActiveJob = useChatStore((state) => state.reconnectToActiveJob)
  const cleanupOrphanedStartingBanners = useChatStore((state) => state.cleanupOrphanedStartingBanners)
  const currentConversationId = useChatStore((state) => state.currentConversation?.id)
  const isDeepResearchStreaming = useChatStore((state) => state.isDeepResearchStreaming)

  useEffect(() => {
    setMounted(true)
  }, [])

  useEffect(() => {
    if (!mounted || !currentConversationId || isDeepResearchStreaming) return

    const restore = async () => {
      await reconnectToActiveJob()
      await cleanupOrphanedStartingBanners()
    }
    restore()
  }, [mounted, currentConversationId, isDeepResearchStreaming, reconnectToActiveJob, cleanupOrphanedStartingBanners])

  return <>{children}</>
}

export const Providers = ({ children, config }: ProvidersProps): ReactNode => {
  const content = (
    <ThemeWrapper>
      <DeepResearchRestorer>{children}</DeepResearchRestorer>
    </ThemeWrapper>
  )

  return (
    <AppConfigProvider config={config}>
      <SessionProvider
        refetchInterval={config.authRequired ? 4 * 60 : 0}
        refetchOnWindowFocus={config.authRequired}
        refetchWhenOffline={false}
      >
        {content}
      </SessionProvider>
    </AppConfigProvider>
  )
}

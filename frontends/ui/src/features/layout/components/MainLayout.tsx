// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * MainLayout Component
 *
 * The main application layout container that orchestrates:
 * - AppBar (top)
 * - SessionsPanel (left, overlay)
 * - ChatArea + InputArea (center, responsive width)
 * - ResearchPanel (right, pushes content - takes 60% when open)
 * - DataSourcesPanel / SettingsPanel (right, overlay)
 *
 * Handles auth state to show different UI for logged-in vs logged-out users.
 */

'use client'

import { type FC, useCallback } from 'react'
import { Flex } from '@/adapters/ui'
import { useReducedMotion } from '@/hooks/use-reduced-motion'
import { AppBar } from './AppBar'
import { SessionsPanel } from './SessionsPanel'
import { ChatArea } from './ChatArea'
import { InputArea } from './InputArea'
import { ResearchPanel } from './ResearchPanel'
import { DataSourcesPanel } from './DataSourcesPanel'
import { SettingsPanel } from './SettingsPanel'
import { useChatStore, useDeepResearch, NoSourcesBanner } from '@/features/chat'
import { hasActiveDeepResearchJob } from '@/features/chat/lib/session-activity'
import { useLayoutStore } from '../store'
import { useSessionUrl } from '@/hooks/use-session-url'

interface MainLayoutProps {
  /** Whether the user is authenticated */
  isAuthenticated?: boolean
  /** Whether authentication is required (false = using default user) */
  authRequired?: boolean
  /** User information for AppBar */
  user?: {
    name?: string
    email?: string
    image?: string
  }
  /** Callback when sign in is clicked */
  onSignIn?: () => void
  /** Callback when sign out is clicked */
  onSignOut?: () => void
}

/**
 * Main application layout with all panels and regions.
 * Manages the overall structure and panel states.
 * Chat state is managed via the useChatStore.
 */
export const MainLayout: FC<MainLayoutProps> = ({
  isAuthenticated = false,
  authRequired = false,
  user,
  onSignIn,
  onSignOut,
}) => {
  const {
    currentConversation,
    getUserConversations,
    selectConversation,
    startNewSessionDraft,
    deleteConversation,
    deleteAllConversations,
    updateConversationTitle,
    isStreaming,
    pendingInteraction,
    isDeepResearchStreaming,
    deepResearchOwnerConversationId,
  } = useChatStore()

  const { rightPanel, closeRightPanel } = useLayoutStore()
  const prefersReducedMotion = useReducedMotion()

  // Deep research SSE hook - manages connection when deep research starts
  useDeepResearch()

  // Sync session state with URL query parameters
  const { updateSessionUrl, clearSessionUrl } = useSessionUrl({ isAuthenticated })

  // Wrap selectConversation to also update URL
  const handleSelectSession = useCallback(
    (sessionId: string) => {
      selectConversation(sessionId)
      updateSessionUrl(sessionId)
    },
    [selectConversation, updateSessionUrl]
  )

  // Start a new unsaved draft session and clear URL until first interaction.
  const handleNewSession = useCallback(() => {
    startNewSessionDraft()
    clearSessionUrl()
    closeRightPanel()
  }, [startNewSessionDraft, clearSessionUrl, closeRightPanel])

  // Wrap deleteConversation to clear URL if deleting current session
  const handleDeleteSession = useCallback(
    (sessionId: string) => {
      const wasCurrentSession = currentConversation?.id === sessionId
      deleteConversation(sessionId)
      if (wasCurrentSession) {
        clearSessionUrl()
      }
    },
    [deleteConversation, currentConversation?.id, clearSessionUrl]
  )

  // Delete all sessions for the current user
  const handleDeleteAllSessions = useCallback(() => {
    deleteAllConversations()
    clearSessionUrl()
  }, [deleteAllConversations, clearSessionUrl])

  // Check if research panel is open (pushes content instead of overlaying)
  const isResearchPanelOpen = rightPanel === 'research'
  const isNavigationBlocked = isStreaming || pendingInteraction !== null

  // Get only conversations for the current authenticated user
  const userConversations = getUserConversations()

  // Convert conversations to session format for sidebar
  const sessions = userConversations.map((conv) => {
    const hasActiveJob = hasActiveDeepResearchJob(conv.messages)

    return {
      id: conv.id,
      title: conv.title,
      date: conv.updatedAt,
      hasActiveDeepResearch: hasActiveJob || (isDeepResearchStreaming && deepResearchOwnerConversationId === conv.id),
    }
  })

  return (
    <Flex direction="col" className="h-screen min-w-[768px] overflow-x-auto overflow-y-hidden">
      {/* AppBar - Fixed at top */}
      <AppBar
        sessionTitle={currentConversation?.title || 'New Session'}
        isAuthenticated={isAuthenticated}
        authRequired={authRequired}
        user={user}
        onNewSession={handleNewSession}
        isNewSessionDisabled={isNavigationBlocked}
        onSignIn={onSignIn}
        onSignOut={onSignOut}
      />

      {/* Main Content Area - using explicit widths instead of flex for smoother animation */}
      <div className="relative flex flex-1 overflow-hidden">
        {/* Center Content: Chat + Input - Responsive to research panel */}
        <div
          className="flex flex-col overflow-hidden"
          style={{
            width: isResearchPanelOpen ? '40%' : '100%',
            transition: prefersReducedMotion ? 'none' : 'width 600ms ease-in-out',
          }}
        >
          {/* Chat Area - Scrollable */}
          <ChatArea isAuthenticated={isAuthenticated} onSignIn={onSignIn} />

          {/* No sources warning - shown when no data sources or files available */}
          <NoSourcesBanner isAuthenticated={isAuthenticated} />

          {/* Input Area - Fixed at bottom of chat */}
          {/* Using WebSocket mode for full HITL (human-in-the-loop) support */}
          <InputArea
            isAuthenticated={isAuthenticated}
            connectionMode="websocket"
          />
        </div>

        {/* Research Panel (Right) - Pushes content, takes 60% width */}
        <ResearchPanel isAuthenticated={isAuthenticated} />
      </div>

      {/* Overlay Panels - These slide over the content */}

      {/* Sessions Panel (Left) - Only functional when authenticated */}
      <SessionsPanel
        sessions={sessions}
        selectedSessionId={currentConversation?.id}
        onSelectSession={handleSelectSession}
        onNewSession={handleNewSession}
        onDeleteSession={handleDeleteSession}
        onDeleteAllSessions={handleDeleteAllSessions}
        onRenameSession={updateConversationTitle}
      />

      {/* Data Sources Panel (Right) - Overlay */}
      <DataSourcesPanel />

      {/* Settings Panel (Right) - Overlay */}
      <SettingsPanel />
    </Flex>
  )
}

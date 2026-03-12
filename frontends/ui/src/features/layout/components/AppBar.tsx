// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * AppBar Component
 *
 * Top navigation bar with menu toggle, logo, session title,
 * and action buttons (Add Sources, Settings, Docs, User Avatar).
 *
 * Shows different states based on authentication:
 * - Auth disabled: Default User avatar with info tooltip (no sign in/out)
 * - Logged out: Sign In button, disabled action buttons
 * - Logged in: User avatar with dropdown menu
 */

'use client'

import { type FC, useCallback, useState } from 'react'
import { Flex, Text, Button, Logo, Avatar, Popover, Divider } from '@/adapters/ui'
import { Menu, Globe, Settings, Book, Lock, Logout, ChevronRight, Info } from '@/adapters/ui/icons'
import { useLayoutStore } from '../store'

interface AppBarProps {
  /** Current session title to display */
  sessionTitle?: string
  /** Whether the user is authenticated */
  isAuthenticated?: boolean
  /** Whether authentication is required (false = using default user) */
  authRequired?: boolean
  /** User info for avatar */
  user?: {
    name?: string
    email?: string
    image?: string
  }
  /** Callback when a new session is requested */
  onNewSession?: () => void
  /** Disable creating a new session while shallow research/HITL is active */
  isNewSessionDisabled?: boolean
  /** Callback when sign in is clicked */
  onSignIn?: () => void
  /** Callback when sign out is clicked */
  onSignOut?: () => void
}

/**
 * Main navigation bar at the top of the application.
 * Controls sidebar toggles and navigation actions.
 */
export const AppBar: FC<AppBarProps> = ({
  sessionTitle = 'New Session',
  isAuthenticated = false,
  authRequired = false,
  user,
  onNewSession,
  isNewSessionDisabled = false,
  onSignIn,
  onSignOut,
}) => {
  const { toggleSessionsPanel, rightPanel, openRightPanel, closeRightPanel } = useLayoutStore()
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false)

  const handleMenuClick = useCallback(() => {
    if (!isAuthenticated) return
    toggleSessionsPanel()
  }, [toggleSessionsPanel, isAuthenticated])

  const handleAddSourcesClick = useCallback(() => {
    if (!isAuthenticated) return
    if (rightPanel === 'data-sources') {
      closeRightPanel()
    } else {
      openRightPanel('data-sources')
    }
  }, [rightPanel, openRightPanel, closeRightPanel, isAuthenticated])

  const handleSettingsClick = useCallback(() => {
    if (!isAuthenticated) return
    if (rightPanel === 'settings') {
      closeRightPanel()
    } else {
      openRightPanel('settings')
    }
  }, [rightPanel, openRightPanel, closeRightPanel, isAuthenticated])

  const handleDocsClick = useCallback(() => {
    window.open('https://github.com/NVIDIA-AI-Blueprints/aiq', '_blank')
  }, [])

  const handleNewSessionClick = useCallback(() => {
    if (!isAuthenticated || isNewSessionDisabled) return
    onNewSession?.()
  }, [isAuthenticated, isNewSessionDisabled, onNewSession])

  const handleSignOut = useCallback(() => {
    setIsUserMenuOpen(false)
    onSignOut?.()
  }, [onSignOut])

  return (
    <header className="border-b border-base">
      <Flex align="center" justify="between" className="h-[var(--header-height)] gap-4 px-4">
        {/* Left section: New session button + Sessions toggle */}
        <Flex align="center" gap="2" className="min-w-0 flex-1">
          <Button
            kind="tertiary"
            size="small"
            onClick={handleNewSessionClick}
            disabled={!isAuthenticated || isNewSessionDisabled}
            aria-label="Create new session"
            title={
              isNewSessionDisabled
                ? 'Cannot create new session while shallow research is active'
                : 'Create new session'
            }
          >
            <Flex align="center" gap="density-lg">
              <Logo kind="logo-only" size="small" />

              <Text kind="label/semibold/lg" className="text-primary whitespace-nowrap">
                AI-Q
              </Text>
            </Flex>
          </Button>

          <Button
            kind="tertiary"
            size="small"
            onClick={handleMenuClick}
            disabled={!isAuthenticated}
            aria-label="Toggle sessions sidebar"
            title="Toggle sessions sidebar"
          >
            <Flex align="center" gap="1">
              <Menu className="h-4 w-4" />
              <Text kind="label/regular/md">Sessions</Text>
            </Flex>
          </Button>

          {isAuthenticated && (
            <div className="ml-4 hidden min-w-0 flex-1 items-center md:flex">
              <Text
                kind="body/regular/md"
                className="block w-full max-w-[360px] truncate text-subtle lg:max-w-[480px] xl:max-w-[560px]"
              >
                {sessionTitle}
              </Text>
            </div>
          )}
        </Flex>

        {/* Right section: Actions + User */}
        <Flex align="center" gap="2" className="shrink-0">
          <Button
            kind="tertiary"
            size="small"
            onClick={handleAddSourcesClick}
            disabled={!isAuthenticated}
            aria-label="Add data sources"
            title="Add data sources"
          >
            <Flex align="center" gap="1">
              <Globe className="h-4 w-4" />
              <Text kind="label/regular/md">Data Sources</Text>
            </Flex>
          </Button>

          <Button
            kind="tertiary"
            size="small"
            onClick={handleSettingsClick}
            disabled={!isAuthenticated}
            aria-label="Open settings"
            title="Open settings"
          >
            <Flex align="center" gap="1">
              <Settings className="h-4 w-4" />
              <Text kind="label/regular/md">Settings</Text>
            </Flex>
          </Button>

          <Button
            kind="tertiary"
            size="small"
            onClick={handleDocsClick}
            aria-label="Open documentation"
            title="Open documentation"
          >
            <Flex align="center" gap="1">
              <Book className="h-4 w-4" />
              <Text kind="label/regular/md">Docs</Text>
              <ChevronRight className="h-3 w-3 -rotate-45" />
            </Flex>
          </Button>

          {/* User section: Auth not required notice, Avatar with dropdown, or Sign In button */}
          {!authRequired ? (
            <Popover
              open={isUserMenuOpen}
              onOpenChange={setIsUserMenuOpen}
              side="bottom"
              align="end"
              slotContent={<AuthDisabledContent />}
            >
              <Button
                kind="tertiary"
                size="small"
                aria-label="Default User - Authentication Not Configured"
                title="Default User set. Authentication Not Configured."
                className="ml-2"
              >
                <Avatar size="small" fallback="D" />
              </Button>
            </Popover>
          ) : isAuthenticated ? (
            <Popover
              open={isUserMenuOpen}
              onOpenChange={setIsUserMenuOpen}
              side="bottom"
              align="end"
              slotContent={<UserDropdownContent user={user} onSignOut={handleSignOut} />}
            >
              <Button
                kind="tertiary"
                size="small"
                aria-label={`User menu for ${user?.name || user?.email || 'User'}`}
                title="User menu"
                className="ml-2"
              >
                <Avatar
                  size="small"
                  src={user?.image}
                  fallback={(user?.name || user?.email || 'U').charAt(0).toUpperCase()}
                />
              </Button>
            </Popover>
          ) : (
            <Button
              kind="primary"
              size="small"
              onClick={onSignIn}
              aria-label="Sign in with NVIDIA SSO"
              title="Sign in with NVIDIA SSO"
              className="ml-2 bg-[#76b900] hover:bg-[#5a8f00]"
            >
              <Flex align="center" gap="1">
                <Lock className="h-4 w-4" />
                <Text kind="label/semibold/sm">Sign In</Text>
              </Flex>
            </Button>
          )}
        </Flex>
      </Flex>
    </header>
  )
}

/**
 * User dropdown content with profile info and sign out button
 */
interface UserDropdownContentProps {
  user?: {
    name?: string
    email?: string
    image?: string
  }
  onSignOut?: () => void
}

const UserDropdownContent: FC<UserDropdownContentProps> = ({ user, onSignOut }) => {
  return (
    <Flex direction="col" gap="3" className="min-w-[240px] p-4">
      {/* User info section */}
      <Flex align="center" gap="3">
        <Avatar
          size="medium"
          src={user?.image}
          fallback={(user?.name || user?.email || 'U').charAt(0).toUpperCase()}
        />
        <Flex direction="col" gap="1">
          <Text kind="label/bold/md" className="text-primary">
            {user?.name || 'User'}
          </Text>
          {user?.email && (
            <Text kind="body/regular/sm" className="text-subtle">
              {user.email}
            </Text>
          )}
        </Flex>
      </Flex>

      <Divider />

      {/* Sign out button */}
      <Button
        kind="secondary"
        size="small"
        onClick={onSignOut}
        className="w-full"
        aria-label="Sign out"
        title="Sign out"
      >
        <Flex align="center" justify="center" gap="2">
          <Logout className="h-4 w-4" />
          <Text kind="label/regular/sm">Sign Out</Text>
        </Flex>
      </Button>
    </Flex>
  )
}

/**
 * Content shown when authentication is disabled
 * Displays info message instead of sign out option
 */
const AuthDisabledContent: FC = () => {
  return (
    <Flex direction="col" gap="3" className="min-w-[240px] p-4">
      {/* User info section */}
      <Flex align="center" gap="3">
        <Avatar size="medium" fallback="D" />
        <Flex direction="col" gap="1">
          <Text kind="label/bold/md" className="text-primary">
            Default User
          </Text>
        </Flex>
      </Flex>

      <Divider />

      {/* Info message */}
      <Flex align="center" gap="2" className="rounded bg-[var(--background-color-surface-raised)] p-3">
        <Info className="h-4 w-4 shrink-0 text-[var(--text-color-subtle)]" />
        <Text kind="body/regular/sm" className="text-subtle">
          Authentication Not Configured
        </Text>
      </Flex>
    </Flex>
  )
}

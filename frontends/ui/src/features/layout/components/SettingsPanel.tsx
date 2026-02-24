// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * SettingsPanel Component
 *
 * Right-side panel for application settings.
 * Currently only contains appearance/theme settings.
 */

'use client'

import { type FC, useCallback } from 'react'
import { Flex, Text, SidePanel } from '@/adapters/ui'
import { Settings } from '@/adapters/ui/icons'
import { useLayoutStore } from '../store'
import type { ThemeMode } from '../types'

/**
 * Settings panel for application preferences.
 * Opens from the right side of the screen.
 */
export const SettingsPanel: FC = () => {
  const { rightPanel, closeRightPanel, openRightPanel, theme, setTheme } = useLayoutStore()

  const isOpen = rightPanel === 'settings'

  const handleOpenChange = useCallback(
    (open: boolean) => {
      if (open) {
        openRightPanel('settings')
      } else {
        closeRightPanel()
      }
    },
    [openRightPanel, closeRightPanel]
  )

  const handleThemeChange = useCallback(
    (newTheme: ThemeMode) => {
      setTheme(newTheme)
    },
    [setTheme]
  )

  return (
    <SidePanel
      className="bg-surface-base top-[var(--header-height)] h-[calc(100vh-var(--header-height))] w-[400px] rounded-l-2xl"
      open={isOpen}
      onOpenChange={handleOpenChange}
      side="right"
      bordered
      closeOnClickOutside={false}
      slotHeading={
        <Flex align="center" gap="2">
          <Settings className="h-5 w-5" />
          Settings
        </Flex>
      }
      slotFooter={
        <Text kind="body/regular/xs" className="text-subtle">
          Settings are saved automatically.
        </Text>
      }
    >
      {/* Appearance Section */}
      <Flex direction="col" gap="3">
        <Text kind="label/semibold/xs" className="text-subtle uppercase">
          Appearance
        </Text>

        <Flex direction="col" gap="2">
          <ThemeOption
            label="Light"
            description="Use light theme"
            selected={theme === 'light'}
            onClick={() => handleThemeChange('light')}
          />
          <ThemeOption
            label="Dark"
            description="Use dark theme"
            selected={theme === 'dark'}
            onClick={() => handleThemeChange('dark')}
          />
          <ThemeOption
            label="System"
            description="Follow system preference"
            selected={theme === 'system'}
            onClick={() => handleThemeChange('system')}
          />
        </Flex>
      </Flex>
    </SidePanel>
  )
}

/**
 * Theme option selector component
 */
interface ThemeOptionProps {
  label: string
  description: string
  selected: boolean
  onClick: () => void
}

const ThemeOption: FC<ThemeOptionProps> = ({ label, description, selected, onClick }) => {
  return (
    <button
      onClick={onClick}
      className={`
        w-full rounded-lg border p-3 text-left transition-colors
        ${
          selected
            ? 'bg-surface-raised border-accent-primary'
            : 'border-base hover:bg-surface-raised-50 bg-transparent'
        }
      `}
    >
      <Flex direction="col">
        <Text kind="label/semibold/sm" className="text-primary">
          {label}
        </Text>
        <Text kind="body/regular/xs" className="text-subtle">
          {description}
        </Text>
      </Flex>
    </button>
  )
}

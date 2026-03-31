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
import { Flex, Text, SidePanel, Select, Switch } from '@/adapters/ui'
import { Settings } from '@/adapters/ui/icons'
import { useLayoutStore } from '../store'
import type { ThemeMode } from '../types'

/**
 * Settings panel for application preferences.
 * Opens from the right side of the screen.
 */
export const SettingsPanel: FC = () => {
  const {
    rightPanel,
    closeRightPanel,
    openRightPanel,
    theme,
    setTheme,
    newUiEnabled,
    setNewUiEnabled,
  } = useLayoutStore()

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
    (value: string) => {
      setTheme(value as ThemeMode)
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
          UI Theme Options
        </Text>

        <Select
          value={theme}
          onValueChange={handleThemeChange}
          side="bottom"
          items={[
            { children: 'System Theme (Auto)', value: 'system' },
            { children: 'Light', value: 'light' },
            { children: 'Dark', value: 'dark' },
          ]}
        />
          <Text kind="label/semibold/xs" className="text-subtle uppercase">
            New UI
          </Text>
          <Switch
            size="small"
            checked={newUiEnabled}
            onCheckedChange={setNewUiEnabled}
            attributes={{
              SwitchTrack: { 'aria-label': 'Enable new UI' },
            }}
          />
      </Flex>
    </SidePanel>
  )
}

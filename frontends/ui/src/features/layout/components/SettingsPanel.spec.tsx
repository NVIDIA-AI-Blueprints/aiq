// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { SettingsPanel } from './SettingsPanel'

// Mock the layout store
const mockCloseRightPanel = vi.fn()
const mockOpenRightPanel = vi.fn()
const mockSetTheme = vi.fn()

vi.mock('../store', () => ({
  useLayoutStore: vi.fn(() => ({
    rightPanel: 'settings',
    closeRightPanel: mockCloseRightPanel,
    openRightPanel: mockOpenRightPanel,
    theme: 'system',
    setTheme: mockSetTheme,
  })),
}))

import { useLayoutStore } from '../store'

describe('SettingsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset mock to default open state
    vi.mocked(useLayoutStore).mockReturnValue({
      rightPanel: 'settings',
      closeRightPanel: mockCloseRightPanel,
      openRightPanel: mockOpenRightPanel,
      theme: 'system',
      setTheme: mockSetTheme,
    })
  })

  test('renders panel heading when open', () => {
    render(<SettingsPanel />)

    expect(screen.getByText('Settings')).toBeInTheDocument()
  })

  test('renders appearance section with theme dropdown', () => {
    render(<SettingsPanel />)

    expect(screen.getByText('UI Theme Options')).toBeInTheDocument()
    // Dropdown trigger shows the current theme label
    expect(screen.getByText('System Theme (Auto)')).toBeInTheDocument()
  })

  test('dropdown trigger label reflects current theme', () => {
    vi.mocked(useLayoutStore).mockReturnValue({
      rightPanel: 'settings',
      closeRightPanel: mockCloseRightPanel,
      openRightPanel: mockOpenRightPanel,
      theme: 'dark',
      setTheme: mockSetTheme,
    })

    render(<SettingsPanel />)

    expect(screen.getByText('Dark')).toBeInTheDocument()
  })

  test('does not render when panel is closed', () => {
    vi.mocked(useLayoutStore).mockReturnValue({
      rightPanel: null,
      closeRightPanel: mockCloseRightPanel,
      openRightPanel: mockOpenRightPanel,
      theme: 'system',
      setTheme: mockSetTheme,
    })

    render(<SettingsPanel />)

    // Panel should not be visible (SidePanel handles this)
    // The heading won't be rendered in closed state
    // This tests the isOpen logic
    expect(screen.queryByText('Settings')).not.toBeInTheDocument()
  })

  test('renders footer text', () => {
    render(<SettingsPanel />)

    expect(screen.getByText(/settings are saved automatically/i)).toBeInTheDocument()
  })
})

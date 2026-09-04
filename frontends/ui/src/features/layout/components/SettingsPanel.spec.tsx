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
  useLayoutStore: vi.fn((selector?: (s: any) => any) => {
    const state = {
      rightPanel: 'settings',
      closeRightPanel: mockCloseRightPanel,
      openRightPanel: mockOpenRightPanel,
      theme: 'system',
      setTheme: mockSetTheme,
    }
    return selector ? selector(state) : state
  }),
}))

import { useLayoutStore } from '../store'

describe('SettingsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset mock to default open state
    vi.mocked(useLayoutStore).mockImplementation((selector?: (s: any) => any) => {
      const state = {
        rightPanel: 'settings',
        closeRightPanel: mockCloseRightPanel,
        openRightPanel: mockOpenRightPanel,
        theme: 'system',
        setTheme: mockSetTheme,
      }
      return selector ? selector(state) : state
    })
  })

  test('renders panel heading when open', () => {
    render(<SettingsPanel />)

    expect(screen.getByText('Settings')).toBeInTheDocument()
  })

  test('renders theme options section with Select trigger', () => {
    render(<SettingsPanel />)

    expect(screen.getByText('UI Theme Options')).toBeInTheDocument()
    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  test('select trigger reflects current theme', () => {
    vi.mocked(useLayoutStore).mockImplementation((selector?: (s: any) => any) => {
      const state = {
        rightPanel: 'settings',
        closeRightPanel: mockCloseRightPanel,
        openRightPanel: mockOpenRightPanel,
        theme: 'dark',
        setTheme: mockSetTheme,
      }
      return selector ? selector(state) : state
    })

    render(<SettingsPanel />)

    const trigger = screen.getByRole('combobox')
    expect(trigger).toHaveTextContent('Dark')
  })

  test('calls setTheme when a theme option is selected', async () => {
    const user = userEvent.setup()

    render(<SettingsPanel />)

    await user.click(screen.getByRole('combobox'))
    await user.click(screen.getByRole('option', { name: /dark/i }))

    expect(mockSetTheme).toHaveBeenCalledWith('dark')
  })

  test('does not render when panel is closed', () => {
    vi.mocked(useLayoutStore).mockImplementation((selector?: (s: any) => any) => {
      const state = {
        rightPanel: null,
        closeRightPanel: mockCloseRightPanel,
        openRightPanel: mockOpenRightPanel,
        theme: 'system',
        setTheme: mockSetTheme,
      }
      return selector ? selector(state) : state
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

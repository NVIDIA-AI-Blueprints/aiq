// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { AppBar } from './AppBar'

// Mock the layout store
const mockToggleSessionsPanel = vi.fn()
const mockOpenRightPanel = vi.fn()
const mockCloseRightPanel = vi.fn()

vi.mock('../store', () => ({
  useLayoutStore: () => ({
    toggleSessionsPanel: mockToggleSessionsPanel,
    rightPanel: null,
    openRightPanel: mockOpenRightPanel,
    closeRightPanel: mockCloseRightPanel,
  }),
}))

describe('AppBar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  test('renders logo and title', () => {
    render(<AppBar />)

    expect(screen.getByText('AI-Q')).toBeInTheDocument()
  })

  test('renders sessions label beside the menu button', () => {
    render(<AppBar isAuthenticated={true} />)

    expect(screen.getByText('Sessions')).toBeInTheDocument()
  })

  test('shows Sign In button when not authenticated', () => {
    render(<AppBar isAuthenticated={false} authRequired={true} />)

    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  test('calls onSignIn when Sign In is clicked', async () => {
    const user = userEvent.setup()
    const onSignIn = vi.fn()

    render(<AppBar isAuthenticated={false} authRequired={true} onSignIn={onSignIn} />)

    await user.click(screen.getByRole('button', { name: /sign in/i }))

    expect(onSignIn).toHaveBeenCalledOnce()
  })

  test('shows session title when authenticated', () => {
    render(<AppBar isAuthenticated={true} sessionTitle="My Research Session" />)

    expect(screen.getByText('My Research Session')).toBeInTheDocument()
  })

  test('disables action buttons when not authenticated', () => {
    render(<AppBar isAuthenticated={false} />)

    expect(screen.getByRole('button', { name: /create new session/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /toggle sessions sidebar/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /add data sources/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /open settings/i })).toBeDisabled()
  })

  test('enables action buttons when authenticated', () => {
    render(<AppBar isAuthenticated={true} />)

    expect(screen.getByRole('button', { name: /create new session/i })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: /toggle sessions sidebar/i })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: /add data sources/i })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: /open settings/i })).not.toBeDisabled()
  })

  test('calls onNewSession when logo button clicked', async () => {
    const user = userEvent.setup()
    const onNewSession = vi.fn()

    render(<AppBar isAuthenticated={true} onNewSession={onNewSession} />)

    await user.click(screen.getByRole('button', { name: /create new session/i }))

    expect(onNewSession).toHaveBeenCalledOnce()
  })

  test('disables new session button when shallow navigation is blocked', () => {
    render(<AppBar isAuthenticated={true} isNewSessionDisabled={true} />)

    expect(screen.getByRole('button', { name: /create new session/i })).toBeDisabled()
    // Other action buttons remain enabled.
    expect(screen.getByRole('button', { name: /toggle sessions sidebar/i })).not.toBeDisabled()
  })

  test('toggles sessions panel when menu button clicked', async () => {
    const user = userEvent.setup()

    render(<AppBar isAuthenticated={true} />)

    await user.click(screen.getByRole('button', { name: /toggle sessions sidebar/i }))

    expect(mockToggleSessionsPanel).toHaveBeenCalledOnce()
  })

  test('opens data-sources panel when Add Sources clicked', async () => {
    const user = userEvent.setup()

    render(<AppBar isAuthenticated={true} />)

    await user.click(screen.getByRole('button', { name: /add data sources/i }))

    expect(mockOpenRightPanel).toHaveBeenCalledWith('data-sources')
  })

  test('opens settings panel when Settings clicked', async () => {
    const user = userEvent.setup()

    render(<AppBar isAuthenticated={true} />)

    await user.click(screen.getByRole('button', { name: /open settings/i }))

    expect(mockOpenRightPanel).toHaveBeenCalledWith('settings')
  })

  test('renders Docs button that opens in new tab', () => {
    render(<AppBar />)

    const docsButton = screen.getByRole('button', { name: /open documentation/i })
    expect(docsButton).toBeInTheDocument()
    expect(docsButton).not.toBeDisabled() // Docs always accessible
  })

  test('shows user avatar when authenticated', () => {
    render(<AppBar isAuthenticated={true} authRequired={true} user={{ name: 'John Doe', email: 'john@example.com' }} />)

    expect(screen.getByRole('button', { name: /user menu for john doe/i })).toBeInTheDocument()
  })

  describe('auth disabled mode', () => {
    test('shows Default User avatar button when auth is disabled', () => {
      render(<AppBar isAuthenticated={true} authRequired={false} />)

      // Should show avatar button with tooltip indicating auth is disabled
      const avatarButton = screen.getByRole('button', {
        name: /default user.*authentication not configured/i,
      })
      expect(avatarButton).toBeInTheDocument()
    })

    test('does not show Sign In button when auth is disabled', () => {
      render(<AppBar isAuthenticated={true} authRequired={false} />)

      expect(screen.queryByRole('button', { name: /sign in/i })).not.toBeInTheDocument()
    })

    test('shows auth disabled popover with info message when clicked', async () => {
      const user = userEvent.setup()

      render(<AppBar isAuthenticated={true} authRequired={false} />)

      const avatarButton = screen.getByRole('button', {
        name: /default user.*authentication not configured/i,
      })
      await user.click(avatarButton)

      // Popover should show "Default User" and info message
      expect(screen.getByText('Default User')).toBeInTheDocument()
      expect(screen.getByText('Authentication Not Configured')).toBeInTheDocument()
    })

    test('does not show Sign Out button when auth is disabled', async () => {
      const user = userEvent.setup()

      render(<AppBar isAuthenticated={true} authRequired={false} />)

      const avatarButton = screen.getByRole('button', {
        name: /default user.*authentication not configured/i,
      })
      await user.click(avatarButton)

      // Should not have a sign out button
      expect(screen.queryByRole('button', { name: /sign out/i })).not.toBeInTheDocument()
    })

    test('action buttons are enabled when auth is disabled (user is authenticated)', () => {
      render(<AppBar isAuthenticated={true} authRequired={false} />)

      expect(screen.getByRole('button', { name: /create new session/i })).not.toBeDisabled()
      expect(screen.getByRole('button', { name: /toggle sessions sidebar/i })).not.toBeDisabled()
      expect(screen.getByRole('button', { name: /add data sources/i })).not.toBeDisabled()
      expect(screen.getByRole('button', { name: /open settings/i })).not.toBeDisabled()
    })

    test('shows session title when auth is disabled', () => {
      render(
        <AppBar isAuthenticated={true} authRequired={false} sessionTitle="My Research Session" />
      )

      expect(screen.getByText('My Research Session')).toBeInTheDocument()
    })
  })
})

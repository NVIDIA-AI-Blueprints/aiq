// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { MainLayout } from './MainLayout'

// Mock the useSessionUrl hook (uses Next.js App Router hooks)
vi.mock('@/hooks/use-session-url', () => ({
  useSessionUrl: vi.fn(() => ({
    updateSessionUrl: vi.fn(),
    clearSessionUrl: vi.fn(),
  })),
}))

// Mock the chat store
vi.mock('@/features/chat', () => ({
  useChatStore: vi.fn(() => ({
    currentConversation: { id: 'session-1', title: 'Test Session' },
    getUserConversations: vi.fn(() => []),
    selectConversation: vi.fn(),
    createConversation: vi.fn(),
    deleteConversation: vi.fn(),
    updateConversationTitle: vi.fn(),
  })),
  useDeepResearch: vi.fn(() => ({
    isResearching: false,
    connect: vi.fn(),
    disconnect: vi.fn(),
    cancel: vi.fn(),
  })),
  NoSourcesBanner: () => <div data-testid="no-sources-banner">No Sources Banner</div>,
}))

// Mock the layout store
vi.mock('../store', () => ({
  useLayoutStore: vi.fn(() => ({
    rightPanel: null,
    isSessionsPanelOpen: false,
    setSessionsPanelOpen: vi.fn(),
    enabledDataSourceIds: ['source-1', 'source-2'],
  })),
}))

// Mock child components
vi.mock('./AppBar', () => ({
  AppBar: ({ sessionTitle }: { sessionTitle: string }) => (
    <div data-testid="app-bar">{sessionTitle}</div>
  ),
}))

vi.mock('./SessionsPanel', () => ({
  SessionsPanel: () => <div data-testid="sessions-panel">Sessions Panel</div>,
}))

vi.mock('./ChatArea', () => ({
  ChatArea: () => <div data-testid="chat-area">Chat Area</div>,
}))

vi.mock('./InputArea', () => ({
  InputArea: () => <div data-testid="input-area">Input Area</div>,
}))

vi.mock('./ResearchPanel', () => ({
  ResearchPanel: () => <div data-testid="research-panel">Research Panel</div>,
}))

vi.mock('./DataSourcesPanel', () => ({
  DataSourcesPanel: () => <div data-testid="data-sources-panel">Data Sources Panel</div>,
}))

vi.mock('./SettingsPanel', () => ({
  SettingsPanel: () => <div data-testid="settings-panel">Settings Panel</div>,
}))

import { useChatStore } from '@/features/chat'
import { useLayoutStore } from '../store'

describe('MainLayout', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  test('renders all main sections', () => {
    render(<MainLayout />)

    expect(screen.getByTestId('app-bar')).toBeInTheDocument()
    expect(screen.getByTestId('sessions-panel')).toBeInTheDocument()
    expect(screen.getByTestId('chat-area')).toBeInTheDocument()
    expect(screen.getByTestId('input-area')).toBeInTheDocument()
    expect(screen.getByTestId('research-panel')).toBeInTheDocument()
    expect(screen.getByTestId('data-sources-panel')).toBeInTheDocument()
    expect(screen.getByTestId('settings-panel')).toBeInTheDocument()
  })

  test('passes session title to AppBar', () => {
    render(<MainLayout />)

    expect(screen.getByTestId('app-bar')).toHaveTextContent('Test Session')
  })

  test('shows "New Session" when no current conversation', () => {
    vi.mocked(useChatStore).mockReturnValue({
      currentConversation: null,
      getUserConversations: vi.fn(() => []),
      selectConversation: vi.fn(),
      createConversation: vi.fn(),
      deleteConversation: vi.fn(),
      updateConversationTitle: vi.fn(),
    } as unknown as ReturnType<typeof useChatStore>)

    render(<MainLayout />)

    expect(screen.getByTestId('app-bar')).toHaveTextContent('New Session')
  })

  test('passes auth state to components', () => {
    const onSignIn = vi.fn()
    const onSignOut = vi.fn()
    const user = { name: 'Test User', email: 'test@example.com' }

    render(
      <MainLayout isAuthenticated={true} user={user} onSignIn={onSignIn} onSignOut={onSignOut} />
    )

    // Components render - props are passed to mocked child components
    expect(screen.getByTestId('app-bar')).toBeInTheDocument()
    expect(screen.getByTestId('chat-area')).toBeInTheDocument()
    expect(screen.getByTestId('input-area')).toBeInTheDocument()
  })

  test('adjusts chat width when details panel is open', () => {
    vi.mocked(useLayoutStore).mockReturnValue({
      rightPanel: 'research',
      isSessionsPanelOpen: false,
      setSessionsPanelOpen: vi.fn(),
      enabledDataSourceIds: ['source-1', 'source-2'],
    } as unknown as ReturnType<typeof useLayoutStore>)

    const { container } = render(<MainLayout />)

    // The chat container should have 40% width when details panel is open
    const chatContainer = container.querySelector('[style*="width"]')
    expect(chatContainer).toHaveStyle({ width: '40%' })
  })

  test('shows full width when details panel is closed', () => {
    vi.mocked(useLayoutStore).mockReturnValue({
      rightPanel: null,
      isSessionsPanelOpen: false,
      setSessionsPanelOpen: vi.fn(),
      enabledDataSourceIds: ['source-1', 'source-2'],
    } as unknown as ReturnType<typeof useLayoutStore>)

    const { container } = render(<MainLayout />)

    const chatContainer = container.querySelector('[style*="width"]')
    expect(chatContainer).toHaveStyle({ width: '100%' })
  })
})

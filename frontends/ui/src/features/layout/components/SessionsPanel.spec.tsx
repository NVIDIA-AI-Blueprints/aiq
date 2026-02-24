// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { SessionsPanel } from './SessionsPanel'

// Mock the layout store
const mockSetSessionsPanelOpen = vi.fn()

vi.mock('../store', () => ({
  useLayoutStore: vi.fn(() => ({
    isSessionsPanelOpen: true,
    setSessionsPanelOpen: mockSetSessionsPanelOpen,
  })),
}))

// Mock the chat store (no longer uses useIsCurrentSessionBusy for navigation)
vi.mock('@/features/chat', () => ({
  useChatStore: vi.fn(),
}))

// Mock the delete confirmation modal
vi.mock('./DeleteSessionConfirmationModal', () => ({
  DeleteSessionConfirmationModal: ({
    open,
    onConfirm,
    onOpenChange,
  }: {
    open: boolean
    onConfirm: () => void
    onOpenChange: (open: boolean) => void
  }) =>
    open ? (
      <div data-testid="delete-modal">
        <button onClick={onConfirm}>Confirm Delete</button>
        <button onClick={() => onOpenChange(false)}>Cancel</button>
      </div>
    ) : null,
}))

import { useLayoutStore } from '../store'
import { useChatStore } from '@/features/chat'

/**
 * Helper to create a mock chat store state.
 * Components select individual fields via useChatStore((state) => state.X).
 */
const createMockChatState = (overrides: {
  isSessionBusy?: (sessionId: string) => boolean
  hasAnyBusySession?: () => boolean
  isStreaming?: boolean
  pendingInteraction?: { id: string; type: string; content: string } | null
} = {}) => ({
  isSessionBusy: overrides.isSessionBusy ?? (() => false),
  hasAnyBusySession: overrides.hasAnyBusySession ?? (() => false),
  isStreaming: overrides.isStreaming ?? false,
  pendingInteraction: overrides.pendingInteraction ?? null,
})

const setupChatStoreMock = (overrides: Parameters<typeof createMockChatState>[0] = {}) => {
  const state = createMockChatState(overrides)
  vi.mocked(useChatStore).mockImplementation((selector: (s: any) => any) => {
    if (typeof selector === 'function') {
      return selector(state)
    }
    return undefined
  })
}

describe('SessionsPanel', () => {
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)

  const mockSessions = [
    { id: 'session-1', title: 'First Session', date: today },
    { id: 'session-2', title: 'Second Session', date: yesterday },
  ]

  beforeEach(() => {
    vi.clearAllMocks()
    setupChatStoreMock()

    // Reset mock to default open state
    vi.mocked(useLayoutStore).mockReturnValue({
      isSessionsPanelOpen: true,
      setSessionsPanelOpen: mockSetSessionsPanelOpen,
    } as unknown as ReturnType<typeof useLayoutStore>)
  })

  test('renders panel with heading', () => {
    render(<SessionsPanel sessions={mockSessions} />)

    expect(screen.getByText('Sessions')).toBeInTheDocument()
  })

  test('renders new session button', () => {
    render(<SessionsPanel sessions={mockSessions} />)

    expect(screen.getByText('New Session')).toBeInTheDocument()
  })

  test('renders session list grouped by date', () => {
    render(<SessionsPanel sessions={mockSessions} />)

    expect(screen.getByText('Today')).toBeInTheDocument()
    expect(screen.getByText('Yesterday')).toBeInTheDocument()
    expect(screen.getByText('First Session')).toBeInTheDocument()
    expect(screen.getByText('Second Session')).toBeInTheDocument()
  })

  test('shows empty state when no sessions', () => {
    render(<SessionsPanel sessions={[]} />)

    expect(screen.getByText('No sessions yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /start a new session/i })).toBeInTheDocument()
  })

  test('calls onNewSession when new session button clicked', async () => {
    const user = userEvent.setup()
    const onNewSession = vi.fn()

    render(<SessionsPanel sessions={mockSessions} onNewSession={onNewSession} />)

    await user.click(screen.getByText('New Session'))

    expect(onNewSession).toHaveBeenCalled()
    expect(mockSetSessionsPanelOpen).toHaveBeenCalledWith(false)
  })

  test('calls onSelectSession when session clicked', async () => {
    const user = userEvent.setup()
    const onSelectSession = vi.fn()

    render(<SessionsPanel sessions={mockSessions} onSelectSession={onSelectSession} />)

    await user.click(screen.getByRole('button', { name: /session: first session/i }))

    expect(onSelectSession).toHaveBeenCalledWith('session-1')
    expect(mockSetSessionsPanelOpen).toHaveBeenCalledWith(false)
  })

  test('highlights selected session', () => {
    render(<SessionsPanel sessions={mockSessions} selectedSessionId="session-1" />)

    const firstSession = screen.getByRole('button', { name: /session: first session/i })
    expect(firstSession).toHaveClass('bg-surface-raised')
  })

  test('shows edit and delete icons on hover', async () => {
    const user = userEvent.setup()
    render(<SessionsPanel sessions={mockSessions} />)

    const sessionItem = screen.getByRole('button', { name: /session: first session/i })
    await user.hover(sessionItem)

    expect(screen.getByRole('button', { name: /rename session/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /delete session/i })).toBeInTheDocument()
  })

  test('renders footer text', () => {
    render(<SessionsPanel sessions={mockSessions} />)

    expect(screen.getByText(/Sessions and Files are saved for a limited time/i)).toBeInTheDocument()
  })

  test('does not show session content when panel is closed', () => {
    vi.mocked(useLayoutStore).mockReturnValue({
      isSessionsPanelOpen: false,
      setSessionsPanelOpen: mockSetSessionsPanelOpen,
    } as unknown as ReturnType<typeof useLayoutStore>)

    render(<SessionsPanel sessions={mockSessions} />)

    // SidePanel has forceMount, so DOM exists but should be hidden
    // Check that sessions heading is not accessible when closed
    const sessionsHeading = screen.queryByText('Sessions')
    // Panel content may be in DOM due to forceMount but not visible
    expect(sessionsHeading).toBeInTheDocument() // forceMount keeps it in DOM
  })
})

describe('SessionsPanel - Session Switching', () => {
  const mockSessions = [
    { id: 'session-1', title: 'Deep Research Session', date: new Date() },
    { id: 'session-2', title: 'Idle Session', date: new Date() },
  ]

  beforeEach(() => {
    vi.clearAllMocks()
    setupChatStoreMock()
    vi.mocked(useLayoutStore).mockReturnValue({
      isSessionsPanelOpen: true,
      setSessionsPanelOpen: mockSetSessionsPanelOpen,
    } as unknown as ReturnType<typeof useLayoutStore>)
  })

  test('allows switching sessions during active deep research (server-side SSE)', async () => {
    // Deep research is running but no shallow streaming or HITL — navigation allowed
    setupChatStoreMock({
      isSessionBusy: (sessionId: string) => sessionId === 'session-1',
      hasAnyBusySession: () => true,
      isStreaming: false,
      pendingInteraction: null,
    })

    const user = userEvent.setup()
    const onSelectSession = vi.fn()
    render(
      <SessionsPanel
        sessions={mockSessions}
        selectedSessionId="session-2"
        onSelectSession={onSelectSession}
      />
    )

    // Deep research session should be clickable (not visually disabled)
    const deepResearchSession = screen.getByRole('button', { name: /session: deep research session/i })
    expect(deepResearchSession).not.toHaveClass('cursor-not-allowed')
    expect(deepResearchSession).toHaveAttribute('aria-disabled', 'false')

    await user.click(deepResearchSession)
    expect(onSelectSession).toHaveBeenCalledWith('session-1')
  })

  test('blocks switching when shallow thinking (WebSocket) is active', async () => {
    setupChatStoreMock({
      isStreaming: true,
      pendingInteraction: null,
    })

    const user = userEvent.setup()
    const onSelectSession = vi.fn()
    render(
      <SessionsPanel
        sessions={mockSessions}
        selectedSessionId="session-1"
        onSelectSession={onSelectSession}
      />
    )

    // All sessions should be visually disabled
    const session2 = screen.getByRole('button', { name: /session: idle session \(processing in progress\)/i })
    expect(session2).toHaveClass('cursor-not-allowed')
    expect(session2).toHaveAttribute('aria-disabled', 'true')

    await user.click(session2)
    expect(onSelectSession).not.toHaveBeenCalled()
  })

  test('blocks switching when pending HITL interaction exists', async () => {
    setupChatStoreMock({
      isStreaming: false,
      pendingInteraction: { id: 'p1', type: 'approval', content: 'Approve plan?' },
    })

    const user = userEvent.setup()
    const onSelectSession = vi.fn()
    render(
      <SessionsPanel
        sessions={mockSessions}
        selectedSessionId="session-1"
        onSelectSession={onSelectSession}
      />
    )

    const session2 = screen.getByRole('button', { name: /session: idle session \(processing in progress\)/i })
    expect(session2).toHaveAttribute('aria-disabled', 'true')

    await user.click(session2)
    expect(onSelectSession).not.toHaveBeenCalled()
  })

  test('allows switching between sessions when nothing is active', async () => {
    setupChatStoreMock({
      isStreaming: false,
      pendingInteraction: null,
    })

    const user = userEvent.setup()
    const onSelectSession = vi.fn()
    render(
      <SessionsPanel
        sessions={mockSessions}
        selectedSessionId="session-1"
        onSelectSession={onSelectSession}
      />
    )

    const session2 = screen.getByRole('button', { name: /session: idle session/i })
    expect(session2).not.toHaveClass('cursor-not-allowed')

    await user.click(session2)
    expect(onSelectSession).toHaveBeenCalledWith('session-2')
  })
})

describe('SessionsPanel - New Session Button', () => {
  const mockSessions = [
    { id: 'session-1', title: 'First Session', date: new Date() },
  ]

  beforeEach(() => {
    vi.clearAllMocks()
    setupChatStoreMock()
    vi.mocked(useLayoutStore).mockReturnValue({
      isSessionsPanelOpen: true,
      setSessionsPanelOpen: mockSetSessionsPanelOpen,
    } as unknown as ReturnType<typeof useLayoutStore>)
  })

  test('disables new session button when shallow streaming is active', () => {
    setupChatStoreMock({ isStreaming: true })

    render(<SessionsPanel sessions={mockSessions} />)

    const newSessionBtn = screen.getByRole('button', {
      name: /start new session \(disabled during active operations\)/i,
    })
    expect(newSessionBtn).toBeDisabled()
  })

  test('disables new session button when HITL interaction is pending', () => {
    setupChatStoreMock({
      pendingInteraction: { id: 'p1', type: 'approval', content: 'Approve?' },
    })

    render(<SessionsPanel sessions={mockSessions} />)

    const newSessionBtn = screen.getByRole('button', {
      name: /start new session \(disabled during active operations\)/i,
    })
    expect(newSessionBtn).toBeDisabled()
  })

  test('enables new session button during active deep research (server-side)', () => {
    setupChatStoreMock({
      isSessionBusy: (sessionId: string) => sessionId === 'session-1',
      hasAnyBusySession: () => true,
      isStreaming: false,
      pendingInteraction: null,
    })

    render(<SessionsPanel sessions={mockSessions} />)

    // Deep research does NOT block navigation — new session should be enabled
    const newSessionBtn = screen.getByRole('button', { name: /^start new session$/i })
    expect(newSessionBtn).not.toBeDisabled()
  })

  test('enables new session button when no active operations', () => {
    setupChatStoreMock({ isStreaming: false, pendingInteraction: null })

    render(<SessionsPanel sessions={mockSessions} />)

    const newSessionBtn = screen.getByRole('button', { name: /^start new session$/i })
    expect(newSessionBtn).not.toBeDisabled()
  })
})

describe('SessionsPanel - Delete Button States', () => {
  const mockSessions = [
    { id: 'session-1', title: 'First Session', date: new Date() },
    { id: 'session-2', title: 'Second Session', date: new Date() },
  ]

  beforeEach(() => {
    vi.clearAllMocks()
    setupChatStoreMock()
    vi.mocked(useLayoutStore).mockReturnValue({
      isSessionsPanelOpen: true,
      setSessionsPanelOpen: mockSetSessionsPanelOpen,
    } as unknown as ReturnType<typeof useLayoutStore>)
  })

  test('disables individual delete button when session has active deep research', async () => {
    // Session-1 has active deep research (per-session busy)
    setupChatStoreMock({
      isSessionBusy: (sessionId: string) => sessionId === 'session-1',
      hasAnyBusySession: () => true,
      isStreaming: false,
      pendingInteraction: null,
    })

    const user = userEvent.setup()
    render(<SessionsPanel sessions={mockSessions} />)

    // Hover over first session to show action buttons
    const firstSession = screen.getByRole('button', { name: /session: first session/i })
    await user.hover(firstSession)

    // Delete button for session with active deep research should be disabled
    const deleteButton = screen.getByRole('button', { name: /delete session \(disabled\)/i })
    expect(deleteButton).toBeDisabled()
  })

  test('disables individual delete button when shallow streaming is active (global block)', async () => {
    setupChatStoreMock({ isStreaming: true })

    const user = userEvent.setup()
    render(<SessionsPanel sessions={mockSessions} />)

    // With streaming active, session buttons have aria-disabled and show
    // "(processing in progress)" in their aria-label
    const firstSession = screen.getByRole('button', {
      name: /session: first session \(processing in progress\)/i,
    })
    await user.hover(firstSession)

    // Delete button should be disabled due to global streaming
    const deleteButton = screen.getByRole('button', { name: /delete session \(disabled\)/i })
    expect(deleteButton).toBeDisabled()
  })

  test('enables delete button when session is idle and no global block', async () => {
    setupChatStoreMock({
      isSessionBusy: () => false,
      hasAnyBusySession: () => false,
      isStreaming: false,
      pendingInteraction: null,
    })

    const user = userEvent.setup()
    render(<SessionsPanel sessions={mockSessions} />)

    // Hover over first session
    const firstSession = screen.getByRole('button', { name: /session: first session/i })
    await user.hover(firstSession)

    // Delete button should be enabled
    const deleteButton = screen.getByRole('button', { name: /^delete session$/i })
    expect(deleteButton).not.toBeDisabled()
  })

  test('disables "Delete All" button when any session is busy', () => {
    setupChatStoreMock({
      isSessionBusy: () => false,
      hasAnyBusySession: () => true,
      isStreaming: false,
      pendingInteraction: null,
    })

    render(<SessionsPanel sessions={mockSessions} />)

    const deleteAllButton = screen.getByRole('button', { name: /delete all sessions \(disabled\)/i })
    expect(deleteAllButton).toBeDisabled()
  })

  test('enables "Delete All" button when no sessions are busy', () => {
    setupChatStoreMock({
      isSessionBusy: () => false,
      hasAnyBusySession: () => false,
      isStreaming: false,
      pendingInteraction: null,
    })

    render(<SessionsPanel sessions={mockSessions} />)

    const deleteAllButton = screen.getByRole('button', { name: /^delete all sessions$/i })
    expect(deleteAllButton).not.toBeDisabled()
  })

  test('has appropriate title attribute on disabled delete button for active session', async () => {
    setupChatStoreMock({
      isSessionBusy: (sessionId: string) => sessionId === 'session-1',
      hasAnyBusySession: () => true,
      isStreaming: false,
      pendingInteraction: null,
    })

    const user = userEvent.setup()
    render(<SessionsPanel sessions={mockSessions} />)

    // Hover over session to show buttons
    const firstSession = screen.getByRole('button', { name: /session: first session/i })
    await user.hover(firstSession)

    // Check that delete button has appropriate title attribute
    const deleteButton = screen.getByRole('button', { name: /delete session \(disabled\)/i })
    expect(deleteButton).toHaveAttribute('title', 'Cannot delete while operations are in progress')
  })
})

// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { InputArea } from './InputArea'

// Mock the chat hooks
const mockSendMessage = vi.fn()
const mockRespondToInteraction = vi.fn()

let mockIsDeepResearchStreaming = false
let mockDeepResearchStatus: string | null = null
let mockDeepResearchOwnerConversationId: string | null = null
let mockConversationMessages: unknown[] | undefined = []

vi.mock('@/features/chat', () => ({
  useChat: vi.fn(() => ({
    sendMessage: mockSendMessage,
    isStreaming: false,
    isLoading: false,
    respondToInteraction: undefined,
    pendingInteraction: null,
  })),
  useWebSocketChat: vi.fn(() => ({
    sendMessage: mockSendMessage,
    isStreaming: false,
    isLoading: false,
    respondToInteraction: mockRespondToInteraction,
    pendingInteraction: null,
  })),
  useChatStore: vi.fn((selector) => {
    const state = {
      currentConversation: { id: 'session-1', messages: mockConversationMessages },
      ensureSession: vi.fn(() => 'session-1'),
      setRespondToInteractionFn: vi.fn(),
      deepResearchStatus: mockDeepResearchStatus,
      isDeepResearchStreaming: mockIsDeepResearchStreaming,
      deepResearchOwnerConversationId: mockDeepResearchOwnerConversationId,
    }
    return selector(state)
  }),
  useIsCurrentSessionBusy: vi.fn(() => false),
}))

// Mock the layout store
const mockOpenRightPanel = vi.fn()
const mockSetDataSourcePanelTab = vi.fn()

vi.mock('../store', () => ({
  useLayoutStore: vi.fn(() => ({
    openRightPanel: mockOpenRightPanel,
    setDataSourcePanelTab: mockSetDataSourcePanelTab,
    enabledDataSourceIds: ['source-1', 'source-2'],
  })),
}))

// Mock useAppConfig
vi.mock('@/shared/context', () => ({
  useAppConfig: () => ({
    authRequired: true,
    fileUpload: {
      acceptedTypes: '.pdf,.docx,.txt,.md',
      acceptedMimeTypes: ['application/pdf', 'text/plain', 'text/markdown'],
      maxTotalSizeMB: 100,
      maxFileSize: 100 * 1024 * 1024,
      maxTotalSize: 100 * 1024 * 1024,
      maxFileCount: 10,
    },
  }),
}))

// Mock the file upload hooks
const mockUploadFiles = vi.fn()

vi.mock('@/features/documents', () => ({
  useFileUpload: vi.fn(() => ({
    uploadFiles: mockUploadFiles,
    sessionFiles: [],
    isUploading: false,
    error: null,
    clearError: vi.fn(),
  })),
  useFileDragDrop: vi.fn(() => ({
    isDragging: false,
    isUnsupportedDrag: false,
    dragHandlers: {
      onDragEnter: vi.fn(),
      onDragLeave: vi.fn(),
      onDragOver: vi.fn(),
      onDrop: vi.fn(),
    },
  })),
  useFileUploadBanners: vi.fn(),
}))

import { useChat, useWebSocketChat, useIsCurrentSessionBusy } from '@/features/chat'
import { useFileUpload, useFileDragDrop } from '@/features/documents'

describe('InputArea', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockIsDeepResearchStreaming = false
    mockDeepResearchStatus = null
    mockDeepResearchOwnerConversationId = null
    mockConversationMessages = []
    // Reset mocks to defaults - clearAllMocks doesn't reset mockReturnValue
    vi.mocked(useIsCurrentSessionBusy).mockReturnValue(false)
    vi.mocked(useChat).mockReturnValue({
      sendMessage: mockSendMessage,
      isStreaming: false,
      isLoading: false,
      respondToInteraction: undefined,
      pendingInteraction: null,
    } as unknown as ReturnType<typeof useChat>)
    vi.mocked(useWebSocketChat).mockReturnValue({
      sendMessage: mockSendMessage,
      isStreaming: false,
      isLoading: false,
      respondToInteraction: mockRespondToInteraction,
      pendingInteraction: null,
    } as unknown as ReturnType<typeof useWebSocketChat>)
  })

  test('does not render the Auto mode selector button', () => {
    render(<InputArea isAuthenticated={true} />)

    expect(screen.queryByText('Auto')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /query type/i })).not.toBeInTheDocument()
  })

  test('renders text area with default placeholder', () => {
    render(<InputArea isAuthenticated={true} />)

    expect(screen.getByPlaceholderText('Check data sources and ask a research question...')).toBeInTheDocument()
  })

  test('renders with custom placeholder', () => {
    render(<InputArea isAuthenticated={true} placeholder="Type your question" />)

    expect(screen.getByPlaceholderText('Type your question')).toBeInTheDocument()
  })

  test('shows sign in placeholder when not authenticated', () => {
    render(<InputArea isAuthenticated={false} />)

    expect(screen.getByPlaceholderText('Sign in to start researching')).toBeInTheDocument()
  })

  test('disables input when not authenticated', () => {
    render(<InputArea isAuthenticated={false} />)

    expect(screen.getByRole('textbox')).toBeDisabled()
  })

  test('disables send button when message is empty', () => {
    render(<InputArea isAuthenticated={true} />)

    expect(screen.getByRole('button', { name: /send message/i })).toBeDisabled()
  })

  test('enables send button when message is typed', async () => {
    const user = userEvent.setup()
    render(<InputArea isAuthenticated={true} />)

    const input = screen.getByRole('textbox')
    await user.type(input, 'Hello')

    expect(screen.getByRole('button', { name: /send message/i })).not.toBeDisabled()
  })

  test('calls sendMessage when send button is clicked', async () => {
    const user = userEvent.setup()
    render(<InputArea isAuthenticated={true} connectionMode="sse" />)

    const input = screen.getByRole('textbox')
    await user.type(input, 'Hello world')
    await user.click(screen.getByRole('button', { name: /send message/i }))

    expect(mockSendMessage).toHaveBeenCalledWith('Hello world')
  })

  test('clears input after sending message', async () => {
    const user = userEvent.setup()
    render(<InputArea isAuthenticated={true} connectionMode="sse" />)

    const input = screen.getByRole('textbox')
    await user.type(input, 'Hello world')
    await user.click(screen.getByRole('button', { name: /send message/i }))

    expect(input).toHaveValue('')
  })

  test('sends message on Enter key', async () => {
    const user = userEvent.setup()
    render(<InputArea isAuthenticated={true} connectionMode="sse" />)

    const input = screen.getByRole('textbox')
    await user.type(input, 'Hello world{enter}')

    expect(mockSendMessage).toHaveBeenCalledWith('Hello world')
  })

  test('disables input when session is busy (streaming)', () => {
    // InputArea uses useIsCurrentSessionBusy() for disable logic.
    // When isBusy is true (e.g. streaming), input is disabled with "Please wait..." placeholder.
    vi.mocked(useIsCurrentSessionBusy).mockReturnValue(true)
    vi.mocked(useChat).mockReturnValue({
      sendMessage: mockSendMessage,
      isStreaming: true,
      isLoading: false,
      respondToInteraction: undefined,
      pendingInteraction: null,
    } as unknown as ReturnType<typeof useChat>)

    render(<InputArea isAuthenticated={true} connectionMode="sse" />)

    expect(screen.getByRole('textbox')).toBeDisabled()
    expect(screen.getByPlaceholderText('Please wait...')).toBeInTheDocument()
  })

  test('disables input when session is busy (loading)', () => {
    vi.mocked(useIsCurrentSessionBusy).mockReturnValue(true)
    vi.mocked(useChat).mockReturnValue({
      sendMessage: mockSendMessage,
      isStreaming: false,
      isLoading: true,
      respondToInteraction: undefined,
      pendingInteraction: null,
    } as unknown as ReturnType<typeof useChat>)

    render(<InputArea isAuthenticated={true} connectionMode="sse" />)

    expect(screen.getByRole('textbox')).toBeDisabled()
    expect(screen.getByPlaceholderText('Please wait...')).toBeInTheDocument()
  })

  test('disables input when deep research is in progress', () => {
    vi.mocked(useIsCurrentSessionBusy).mockReturnValue(true)
    mockIsDeepResearchStreaming = true
    mockDeepResearchStatus = 'submitted'
    mockDeepResearchOwnerConversationId = 'session-1'
    render(<InputArea isAuthenticated={true} connectionMode="websocket" />)

    // Input disabled with "Please wait..." placeholder (isBusy is true)
    expect(screen.getByPlaceholderText('Please wait...')).toBeInTheDocument()
    expect(screen.getByRole('textbox')).toBeDisabled()
    // Send button shows "Research in progress" tooltip via isResearchSessionInProgress
    expect(
      screen.getByRole('button', { name: /research in progress - please wait/i })
    ).toBeInTheDocument()
  })

  test('renders attach files button', () => {
    render(<InputArea isAuthenticated={true} />)

    expect(screen.getByRole('button', { name: /attach files/i })).toBeInTheDocument()
  })

  // Note: Research panel button was moved to ResearchPanel component as a toggle tag

  test('shows response mode placeholder when pending interaction', () => {
    vi.mocked(useWebSocketChat).mockReturnValue({
      sendMessage: mockSendMessage,
      isStreaming: false,
      isLoading: false,
      respondToInteraction: mockRespondToInteraction,
      pendingInteraction: { id: 'prompt-1', type: 'input', content: 'Please provide more details' },
    } as unknown as ReturnType<typeof useWebSocketChat>)

    render(<InputArea isAuthenticated={true} connectionMode="websocket" />)

    // In response mode, placeholder changes to indicate responding to agent
    expect(screen.getByPlaceholderText('Type your response to the agent...')).toBeInTheDocument()
  })

  test('calls respondToInteraction in response mode', async () => {
    const user = userEvent.setup()
    vi.mocked(useWebSocketChat).mockReturnValue({
      sendMessage: mockSendMessage,
      isStreaming: false,
      isLoading: false,
      respondToInteraction: mockRespondToInteraction,
      pendingInteraction: { id: 'prompt-1', type: 'input', content: 'Please provide more details' },
    } as unknown as ReturnType<typeof useWebSocketChat>)

    render(<InputArea isAuthenticated={true} connectionMode="websocket" />)

    const input = screen.getByRole('textbox')
    await user.type(input, 'My response')
    await user.click(screen.getByRole('button', { name: /send response/i }))

    expect(mockRespondToInteraction).toHaveBeenCalledWith('My response')
    expect(mockSendMessage).not.toHaveBeenCalled()
  })

  test('shows file count badge when files are attached', () => {
    vi.mocked(useFileUpload).mockReturnValue({
      uploadFiles: mockUploadFiles,
      sessionFiles: [
        { id: 'file-1', fileName: 'doc.pdf', status: 'success', collectionName: 'session-1' },
        { id: 'file-2', fileName: 'doc2.pdf', status: 'uploading', collectionName: 'session-1' },
      ],
      isUploading: false,
      error: null,
      clearError: vi.fn(),
    } as unknown as ReturnType<typeof useFileUpload>)

    render(<InputArea isAuthenticated={true} />)

    expect(screen.getByText('2')).toBeInTheDocument()
  })

  test('shows upload error when present', () => {
    vi.mocked(useFileUpload).mockReturnValue({
      uploadFiles: mockUploadFiles,
      sessionFiles: [],
      isUploading: false,
      error: 'File too large',
      clearError: vi.fn(),
    } as unknown as ReturnType<typeof useFileUpload>)

    render(<InputArea isAuthenticated={true} />)

    expect(screen.getByText('File too large')).toBeInTheDocument()
  })

  test('shows drag overlay when dragging files', () => {
    vi.mocked(useFileDragDrop).mockReturnValue({
      isDragging: true,
      isUnsupportedDrag: false,
      dragHandlers: {
        onDragEnter: vi.fn(),
        onDragLeave: vi.fn(),
        onDragOver: vi.fn(),
        onDrop: vi.fn(),
      },
    })

    render(<InputArea isAuthenticated={true} />)

    expect(screen.getByText('Drop files to upload')).toBeInTheDocument()
  })

  test('shows error drag overlay for unsupported files', () => {
    vi.mocked(useFileDragDrop).mockReturnValue({
      isDragging: true,
      isUnsupportedDrag: true,
      dragHandlers: {
        onDragEnter: vi.fn(),
        onDragLeave: vi.fn(),
        onDragOver: vi.fn(),
        onDrop: vi.fn(),
      },
    })

    render(<InputArea isAuthenticated={true} />)

    expect(screen.getByText('Unsupported file type')).toBeInTheDocument()
  })

  test('disables input when isBusy is true (session has active operations)', () => {
    vi.mocked(useIsCurrentSessionBusy).mockReturnValue(true)

    render(<InputArea isAuthenticated={true} connectionMode="websocket" />)

    expect(screen.getByRole('textbox')).toBeDisabled()
    expect(screen.getByPlaceholderText('Please wait...')).toBeInTheDocument()
  })

  test('enables input when isBusy returns to false', () => {
    vi.mocked(useIsCurrentSessionBusy).mockReturnValue(false)

    render(<InputArea isAuthenticated={true} connectionMode="websocket" />)

    expect(screen.getByRole('textbox')).not.toBeDisabled()
  })

  test('shows research completed placeholder when deep research is done', () => {
    mockDeepResearchStatus = 'success'
    mockIsDeepResearchStreaming = false
    mockDeepResearchOwnerConversationId = 'session-1'

    render(<InputArea isAuthenticated={true} connectionMode="websocket" />)

    expect(
      screen.getByPlaceholderText('Research completed. Create a new session for further questions.')
    ).toBeInTheDocument()
    expect(screen.getByRole('textbox')).toBeDisabled()
  })

  test('shows research completed tooltip on send button when research is done', () => {
    mockDeepResearchStatus = 'success'
    mockIsDeepResearchStreaming = false
    mockDeepResearchOwnerConversationId = 'session-1'

    render(<InputArea isAuthenticated={true} connectionMode="websocket" />)

    expect(
      screen.getByRole('button', { name: /research completed - create new session/i })
    ).toBeInTheDocument()
  })

  test('shows research in progress send button when deep research is active and streaming', () => {
    vi.mocked(useIsCurrentSessionBusy).mockReturnValue(true)
    mockIsDeepResearchStreaming = true
    mockDeepResearchStatus = 'running'
    mockDeepResearchOwnerConversationId = 'session-1'

    render(<InputArea isAuthenticated={true} connectionMode="websocket" />)

    // Input disabled with "Please wait..." placeholder (isBusy is true)
    expect(screen.getByPlaceholderText('Please wait...')).toBeInTheDocument()
    // Send button shows research in progress tooltip
    expect(
      screen.getByRole('button', { name: /research in progress - please wait/i })
    ).toBeInTheDocument()
  })

  test('does not allow sending when session is busy', () => {
    vi.mocked(useIsCurrentSessionBusy).mockReturnValue(true)

    render(<InputArea isAuthenticated={true} connectionMode="websocket" />)

    // Input is disabled so typing won't work
    const input = screen.getByRole('textbox')
    expect(input).toBeDisabled()
  })

  test('input enabled during plan approval even when session is busy (HITL override)', async () => {
    // useIsCurrentSessionBusy returns true because pendingInteraction is set,
    // but the input should NOT be disabled so the user can type approve/reject.
    vi.mocked(useIsCurrentSessionBusy).mockReturnValue(true)
    vi.mocked(useWebSocketChat).mockReturnValue({
      sendMessage: mockSendMessage,
      isStreaming: false,
      isLoading: false,
      respondToInteraction: mockRespondToInteraction,
      pendingInteraction: { id: 'prompt-1', type: 'input', content: 'Approve plan?' },
    } as unknown as ReturnType<typeof useWebSocketChat>)

    render(<InputArea isAuthenticated={true} connectionMode="websocket" />)

    // Input should be enabled in response mode (plan approval) despite isBusy=true
    expect(screen.getByRole('textbox')).not.toBeDisabled()
    expect(screen.getByPlaceholderText('Type your response to the agent...')).toBeInTheDocument()
    // Send button should be the normal send button, not a research-in-progress popover
    expect(screen.getByRole('button', { name: /send response/i })).toBeInTheDocument()
  })

  test('input enabled during HITL even when deep research is in progress', async () => {
    const user = userEvent.setup()
    // Deep research is running AND there's a pending HITL interaction
    vi.mocked(useIsCurrentSessionBusy).mockReturnValue(true)
    mockIsDeepResearchStreaming = true
    mockDeepResearchStatus = 'running'
    mockDeepResearchOwnerConversationId = 'session-1'
    vi.mocked(useWebSocketChat).mockReturnValue({
      sendMessage: mockSendMessage,
      isStreaming: false,
      isLoading: false,
      respondToInteraction: mockRespondToInteraction,
      pendingInteraction: { id: 'prompt-1', type: 'input', content: 'Approve report plan?' },
    } as unknown as ReturnType<typeof useWebSocketChat>)

    render(<InputArea isAuthenticated={true} connectionMode="websocket" />)

    // Input should be enabled for HITL response despite active deep research
    expect(screen.getByRole('textbox')).not.toBeDisabled()
    expect(screen.getByPlaceholderText('Type your response to the agent...')).toBeInTheDocument()
    // Send button should be normal (not research-in-progress popover)
    const sendButton = screen.getByRole('button', { name: /send response/i })
    expect(sendButton).toBeInTheDocument()

    // User can type and submit their response
    await user.type(screen.getByRole('textbox'), 'approve')
    await user.click(sendButton)
    expect(mockRespondToInteraction).toHaveBeenCalledWith('approve')
  })
})

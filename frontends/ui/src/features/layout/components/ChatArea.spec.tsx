// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { render, screen } from '@/test-utils'
import userEvent from '@testing-library/user-event'
import { vi, describe, test, expect, beforeEach } from 'vitest'
import { ChatArea } from './ChatArea'

// Mock the chat store
const mockRespondToPrompt = vi.fn()
const mockDismissErrorCard = vi.fn()
const mockGetThinkingStepsForMessage = vi.fn(() => [])

vi.mock('@/features/chat', () => ({
  useChatStore: vi.fn(() => ({
    currentConversation: { messages: [] },
    isLoading: false,
    isStreaming: false,
    thinkingSteps: [],
    respondToPrompt: mockRespondToPrompt,
    dismissErrorCard: mockDismissErrorCard,
    getThinkingStepsForMessage: mockGetThinkingStepsForMessage,
  })),
  AgentPrompt: ({ content }: { content: string }) => (
    <div data-testid="agent-prompt">{content}</div>
  ),
  AgentResponse: ({ content }: { content: string }) => (
    <div data-testid="agent-response">{content}</div>
  ),
  ErrorBanner: ({ message }: { message: string }) => <div data-testid="error-card">{message}</div>,
  FileUploadBanner: ({ type }: { type: string }) => <div data-testid="file-banner">{type}</div>,
  UserMessage: ({ content }: { content: string }) => (
    <div data-testid="user-message">{content}</div>
  ),
  ChatThinking: () => <div data-testid="chat-thinking">Thinking...</div>,
}))

import { useChatStore } from '@/features/chat'

describe('ChatArea', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  test('renders welcome state when not authenticated', () => {
    render(<ChatArea isAuthenticated={false} />)

    expect(screen.getByText('Welcome to AI-Q')).toBeInTheDocument()
    expect(screen.getByText(/sign in with your account/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in with.*sso/i })).toBeInTheDocument()
  })

  test('renders welcome state when authenticated with no messages', () => {
    render(<ChatArea isAuthenticated={true} />)

    expect(screen.getByText('Welcome to AI-Q')).toBeInTheDocument()
    expect(screen.getByText(/AI-powered research companion/i)).toBeInTheDocument()
  })

  test('calls onSignIn when sign in button clicked', async () => {
    const user = userEvent.setup()
    const onSignIn = vi.fn()

    render(<ChatArea isAuthenticated={false} onSignIn={onSignIn} />)

    await user.click(screen.getByRole('button', { name: /sign in with.*sso/i }))

    expect(onSignIn).toHaveBeenCalled()
  })

  test('renders user messages', () => {
    vi.mocked(useChatStore).mockReturnValue({
      currentConversation: {
        messages: [{ id: 'msg-1', role: 'user', content: 'Hello world', messageType: 'user' }],
      },
      isLoading: false,
      isStreaming: false,
      thinkingSteps: [],
      respondToPrompt: mockRespondToPrompt,
      dismissErrorCard: mockDismissErrorCard,
      getThinkingStepsForMessage: mockGetThinkingStepsForMessage,
    } as unknown as ReturnType<typeof useChatStore>)

    render(<ChatArea isAuthenticated={true} />)

    expect(screen.getByTestId('user-message')).toHaveTextContent('Hello world')
  })

  test('renders status messages', () => {
    vi.mocked(useChatStore).mockReturnValue({
      currentConversation: {
        messages: [
          {
            id: 'msg-1',
            role: 'assistant',
            content: 'Processing...',
            messageType: 'status',
            statusType: 'thinking',
          },
        ],
      },
      isLoading: false,
      isStreaming: false,
      thinkingSteps: [],
      respondToPrompt: mockRespondToPrompt,
      dismissErrorCard: mockDismissErrorCard,
      getThinkingStepsForMessage: mockGetThinkingStepsForMessage,
    } as unknown as ReturnType<typeof useChatStore>)

    render(<ChatArea isAuthenticated={true} />)

    // Status messages render inline with the status type
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  test('renders agent prompts', () => {
    vi.mocked(useChatStore).mockReturnValue({
      currentConversation: {
        messages: [
          {
            id: 'msg-1',
            role: 'assistant',
            content: 'Please provide more details',
            messageType: 'prompt',
            promptType: 'input',
          },
        ],
      },
      isLoading: false,
      isStreaming: false,
      respondToPrompt: mockRespondToPrompt,
      dismissErrorCard: mockDismissErrorCard,
    } as unknown as ReturnType<typeof useChatStore>)

    render(<ChatArea isAuthenticated={true} />)

    expect(screen.getByTestId('agent-prompt')).toBeInTheDocument()
  })

  test('renders agent responses', () => {
    vi.mocked(useChatStore).mockReturnValue({
      currentConversation: {
        messages: [
          {
            id: 'msg-1',
            role: 'assistant',
            content: 'Here is your answer',
            messageType: 'agent_response',
          },
        ],
      },
      isLoading: false,
      isStreaming: false,
      respondToPrompt: mockRespondToPrompt,
      dismissErrorCard: mockDismissErrorCard,
    } as unknown as ReturnType<typeof useChatStore>)

    render(<ChatArea isAuthenticated={true} />)

    expect(screen.getByTestId('agent-response')).toHaveTextContent('Here is your answer')
  })

  test('renders file messages', () => {
    vi.mocked(useChatStore).mockReturnValue({
      currentConversation: {
        messages: [
          {
            id: 'msg-1',
            role: 'assistant',
            content: '',
            messageType: 'file',
            fileData: {
              fileName: 'document.pdf',
              fileSize: 1024,
              fileStatus: 'success',
            },
          },
        ],
      },
      isLoading: false,
      isStreaming: false,
      thinkingSteps: [],
      respondToPrompt: mockRespondToPrompt,
      dismissErrorCard: mockDismissErrorCard,
      getThinkingStepsForMessage: mockGetThinkingStepsForMessage,
    } as unknown as ReturnType<typeof useChatStore>)

    render(<ChatArea isAuthenticated={true} />)

    // File messages render inline with the file name
    expect(screen.getByText(/document\.pdf/)).toBeInTheDocument()
  })

  test('renders error banners', () => {
    vi.mocked(useChatStore).mockReturnValue({
      currentConversation: {
        messages: [
          {
            id: 'msg-1',
            role: 'assistant',
            content: '',
            messageType: 'error',
            errorData: {
              errorCode: 'E001',
              errorMessage: 'Something went wrong',
              isRetryable: true,
            },
          },
        ],
      },
      isLoading: false,
      isStreaming: false,
      thinkingSteps: [],
      respondToPrompt: mockRespondToPrompt,
      dismissErrorCard: mockDismissErrorCard,
      getThinkingStepsForMessage: mockGetThinkingStepsForMessage,
    } as unknown as ReturnType<typeof useChatStore>)

    render(<ChatArea isAuthenticated={true} />)

    expect(screen.getByTestId('error-card')).toBeInTheDocument()
  })

  test('does not render assistant messages (full reports)', () => {
    vi.mocked(useChatStore).mockReturnValue({
      currentConversation: {
        messages: [
          {
            id: 'msg-1',
            role: 'assistant',
            content: 'Full report content',
            messageType: 'assistant',
          },
        ],
      },
      isLoading: false,
      isStreaming: false,
      respondToPrompt: mockRespondToPrompt,
      dismissErrorCard: mockDismissErrorCard,
    } as unknown as ReturnType<typeof useChatStore>)

    render(<ChatArea isAuthenticated={true} />)

    // Should show welcome state since assistant messages are filtered out
    expect(screen.getByText('Welcome to AI-Q')).toBeInTheDocument()
  })

  test('renders chat messages area with aria-label', () => {
    render(<ChatArea isAuthenticated={true} />)

    // The Flex component renders with aria-label
    expect(screen.getByLabelText(/chat messages/i)).toBeInTheDocument()
  })

  test('handles null currentConversation', () => {
    vi.mocked(useChatStore).mockReturnValue({
      currentConversation: null,
      isLoading: false,
      isStreaming: false,
      respondToPrompt: mockRespondToPrompt,
      dismissErrorCard: mockDismissErrorCard,
    } as unknown as ReturnType<typeof useChatStore>)

    render(<ChatArea isAuthenticated={true} />)

    // Should render welcome state
    expect(screen.getByText('Welcome to AI-Q')).toBeInTheDocument()
  })

  test('renders file upload banners', () => {
    vi.mocked(useChatStore).mockReturnValue({
      currentConversation: {
        messages: [
          {
            id: 'msg-1',
            role: 'assistant',
            content: '',
            messageType: 'file_upload_status',
            fileUploadStatusData: {
              type: 'uploaded',
              fileCount: 2,
            },
          },
        ],
      },
      isLoading: false,
      isStreaming: false,
      respondToPrompt: mockRespondToPrompt,
      dismissErrorCard: mockDismissErrorCard,
    } as unknown as ReturnType<typeof useChatStore>)

    render(<ChatArea isAuthenticated={true} />)

    expect(screen.getByTestId('file-banner')).toBeInTheDocument()
  })
})

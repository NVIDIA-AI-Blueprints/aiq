// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Tests for chat store session busy selectors
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { useChatStore, selectHasConnectionError } from './store'
import type { Conversation, ChatMessage } from './types'

describe('ChatStore - Session Busy Selectors', () => {
  beforeEach(() => {
    // Reset store to initial state
    useChatStore.setState({
      conversations: [],
      currentConversation: null,
      isStreaming: false,
      isDeepResearchStreaming: false,
      deepResearchStatus: null,
      deepResearchOwnerConversationId: null,
      pendingInteraction: null,
    })
  })

  describe('isSessionBusy', () => {
    it('returns false when session has no active operations', () => {
      const conversation: Conversation = {
        id: 'session-1',
        userId: 'user-1',
        title: 'Test Session',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        conversations: [conversation],
        currentConversation: null,
        isStreaming: false,
        isDeepResearchStreaming: false,
        deepResearchStatus: null,
        deepResearchOwnerConversationId: null,
      })

      const { isSessionBusy } = useChatStore.getState()
      expect(isSessionBusy('session-1')).toBe(false)
    })

    it('returns true when session is the current session with active shallow thinking', () => {
      const conversation: Conversation = {
        id: 'session-1',
        userId: 'user-1',
        title: 'Test Session',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        conversations: [conversation],
        currentConversation: conversation,
        isStreaming: true,
        isDeepResearchStreaming: false,
        deepResearchStatus: null,
        deepResearchOwnerConversationId: null,
      })

      const { isSessionBusy } = useChatStore.getState()
      expect(isSessionBusy('session-1')).toBe(true)
    })

    it('returns true when session has active deep research stream', () => {
      const conversation: Conversation = {
        id: 'session-1',
        userId: 'user-1',
        title: 'Test Session',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        conversations: [conversation],
        currentConversation: conversation,
        isStreaming: false,
        isDeepResearchStreaming: true,
        deepResearchStatus: 'running',
        deepResearchOwnerConversationId: 'session-1',
      })

      const { isSessionBusy } = useChatStore.getState()
      expect(isSessionBusy('session-1')).toBe(true)
    })

    it('returns true when background session has running deep research job (via message history)', () => {
      const message: ChatMessage = {
        id: 'msg-1',
        role: 'assistant',
        content: 'Research started',
        messageType: 'agent_response',
        timestamp: new Date(),
        deepResearchJobId: 'job-123',
        deepResearchJobStatus: 'running',
        isDeepResearchActive: true,
      }

      const conversation: Conversation = {
        id: 'session-background',
        userId: 'user-1',
        title: 'Background Session',
        messages: [message],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      const currentConversation: Conversation = {
        id: 'session-current',
        userId: 'user-1',
        title: 'Current Session',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        conversations: [conversation, currentConversation],
        currentConversation: currentConversation,
        isStreaming: false,
        isDeepResearchStreaming: false,
        deepResearchStatus: null,
        deepResearchOwnerConversationId: null,
      })

      const { isSessionBusy } = useChatStore.getState()
      expect(isSessionBusy('session-background')).toBe(true)
    })

    it('returns true when background session has submitted deep research job', () => {
      const message: ChatMessage = {
        id: 'msg-1',
        role: 'assistant',
        content: 'Research started',
        messageType: 'agent_response',
        timestamp: new Date(),
        deepResearchJobId: 'job-123',
        deepResearchJobStatus: 'submitted',
        isDeepResearchActive: true,
      }

      const conversation: Conversation = {
        id: 'session-1',
        userId: 'user-1',
        title: 'Test Session',
        messages: [message],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        conversations: [conversation],
        currentConversation: null,
        isStreaming: false,
        isDeepResearchStreaming: false,
        deepResearchStatus: null,
        deepResearchOwnerConversationId: null,
      })

      const { isSessionBusy } = useChatStore.getState()
      expect(isSessionBusy('session-1')).toBe(true)
    })

    it('returns false when session has completed deep research job (success)', () => {
      const message: ChatMessage = {
        id: 'msg-1',
        role: 'assistant',
        content: 'Research complete',
        messageType: 'agent_response',
        timestamp: new Date(),
        deepResearchJobId: 'job-123',
        deepResearchJobStatus: 'success',
        isDeepResearchActive: false,
      }

      const conversation: Conversation = {
        id: 'session-1',
        userId: 'user-1',
        title: 'Test Session',
        messages: [message],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        conversations: [conversation],
        currentConversation: conversation,
        isStreaming: false,
        isDeepResearchStreaming: false,
        deepResearchStatus: 'success',
        deepResearchOwnerConversationId: null,
      })

      const { isSessionBusy } = useChatStore.getState()
      expect(isSessionBusy('session-1')).toBe(false)
    })

    it('returns false when session has failed deep research job', () => {
      const message: ChatMessage = {
        id: 'msg-1',
        role: 'assistant',
        content: 'Research failed',
        messageType: 'agent_response',
        timestamp: new Date(),
        deepResearchJobId: 'job-123',
        deepResearchJobStatus: 'failure',
        isDeepResearchActive: false,
      }

      const conversation: Conversation = {
        id: 'session-1',
        userId: 'user-1',
        title: 'Test Session',
        messages: [message],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        conversations: [conversation],
        currentConversation: conversation,
        isStreaming: false,
        isDeepResearchStreaming: false,
        deepResearchStatus: 'failure',
        deepResearchOwnerConversationId: null,
      })

      const { isSessionBusy } = useChatStore.getState()
      expect(isSessionBusy('session-1')).toBe(false)
    })

    it('returns false when session has interrupted deep research job', () => {
      const message: ChatMessage = {
        id: 'msg-1',
        role: 'assistant',
        content: 'Research interrupted',
        messageType: 'agent_response',
        timestamp: new Date(),
        deepResearchJobId: 'job-123',
        deepResearchJobStatus: 'interrupted',
        isDeepResearchActive: false,
      }

      const conversation: Conversation = {
        id: 'session-1',
        userId: 'user-1',
        title: 'Test Session',
        messages: [message],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        conversations: [conversation],
        currentConversation: conversation,
        isStreaming: false,
        isDeepResearchStreaming: false,
        deepResearchStatus: 'interrupted',
        deepResearchOwnerConversationId: null,
      })

      const { isSessionBusy } = useChatStore.getState()
      expect(isSessionBusy('session-1')).toBe(false)
    })

    it('checks most recent agent_response message for job status', () => {
      const oldMessage: ChatMessage = {
        id: 'msg-1',
        role: 'assistant',
        content: 'Old research',
        messageType: 'agent_response',
        timestamp: new Date(Date.now() - 10000),
        deepResearchJobId: 'job-old',
        deepResearchJobStatus: 'running',
      }

      const newMessage: ChatMessage = {
        id: 'msg-2',
        role: 'assistant',
        content: 'New research complete',
        messageType: 'agent_response',
        timestamp: new Date(),
        deepResearchJobId: 'job-new',
        deepResearchJobStatus: 'success',
      }

      const conversation: Conversation = {
        id: 'session-1',
        userId: 'user-1',
        title: 'Test Session',
        messages: [oldMessage, newMessage],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        conversations: [conversation],
        currentConversation: null,
        isStreaming: false,
        isDeepResearchStreaming: false,
        deepResearchStatus: null,
        deepResearchOwnerConversationId: null,
      })

      const { isSessionBusy } = useChatStore.getState()
      // Should be false because the most recent message with job ID has 'success' status
      expect(isSessionBusy('session-1')).toBe(false)
    })
  })

  describe('hasAnyBusySession', () => {
    it('returns false when no sessions have active operations', () => {
      const conversation1: Conversation = {
        id: 'session-1',
        userId: 'user-1',
        title: 'Session 1',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      const conversation2: Conversation = {
        id: 'session-2',
        userId: 'user-1',
        title: 'Session 2',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        conversations: [conversation1, conversation2],
        currentConversation: null,
        isStreaming: false,
        isDeepResearchStreaming: false,
        deepResearchStatus: null,
        deepResearchOwnerConversationId: null,
      })

      const { hasAnyBusySession } = useChatStore.getState()
      expect(hasAnyBusySession()).toBe(false)
    })

    it('returns true when at least one session has active operations', () => {
      const message: ChatMessage = {
        id: 'msg-1',
        role: 'assistant',
        content: 'Research running',
        messageType: 'agent_response',
        timestamp: new Date(),
        deepResearchJobId: 'job-123',
        deepResearchJobStatus: 'running',
      }

      const busyConversation: Conversation = {
        id: 'session-busy',
        userId: 'user-1',
        title: 'Busy Session',
        messages: [message],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      const idleConversation: Conversation = {
        id: 'session-idle',
        userId: 'user-1',
        title: 'Idle Session',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        conversations: [busyConversation, idleConversation],
        currentConversation: idleConversation,
        isStreaming: false,
        isDeepResearchStreaming: false,
        deepResearchStatus: null,
        deepResearchOwnerConversationId: null,
      })

      const { hasAnyBusySession } = useChatStore.getState()
      expect(hasAnyBusySession()).toBe(true)
    })

    it('returns true when current session is streaming (shallow thinking)', () => {
      const conversation: Conversation = {
        id: 'session-1',
        userId: 'user-1',
        title: 'Test Session',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        conversations: [conversation],
        currentConversation: conversation,
        isStreaming: true,
        isDeepResearchStreaming: false,
        deepResearchStatus: null,
        deepResearchOwnerConversationId: null,
      })

      const { hasAnyBusySession } = useChatStore.getState()
      expect(hasAnyBusySession()).toBe(true)
    })

    it('returns true when pendingInteraction is set (HITL prompt awaiting response)', () => {
      const conversation: Conversation = {
        id: 'session-1',
        userId: 'user-1',
        title: 'Session 1',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        conversations: [conversation],
        currentConversation: conversation,
        isStreaming: false,
        isDeepResearchStreaming: false,
        deepResearchStatus: null,
        deepResearchOwnerConversationId: null,
        pendingInteraction: {
          id: 'prompt-1',
          parentId: 'msg-1',
          inputType: 'approval',
          text: 'Do you approve this research plan?',
        } as any,
      })

      const { hasAnyBusySession } = useChatStore.getState()
      expect(hasAnyBusySession()).toBe(true)
    })

    it('returns false when all sessions have terminal job statuses', () => {
      const message1: ChatMessage = {
        id: 'msg-1',
        role: 'assistant',
        content: 'Research complete',
        messageType: 'agent_response',
        timestamp: new Date(),
        deepResearchJobId: 'job-1',
        deepResearchJobStatus: 'success',
      }

      const message2: ChatMessage = {
        id: 'msg-2',
        role: 'assistant',
        content: 'Research failed',
        messageType: 'agent_response',
        timestamp: new Date(),
        deepResearchJobId: 'job-2',
        deepResearchJobStatus: 'failure',
      }

      const conversation1: Conversation = {
        id: 'session-1',
        userId: 'user-1',
        title: 'Session 1',
        messages: [message1],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      const conversation2: Conversation = {
        id: 'session-2',
        userId: 'user-1',
        title: 'Session 2',
        messages: [message2],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        conversations: [conversation1, conversation2],
        currentConversation: null,
        isStreaming: false,
        isDeepResearchStreaming: false,
        deepResearchStatus: null,
        deepResearchOwnerConversationId: null,
      })

      const { hasAnyBusySession } = useChatStore.getState()
      expect(hasAnyBusySession()).toBe(false)
    })
  })

  describe('Edge Cases', () => {
    it('handles session not found in conversations list', () => {
      useChatStore.setState({
        conversations: [],
        currentConversation: null,
        isStreaming: false,
        isDeepResearchStreaming: false,
        deepResearchStatus: null,
        deepResearchOwnerConversationId: null,
      })

      const { isSessionBusy } = useChatStore.getState()
      expect(isSessionBusy('non-existent-session')).toBe(false)
    })

    it('handles session with no messages', () => {
      const conversation: Conversation = {
        id: 'session-1',
        userId: 'user-1',
        title: 'Empty Session',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        conversations: [conversation],
        currentConversation: null,
        isStreaming: false,
        isDeepResearchStreaming: false,
        deepResearchStatus: null,
        deepResearchOwnerConversationId: null,
      })

      const { isSessionBusy } = useChatStore.getState()
      expect(isSessionBusy('session-1')).toBe(false)
    })

    it('handles session with messages but no deep research jobs', () => {
      const userMessage: ChatMessage = {
        id: 'msg-1',
        role: 'user',
        content: 'Hello',
        messageType: 'user',
        timestamp: new Date(),
      }

      const agentMessage: ChatMessage = {
        id: 'msg-2',
        role: 'assistant',
        content: 'Hello back',
        messageType: 'agent_response',
        timestamp: new Date(),
      }

      const conversation: Conversation = {
        id: 'session-1',
        userId: 'user-1',
        title: 'Test Session',
        messages: [userMessage, agentMessage],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        conversations: [conversation],
        currentConversation: conversation,
        isStreaming: false,
        isDeepResearchStreaming: false,
        deepResearchStatus: null,
        deepResearchOwnerConversationId: null,
      })

      const { isSessionBusy } = useChatStore.getState()
      expect(isSessionBusy('session-1')).toBe(false)
    })

    it('prioritizes ephemeral state over message history for current session', () => {
      // Current session with ephemeral streaming state, but messages show completed job
      const message: ChatMessage = {
        id: 'msg-1',
        role: 'assistant',
        content: 'Research complete',
        messageType: 'agent_response',
        timestamp: new Date(),
        deepResearchJobId: 'job-old',
        deepResearchJobStatus: 'success',
      }

      const conversation: Conversation = {
        id: 'session-1',
        userId: 'user-1',
        title: 'Test Session',
        messages: [message],
        createdAt: new Date(),
        updatedAt: new Date(),
      }

      useChatStore.setState({
        conversations: [conversation],
        currentConversation: conversation,
        isStreaming: true, // Currently streaming shallow thinking
        isDeepResearchStreaming: false,
        deepResearchStatus: null,
        deepResearchOwnerConversationId: null,
      })

      const { isSessionBusy } = useChatStore.getState()
      // Should return true because of ephemeral isStreaming, not because of message status
      expect(isSessionBusy('session-1')).toBe(true)
    })
  })
})

describe('selectHasConnectionError', () => {
  beforeEach(() => {
    useChatStore.setState({
      conversations: [],
      currentConversation: null,
    })
  })

  it('returns false when no conversation exists', () => {
    expect(selectHasConnectionError(useChatStore.getState())).toBe(false)
  })

  it('returns false when conversation has no error messages', () => {
    const conversation: Conversation = {
      id: 'conv-1',
      userId: 'user-1',
      title: 'Test',
      messages: [
        { id: 'm1', role: 'user', content: 'Hello', timestamp: new Date(), messageType: 'user' } as ChatMessage,
      ],
      createdAt: new Date(),
      updatedAt: new Date(),
    }

    useChatStore.setState({ currentConversation: conversation })
    expect(selectHasConnectionError(useChatStore.getState())).toBe(false)
  })

  it('returns true when conversation has a connection.failed error', () => {
    const conversation: Conversation = {
      id: 'conv-1',
      userId: 'user-1',
      title: 'Test',
      messages: [
        {
          id: 'err-1',
          role: 'assistant',
          content: 'Connection failed',
          timestamp: new Date(),
          messageType: 'error',
          errorData: { errorCode: 'connection.failed' },
        } as ChatMessage,
      ],
      createdAt: new Date(),
      updatedAt: new Date(),
    }

    useChatStore.setState({ currentConversation: conversation })
    expect(selectHasConnectionError(useChatStore.getState())).toBe(true)
  })

  it('returns true for any connection.* error code', () => {
    const conversation: Conversation = {
      id: 'conv-1',
      userId: 'user-1',
      title: 'Test',
      messages: [
        {
          id: 'err-1',
          role: 'assistant',
          content: 'Connection lost',
          timestamp: new Date(),
          messageType: 'error',
          errorData: { errorCode: 'connection.lost' },
        } as ChatMessage,
      ],
      createdAt: new Date(),
      updatedAt: new Date(),
    }

    useChatStore.setState({ currentConversation: conversation })
    expect(selectHasConnectionError(useChatStore.getState())).toBe(true)
  })

  it('returns false for non-connection errors (agent, system)', () => {
    const conversation: Conversation = {
      id: 'conv-1',
      userId: 'user-1',
      title: 'Test',
      messages: [
        {
          id: 'err-1',
          role: 'assistant',
          content: 'Agent error',
          timestamp: new Date(),
          messageType: 'error',
          errorData: { errorCode: 'agent.response_failed' },
        } as ChatMessage,
      ],
      createdAt: new Date(),
      updatedAt: new Date(),
    }

    useChatStore.setState({ currentConversation: conversation })
    expect(selectHasConnectionError(useChatStore.getState())).toBe(false)
  })
})

describe('dismissConnectionErrors', () => {
  beforeEach(() => {
    useChatStore.setState({
      conversations: [],
      currentConversation: null,
    })
  })

  it('removes all connection.* error messages from current conversation', () => {
    const conversation: Conversation = {
      id: 'conv-1',
      userId: 'user-1',
      title: 'Test',
      messages: [
        { id: 'm1', role: 'user', content: 'Hello', timestamp: new Date(), messageType: 'user' } as ChatMessage,
        {
          id: 'err-1',
          role: 'assistant',
          content: 'Connection failed',
          timestamp: new Date(),
          messageType: 'error',
          errorData: { errorCode: 'connection.failed' },
        } as ChatMessage,
        {
          id: 'err-2',
          role: 'assistant',
          content: 'Connection lost',
          timestamp: new Date(),
          messageType: 'error',
          errorData: { errorCode: 'connection.lost' },
        } as ChatMessage,
      ],
      createdAt: new Date(),
      updatedAt: new Date(),
    }

    useChatStore.setState({
      conversations: [conversation],
      currentConversation: conversation,
    })

    useChatStore.getState().dismissConnectionErrors()

    const state = useChatStore.getState()
    expect(state.currentConversation!.messages).toHaveLength(1)
    expect(state.currentConversation!.messages[0].id).toBe('m1')
  })

  it('does not remove non-connection error messages', () => {
    const conversation: Conversation = {
      id: 'conv-1',
      userId: 'user-1',
      title: 'Test',
      messages: [
        {
          id: 'err-1',
          role: 'assistant',
          content: 'Connection failed',
          timestamp: new Date(),
          messageType: 'error',
          errorData: { errorCode: 'connection.failed' },
        } as ChatMessage,
        {
          id: 'err-2',
          role: 'assistant',
          content: 'Agent error',
          timestamp: new Date(),
          messageType: 'error',
          errorData: { errorCode: 'agent.response_failed' },
        } as ChatMessage,
      ],
      createdAt: new Date(),
      updatedAt: new Date(),
    }

    useChatStore.setState({
      conversations: [conversation],
      currentConversation: conversation,
    })

    useChatStore.getState().dismissConnectionErrors()

    const state = useChatStore.getState()
    expect(state.currentConversation!.messages).toHaveLength(1)
    expect(state.currentConversation!.messages[0].id).toBe('err-2')
  })

  it('does nothing when no connection errors exist', () => {
    const conversation: Conversation = {
      id: 'conv-1',
      userId: 'user-1',
      title: 'Test',
      messages: [
        { id: 'm1', role: 'user', content: 'Hello', timestamp: new Date(), messageType: 'user' } as ChatMessage,
      ],
      createdAt: new Date(),
      updatedAt: new Date(),
    }

    useChatStore.setState({
      conversations: [conversation],
      currentConversation: conversation,
    })

    useChatStore.getState().dismissConnectionErrors()

    const state = useChatStore.getState()
    expect(state.currentConversation!.messages).toHaveLength(1)
  })

  it('does nothing when no current conversation exists', () => {
    useChatStore.setState({ currentConversation: null })
    // Should not throw
    useChatStore.getState().dismissConnectionErrors()
    expect(useChatStore.getState().currentConversation).toBeNull()
  })

  it('also updates the conversations list', () => {
    const conversation: Conversation = {
      id: 'conv-1',
      userId: 'user-1',
      title: 'Test',
      messages: [
        {
          id: 'err-1',
          role: 'assistant',
          content: 'Connection failed',
          timestamp: new Date(),
          messageType: 'error',
          errorData: { errorCode: 'connection.failed' },
        } as ChatMessage,
      ],
      createdAt: new Date(),
      updatedAt: new Date(),
    }

    useChatStore.setState({
      conversations: [conversation],
      currentConversation: conversation,
    })

    useChatStore.getState().dismissConnectionErrors()

    const state = useChatStore.getState()
    const convInList = state.conversations.find((c) => c.id === 'conv-1')
    expect(convInList!.messages).toHaveLength(0)
  })
})

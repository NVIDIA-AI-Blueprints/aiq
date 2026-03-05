// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, test, expect } from 'vitest'
import { pruneMessageForStorage, capString, stripThinkingStepsForStorage, prunePlanMessages } from './prune-message-for-storage'
import type { ChatMessage } from '../types'

describe('prune-message-for-storage', () => {
  describe('pruneMessageForStorage', () => {
    test('removes heavy refetchable fields', () => {
      const message: ChatMessage = {
        id: 'msg_1',
        role: 'assistant',
        content: 'Test message',
        timestamp: new Date(),
        messageType: 'agent_response',
        // Heavy fields that should be removed
        reportContent: 'Large report content...',
        citations: [{ id: 'c1', url: 'http://example.com', content: 'Citation content', timestamp: new Date(), isCited: true }],
        deepResearchTodos: [{ id: 't1', content: 'Todo item', status: 'pending' }],
        deepResearchLLMSteps: [{ id: 'l1', name: 'gpt-4', content: 'Step', timestamp: new Date(), isComplete: false }],
        deepResearchAgents: [{ id: 'a1', name: 'Agent', startedAt: new Date(), status: 'complete' }],
        deepResearchToolCalls: [{ id: 'tc1', name: 'search', timestamp: new Date(), status: 'complete' }],
        deepResearchFiles: [{ id: 'f1', filename: 'file.txt', content: 'File content', timestamp: new Date() }],
        intermediateSteps: [{ id: 'i1', name: 'Step', status: 'complete', content: 'Content', timestamp: new Date() }],
      }

      const pruned = pruneMessageForStorage(message)

      // Essential fields kept
      expect(pruned.id).toBe('msg_1')
      expect(pruned.role).toBe('assistant')
      expect(pruned.content).toBe('Test message')
      expect(pruned.messageType).toBe('agent_response')

      // Heavy fields removed
      expect(pruned.reportContent).toBeUndefined()
      expect(pruned.citations).toBeUndefined()
      expect(pruned.deepResearchTodos).toBeUndefined()
      expect(pruned.deepResearchLLMSteps).toBeUndefined()
      expect(pruned.deepResearchAgents).toBeUndefined()
      expect(pruned.deepResearchToolCalls).toBeUndefined()
      expect(pruned.deepResearchFiles).toBeUndefined()
      expect(pruned.intermediateSteps).toBeUndefined()
    })

    test('keeps essential UI fields', () => {
      const message: ChatMessage = {
        id: 'msg_2',
        role: 'user',
        content: 'User question',
        timestamp: new Date(),
        messageType: 'user',
        thinkingSteps: [
          {
            id: 'ts1',
            userMessageId: 'msg_2',
            category: 'tools',
            functionName: 'test_function',
            displayName: 'Thinking',
            content: 'Thought process',
            timestamp: new Date(),
            isComplete: true,
          },
        ],
        planMessages: [
          {
            id: 'pm1',
            text: 'Plan message',
            inputType: 'approval',
            timestamp: new Date(),
          },
        ],
        enabledDataSources: ['web_search'],
        messageFiles: [{ id: 'f1', fileName: 'doc.pdf' }],
        deepResearchJobId: 'job_123',
        deepResearchJobStatus: 'success',
      }

      const pruned = pruneMessageForStorage(message)

      expect(pruned.thinkingSteps).toBeDefined()
      expect(pruned.thinkingSteps).toHaveLength(1)
      expect(pruned.planMessages).toBeDefined()
      expect(pruned.planMessages).toHaveLength(1)
      expect(pruned.enabledDataSources).toEqual(['web_search'])
      expect(pruned.messageFiles).toHaveLength(1)
      expect(pruned.deepResearchJobId).toBe('job_123')
      expect(pruned.deepResearchJobStatus).toBe('success')
    })

    test('strips thinking step content and removes deep research steps', () => {
      const message: ChatMessage = {
        id: 'msg_3',
        role: 'user',
        content: 'Question',
        timestamp: new Date(),
        messageType: 'user',
        thinkingSteps: [
          {
            id: 'ts_shallow',
            userMessageId: 'msg_3',
            category: 'tools',
            functionName: 'web_search_tool',
            displayName: 'Web Search',
            content: 'Large content that is never displayed in ChatThinking',
            rawPayload: '{"raw": "payload data"}',
            timestamp: new Date(),
            isComplete: true,
            isDeepResearch: false,
          },
          {
            id: 'ts_deep',
            userMessageId: 'msg_3',
            category: 'agents',
            functionName: 'deep_agent',
            displayName: 'Deep Agent',
            content: 'Deep research content',
            timestamp: new Date(),
            isComplete: true,
            isDeepResearch: true,
          },
        ],
      }

      const pruned = pruneMessageForStorage(message)

      // Deep research step removed entirely
      expect(pruned.thinkingSteps).toHaveLength(1)
      expect(pruned.thinkingSteps![0].id).toBe('ts_shallow')

      // Shallow step content stripped
      expect(pruned.thinkingSteps![0].content).toBe('')
      expect(pruned.thinkingSteps![0].rawPayload).toBeUndefined()

      // Display fields preserved
      expect(pruned.thinkingSteps![0].displayName).toBe('Web Search')
      expect(pruned.thinkingSteps![0].functionName).toBe('web_search_tool')
      expect(pruned.thinkingSteps![0].isTopLevel).toBeUndefined()
    })

    test('caps plan message text during pruning', () => {
      const message: ChatMessage = {
        id: 'msg_4',
        role: 'assistant',
        content: 'Response',
        timestamp: new Date(),
        messageType: 'agent_response',
        planMessages: [
          {
            id: 'pm1',
            text: 'x'.repeat(20000),
            inputType: 'approval',
            timestamp: new Date(),
            userResponse: 'y'.repeat(5000),
          },
        ],
      }

      const pruned = pruneMessageForStorage(message)

      expect(pruned.planMessages![0].text).toHaveLength(10000)
      expect(pruned.planMessages![0].userResponse).toHaveLength(2000)
    })

    test('handles messages without thinkingSteps or planMessages', () => {
      const message: ChatMessage = {
        id: 'msg_5',
        role: 'user',
        content: 'Simple message',
        timestamp: new Date(),
      }

      const pruned = pruneMessageForStorage(message)

      expect(pruned.id).toBe('msg_5')
      expect(pruned.content).toBe('Simple message')
      expect(pruned.thinkingSteps).toBeUndefined()
      expect(pruned.planMessages).toBeUndefined()
    })
  })

  describe('capString', () => {
    test('returns original string if under limit', () => {
      const result = capString('hello', 10)
      expect(result).toBe('hello')
    })

    test('truncates string if over limit', () => {
      const result = capString('hello world', 5)
      expect(result).toBe('hello')
    })

    test('handles empty string', () => {
      const result = capString('', 10)
      expect(result).toBe('')
    })
  })

  describe('stripThinkingStepsForStorage', () => {
    test('removes deep research steps', () => {
      const steps = [
        {
          id: 'ts_shallow',
          userMessageId: 'msg_1',
          category: 'tools' as const,
          functionName: 'web_search',
          displayName: 'Web Search',
          content: 'some content',
          timestamp: new Date(),
          isComplete: true,
          isDeepResearch: false,
        },
        {
          id: 'ts_deep',
          userMessageId: 'msg_1',
          category: 'agents' as const,
          functionName: 'deep_agent',
          displayName: 'Deep Agent',
          content: 'deep content',
          timestamp: new Date(),
          isComplete: true,
          isDeepResearch: true,
        },
      ]

      const stripped = stripThinkingStepsForStorage(steps)

      expect(stripped).toHaveLength(1)
      expect(stripped[0].id).toBe('ts_shallow')
    })

    test('strips content from shallow steps', () => {
      const steps = [
        {
          id: 'ts1',
          userMessageId: 'msg_1',
          category: 'tools' as const,
          functionName: 'test_function',
          displayName: 'Step 1',
          content: 'x'.repeat(10000),
          rawPayload: '{"large": "payload"}',
          timestamp: new Date(),
          isComplete: true,
        },
      ]

      const stripped = stripThinkingStepsForStorage(steps)

      expect(stripped).toHaveLength(1)
      expect(stripped[0].content).toBe('')
      expect(stripped[0].rawPayload).toBeUndefined()
      expect(stripped[0].displayName).toBe('Step 1')
      expect(stripped[0].functionName).toBe('test_function')
    })

    test('preserves display fields', () => {
      const ts = new Date()
      const steps = [
        {
          id: 'ts1',
          userMessageId: 'msg_1',
          category: 'tools' as const,
          functionName: 'search_tool',
          displayName: 'Search Tool',
          content: 'content',
          timestamp: ts,
          isComplete: true,
          isTopLevel: true,
        },
      ]

      const stripped = stripThinkingStepsForStorage(steps)

      expect(stripped[0].id).toBe('ts1')
      expect(stripped[0].userMessageId).toBe('msg_1')
      expect(stripped[0].functionName).toBe('search_tool')
      expect(stripped[0].displayName).toBe('Search Tool')
      expect(stripped[0].timestamp).toBe(ts)
      expect(stripped[0].isComplete).toBe(true)
      expect(stripped[0].isTopLevel).toBe(true)
    })

    test('handles empty array', () => {
      const stripped = stripThinkingStepsForStorage([])
      expect(stripped).toHaveLength(0)
    })
  })

  describe('prunePlanMessages', () => {
    test('caps text content in plan messages', () => {
      const planMessages = [
        {
          id: 'pm1',
          text: 'x'.repeat(20000),
          inputType: 'approval' as const,
          timestamp: new Date(),
        },
      ]

      const pruned = prunePlanMessages(planMessages, 100)

      expect(pruned).toHaveLength(1)
      expect(pruned[0].text).toHaveLength(100)
    })

    test('caps user response content', () => {
      const planMessages = [
        {
          id: 'pm1',
          text: 'Plan text',
          inputType: 'text' as const,
          timestamp: new Date(),
          userResponse: 'x'.repeat(5000),
        },
      ]

      const pruned = prunePlanMessages(planMessages)

      expect(pruned[0].userResponse).toHaveLength(2000)
    })

    test('keeps other plan message fields intact', () => {
      const planMessages = [
        {
          id: 'pm1',
          text: 'Short text',
          inputType: 'multiple_choice' as const,
          timestamp: new Date(),
          placeholder: 'Choose an option',
          required: true,
        },
      ]

      const pruned = prunePlanMessages(planMessages)

      expect(pruned[0].id).toBe('pm1')
      expect(pruned[0].inputType).toBe('multiple_choice')
      expect(pruned[0].placeholder).toBe('Choose an option')
      expect(pruned[0].required).toBe(true)
    })
  })
})

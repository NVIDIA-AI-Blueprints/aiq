// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, test, expect } from 'vitest'
import { pruneMessageForStorage, capString, pruneThinkingSteps, prunePlanMessages } from './prune-message-for-storage'
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

      // Essential fields kept
      expect(pruned.thinkingSteps).toBeDefined()
      expect(pruned.thinkingSteps).toHaveLength(1)
      expect(pruned.planMessages).toBeDefined()
      expect(pruned.planMessages).toHaveLength(1)
      expect(pruned.enabledDataSources).toEqual(['web_search'])
      expect(pruned.messageFiles).toHaveLength(1)
      expect(pruned.deepResearchJobId).toBe('job_123')
      expect(pruned.deepResearchJobStatus).toBe('success')
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

  describe('pruneThinkingSteps', () => {
    test('caps content length in thinking steps', () => {
      const steps = [
        {
          id: 'ts1',
          userMessageId: 'msg_1',
          category: 'tools' as const,
          functionName: 'test_function',
          displayName: 'Step 1',
          content: 'x'.repeat(10000),
          timestamp: new Date(),
          isComplete: true,
        },
      ]

      const pruned = pruneThinkingSteps(steps, 100)

      expect(pruned).toHaveLength(1)
      expect(pruned[0].content).toHaveLength(100)
      expect(pruned[0].displayName).toBe('Step 1')
    })

    test('keeps other step fields intact', () => {
      const steps = [
        {
          id: 'ts1',
          userMessageId: 'msg_1',
          category: 'tools' as const,
          functionName: 'test_function',
          displayName: 'Step 1',
          content: 'Short content',
          timestamp: new Date(),
          isComplete: true,
          isDeepResearch: true,
        },
      ]

      const pruned = pruneThinkingSteps(steps, 5000)

      expect(pruned[0].id).toBe('ts1')
      expect(pruned[0].isDeepResearch).toBe(true)
      expect(pruned[0].isComplete).toBe(true)
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

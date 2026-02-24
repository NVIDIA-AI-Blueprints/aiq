// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, test, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useSessionUrl } from './use-session-url'

// Mock Next.js navigation hooks
const mockRouter = {
  replace: vi.fn(),
  push: vi.fn(),
}

const mockPathname = '/'
let mockSearchParams = new URLSearchParams()

vi.mock('next/navigation', () => ({
  useRouter: () => mockRouter,
  usePathname: () => mockPathname,
  useSearchParams: () => mockSearchParams,
}))

// Mock chat store
const mockChatStore = {
  currentConversation: null as { id: string } | null,
  currentUserId: null as string | null,
  selectConversation: vi.fn(),
  getUserConversations: vi.fn((): Array<{ id: string; title: string }> => []),
}

vi.mock('@/features/chat', () => ({
  useChatStore: () => mockChatStore,
}))

describe('useSessionUrl', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSearchParams = new URLSearchParams()
    mockChatStore.currentConversation = null
    mockChatStore.currentUserId = null
    mockChatStore.getUserConversations.mockReturnValue([])
  })

  describe('initialization', () => {
    test('returns updateSessionUrl and clearSessionUrl functions', () => {
      const { result } = renderHook(() => useSessionUrl({ isAuthenticated: false }))

      expect(result.current.updateSessionUrl).toBeInstanceOf(Function)
      expect(result.current.clearSessionUrl).toBeInstanceOf(Function)
    })
  })

  describe('updateSessionUrl', () => {
    test('adds session parameter to URL', () => {
      const { result } = renderHook(() => useSessionUrl({ isAuthenticated: true }))

      act(() => {
        result.current.updateSessionUrl('session-123')
      })

      expect(mockRouter.replace).toHaveBeenCalledWith('/?session=session-123')
    })

    test('removes session parameter when null', () => {
      mockSearchParams = new URLSearchParams('session=old-session')

      const { result } = renderHook(() => useSessionUrl({ isAuthenticated: true }))

      act(() => {
        result.current.updateSessionUrl(null)
      })

      expect(mockRouter.replace).toHaveBeenCalledWith('/')
    })

    test('preserves other query parameters', () => {
      mockSearchParams = new URLSearchParams('other=param')

      const { result } = renderHook(() => useSessionUrl({ isAuthenticated: true }))

      act(() => {
        result.current.updateSessionUrl('session-123')
      })

      expect(mockRouter.replace).toHaveBeenCalledWith('/?other=param&session=session-123')
    })
  })

  describe('clearSessionUrl', () => {
    test('removes session parameter from URL', () => {
      mockSearchParams = new URLSearchParams('session=old-session')

      const { result } = renderHook(() => useSessionUrl({ isAuthenticated: true }))

      act(() => {
        result.current.clearSessionUrl()
      })

      expect(mockRouter.replace).toHaveBeenCalledWith('/')
    })
  })

  describe('initial URL sync', () => {
    test('selects conversation when session exists in URL', async () => {
      mockSearchParams = new URLSearchParams('session=session-123')
      mockChatStore.currentUserId = 'user-1'
      mockChatStore.getUserConversations.mockReturnValue([
        { id: 'session-123', title: 'Test Session' },
      ])

      renderHook(() => useSessionUrl({ isAuthenticated: true }))

      expect(mockChatStore.selectConversation).toHaveBeenCalledWith('session-123')
    })

    test('clears invalid session from URL', async () => {
      mockSearchParams = new URLSearchParams('session=invalid-session')
      mockChatStore.currentUserId = 'user-1'
      mockChatStore.getUserConversations.mockReturnValue([
        { id: 'session-123', title: 'Test Session' },
      ])

      renderHook(() => useSessionUrl({ isAuthenticated: true }))

      expect(mockRouter.replace).toHaveBeenCalledWith('/')
    })

    test('does nothing when not authenticated', async () => {
      mockSearchParams = new URLSearchParams('session=session-123')
      mockChatStore.currentUserId = 'user-1'
      mockChatStore.getUserConversations.mockReturnValue([
        { id: 'session-123', title: 'Test Session' },
      ])

      renderHook(() => useSessionUrl({ isAuthenticated: false }))

      expect(mockChatStore.selectConversation).not.toHaveBeenCalled()
    })

    test('does nothing when no currentUserId', async () => {
      mockSearchParams = new URLSearchParams('session=session-123')
      mockChatStore.currentUserId = null
      mockChatStore.getUserConversations.mockReturnValue([
        { id: 'session-123', title: 'Test Session' },
      ])

      renderHook(() => useSessionUrl({ isAuthenticated: true }))

      expect(mockChatStore.selectConversation).not.toHaveBeenCalled()
    })

    test('does nothing when no session in URL', async () => {
      mockSearchParams = new URLSearchParams()
      mockChatStore.currentUserId = 'user-1'

      renderHook(() => useSessionUrl({ isAuthenticated: true }))

      expect(mockChatStore.selectConversation).not.toHaveBeenCalled()
    })
  })

  describe('URL sync on conversation change', () => {
    test('updates URL when current conversation changes', async () => {
      mockChatStore.currentUserId = 'user-1'
      mockChatStore.currentConversation = { id: 'session-123' }

      const { rerender } = renderHook(() => useSessionUrl({ isAuthenticated: true }))

      // Trigger initial sync
      rerender()

      // Change conversation
      mockChatStore.currentConversation = { id: 'session-456' }
      rerender()

      expect(mockRouter.replace).toHaveBeenCalledWith('/?session=session-456')
    })

    test('clears URL when conversation is cleared', async () => {
      mockSearchParams = new URLSearchParams('session=session-123')
      mockChatStore.currentUserId = 'user-1'
      mockChatStore.currentConversation = { id: 'session-123' }
      mockChatStore.getUserConversations.mockReturnValue([
        { id: 'session-123', title: 'Test Session' },
      ])

      const { rerender } = renderHook(() => useSessionUrl({ isAuthenticated: true }))

      // Initial sync happens
      rerender()

      // Clear conversation
      mockChatStore.currentConversation = null
      rerender()

      expect(mockRouter.replace).toHaveBeenCalledWith('/')
    })
  })
})

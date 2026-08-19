// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Integration coverage for the chat auto-follow behavior.
 *
 * Verifies that ChatArea follows content growth (streamed answer / thinking
 * trace) when the user is pinned to the bottom, and leaves the viewport alone
 * when the user has scrolled up to read history. happy-dom has no real layout
 * engine, so we stub the scroll geometry and capture the ResizeObserver callback
 * the component registers, then drive it directly.
 */

import { render, screen, fireEvent, act } from '@/test-utils'
import { vi, describe, test, expect, beforeEach, afterEach } from 'vitest'

import { ChatArea } from './ChatArea'

const state = {
  currentConversation: {
    id: 'conv-1',
    messages: [{ id: 'u1', role: 'user', content: 'Hello', messageType: 'user' }],
  },
  isLoading: false,
  isStreaming: false,
  currentUserMessageId: undefined as string | undefined,
  thinkingSteps: [],
  respondToPrompt: vi.fn(),
  dismissErrorCard: vi.fn(),
  getThinkingStepsForMessage: vi.fn(() => [] as unknown[]),
}

vi.mock('@/features/chat', () => ({
  useChatStore: vi.fn((selector?: (s: typeof state) => unknown) =>
    selector ? selector(state) : state
  ),
  AgentPrompt: () => <div />,
  AgentResponse: ({ content }: { content: string }) => <div data-testid="agent-response">{content}</div>,
  ErrorBanner: () => <div />,
  FileUploadBanner: () => <div />,
  DeepResearchBanner: () => <div />,
  UserMessage: ({ content }: { content: string }) => <div data-testid="user-message">{content}</div>,
  ChatThinking: () => <div />,
}))

type Geometry = { scrollTop: number; scrollHeight: number; clientHeight: number }

const setGeometry = (el: HTMLElement, g: Geometry): { current: number } => {
  const ref = { current: g.scrollTop }
  Object.defineProperty(el, 'scrollTop', {
    configurable: true,
    get: () => ref.current,
    set: (v: number) => {
      ref.current = v
    },
  })
  Object.defineProperty(el, 'scrollHeight', { configurable: true, get: () => g.scrollHeight })
  Object.defineProperty(el, 'clientHeight', { configurable: true, get: () => g.clientHeight })
  return ref
}

describe('ChatArea auto-follow', () => {
  let roCallback: ResizeObserverCallback | null
  let originalRO: typeof ResizeObserver

  beforeEach(() => {
    roCallback = null
    originalRO = globalThis.ResizeObserver
    class MockResizeObserver {
      constructor(cb: ResizeObserverCallback) {
        roCallback = cb
      }
      observe = vi.fn()
      unobserve = vi.fn()
      disconnect = vi.fn()
    }
    vi.stubGlobal('ResizeObserver', MockResizeObserver)
  })

  afterEach(() => {
    vi.stubGlobal('ResizeObserver', originalRO)
    vi.restoreAllMocks()
  })

  const growContent = (): void => {
    expect(typeof roCallback).toBe('function')
    act(() => {
      roCallback?.([], {} as ResizeObserver)
    })
  }

  test('follows content growth while the user is pinned to the bottom', () => {
    render(<ChatArea isAuthenticated />)
    const container = screen.getByLabelText(/chat messages/i) as HTMLElement
    // distance from bottom = 1000 - 800 - 200 = 0 => pinned
    const scrollTop = setGeometry(container, { scrollTop: 800, scrollHeight: 1000, clientHeight: 200 })

    fireEvent.scroll(container) // record that the user is pinned
    growContent() // simulate streamed tokens / expanding thinking trace

    expect(scrollTop.current).toBe(1000) // viewport followed to the new bottom
  })

  test('does NOT move the viewport when the user has scrolled up', () => {
    render(<ChatArea isAuthenticated />)
    const container = screen.getByLabelText(/chat messages/i) as HTMLElement
    // distance from bottom = 1000 - 0 - 200 = 800 => NOT pinned
    const scrollTop = setGeometry(container, { scrollTop: 0, scrollHeight: 1000, clientHeight: 200 })

    fireEvent.scroll(container) // record that the user scrolled up
    growContent() // content grows underneath

    expect(scrollTop.current).toBe(0) // viewport left exactly where the user put it
  })

  test('re-pins to the bottom once the user scrolls back down', () => {
    render(<ChatArea isAuthenticated />)
    const container = screen.getByLabelText(/chat messages/i) as HTMLElement

    // First scroll up (not pinned), grow -> no movement
    const scrollTop = setGeometry(container, { scrollTop: 0, scrollHeight: 1000, clientHeight: 200 })
    fireEvent.scroll(container)
    growContent()
    expect(scrollTop.current).toBe(0)

    // User scrolls back to the bottom, then content grows -> follows again
    scrollTop.current = 800 // distance 0 => pinned
    fireEvent.scroll(container)
    growContent()
    expect(scrollTop.current).toBe(1000)
  })
})

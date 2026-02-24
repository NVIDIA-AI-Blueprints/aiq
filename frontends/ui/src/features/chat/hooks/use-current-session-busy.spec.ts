// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Tests for useIsCurrentSessionBusy hook
 *
 * Tests cover three categories:
 * 1. Ephemeral state (normal operation — isStreaming, SSE, deepResearchStatus)
 * 2. Persisted state (page refresh recovery — message history, pendingInteraction)
 * 3. Combined state (ephemeral + persisted together)
 */

import { renderHook } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { useIsCurrentSessionBusy } from './use-current-session-busy'
import { useChatStore } from '../store'

// Mock the chat store
vi.mock('../store', () => ({
  useChatStore: vi.fn(),
}))

// Mock the session-activity utility (pure functions tested separately)
vi.mock('../lib/session-activity', () => ({
  hasActiveDeepResearchJob: vi.fn(() => false),
}))

import { hasActiveDeepResearchJob } from '../lib/session-activity'
const mockHasActiveJob = hasActiveDeepResearchJob as unknown as ReturnType<typeof vi.fn>

/**
 * Default idle state — all flags off, no persisted activity.
 */
const idleState = {
  isStreaming: false,
  isDeepResearchStreaming: false,
  deepResearchStatus: null,
  currentConversation: { id: 'conv-1', messages: [] },
  pendingInteraction: null,
}

describe('useIsCurrentSessionBusy', () => {
  const mockUseChatStore = useChatStore as unknown as ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.clearAllMocks()
    mockHasActiveJob.mockReturnValue(false)
  })

  // ─── Ephemeral State Tests ─────────────────────────────────────

  it('returns false when no operations are active', () => {
    mockUseChatStore.mockImplementation((selector: (state: any) => any) =>
      selector(idleState)
    )

    const { result } = renderHook(() => useIsCurrentSessionBusy())
    expect(result.current).toBe(false)
  })

  it('returns true when WebSocket is streaming (shallow thinking)', () => {
    mockUseChatStore.mockImplementation((selector: (state: any) => any) =>
      selector({ ...idleState, isStreaming: true })
    )

    const { result } = renderHook(() => useIsCurrentSessionBusy())
    expect(result.current).toBe(true)
  })

  it('returns true when deep research SSE is streaming', () => {
    mockUseChatStore.mockImplementation((selector: (state: any) => any) =>
      selector({ ...idleState, isDeepResearchStreaming: true, deepResearchStatus: 'running' })
    )

    const { result } = renderHook(() => useIsCurrentSessionBusy())
    expect(result.current).toBe(true)
  })

  it('returns true when deep research status is "submitted"', () => {
    mockUseChatStore.mockImplementation((selector: (state: any) => any) =>
      selector({ ...idleState, deepResearchStatus: 'submitted' })
    )

    const { result } = renderHook(() => useIsCurrentSessionBusy())
    expect(result.current).toBe(true)
  })

  it('returns true when deep research status is "running"', () => {
    mockUseChatStore.mockImplementation((selector: (state: any) => any) =>
      selector({ ...idleState, deepResearchStatus: 'running' })
    )

    const { result } = renderHook(() => useIsCurrentSessionBusy())
    expect(result.current).toBe(true)
  })

  it('returns false when deep research status is "success" (terminal state)', () => {
    mockUseChatStore.mockImplementation((selector: (state: any) => any) =>
      selector({ ...idleState, deepResearchStatus: 'success' })
    )

    const { result } = renderHook(() => useIsCurrentSessionBusy())
    expect(result.current).toBe(false)
  })

  it('returns false when deep research status is "failure" (terminal state)', () => {
    mockUseChatStore.mockImplementation((selector: (state: any) => any) =>
      selector({ ...idleState, deepResearchStatus: 'failure' })
    )

    const { result } = renderHook(() => useIsCurrentSessionBusy())
    expect(result.current).toBe(false)
  })

  it('returns false when deep research status is "interrupted" (terminal state)', () => {
    mockUseChatStore.mockImplementation((selector: (state: any) => any) =>
      selector({ ...idleState, deepResearchStatus: 'interrupted' })
    )

    const { result } = renderHook(() => useIsCurrentSessionBusy())
    expect(result.current).toBe(false)
  })

  it('returns true when both shallow and deep research are active', () => {
    mockUseChatStore.mockImplementation((selector: (state: any) => any) =>
      selector({
        ...idleState,
        isStreaming: true,
        isDeepResearchStreaming: true,
        deepResearchStatus: 'running',
      })
    )

    const { result } = renderHook(() => useIsCurrentSessionBusy())
    expect(result.current).toBe(true)
  })

  // ─── Persisted State Tests (Page Refresh Recovery) ─────────────

  it('returns true when message history has active deep research job (refresh scenario)', () => {
    // Simulate page refresh: ephemeral state is reset, but persisted messages indicate active job
    mockHasActiveJob.mockReturnValue(true)

    mockUseChatStore.mockImplementation((selector: (state: any) => any) =>
      selector(idleState) // All ephemeral state is idle
    )

    const { result } = renderHook(() => useIsCurrentSessionBusy())
    expect(result.current).toBe(true)
  })

  it('returns true when pending HITL interaction exists (refresh scenario)', () => {
    mockUseChatStore.mockImplementation((selector: (state: any) => any) =>
      selector({
        ...idleState,
        pendingInteraction: { type: 'plan_approval', content: 'Approve this plan?' },
      })
    )

    const { result } = renderHook(() => useIsCurrentSessionBusy())
    expect(result.current).toBe(true)
  })

  it('returns false when currentConversation is null', () => {
    mockUseChatStore.mockImplementation((selector: (state: any) => any) =>
      selector({ ...idleState, currentConversation: null })
    )

    const { result } = renderHook(() => useIsCurrentSessionBusy())
    expect(result.current).toBe(false)
  })

  // ─── Combined State Tests ──────────────────────────────────────

  it('returns true when both ephemeral streaming and persisted HITL are active', () => {
    mockUseChatStore.mockImplementation((selector: (state: any) => any) =>
      selector({
        ...idleState,
        isStreaming: true,
        pendingInteraction: { type: 'plan_approval' },
      })
    )

    const { result } = renderHook(() => useIsCurrentSessionBusy())
    expect(result.current).toBe(true)
  })

  it('returns true when ephemeral is idle but both persisted flags are active', () => {
    mockHasActiveJob.mockReturnValue(true)

    mockUseChatStore.mockImplementation((selector: (state: any) => any) =>
      selector({
        ...idleState,
        pendingInteraction: { type: 'plan_approval' },
      })
    )

    const { result } = renderHook(() => useIsCurrentSessionBusy())
    expect(result.current).toBe(true)
  })
})

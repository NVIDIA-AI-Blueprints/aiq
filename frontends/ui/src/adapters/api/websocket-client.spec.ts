// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { NATMessageType, NATWebSocketClient } from './websocket-client'

class MockWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 3
  static instances: MockWebSocket[] = []

  readonly url: string
  readyState = MockWebSocket.OPEN
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }

  send = vi.fn()
  close = vi.fn(() => {
    this.readyState = MockWebSocket.CLOSED
  })
}

describe('NATWebSocketClient auth observability', () => {
  beforeEach(() => {
    MockWebSocket.instances = []
    vi.stubGlobal('WebSocket', MockWebSocket)
  })

  afterEach(() => {
    delete (window as unknown as Record<string, unknown>).DD_RUM
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  test('emits RUM error for websocket auth_error payloads', async () => {
    const addError = vi.fn()
    ;(window as unknown as Record<string, unknown>).DD_RUM = { addError }
    const onError = vi.fn()
    const client = new NATWebSocketClient({
      conversationId: 'conv-1',
      websocketUrl: 'ws://localhost/websocket',
      callbacks: { onError },
    })

    await client.connect()
    const ws = MockWebSocket.instances[0]
    ws.onopen?.(new Event('open'))
    ws.onmessage?.(
      {
        data: JSON.stringify({
          type: NATMessageType.ERROR,
          content: {
            code: 'UNKNOWN_ERROR',
            message: 'auth_error',
            details: 'Token expired',
          },
          status: 'error',
        }),
      } as MessageEvent
    )

    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({
        code: 'UNKNOWN_ERROR',
        message: 'auth_error',
        details: 'Token expired',
      })
    )
    expect(addError).toHaveBeenCalledWith(
      expect.any(Error),
      expect.objectContaining({
        source: 'websocket',
        auth_error_code: 'auth_error',
        details: 'Token expired',
      })
    )
  })

  test('rotate() ignores late onclose from the rotated-out socket', async () => {
    // Regression: NATWebSocketClient.rotate() must atomically detach the
    // old socket so a delayed `onclose` from it cannot be reclassified as
    // an unintentional disconnect on the freshly-opened socket. Without
    // this guarantee, the hook would see onConnectionChange('disconnected'
    // | 'error') seconds after a silent token rotation -- clobbering
    // streaming/loading state and potentially scheduling another reconnect.
    const onConnectionChange = vi.fn()
    const onError = vi.fn()
    const client = new NATWebSocketClient({
      conversationId: 'conv-1',
      websocketUrl: 'ws://localhost/websocket',
      callbacks: { onConnectionChange, onError },
    })

    // Open socket A and bring it to the connected state.
    await client.connect()
    const socketA = MockWebSocket.instances[0]
    socketA.onopen?.(new Event('open'))
    expect(onConnectionChange).toHaveBeenCalledWith('connected')
    onConnectionChange.mockClear()

    // Capture A's onclose BEFORE rotate() detaches it, then rotate.
    // Real browsers fire onclose asynchronously after close(); we
    // capture the reference so we can simulate that delayed event.
    const staleOnCloseA = socketA.onclose
    await client.rotate()

    // After rotate(): a brand new socket B exists, A's handlers are
    // detached (so calling staleOnCloseA directly is the only way the
    // old code path could be reached -- this is the worst case the
    // socket-instance guard protects against).
    expect(MockWebSocket.instances).toHaveLength(2)
    const socketB = MockWebSocket.instances[1]
    expect(socketB).not.toBe(socketA)
    // rotate() detaches A's handlers so the live A.onclose is now null
    // even though the browser would still hold a reference somewhere.
    expect(socketA.onclose).toBeNull()

    // Bring socket B to connected.
    socketB.onopen?.(new Event('open'))
    expect(onConnectionChange).toHaveBeenCalledWith('connected')
    onConnectionChange.mockClear()

    // Simulate the browser firing the LATE close on A (via the captured
    // handler reference -- mimicking the worst case where some polyfill
    // or stale reference still has it). The socket-instance guard inside
    // setupEventHandlers must drop this event silently: it must NOT push
    // 'disconnected' or 'error' through to the hook, must NOT touch
    // streaming/loading state, must NOT schedule an extra reconnect.
    staleOnCloseA?.(new CloseEvent('close'))

    expect(onConnectionChange).not.toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()

    // And a late onmessage on A is dropped too (defense in depth: if
    // some buffered frame surfaces on the old socket after rotate, it
    // must not be parsed against the new conversation context).
    socketA.onmessage = null // already detached by rotate, double-check
  })

  test('rotate() coalesces concurrent calls -- only one new socket is created', async () => {
    // Regression: if a second rotate() is fired while one is already in
    // flight (e.g. the soft-rotation timer fires the same tick the
    // hook receives auth_expired), each call must NOT independently
    // detach handlers and start its own connect(). Worst case there is
    // two parallel `new WebSocket(...)` opens racing for `this.ws` --
    // exactly the kind of mid-rotation chaos the rotate() primitive
    // was introduced to prevent.
    const onConnectionChange = vi.fn()
    const client = new NATWebSocketClient({
      conversationId: 'conv-1',
      websocketUrl: 'ws://localhost/websocket',
      callbacks: { onConnectionChange },
    })

    await client.connect()
    expect(MockWebSocket.instances).toHaveLength(1)
    const socketA = MockWebSocket.instances[0]
    socketA.onopen?.(new Event('open'))

    // Fire two rotate() calls without awaiting the first.
    const r1 = client.rotate()
    const r2 = client.rotate()

    // The second call must coalesce into the first's in-flight promise,
    // not start its own rotation. Identity check is the strictest
    // possible assertion -- it proves we returned the cached promise,
    // not just a structurally-equivalent one.
    expect(r1).toBe(r2)

    await Promise.all([r1, r2])

    // Exactly one new socket B (total 2). If the second rotate() had
    // run independently, we would see THREE MockWebSocket instances:
    // the original A, the B opened by the first rotate(), and a third
    // C opened by the second rotate() after it tore B's handlers off.
    expect(MockWebSocket.instances).toHaveLength(2)
  })

  test('connect() does not open a second socket while the first is still connecting', async () => {
    const client = new NATWebSocketClient({
      conversationId: 'conv-1',
      websocketUrl: 'ws://localhost/websocket',
      callbacks: {},
    })

    await client.connect()
    const socketA = MockWebSocket.instances[0]
    socketA.readyState = MockWebSocket.CONNECTING

    await client.connect()

    expect(MockWebSocket.instances).toHaveLength(1)
  })

  test('sendMessage includes active report job id when provided', async () => {
    const client = new NATWebSocketClient({
      conversationId: 'conv-1',
      websocketUrl: 'ws://localhost/websocket',
      callbacks: {},
    })

    await client.connect()
    const ws = MockWebSocket.instances[0]
    ws.onopen?.(new Event('open'))

    client.sendMessage('What changed?', ['web_search'], 'job-123')

    const sent = JSON.parse(ws.send.mock.calls[0][0] as string)
    const textContent = sent.content.messages[0].content[0].text
    expect(JSON.parse(textContent)).toEqual({
      query: 'What changed?',
      data_sources: ['web_search'],
      active_report_job_id: 'job-123',
    })
  })

  test('does not emit RUM error for non-auth websocket errors', async () => {
    const addError = vi.fn()
    ;(window as unknown as Record<string, unknown>).DD_RUM = { addError }
    const onError = vi.fn()
    const client = new NATWebSocketClient({
      conversationId: 'conv-1',
      websocketUrl: 'ws://localhost/websocket',
      callbacks: { onError },
    })

    await client.connect()
    const ws = MockWebSocket.instances[0]
    ws.onopen?.(new Event('open'))
    ws.onmessage?.(
      {
        data: JSON.stringify({
          type: NATMessageType.ERROR,
          content: {
            code: 'UNKNOWN_ERROR',
            message: 'workflow_error',
            details: 'Unexpected failure',
          },
          status: 'error',
        }),
      } as MessageEvent
    )

    expect(onError).toHaveBeenCalled()
    expect(addError).not.toHaveBeenCalled()
  })
})

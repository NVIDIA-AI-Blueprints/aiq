// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { trackAuthEvent } from './rum'

const getWindowWithRum = () =>
  window as unknown as {
    DD_RUM?: {
      addAction?: ReturnType<typeof vi.fn>
      addError?: ReturnType<typeof vi.fn>
    }
  }

describe('trackAuthEvent', () => {
  const addAction = vi.fn()
  const addError = vi.fn()

  beforeEach(() => {
    addAction.mockClear()
    addError.mockClear()
    getWindowWithRum().DD_RUM = { addAction, addError }
  })

  afterEach(() => {
    delete getWindowWithRum().DD_RUM
  })

  test('routes expected auth lifecycle codes to RUM actions', () => {
    trackAuthEvent('token_missing', { path: '/api/chat' })
    trackAuthEvent('token_expired', { path: '/api/chat' })

    expect(addAction).toHaveBeenCalledTimes(2)
    expect(addAction).toHaveBeenNthCalledWith(1, 'Auth: token_missing', {
      auth_error_code: 'token_missing',
      path: '/api/chat',
    })
    expect(addAction).toHaveBeenNthCalledWith(2, 'Auth: token_expired', {
      auth_error_code: 'token_expired',
      path: '/api/chat',
    })
    expect(addError).not.toHaveBeenCalled()
  })

  test('routes unexpected auth codes to RUM errors', () => {
    trackAuthEvent('token_invalid', { source: 'websocket' })

    expect(addError).toHaveBeenCalledTimes(1)
    expect(addError.mock.calls[0][0]).toBeInstanceOf(Error)
    expect(addError.mock.calls[0][0].message).toBe('Auth: token_invalid')
    expect(addError.mock.calls[0][1]).toEqual({
      source: 'websocket',
      auth_error_code: 'token_invalid',
    })
    expect(addAction).not.toHaveBeenCalled()
  })
})

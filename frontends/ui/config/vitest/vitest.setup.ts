// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import '@testing-library/jest-dom/vitest'
import crypto from 'crypto'
import { createElement } from 'react'
import { beforeAll, afterEach, afterAll, vi } from 'vitest'
import { server } from '../../src/mocks/server'
import { resetDatabase } from '../../src/mocks/database'

// Prevent external-svg-loader timer from firing after test environment teardown.
// The library schedules a setTimeout that accesses `document`, which no longer
// exists once happy-dom cleans up, causing "ReferenceError: document is not defined".
vi.mock('external-svg-loader', () => ({}))

const createSvgIcon = (props: Record<string, unknown>, testId: string) => {
  const {
    className,
    role,
    width,
    height,
    style,
    color,
    'aria-label': ariaLabel,
    'aria-hidden': ariaHidden,
  } = props

  return createElement('svg', {
    className,
    role,
    width,
    height,
    style,
    color,
    'aria-label': ariaLabel,
    'aria-hidden': ariaHidden,
    'data-testid': testId,
  })
}

vi.mock('@nv-brand-assets/react-icons', () => ({
  NvidiaGUIIcon: (props: Record<string, unknown>) =>
    createSvgIcon(props, 'mock-nvidia-gui-icon'),
}))
vi.mock('@nv-brand-assets/react-marketing-icons', () => ({
  NvidiaMarketingIcon: (props: Record<string, unknown>) =>
    createSvgIcon(props, 'mock-nvidia-marketing-icon'),
}))

// @ts-expect-error - Setting NODE_ENV for tests
process.env.NODE_ENV = 'test'

// Crypto polyfill
Object.defineProperty(global, 'crypto', {
  value: {
    getRandomValues: (arr: unknown[]) => crypto.randomBytes(arr.length),
  },
})

// Session storage mock
const sessionStorageMock = (function () {
  let storage: Record<string, unknown> = {}

  return {
    clear: () => (storage = {}),
    getItem: (key: string) => storage[key],
    getAll: () => storage,
    removeItem: (key: string) => {
      delete storage[key]
    },
    setItem: (key: string, value: unknown) => {
      storage[key] = value
    },
  }
})()

// Browser API mocks for happy-dom
class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

class IntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

class MutationObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(global, 'sessionStorage', { value: sessionStorageMock })
global.ResizeObserver = ResizeObserver
// @ts-expect-error - Partial mock
global.IntersectionObserver = IntersectionObserver
// @ts-expect-error - Partial mock
global.MutationObserver = MutationObserver

// MSW server lifecycle
beforeAll(() => {
  sessionStorageMock.clear()
  return server.listen({ onUnhandledRequest: 'bypass' })
})

afterEach(() => {
  server.resetHandlers()
  resetDatabase()
})

afterAll(() => server.close())

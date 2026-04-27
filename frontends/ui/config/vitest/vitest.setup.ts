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

// Storage mocks — Node.js 22+ exposes a broken built-in localStorage when
// `--localstorage-file` is passed without a valid path, overriding happy-dom's
// implementation.  Provide explicit in-memory mocks for both storages.
function createStorageMock() {
  let storage: Record<string, string> = {}

  return {
    clear: () => (storage = {}),
    getItem: (key: string) => (key in storage ? storage[key] : null),
    getAll: () => storage,
    key: (index: number) => Object.keys(storage)[index] ?? null,
    get length() {
      return Object.keys(storage).length
    },
    removeItem: (key: string) => {
      delete storage[key]
    },
    setItem: (key: string, value: string) => {
      storage[key] = String(value)
    },
  }
}

const localStorageMock = createStorageMock()
const sessionStorageMock = createStorageMock()

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

Object.defineProperty(global, 'localStorage', { value: localStorageMock, configurable: true })
Object.defineProperty(global, 'sessionStorage', { value: sessionStorageMock, configurable: true })
global.ResizeObserver = ResizeObserver
// @ts-expect-error - Partial mock
global.IntersectionObserver = IntersectionObserver
// @ts-expect-error - Partial mock
global.MutationObserver = MutationObserver

// MSW server lifecycle
beforeAll(() => {
  localStorageMock.clear()
  sessionStorageMock.clear()
  return server.listen({ onUnhandledRequest: 'bypass' })
})

afterEach(() => {
  server.resetHandlers()
  resetDatabase()
})

afterAll(() => server.close())

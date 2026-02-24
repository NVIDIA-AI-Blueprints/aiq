// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createDataSourcesClient } from './data-sources-client'

// Mock the config - note: browser environment uses relative URLs
vi.mock('./config', () => ({
  apiConfig: {
    baseUrl: '',
  },
}))

describe('createDataSourcesClient', () => {
  let mockFetch: ReturnType<typeof vi.fn>

  beforeEach(() => {
    mockFetch = vi.fn()
    global.fetch = mockFetch as typeof fetch
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  describe('getDataSources', () => {
    test('fetches data sources successfully', async () => {
      const mockDataSources = [
        { id: 'web', name: 'Web Search', description: 'Search the web' },
        { id: 'docs', name: 'Documents', description: 'Search documents' },
      ]

      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ data_sources: mockDataSources }),
      })

      const client = createDataSourcesClient()
      const result = await client.getDataSources()

      expect(result.data_sources).toEqual(mockDataSources)
      expect(result.knowledge_layer).toBe(false)
      expect(mockFetch).toHaveBeenCalledWith('/api/v1/data_sources', {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
        signal: undefined,
      })
    })

    test('includes auth token in headers when provided', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ data_sources: [] }),
      })

      const client = createDataSourcesClient({ authToken: 'test-token' })
      await client.getDataSources()

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: {
            'Content-Type': 'application/json',
            Authorization: 'Bearer test-token',
          },
        })
      )
    })

    test('handles array response format', async () => {
      const mockDataSources = [
        { id: 'web', name: 'Web Search' },
        { id: 'docs', name: 'Documents' },
      ]

      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockDataSources),
      })

      const client = createDataSourcesClient()
      const result = await client.getDataSources()

      expect(result.data_sources).toEqual(mockDataSources)
    })

    test('detects knowledge_layer availability', async () => {
      const mockDataSources = [
        { id: 'web', name: 'Web Search' },
        { id: 'knowledge_layer', name: 'Knowledge Layer' },
      ]

      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ data_sources: mockDataSources }),
      })

      const client = createDataSourcesClient()
      const result = await client.getDataSources()

      expect(result.knowledge_layer).toBe(true)
      expect(result.data_sources).not.toContainEqual(
        expect.objectContaining({ id: 'knowledge_layer' })
      )
    })

    test('filters out knowledge_layer from data sources', async () => {
      const mockDataSources = [
        { id: 'web', name: 'Web Search' },
        { id: 'knowledge_layer', name: 'Knowledge Layer' },
        { id: 'docs', name: 'Documents' },
      ]

      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ data_sources: mockDataSources }),
      })

      const client = createDataSourcesClient()
      const result = await client.getDataSources()

      expect(result.data_sources).toHaveLength(2)
      expect(result.data_sources.map((s) => s.id)).toEqual(['web', 'docs'])
    })

    test('handles API error with error message', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        statusText: 'Internal Server Error',
        json: () => Promise.resolve({ error: { message: 'Database connection failed' } }),
      })

      const client = createDataSourcesClient()

      await expect(client.getDataSources()).rejects.toThrow('Database connection failed')
    })

    test('handles API error without error message', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        statusText: 'Internal Server Error',
        json: () => Promise.resolve({}),
      })

      const client = createDataSourcesClient()

      await expect(client.getDataSources()).rejects.toThrow(
        'Failed to fetch data sources: Internal Server Error'
      )
    })

    test('handles API error with invalid JSON', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        statusText: 'Internal Server Error',
        json: () => Promise.reject(new Error('Invalid JSON')),
      })

      const client = createDataSourcesClient()

      await expect(client.getDataSources()).rejects.toThrow(
        'Failed to fetch data sources: Internal Server Error'
      )
    })

    test('passes abort signal to fetch', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ data_sources: [] }),
      })

      const controller = new AbortController()
      const client = createDataSourcesClient()
      await client.getDataSources(controller.signal)

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          signal: controller.signal,
        })
      )
    })

    test('handles empty data sources', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ data_sources: [] }),
      })

      const client = createDataSourcesClient()
      const result = await client.getDataSources()

      expect(result.data_sources).toEqual([])
      expect(result.knowledge_layer).toBe(false)
    })
  })
})

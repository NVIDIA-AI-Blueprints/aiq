// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createDocumentsClient } from './documents-client'

// Mock the config - note: browser environment uses relative URLs
vi.mock('./config', () => ({
  apiConfig: {
    collectionsUrl: '/api/v1/collections',
    documentsBaseUrl: '/api/v1',
  },
}))

// Mock the schemas
vi.mock('./documents-schemas', () => ({
  CollectionInfoSchema: {
    parse: (data: unknown) => data,
  },
  CollectionListResponseSchema: {
    parse: (data: unknown) => data,
  },
  FileInfoSchema: {
    parse: (data: unknown) => data,
  },
  FileListResponseSchema: {
    parse: (data: unknown) => data,
  },
  UploadResponseSchema: {
    parse: (data: unknown) => data,
  },
  IngestionJobStatusSchema: {
    parse: (data: unknown) => data,
  },
}))

describe('createDocumentsClient', () => {
  let mockFetch: ReturnType<typeof vi.fn>

  beforeEach(() => {
    mockFetch = vi.fn()
    global.fetch = mockFetch as typeof fetch
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  describe('createCollection', () => {
    test('creates collection successfully', async () => {
      const mockCollection = { name: 'test-collection', description: 'Test' }

      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockCollection),
      })

      const client = createDocumentsClient()
      const result = await client.createCollection('test-collection', 'Test')

      expect(result).toEqual(mockCollection)
      expect(mockFetch).toHaveBeenCalledWith('/api/v1/collections', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'test-collection', description: 'Test' }),
      })
    })

    test('includes auth token when provided', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ name: 'test' }),
      })

      const client = createDocumentsClient({ authToken: 'test-token' })
      await client.createCollection('test')

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

    test('handles API error', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        statusText: 'Bad Request',
        json: () => Promise.resolve({ error: { message: 'Invalid collection name' } }),
      })

      const client = createDocumentsClient()

      await expect(client.createCollection('test')).rejects.toThrow('Invalid collection name')
    })
  })

  describe('listCollections', () => {
    test('lists collections successfully', async () => {
      const mockCollections = {
        collections: [
          { name: 'collection-1' },
          { name: 'collection-2' },
        ],
      }

      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockCollections),
      })

      const client = createDocumentsClient()
      const result = await client.listCollections()

      expect(result).toEqual(mockCollections.collections)
    })
  })

  describe('getCollection', () => {
    test('gets collection successfully', async () => {
      const mockCollection = { name: 'test-collection' }

      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockCollection),
      })

      const client = createDocumentsClient()
      const result = await client.getCollection('test-collection')

      expect(result).toEqual(mockCollection)
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/collections/test-collection',
        expect.any(Object)
      )
    })

    test('returns null for 404', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        status: 404,
      })

      const client = createDocumentsClient()
      const result = await client.getCollection('nonexistent')

      expect(result).toBeNull()
    })

    test('passes abort signal', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ name: 'test' }),
      })

      const controller = new AbortController()
      const client = createDocumentsClient()
      await client.getCollection('test', controller.signal)

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          signal: controller.signal,
        })
      )
    })
  })

  describe('deleteCollection', () => {
    test('deletes collection successfully', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
      })

      const client = createDocumentsClient()
      await client.deleteCollection('test-collection')

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/collections/test-collection',
        expect.objectContaining({
          method: 'DELETE',
        })
      )
    })

    test('ignores 404 on delete', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        status: 404,
      })

      const client = createDocumentsClient()

      await expect(client.deleteCollection('nonexistent')).resolves.not.toThrow()
    })
  })

  describe('uploadFiles', () => {
    test('uploads files successfully with fetch', async () => {
      const mockResponse = {
        job_id: 'job-123',
        file_ids: ['file-1', 'file-2'],
      }

      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse),
      })

      const client = createDocumentsClient()
      const files = [
        new File(['content1'], 'file1.pdf', { type: 'application/pdf' }),
        new File(['content2'], 'file2.pdf', { type: 'application/pdf' }),
      ]

      const result = await client.uploadFiles('test-collection', files)

      expect(result).toEqual(mockResponse)
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/collections/test-collection/documents',
        expect.objectContaining({
          method: 'POST',
          body: expect.any(FormData),
        })
      )
    })

    test('handles upload error', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        statusText: 'Bad Request',
        json: () => Promise.resolve({ error: { message: 'File too large' } }),
      })

      const client = createDocumentsClient()
      const files = [new File(['content'], 'file.pdf', { type: 'application/pdf' })]

      await expect(client.uploadFiles('test-collection', files)).rejects.toThrow('File too large')
    })

    test('passes abort signal', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ job_id: 'job-1', file_ids: ['file-1'] }),
      })

      const controller = new AbortController()
      const client = createDocumentsClient()
      const files = [new File(['content'], 'file.pdf', { type: 'application/pdf' })]

      await client.uploadFiles('test-collection', files, { signal: controller.signal })

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          signal: controller.signal,
        })
      )
    })
  })

  describe('listFiles', () => {
    test('lists files successfully with wrapped response', async () => {
      const mockFiles = {
        files: [
          { file_id: 'file-1', file_name: 'doc1.pdf' },
          { file_id: 'file-2', file_name: 'doc2.pdf' },
        ],
      }

      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockFiles),
      })

      const client = createDocumentsClient()
      const result = await client.listFiles('test-collection')

      expect(result).toEqual(mockFiles.files)
    })

    test('lists files successfully with array response', async () => {
      const mockFiles = [
        { file_id: 'file-1', file_name: 'doc1.pdf' },
        { file_id: 'file-2', file_name: 'doc2.pdf' },
      ]

      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockFiles),
      })

      const client = createDocumentsClient()
      const result = await client.listFiles('test-collection')

      expect(result).toEqual(mockFiles)
    })
  })

  describe('deleteFiles', () => {
    test('deletes files successfully', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
      })

      const client = createDocumentsClient()
      await client.deleteFiles('test-collection', ['file-1', 'file-2'])

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/collections/test-collection/documents',
        expect.objectContaining({
          method: 'DELETE',
          body: JSON.stringify({ file_ids: ['file-1', 'file-2'] }),
        })
      )
    })

    test('ignores 404 on delete', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        status: 404,
      })

      const client = createDocumentsClient()

      await expect(client.deleteFiles('test', ['file-1'])).resolves.not.toThrow()
    })
  })

  describe('getJobStatus', () => {
    test('gets job status successfully', async () => {
      const mockStatus = {
        job_id: 'job-123',
        status: 'in_progress',
        file_details: [
          { file_id: 'file-1', file_name: 'doc.pdf', status: 'processing', progress_percent: 50 },
        ],
      }

      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockStatus),
      })

      const client = createDocumentsClient()
      const result = await client.getJobStatus('job-123')

      expect(result).toEqual(mockStatus)
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/documents/job-123/status',
        expect.any(Object)
      )
    })

    test('returns null for 404', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        status: 404,
      })

      const client = createDocumentsClient()
      const result = await client.getJobStatus('nonexistent')

      expect(result).toBeNull()
    })

    test('passes abort signal', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ job_id: 'job-1', status: 'completed', file_details: [] }),
      })

      const controller = new AbortController()
      const client = createDocumentsClient()
      await client.getJobStatus('job-1', controller.signal)

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          signal: controller.signal,
        })
      )
    })

    test('handles API error', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        json: () => Promise.resolve({}),
      })

      const client = createDocumentsClient()

      await expect(client.getJobStatus('job-123')).rejects.toThrow(
        'Failed to get job status: Internal Server Error'
      )
    })
  })
})

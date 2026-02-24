// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Tests for layout configuration building
 *
 * Verifies that file upload configuration is correctly built from
 * environment variables with proper defaults and MIME type mapping.
 */

import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { getFileUploadConfigFromEnv } from '@/shared/config/file-upload'

// Store original env
const originalEnv = process.env

describe('File Upload Configuration', () => {
  beforeEach(() => {
    // Reset env before each test
    vi.resetModules()
    process.env = { ...originalEnv }
  })

  afterEach(() => {
    process.env = originalEnv
  })

  const buildFileUploadConfig = () => getFileUploadConfigFromEnv(process.env)

  describe('default values', () => {
    test('uses default accepted types when env var not set', () => {
      const config = buildFileUploadConfig()

      expect(config.acceptedTypes).toBe('.pdf,.md,.docx,.html,.txt')
    })

    test('uses default max size when env var not set', () => {
      const config = buildFileUploadConfig()

      expect(config.maxTotalSizeMB).toBe(100)
      expect(config.maxFileSize).toBe(100 * 1024 * 1024)
      expect(config.maxTotalSize).toBe(100 * 1024 * 1024)
    })

    test('uses default max file count when env var not set', () => {
      const config = buildFileUploadConfig()

      expect(config.maxFileCount).toBe(10)
    })

    test('uses default file expiration check interval (0) when env var not set', () => {
      const config = buildFileUploadConfig()

      expect(config.fileExpirationCheckIntervalHours).toBe(0)
    })

    test('builds correct MIME types from default extensions', () => {
      const config = buildFileUploadConfig()

      expect(config.acceptedMimeTypes).toContain('application/pdf')
      expect(config.acceptedMimeTypes).toContain('text/markdown')
      expect(config.acceptedMimeTypes).toContain('text/x-markdown')
      expect(config.acceptedMimeTypes).toContain('text/html')
      expect(config.acceptedMimeTypes).toContain('text/plain')
      expect(
        config.acceptedMimeTypes.includes(
          'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
      ).toBe(true)
    })
  })

  describe('environment variable overrides', () => {
    test('FILE_UPLOAD_ACCEPTED_TYPES overrides default accepted types', () => {
      process.env.FILE_UPLOAD_ACCEPTED_TYPES = '.csv,.json'

      const config = buildFileUploadConfig()

      expect(config.acceptedTypes).toBe('.csv,.json')
      expect(config.acceptedMimeTypes).toContain('text/csv')
      expect(config.acceptedMimeTypes).toContain('application/json')
      expect(config.acceptedMimeTypes).not.toContain('application/pdf')
    })

    test('FILE_UPLOAD_MAX_SIZE_MB overrides default max size', () => {
      process.env.FILE_UPLOAD_MAX_SIZE_MB = '50'

      const config = buildFileUploadConfig()

      expect(config.maxTotalSizeMB).toBe(50)
      expect(config.maxFileSize).toBe(50 * 1024 * 1024)
      expect(config.maxTotalSize).toBe(50 * 1024 * 1024)
    })

    test('FILE_UPLOAD_MAX_FILE_COUNT overrides default max file count', () => {
      process.env.FILE_UPLOAD_MAX_FILE_COUNT = '5'

      const config = buildFileUploadConfig()

      expect(config.maxFileCount).toBe(5)
    })

    test('FILE_EXPIRATION_CHECK_INTERVAL_HOURS overrides default', () => {
      process.env.FILE_EXPIRATION_CHECK_INTERVAL_HOURS = '12'

      const config = buildFileUploadConfig()

      expect(config.fileExpirationCheckIntervalHours).toBe(12)
    })

    test('all env vars can be set together', () => {
      process.env.FILE_UPLOAD_ACCEPTED_TYPES = '.pdf,.txt'
      process.env.FILE_UPLOAD_MAX_SIZE_MB = '25'
      process.env.FILE_UPLOAD_MAX_FILE_COUNT = '3'

      const config = buildFileUploadConfig()

      expect(config.acceptedTypes).toBe('.pdf,.txt')
      expect(config.maxTotalSizeMB).toBe(25)
      expect(config.maxFileSize).toBe(25 * 1024 * 1024)
      expect(config.maxFileCount).toBe(3)
      expect(config.acceptedMimeTypes).toContain('application/pdf')
      expect(config.acceptedMimeTypes).toContain('text/plain')
      expect(config.acceptedMimeTypes).toHaveLength(2)
    })
  })

  describe('edge cases', () => {
    test('handles invalid number for max size (falls back to default)', () => {
      process.env.FILE_UPLOAD_MAX_SIZE_MB = 'invalid'

      const config = buildFileUploadConfig()

      expect(config.maxTotalSizeMB).toBe(100) // Default
    })

    test('handles invalid number for max file count (falls back to default)', () => {
      process.env.FILE_UPLOAD_MAX_FILE_COUNT = 'invalid'

      const config = buildFileUploadConfig()

      expect(config.maxFileCount).toBe(10) // Default
    })

    test('handles extensions with spaces', () => {
      process.env.FILE_UPLOAD_ACCEPTED_TYPES = '.pdf, .txt , .md'

      const config = buildFileUploadConfig()

      expect(config.acceptedMimeTypes).toContain('application/pdf')
      expect(config.acceptedMimeTypes).toContain('text/plain')
      expect(config.acceptedMimeTypes).toContain('text/markdown')
    })

    test('handles uppercase extensions', () => {
      process.env.FILE_UPLOAD_ACCEPTED_TYPES = '.PDF,.TXT'

      const config = buildFileUploadConfig()

      expect(config.acceptedMimeTypes).toContain('application/pdf')
      expect(config.acceptedMimeTypes).toContain('text/plain')
    })

    test('unknown extensions do not add MIME types', () => {
      process.env.FILE_UPLOAD_ACCEPTED_TYPES = '.xyz,.unknown'

      const config = buildFileUploadConfig()

      expect(config.acceptedTypes).toBe('.xyz,.unknown')
      expect(config.acceptedMimeTypes).toHaveLength(0)
    })
  })
})

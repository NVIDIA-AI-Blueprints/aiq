// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, test, expect } from 'vitest'
import {
  validateFileUpload,
  isValidFileExtension,
  isValidMimeType,
  formatBytes,
  createEmptyValidationContext,
  type ValidationContext,
} from './validation'
import { MAX_FILE_SIZE, MAX_FILE_COUNT } from './constants'

describe('validation', () => {
  const createFile = (name: string, size: number = 1024, type: string = 'application/pdf'): File => {
    return new File(['x'.repeat(size)], name, { type })
  }

  describe('isValidFileExtension', () => {
    test('accepts valid extensions', () => {
      expect(isValidFileExtension('document.pdf')).toBe(true)
      expect(isValidFileExtension('document.docx')).toBe(true)
      expect(isValidFileExtension('document.txt')).toBe(true)
      expect(isValidFileExtension('document.md')).toBe(true)
    })

    test('rejects invalid extensions', () => {
      expect(isValidFileExtension('document.exe')).toBe(false)
      expect(isValidFileExtension('document.js')).toBe(false)
      expect(isValidFileExtension('document.png')).toBe(false)
      expect(isValidFileExtension('document.html')).toBe(false)
    })

    test('rejects files without extension', () => {
      expect(isValidFileExtension('document')).toBe(false)
    })

    test('handles case insensitivity', () => {
      expect(isValidFileExtension('document.PDF')).toBe(true)
      expect(isValidFileExtension('document.Pdf')).toBe(true)
    })
  })

  describe('isValidMimeType', () => {
    test('accepts valid mime types', () => {
      expect(isValidMimeType('application/pdf')).toBe(true)
      expect(isValidMimeType('text/plain')).toBe(true)
      expect(isValidMimeType('text/markdown')).toBe(true)
    })

    test('accepts empty mime type (some files lack it)', () => {
      expect(isValidMimeType('')).toBe(true)
    })

    test('rejects invalid mime types', () => {
      expect(isValidMimeType('image/png')).toBe(false)
      expect(isValidMimeType('application/javascript')).toBe(false)
      expect(isValidMimeType('text/html')).toBe(false)
    })
  })

  describe('formatBytes', () => {
    test('formats bytes correctly', () => {
      expect(formatBytes(0)).toBe('0 B')
      expect(formatBytes(500)).toBe('500 B')
      expect(formatBytes(1024)).toBe('1 KB')
      expect(formatBytes(1536)).toBe('1.5 KB')
      expect(formatBytes(1048576)).toBe('1 MB')
      expect(formatBytes(1073741824)).toBe('1 GB')
    })
  })

  describe('createEmptyValidationContext', () => {
    test('creates empty context', () => {
      const context = createEmptyValidationContext()

      expect(context.existingTotalSize).toBe(0)
      expect(context.existingFileCount).toBe(0)
      expect(context.existingFileNames.size).toBe(0)
    })
  })

  describe('validateFileUpload', () => {
    describe('basic validation', () => {
      test('accepts valid files', () => {
        const files = [createFile('doc1.pdf'), createFile('doc2.txt')]

        const result = validateFileUpload(files)

        expect(result.valid).toBe(true)
        expect(result.validFiles).toHaveLength(2)
        expect(result.fileErrors).toHaveLength(0)
        expect(result.batchErrors).toHaveLength(0)
        expect(result.summary).toBeNull()
      })

      test('rejects invalid file types', () => {
        const files = [createFile('document.exe')]

        const result = validateFileUpload(files)

        expect(result.valid).toBe(false)
        expect(result.validFiles).toHaveLength(0)
        expect(result.fileErrors).toHaveLength(1)
        expect(result.fileErrors[0].code).toBe('INVALID_TYPE')
      })

      test('rejects oversized files', () => {
        const files = [createFile('large.pdf', MAX_FILE_SIZE + 1)]

        const result = validateFileUpload(files)

        expect(result.valid).toBe(false)
        expect(result.validFiles).toHaveLength(0)
        expect(result.fileErrors).toHaveLength(1)
        expect(result.fileErrors[0].code).toBe('FILE_TOO_LARGE')
      })
    })

    describe('duplicate detection', () => {
      test('detects duplicates within batch', () => {
        const files = [createFile('doc.pdf'), createFile('doc.pdf')]

        const result = validateFileUpload(files)

        // First file is valid, second is duplicate
        expect(result.validFiles).toHaveLength(1)
        expect(result.fileErrors).toHaveLength(1)
        expect(result.fileErrors[0].code).toBe('DUPLICATE_FILE')
      })

      test('detects duplicates against existing session files', () => {
        const files = [createFile('existing.pdf')]
        const context: ValidationContext = {
          existingTotalSize: 1024,
          existingFileCount: 1,
          existingFileNames: new Set(['existing.pdf']),
        }

        const result = validateFileUpload(files, context)

        expect(result.validFiles).toHaveLength(0)
        expect(result.fileErrors).toHaveLength(1)
        expect(result.fileErrors[0].code).toBe('DUPLICATE_FILE')
        expect(result.fileErrors[0].message).toContain('already exists in this session')
      })
    })

    describe('partial batch uploads (file-level errors allow other files)', () => {
      test('allows valid files when some have invalid types', () => {
        const files = [createFile('valid.pdf'), createFile('invalid.exe')]

        const result = validateFileUpload(files)

        // valid should be false (there were errors), but validFiles should have the valid one
        expect(result.valid).toBe(false)
        expect(result.validFiles).toHaveLength(1)
        expect(result.validFiles[0].name).toBe('valid.pdf')
        expect(result.fileErrors).toHaveLength(1)
        expect(result.fileErrors[0].file.name).toBe('invalid.exe')
      })

      test('allows valid files when some are duplicates', () => {
        const files = [createFile('new.pdf'), createFile('existing.pdf')]
        const context: ValidationContext = {
          existingTotalSize: 1024,
          existingFileCount: 1,
          existingFileNames: new Set(['existing.pdf']),
        }

        const result = validateFileUpload(files, context)

        expect(result.valid).toBe(false)
        expect(result.validFiles).toHaveLength(1)
        expect(result.validFiles[0].name).toBe('new.pdf')
        expect(result.fileErrors).toHaveLength(1)
        expect(result.fileErrors[0].code).toBe('DUPLICATE_FILE')
      })

      test('allows valid files when some are oversized', () => {
        const files = [createFile('small.pdf', 1024), createFile('huge.pdf', MAX_FILE_SIZE + 1)]

        const result = validateFileUpload(files)

        expect(result.valid).toBe(false)
        expect(result.validFiles).toHaveLength(1)
        expect(result.validFiles[0].name).toBe('small.pdf')
        expect(result.fileErrors).toHaveLength(1)
        expect(result.fileErrors[0].code).toBe('FILE_TOO_LARGE')
      })

      test('handles multiple file-level errors in same batch', () => {
        const files = [
          createFile('valid.pdf'),
          createFile('invalid.exe'),
          createFile('duplicate.pdf'),
          createFile('duplicate.pdf'), // duplicate within batch
        ]

        const result = validateFileUpload(files)

        expect(result.validFiles).toHaveLength(2) // valid.pdf and first duplicate.pdf
        expect(result.fileErrors).toHaveLength(2) // invalid.exe and second duplicate.pdf
      })
    })

    describe('batch-level errors (block entire upload)', () => {
      test('blocks all files when max count exceeded', () => {
        const files = Array.from({ length: MAX_FILE_COUNT + 1 }, (_, i) => createFile(`doc${i}.pdf`))

        const result = validateFileUpload(files)

        expect(result.valid).toBe(false)
        expect(result.validFiles).toHaveLength(0)
        expect(result.batchErrors).toHaveLength(1)
        expect(result.batchErrors[0].code).toBe('MAX_FILES_EXCEEDED')
      })

      test('blocks all files when max count exceeded including existing', () => {
        const files = [createFile('new.pdf')]
        const context: ValidationContext = {
          existingTotalSize: 1024,
          existingFileCount: MAX_FILE_COUNT,
          existingFileNames: new Set(),
        }

        const result = validateFileUpload(files, context)

        expect(result.valid).toBe(false)
        expect(result.validFiles).toHaveLength(0)
        expect(result.batchErrors).toHaveLength(1)
        expect(result.batchErrors[0].code).toBe('MAX_FILES_EXCEEDED')
      })

      test('batch errors take precedence over file errors', () => {
        // When valid files exceed batch limit, batch error blocks all (even with file errors present)
        // Need MAX_FILE_COUNT + 1 valid files to trigger batch error
        const files = [
          ...Array.from({ length: MAX_FILE_COUNT + 1 }, (_, i) => createFile(`doc${i}.pdf`)),
          createFile('invalid.exe'), // This file-level error doesn't matter - batch error wins
        ]

        const result = validateFileUpload(files)

        expect(result.validFiles).toHaveLength(0) // Batch error blocks all
        expect(result.batchErrors).toHaveLength(1)
        expect(result.batchErrors[0].code).toBe('MAX_FILES_EXCEEDED')
        expect(result.fileErrors).toHaveLength(1) // File error is still recorded
      })
    })

    describe('summary generation', () => {
      test('generates summary for single file error', () => {
        const files = [createFile('invalid.exe')]

        const result = validateFileUpload(files)

        expect(result.summary).toContain('invalid.exe')
        expect(result.summary).toContain('not a supported file type')
      })

      test('generates summary for multiple file errors', () => {
        const files = [createFile('a.exe'), createFile('b.png')]

        const result = validateFileUpload(files)

        expect(result.summary).toContain('2 files have issues')
      })

      test('generates summary for batch errors', () => {
        const files = Array.from({ length: MAX_FILE_COUNT + 1 }, (_, i) => createFile(`doc${i}.pdf`))

        const result = validateFileUpload(files)

        expect(result.summary).toContain('file limit')
      })

      test('no summary for valid batch', () => {
        const files = [createFile('valid.pdf')]

        const result = validateFileUpload(files)

        expect(result.summary).toBeNull()
      })
    })

    describe('custom configuration', () => {
      test('uses custom accepted file types from config', () => {
        const customConfig = {
          acceptedTypes: '.csv,.json',
          acceptedMimeTypes: ['text/csv', 'application/json'],
          maxTotalSizeMB: 100,
          maxFileSize: 100 * 1024 * 1024,
          maxTotalSize: 100 * 1024 * 1024,
          maxFileCount: 10,
          fileExpirationCheckIntervalHours: 0,
        }

        // CSV should be valid with custom config
        expect(isValidFileExtension('data.csv', customConfig)).toBe(true)
        expect(isValidFileExtension('config.json', customConfig)).toBe(true)

        // PDF should be invalid with custom config (not in accepted types)
        expect(isValidFileExtension('document.pdf', customConfig)).toBe(false)
      })

      test('uses custom MIME types from config', () => {
        const customConfig = {
          acceptedTypes: '.csv,.json',
          acceptedMimeTypes: ['text/csv', 'application/json'],
          maxTotalSizeMB: 100,
          maxFileSize: 100 * 1024 * 1024,
          maxTotalSize: 100 * 1024 * 1024,
          maxFileCount: 10,
          fileExpirationCheckIntervalHours: 0,
        }

        expect(isValidMimeType('text/csv', customConfig)).toBe(true)
        expect(isValidMimeType('application/json', customConfig)).toBe(true)
        expect(isValidMimeType('application/pdf', customConfig)).toBe(false)
      })

      test('uses custom max file size from config', () => {
        const smallSizeConfig = {
          acceptedTypes: '.pdf,.txt',
          acceptedMimeTypes: ['application/pdf', 'text/plain'],
          maxTotalSizeMB: 1,
          maxFileSize: 1 * 1024 * 1024, // 1MB limit
          maxTotalSize: 1 * 1024 * 1024,
          maxFileCount: 10,
          fileExpirationCheckIntervalHours: 0,
        }

        // 500KB file should pass with 1MB limit
        const smallFile = createFile('small.pdf', 500 * 1024)
        const smallResult = validateFileUpload([smallFile], createEmptyValidationContext(), smallSizeConfig)
        expect(smallResult.valid).toBe(true)

        // 2MB file should fail with 1MB limit
        const largeFile = createFile('large.pdf', 2 * 1024 * 1024)
        const largeResult = validateFileUpload([largeFile], createEmptyValidationContext(), smallSizeConfig)
        expect(largeResult.valid).toBe(false)
        expect(largeResult.fileErrors[0].code).toBe('FILE_TOO_LARGE')
      })

      test('uses custom max file count from config', () => {
        const limitedConfig = {
          acceptedTypes: '.pdf,.txt',
          acceptedMimeTypes: ['application/pdf', 'text/plain'],
          maxTotalSizeMB: 100,
          maxFileSize: 100 * 1024 * 1024,
          maxTotalSize: 100 * 1024 * 1024,
          maxFileCount: 3, // Only 3 files allowed
          fileExpirationCheckIntervalHours: 0,
        }

        // 3 files should pass
        const threeFiles = [createFile('a.pdf'), createFile('b.pdf'), createFile('c.pdf')]
        const passResult = validateFileUpload(threeFiles, createEmptyValidationContext(), limitedConfig)
        expect(passResult.valid).toBe(true)
        expect(passResult.validFiles).toHaveLength(3)

        // 4 files should fail
        const fourFiles = [createFile('a.pdf'), createFile('b.pdf'), createFile('c.pdf'), createFile('d.pdf')]
        const failResult = validateFileUpload(fourFiles, createEmptyValidationContext(), limitedConfig)
        expect(failResult.valid).toBe(false)
        expect(failResult.batchErrors[0].code).toBe('MAX_FILES_EXCEEDED')
      })

      test('uses custom total size limit from config', () => {
        const smallTotalConfig = {
          acceptedTypes: '.pdf,.txt',
          acceptedMimeTypes: ['application/pdf', 'text/plain'],
          maxTotalSizeMB: 1,
          maxFileSize: 100 * 1024 * 1024, // Individual files can be large
          maxTotalSize: 1 * 1024 * 1024, // But total is limited to 1MB
          maxFileCount: 10,
          fileExpirationCheckIntervalHours: 0,
        }

        // Two 400KB files should pass (total 800KB < 1MB)
        const smallFiles = [createFile('a.pdf', 400 * 1024), createFile('b.pdf', 400 * 1024)]
        const passResult = validateFileUpload(smallFiles, createEmptyValidationContext(), smallTotalConfig)
        expect(passResult.valid).toBe(true)

        // Two 600KB files should fail (total 1.2MB > 1MB)
        const largeFiles = [createFile('a.pdf', 600 * 1024), createFile('b.pdf', 600 * 1024)]
        const failResult = validateFileUpload(largeFiles, createEmptyValidationContext(), smallTotalConfig)
        expect(failResult.valid).toBe(false)
        expect(failResult.batchErrors[0].code).toBe('TOTAL_SIZE_EXCEEDED')
      })

      test('validateFileUpload rejects files not in custom accepted types', () => {
        const customConfig = {
          acceptedTypes: '.csv,.json',
          acceptedMimeTypes: ['text/csv', 'application/json'],
          maxTotalSizeMB: 100,
          maxFileSize: 100 * 1024 * 1024,
          maxTotalSize: 100 * 1024 * 1024,
          maxFileCount: 10,
          fileExpirationCheckIntervalHours: 0,
        }

        const files = [createFile('data.pdf')]
        const result = validateFileUpload(files, createEmptyValidationContext(), customConfig)

        expect(result.valid).toBe(false)
        expect(result.fileErrors[0].code).toBe('INVALID_TYPE')
        expect(result.fileErrors[0].message).toContain('.csv,.json')
      })
    })
  })
})

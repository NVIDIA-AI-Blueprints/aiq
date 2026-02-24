// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, test, expect } from 'vitest'
import { mapBackendStatus, mapToDisplayStatus, normalizeFileName } from './utils'

describe('utils', () => {
  describe('mapBackendStatus', () => {
    test('maps uploading status', () => {
      expect(mapBackendStatus('uploading')).toBe('uploading')
    })

    test('maps ingesting status', () => {
      expect(mapBackendStatus('ingesting')).toBe('ingesting')
    })

    test('maps success status', () => {
      expect(mapBackendStatus('success')).toBe('success')
    })

    test('maps failed status', () => {
      expect(mapBackendStatus('failed')).toBe('failed')
    })

    test('defaults unknown status to uploading', () => {
      expect(mapBackendStatus('unknown' as never)).toBe('uploading')
    })
  })

  describe('mapToDisplayStatus', () => {
    test('maps uploading to uploading', () => {
      expect(mapToDisplayStatus('uploading')).toBe('uploading')
    })

    test('maps ingesting to ingesting', () => {
      expect(mapToDisplayStatus('ingesting')).toBe('ingesting')
    })

    test('maps success to available', () => {
      expect(mapToDisplayStatus('success')).toBe('available')
    })

    test('maps failed to error', () => {
      expect(mapToDisplayStatus('failed')).toBe('error')
    })

    test('defaults unknown status to uploading', () => {
      expect(mapToDisplayStatus('unknown' as never)).toBe('uploading')
    })
  })

  describe('normalizeFileName', () => {
    test('extracts original filename from tmp prefix pattern', () => {
      expect(normalizeFileName('tmp_m04en5b_original-file.pdf')).toBe('original-file.pdf')
    })

    test('handles various alphanumeric IDs', () => {
      expect(normalizeFileName('tmp_abc123_document.docx')).toBe('document.docx')
      expect(normalizeFileName('tmp_XYZ789_report.txt')).toBe('report.txt')
      expect(normalizeFileName('tmp_a1b2c3d4_file.md')).toBe('file.md')
    })

    test('preserves underscores in original filename', () => {
      expect(normalizeFileName('tmp_abc123_my_file_name.pdf')).toBe('my_file_name.pdf')
    })

    test('returns original if not matching tmp pattern', () => {
      expect(normalizeFileName('regular-file.pdf')).toBe('regular-file.pdf')
      expect(normalizeFileName('document.txt')).toBe('document.txt')
    })

    test('returns original for partial matches', () => {
      expect(normalizeFileName('tmp_file.pdf')).toBe('tmp_file.pdf') // Missing second underscore portion
      expect(normalizeFileName('tmp__file.pdf')).toBe('tmp__file.pdf') // Empty ID portion
    })

    test('handles empty string', () => {
      expect(normalizeFileName('')).toBe('')
    })

    test('handles filenames starting with tmp but not matching pattern', () => {
      expect(normalizeFileName('tmp-file.pdf')).toBe('tmp-file.pdf')
      expect(normalizeFileName('tmpfile.pdf')).toBe('tmpfile.pdf')
    })

    test('handles special characters in original filename', () => {
      expect(normalizeFileName('tmp_abc123_file (1).pdf')).toBe('file (1).pdf')
      expect(normalizeFileName('tmp_xyz789_report-2024.01.15.docx')).toBe('report-2024.01.15.docx')
    })
  })
})

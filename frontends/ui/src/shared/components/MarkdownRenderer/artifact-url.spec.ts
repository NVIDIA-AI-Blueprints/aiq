// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, test, expect } from 'vitest'
import { isArtifactRef, artifactIdFromRef, resolveArtifactUrl, rewriteArtifactRefs } from './artifact-url'

describe('artifact-url', () => {
  describe('isArtifactRef', () => {
    test('detects the artifact scheme', () => {
      expect(isArtifactRef('artifact://art_1')).toBe(true)
      expect(isArtifactRef('https://example.com/x.png')).toBe(false)
      expect(isArtifactRef(undefined)).toBe(false)
    })
  })

  describe('artifactIdFromRef', () => {
    test('strips the scheme and trims', () => {
      expect(artifactIdFromRef('artifact://  art_42 ')).toBe('art_42')
    })
  })

  describe('resolveArtifactUrl', () => {
    test('builds the same-origin content URL', () => {
      expect(resolveArtifactUrl('artifact://art_42', 'job-1')).toBe(
        '/api/jobs/async/job/job-1/artifacts/art_42/content'
      )
    })

    test('returns the original src for non-artifact refs', () => {
      expect(resolveArtifactUrl('https://example.com/x.png', 'job-1')).toBe(
        'https://example.com/x.png'
      )
    })

    test('returns the original src when job id is missing', () => {
      expect(resolveArtifactUrl('artifact://art_42', undefined)).toBe('artifact://art_42')
    })
  })

  describe('rewriteArtifactRefs', () => {
    test('rewrites every artifact image ref to a relative content URL', () => {
      const md = 'See ![Chart](artifact://art_1) and ![Other](artifact://art_2).'
      expect(rewriteArtifactRefs(md, 'job-1')).toBe(
        'See ![Chart](/api/jobs/async/job/job-1/artifacts/art_1/content) and ' +
          '![Other](/api/jobs/async/job/job-1/artifacts/art_2/content).'
      )
    })

    test('supports an absolute origin for downloaded markdown', () => {
      const md = '![Chart](artifact://art_1)'
      expect(rewriteArtifactRefs(md, 'job-1', 'https://host')).toBe(
        '![Chart](https://host/api/jobs/async/job/job-1/artifacts/art_1/content)'
      )
    })

    test('leaves markdown untouched without a job id', () => {
      const md = '![Chart](artifact://art_1)'
      expect(rewriteArtifactRefs(md, undefined)).toBe(md)
    })
  })
})

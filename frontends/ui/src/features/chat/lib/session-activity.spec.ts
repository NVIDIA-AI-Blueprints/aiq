// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Tests for session-activity utility functions
 */

import { describe, it, expect } from 'vitest'
import {
  hasActiveDeepResearchJob,
  hasCompletedDeepResearchReport,
  hasExpiredDeepResearchReport,
  getPersistedActivityFlags,
  hasNoUserChatMessages,
} from './session-activity'
import type { ChatMessage } from '../types'

/**
 * Helper to create a minimal ChatMessage for testing
 */
const makeMessage = (overrides: Partial<ChatMessage> = {}): ChatMessage => ({
  id: 'msg-1',
  role: 'assistant',
  content: '',
  timestamp: new Date(),
  ...overrides,
})

describe('hasNoUserChatMessages', () => {
  it('returns true when there are no user messages', () => {
    expect(hasNoUserChatMessages([])).toBe(true)
    expect(
      hasNoUserChatMessages([
        makeMessage({
          messageType: 'file_upload_status',
          fileUploadStatusData: { type: 'uploaded', fileCount: 1, jobId: 'j1' },
        }),
      ])
    ).toBe(true)
  })

  it('returns false when a user message exists', () => {
    expect(hasNoUserChatMessages([makeMessage({ messageType: 'user', content: 'hi' })])).toBe(false)
  })
})

describe('hasActiveDeepResearchJob', () => {
  it('returns false for empty message array', () => {
    expect(hasActiveDeepResearchJob([])).toBe(false)
  })

  it('returns false when no messages have deep research job IDs', () => {
    const messages = [
      makeMessage({ messageType: 'user' }),
      makeMessage({ messageType: 'agent_response' }),
    ]
    expect(hasActiveDeepResearchJob(messages)).toBe(false)
  })

  it('returns true when most recent job status is "submitted"', () => {
    const messages = [
      makeMessage({
        messageType: 'agent_response',
        deepResearchJobId: 'job-1',
        deepResearchJobStatus: 'submitted',
      }),
    ]
    expect(hasActiveDeepResearchJob(messages)).toBe(true)
  })

  it('returns true when most recent job status is "running"', () => {
    const messages = [
      makeMessage({
        messageType: 'agent_response',
        deepResearchJobId: 'job-1',
        deepResearchJobStatus: 'running',
      }),
    ]
    expect(hasActiveDeepResearchJob(messages)).toBe(true)
  })

  it('returns false when most recent job status is "success"', () => {
    const messages = [
      makeMessage({
        messageType: 'agent_response',
        deepResearchJobId: 'job-1',
        deepResearchJobStatus: 'success',
      }),
    ]
    expect(hasActiveDeepResearchJob(messages)).toBe(false)
  })

  it('returns false when most recent job status is "failure"', () => {
    const messages = [
      makeMessage({
        messageType: 'agent_response',
        deepResearchJobId: 'job-1',
        deepResearchJobStatus: 'failure',
      }),
    ]
    expect(hasActiveDeepResearchJob(messages)).toBe(false)
  })

  it('returns false when most recent job status is "interrupted"', () => {
    const messages = [
      makeMessage({
        messageType: 'agent_response',
        deepResearchJobId: 'job-1',
        deepResearchJobStatus: 'interrupted',
      }),
    ]
    expect(hasActiveDeepResearchJob(messages)).toBe(false)
  })

  it('checks MOST RECENT job message, not first', () => {
    const messages = [
      makeMessage({
        id: 'msg-old',
        messageType: 'agent_response',
        deepResearchJobId: 'job-1',
        deepResearchJobStatus: 'running',
      }),
      makeMessage({ id: 'msg-middle', messageType: 'user' }),
      makeMessage({
        id: 'msg-new',
        messageType: 'agent_response',
        deepResearchJobId: 'job-2',
        deepResearchJobStatus: 'success',
      }),
    ]
    // Most recent job (job-2) is success, so not active
    expect(hasActiveDeepResearchJob(messages)).toBe(false)
  })

  it('returns true when most recent job is running even if older jobs are complete', () => {
    const messages = [
      makeMessage({
        id: 'msg-old',
        messageType: 'agent_response',
        deepResearchJobId: 'job-1',
        deepResearchJobStatus: 'success',
      }),
      makeMessage({ id: 'msg-user', messageType: 'user' }),
      makeMessage({
        id: 'msg-new',
        messageType: 'agent_response',
        deepResearchJobId: 'job-2',
        deepResearchJobStatus: 'running',
      }),
    ]
    expect(hasActiveDeepResearchJob(messages)).toBe(true)
  })

  it('ignores messages without deepResearchJobId', () => {
    const messages = [
      makeMessage({
        messageType: 'agent_response',
        deepResearchJobId: 'job-1',
        deepResearchJobStatus: 'running',
      }),
      // Non-DR agent_response at the end — should be skipped
      makeMessage({
        id: 'msg-latest',
        messageType: 'agent_response',
        content: 'Just a regular response',
      }),
    ]
    // The latest agent_response with a job ID is job-1 (running)
    expect(hasActiveDeepResearchJob(messages)).toBe(true)
  })
})

describe('report status helpers', () => {
  it('returns true for completed report sessions with a visible report action', () => {
    const messages = [
      makeMessage({
        messageType: 'agent_response',
        deepResearchJobId: 'job-1',
        deepResearchJobStatus: 'success',
        showViewReport: true,
      }),
    ]

    expect(hasCompletedDeepResearchReport(messages)).toBe(true)
    expect(hasExpiredDeepResearchReport(messages)).toBe(false)
  })

  it('returns true for expired reports and does not also count them as completed', () => {
    const messages = [
      makeMessage({
        messageType: 'agent_response',
        deepResearchJobId: 'job-1',
        deepResearchJobStatus: 'failure',
        deepResearchReportExpired: true,
        showViewReport: false,
      }),
    ]

    expect(hasExpiredDeepResearchReport(messages)).toBe(true)
    expect(hasCompletedDeepResearchReport(messages)).toBe(false)
  })

  it('uses the latest deep research job message for report state', () => {
    const messages = [
      makeMessage({
        id: 'old-job',
        messageType: 'agent_response',
        deepResearchJobId: 'job-1',
        deepResearchJobStatus: 'success',
        showViewReport: true,
      }),
      makeMessage({
        id: 'latest-job',
        messageType: 'agent_response',
        deepResearchJobId: 'job-2',
        deepResearchJobStatus: 'failure',
        deepResearchReportExpired: true,
      }),
    ]

    expect(hasCompletedDeepResearchReport(messages)).toBe(false)
    expect(hasExpiredDeepResearchReport(messages)).toBe(true)
  })
})

describe('getPersistedActivityFlags', () => {
  it('returns all false for empty messages and no pending interaction', () => {
    const flags = getPersistedActivityFlags([], null)
    expect(flags.hasActiveDeepResearch).toBe(false)
    expect(flags.hasPendingHITL).toBe(false)
  })

  it('detects active deep research from messages', () => {
    const messages = [
      makeMessage({
        messageType: 'agent_response',
        deepResearchJobId: 'job-1',
        deepResearchJobStatus: 'running',
      }),
    ]
    const flags = getPersistedActivityFlags(messages, null)
    expect(flags.hasActiveDeepResearch).toBe(true)
    expect(flags.hasPendingHITL).toBe(false)
  })

  it('detects pending HITL interaction', () => {
    const flags = getPersistedActivityFlags([], { type: 'clarification', content: 'Approve?' })
    expect(flags.hasActiveDeepResearch).toBe(false)
    expect(flags.hasPendingHITL).toBe(true)
  })

  it('detects both active deep research and pending HITL', () => {
    const messages = [
      makeMessage({
        messageType: 'agent_response',
        deepResearchJobId: 'job-1',
        deepResearchJobStatus: 'submitted',
      }),
    ]
    const flags = getPersistedActivityFlags(messages, { type: 'clarification' })
    expect(flags.hasActiveDeepResearch).toBe(true)
    expect(flags.hasPendingHITL).toBe(true)
  })
})

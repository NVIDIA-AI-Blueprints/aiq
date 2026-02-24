// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Error Registry
 *
 * Centralized metadata for all error types used in the chat UI.
 * This registry makes it easy to maintain consistent error messages,
 * icons, and retry behavior across the application.
 */

import type { ErrorCode, ErrorCategory } from '../types'

/** Metadata for each error type */
export interface ErrorMeta {
  /** KUI Banner status */
  status: 'error' | 'warning' | 'info'
  /** Human-readable title */
  title: string
  /** Default message if none provided */
  defaultMessage: string
  /** Error category for grouping */
  category: ErrorCategory
  /** Whether the error is retryable */
  isRetryable: boolean
}

/**
 * Registry of all error types with their metadata.
 * Add new errors here to maintain consistency across the UI.
 */
export const ERROR_REGISTRY: Record<ErrorCode, ErrorMeta> = {
  // ============================================================
  // Connection Errors
  // ============================================================
  'connection.lost': {
    status: 'error',
    title: 'Connection Lost',
    defaultMessage: 'Lost connection to the server. Please check your network.',
    category: 'connection',
    isRetryable: true,
  },
  'connection.failed': {
    status: 'error',
    title: 'Connection Failed',
    defaultMessage: 'Unable to connect to the server. Please check your network connection.',
    category: 'connection',
    isRetryable: true,
  },
  'connection.timeout': {
    status: 'warning',
    title: 'Request Timeout',
    defaultMessage: 'The request took too long to complete.',
    category: 'connection',
    isRetryable: true,
  },

  // ============================================================
  // File Errors
  // ============================================================
  'file.upload_failed': {
    status: 'error',
    title: 'Upload Failed',
    defaultMessage: 'Failed to upload the file. Please try again.',
    category: 'file',
    isRetryable: true,
  },
  'file.too_large': {
    status: 'error',
    title: 'File Too Large',
    defaultMessage: 'The file exceeds the maximum allowed size.',
    category: 'file',
    isRetryable: false,
  },
  'file.invalid_type': {
    status: 'error',
    title: 'Invalid File Type',
    defaultMessage: 'This file type is not supported.',
    category: 'file',
    isRetryable: false,
  },
  'file.ingest_failed': {
    status: 'warning',
    title: 'Processing Failed',
    defaultMessage: 'Failed to process the file contents.',
    category: 'file',
    isRetryable: true,
  },

  // ============================================================
  // Auth Errors
  // ============================================================
  'auth.session_expired': {
    status: 'error',
    title: 'Session Expired',
    defaultMessage: 'Your session has expired. Please sign in again.',
    category: 'auth',
    isRetryable: false,
  },
  'auth.unauthorized': {
    status: 'error',
    title: 'Unauthorized',
    defaultMessage: 'You do not have permission to perform this action.',
    category: 'auth',
    isRetryable: false,
  },

  // ============================================================
  // Agent Errors
  // ============================================================
  'agent.response_failed': {
    status: 'error',
    title: 'Response Failed',
    defaultMessage: 'The assistant encountered an error generating a response.',
    category: 'agent',
    isRetryable: true,
  },
  'agent.response_interrupted': {
    status: 'warning',
    title: 'Response Interrupted',
    defaultMessage: 'Your previous request was not completed. Please resend your message.',
    category: 'agent',
    isRetryable: true,
  },
  'agent.tool_error': {
    status: 'error',
    title: 'Tool Error',
    defaultMessage: 'A tool the assistant was using encountered an error.',
    category: 'agent',
    isRetryable: true,
  },
  'agent.deep_research_failed': {
    status: 'error',
    title: 'Deep Research Failed',
    defaultMessage: 'The deep research process encountered an error.',
    category: 'agent',
    isRetryable: true,
  },

  // ============================================================
  // System Errors
  // ============================================================
  'system.unknown': {
    status: 'error',
    title: 'Something Went Wrong',
    defaultMessage: 'An unexpected error occurred. Please try again.',
    category: 'system',
    isRetryable: true,
  },
}

/**
 * Get error metadata by code.
 * Falls back to system.unknown if code not found.
 */
export const getErrorMeta = (code: ErrorCode): ErrorMeta => {
  return ERROR_REGISTRY[code] || ERROR_REGISTRY['system.unknown']
}

/**
 * Get the category from an error code.
 * Error codes use dot-notation: "category.specific_error"
 */
export const getErrorCategory = (code: ErrorCode): ErrorCategory => {
  return ERROR_REGISTRY[code]?.category || 'system'
}

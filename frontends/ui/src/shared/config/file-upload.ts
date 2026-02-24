// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { FileUploadConfig } from '@/shared/context'

const DEFAULT_ACCEPTED_TYPES = '.pdf,.md,.docx,.html,.txt'
const DEFAULT_MAX_SIZE_MB = 100
const DEFAULT_MAX_FILE_COUNT = 10
const DEFAULT_EXPIRATION_CHECK_INTERVAL_HOURS = 0

const EXTENSION_TO_MIME: Record<string, string[]> = {
  '.pdf': ['application/pdf'],
  '.md': ['text/markdown', 'text/x-markdown'],
  '.docx': ['application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
  '.html': ['text/html'],
  '.txt': ['text/plain'],
  '.csv': ['text/csv'],
  '.json': ['application/json'],
}

const parsePositiveNumber = (value: string | undefined): number | null => {
  if (!value) return null
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return null
  if (parsed <= 0) return null
  return parsed
}

export const buildAcceptedMimeTypes = (acceptedTypes: string): string[] => {
  const mimeTypes = new Set<string>()
  const extensions = acceptedTypes
    .split(',')
    .map((ext) => ext.toLowerCase().trim())
    .filter(Boolean)

  for (const ext of extensions) {
    const mimes = EXTENSION_TO_MIME[ext]
    if (!mimes) continue
    for (const mime of mimes) {
      mimeTypes.add(mime.toLowerCase())
    }
  }

  return Array.from(mimeTypes)
}

export const getFileUploadConfigFromEnv = (
  env: NodeJS.ProcessEnv = process.env
): FileUploadConfig => {
  const acceptedTypes = env.FILE_UPLOAD_ACCEPTED_TYPES || DEFAULT_ACCEPTED_TYPES
  const maxTotalSizeMB = parsePositiveNumber(env.FILE_UPLOAD_MAX_SIZE_MB) ?? DEFAULT_MAX_SIZE_MB
  const maxFileCount =
    parsePositiveNumber(env.FILE_UPLOAD_MAX_FILE_COUNT) ?? DEFAULT_MAX_FILE_COUNT
  const fileExpirationCheckIntervalHours =
    parsePositiveNumber(env.FILE_EXPIRATION_CHECK_INTERVAL_HOURS) ??
    DEFAULT_EXPIRATION_CHECK_INTERVAL_HOURS
  const maxSizeBytes = maxTotalSizeMB * 1024 * 1024

  return {
    acceptedTypes,
    acceptedMimeTypes: buildAcceptedMimeTypes(acceptedTypes),
    maxTotalSizeMB,
    maxFileSize: maxSizeBytes,
    maxTotalSize: maxSizeBytes,
    maxFileCount,
    fileExpirationCheckIntervalHours,
  }
}


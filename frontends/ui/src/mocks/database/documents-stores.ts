// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Document Stores
 *
 * Lightweight Map-based store for MSW mock data.
 * Uses existing Zod schemas from documents-schemas.ts for type safety.
 */

import type { ZodType } from 'zod'
import {
  CollectionInfoSchema,
  FileInfoSchema,
  IngestionJobStatusSchema,
  type CollectionInfo,
  type FileInfo,
  type IngestionJobStatus,
} from '@/adapters/api/documents-schemas'

/**
 * Simple in-memory store backed by a Map.
 * Drop-in replacement for @ngc-platform/mock-database Store.
 */
export class MockStore<T> {
  private data = new Map<string, T>()
  private getId: (item: T) => string
  private schema: ZodType<T>

  constructor(schema: ZodType<T>, getId: (item: T) => string) {
    this.schema = schema
    this.getId = getId
  }

  /** Insert a new item and return it. */
  insert(item: T): T {
    const parsed = this.schema.parse(item) as T
    this.data.set(this.getId(parsed), parsed)
    return parsed
  }

  /** Insert or update an item and return it. */
  upsert(item: T): T {
    const parsed = this.schema.parse(item) as T
    this.data.set(this.getId(parsed), parsed)
    return parsed
  }

  /** Remove an item from the store. */
  remove(item: T): void {
    this.data.delete(this.getId(item))
  }

  /** Get an item by its ID, or undefined if not found. */
  getById(id: string): T | undefined {
    return this.data.get(id)
  }

  /** Return all items matching the predicate. */
  query(predicate: (item: T) => boolean): T[] {
    return Array.from(this.data.values()).filter(predicate)
  }
}

/**
 * Create fresh document stores for the mock database.
 * Called by the database factory to ensure test isolation.
 */
export const createDocumentStores = () => ({
  collections: new MockStore<CollectionInfo>(CollectionInfoSchema, (c) => c.name),
  files: new MockStore<FileInfo>(FileInfoSchema, (f) => f.file_id),
  jobs: new MockStore<IngestionJobStatus>(IngestionJobStatusSchema, (j) => j.job_id),
})

export type DocumentStores = ReturnType<typeof createDocumentStores>

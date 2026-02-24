// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Mock Database
 *
 * Lightweight singleton database with relationship tracking.
 * Provides type-safe stores for collections, files, and jobs.
 */

import { createDocumentStores, MockStore } from './documents-stores'

// ============================================================================
// RelationType enum (replaces @ngc-platform/mock-database RelationType)
// ============================================================================

export enum RelationType {
  BELONGS_TO = 'BELONGS_TO',
}

// ============================================================================
// SimpleMockDatabase
// ============================================================================

/**
 * Minimal mock database container with relationship tracking.
 * Drop-in replacement for @ngc-platform/mock-database MockDatabase.
 */
class SimpleMockDatabase {
  /** Access stores via db.model.<group>.<store> */
  model = {
    documents: createDocumentStores(),
  }

  /**
   * Relationship index: "sourceId::relationType" -> Set of target IDs.
   * Keeps track of which items are related to which.
   */
  private relations = new Map<string, Set<string>>()

  /** Build a relationship key from a source item and relationship type. */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private relationKey(source: any, relationship: RelationType): string {
    // Identify source by whichever ID field it has
    const id = source.name ?? source.file_id ?? source.job_id ?? JSON.stringify(source)
    return `${id}::${relationship}`
  }

  /** Register a relationship between source and target items. */
  relate({
    source,
    relationship,
    target,
  }: {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    source: any
    relationship: RelationType
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    target: any
  }): void {
    const key = this.relationKey(source, relationship)
    if (!this.relations.has(key)) {
      this.relations.set(key, new Set())
    }
    const targetId = target.name ?? target.file_id ?? target.job_id ?? JSON.stringify(target)
    this.relations.get(key)!.add(targetId)
  }

  /**
   * Get all items in `target` store that are related to `source`.
   * Matches the @ngc-platform/mock-database getRelated signature.
   */
  getRelated<T>({
    source,
    relationship,
    target,
  }: {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    source: any
    relationship: RelationType
    target: MockStore<T>
  }): T[] {
    const key = this.relationKey(source, relationship)
    const relatedIds = this.relations.get(key)
    if (!relatedIds) return []

    const results: T[] = []
    for (const id of relatedIds) {
      const item = target.getById(id)
      if (item) results.push(item)
    }
    return results
  }
}

// ============================================================================
// Singleton
// ============================================================================

let db = new SimpleMockDatabase()

/**
 * Get the current database instance.
 * Use this in handlers to access stores.
 */
export const getDb = () => db

/**
 * Reset the database with fresh stores.
 * Use this for test isolation between test runs.
 */
export const resetDatabase = () => {
  db = new SimpleMockDatabase()
}

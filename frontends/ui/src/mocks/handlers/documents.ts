// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * MSW Handlers for Document APIs
 *
 * Stateful mock handlers that simulate file upload and ingestion.
 * Uses lightweight in-memory stores for type-safe state management.
 */

import { http, HttpResponse, delay } from 'msw'
import type {
  CollectionInfo,
  FileInfo,
  FileProgress,
  IngestionJobStatus,
} from '@/adapters/api/documents-schemas'
import type { DocumentFileStatus } from '@/features/documents/types'
import { getDb, RelationType, resetDatabase } from '../database'

// ============================================================================
// Job Processing State (for timing simulation)
// ============================================================================

// Track job processing state for async simulation
// This remains a Map because it's timing/simulation state, not persisted data
const jobProcessingState = new Map<
  string,
  {
    currentFileIndex: number
    currentPhase: 'uploading' | 'ingesting' | 'done'
    startTime: number
  }
>()

// ============================================================================
// Helper Functions
// ============================================================================

const generateId = () => crypto.randomUUID()

const now = () => new Date().toISOString()

// Simulate job progress based on elapsed time
// All files are processed CONCURRENTLY (upload together, then ingest together)
const updateJobProgress = (jobId: string): IngestionJobStatus | null => {
  const db = getDb()
  const jobEntity = db.model.documents.jobs.getById(jobId)

  if (!jobEntity) return null

  const job = { ...jobEntity } as IngestionJobStatus
  if (job.status === 'completed' || job.status === 'failed') {
    return job
  }

  const processingState = jobProcessingState.get(jobId)
  if (!processingState) {
    return job
  }

  const elapsed = Date.now() - processingState.startTime

  // Timing configuration (in ms) - CONCURRENT processing
  // All files upload together, then all files ingest together
  const UPLOAD_DURATION = 3 * 1000 // 3 seconds for all files to upload
  const INGEST_DURATION = 15 * 1000 // 15 seconds for all files to ingest
  const TOTAL_DURATION = UPLOAD_DURATION + INGEST_DURATION

  // Determine current phase based on elapsed time
  let currentPhase: 'uploading' | 'ingesting' | 'completed'
  let phaseProgress: number

  if (elapsed < UPLOAD_DURATION) {
    // Phase 1: All files uploading together
    currentPhase = 'uploading'
    phaseProgress = Math.min(100, Math.floor((elapsed / UPLOAD_DURATION) * 100))
  } else if (elapsed < TOTAL_DURATION) {
    // Phase 2: All files ingesting together
    currentPhase = 'ingesting'
    const ingestElapsed = elapsed - UPLOAD_DURATION
    phaseProgress = Math.min(100, Math.floor((ingestElapsed / INGEST_DURATION) * 100))
  } else {
    // Phase 3: All files complete
    currentPhase = 'completed'
    phaseProgress = 100
  }

  // Update ALL files to the same status (concurrent processing)
  const updatedFileDetails = job.file_details.map((fileDetail) => {
    const fileEntity = db.model.documents.files.getById(fileDetail.file_id)

    if (currentPhase === 'completed') {
      // All files are done
      if (fileEntity && fileEntity.status !== 'success') {
        db.model.documents.files.upsert({
          ...fileEntity,
          status: 'success',
          ingested_at: now(),
          chunk_count: Math.floor(Math.random() * 50) + 10,
        })
      }
      return {
        ...fileDetail,
        status: 'success' as DocumentFileStatus,
        progress_percent: 100,
      }
    } else if (currentPhase === 'ingesting') {
      // All files are ingesting
      if (fileEntity) {
        db.model.documents.files.upsert({ ...fileEntity, status: 'ingesting' })
      }
      return {
        ...fileDetail,
        status: 'ingesting' as DocumentFileStatus,
        progress_percent: phaseProgress,
      }
    } else {
      // All files are uploading
      if (fileEntity) {
        db.model.documents.files.upsert({ ...fileEntity, status: 'uploading' })
      }
      return {
        ...fileDetail,
        status: 'uploading' as DocumentFileStatus,
        progress_percent: phaseProgress,
      }
    }
  })

  // Update job status
  const completedFiles = currentPhase === 'completed' ? job.total_files : 0
  const updatedJob: IngestionJobStatus = {
    ...job,
    file_details: updatedFileDetails,
    processed_files: completedFiles,
  }

  if (currentPhase === 'completed') {
    updatedJob.status = 'completed'
    updatedJob.completed_at = now()

    // Update collection stats
    const collectionEntity = db.model.documents.collections.getById(job.collection_name)
    if (collectionEntity) {
      const totalChunks = updatedFileDetails.reduce((sum, f) => {
        const fileEntity = db.model.documents.files.getById(f.file_id)
        return sum + (fileEntity?.chunk_count || 0)
      }, 0)

      db.model.documents.collections.upsert({
        ...collectionEntity,
        file_count: job.total_files,
        chunk_count: totalChunks,
        updated_at: now(),
      })
    }

    jobProcessingState.delete(jobId)
  } else if (job.status === 'pending') {
    updatedJob.status = 'processing'
    updatedJob.started_at = now()
  }

  // Persist the updated job
  db.model.documents.jobs.upsert(updatedJob)

  return updatedJob
}

// ============================================================================
// Handlers
// ============================================================================

const baseUrl = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'

export const documentHandlers = [
  // --------------------------------------------------------------------------
  // Collections
  // --------------------------------------------------------------------------

  // POST /v1/collections - Create collection
  http.post(`${baseUrl}/v1/collections`, async ({ request }) => {
    await delay(200)

    const db = getDb()
    const body = (await request.json()) as { name: string; description?: string }
    const { name, description } = body

    // Check if collection already exists
    const existing = db.model.documents.collections.getById(name)
    if (existing) {
      return HttpResponse.json(
        { error: { code: 'COLLECTION_EXISTS', message: 'Collection already exists' } },
        { status: 409 }
      )
    }

    const collection: CollectionInfo = {
      name,
      description,
      file_count: 0,
      chunk_count: 0,
      created_at: now(),
      updated_at: now(),
      backend: 'mock',
      metadata: {},
    }

    db.model.documents.collections.insert(collection)

    return HttpResponse.json(collection, { status: 201 })
  }),

  // GET /v1/collections - List collections
  http.get(`${baseUrl}/v1/collections`, async () => {
    await delay(100)

    const db = getDb()
    const allCollections = db.model.documents.collections.query(() => true)

    return HttpResponse.json({
      collections: allCollections,
    })
  }),

  // GET /v1/collections/:name - Get collection
  http.get(`${baseUrl}/v1/collections/:name`, async ({ params }) => {
    await delay(100)

    const db = getDb()
    const { name } = params as { name: string }
    const collection = db.model.documents.collections.getById(name)

    if (!collection) {
      return HttpResponse.json(
        { error: { code: 'NOT_FOUND', message: 'Collection not found' } },
        { status: 404 }
      )
    }

    return HttpResponse.json(collection)
  }),

  // DELETE /v1/collections/:name - Delete collection
  http.delete(`${baseUrl}/v1/collections/:name`, async ({ params }) => {
    await delay(200)

    const db = getDb()
    const { name } = params as { name: string }

    const collection = db.model.documents.collections.getById(name)
    if (!collection) {
      return HttpResponse.json(
        { error: { code: 'NOT_FOUND', message: 'Collection not found' } },
        { status: 404 }
      )
    }

    // Delete associated files using relationship query
    const collectionFiles = db.getRelated({
      source: collection,
      relationship: RelationType.BELONGS_TO,
      target: db.model.documents.files,
    })

    for (const file of collectionFiles) {
      db.model.documents.files.remove(file)
    }

    // Delete the collection
    db.model.documents.collections.remove(collection)

    return new HttpResponse(null, { status: 204 })
  }),

  // --------------------------------------------------------------------------
  // Documents
  // --------------------------------------------------------------------------

  // POST /v1/collections/:name/documents - Upload files
  http.post(`${baseUrl}/v1/collections/:name/documents`, async ({ params, request }) => {
    await delay(300)

    const db = getDb()
    const { name: collectionName } = params as { name: string }

    // Ensure collection exists, create if not
    let collection = db.model.documents.collections.getById(collectionName)
    if (!collection) {
      const newCollection: CollectionInfo = {
        name: collectionName,
        description: `Auto-created collection for ${collectionName}`,
        file_count: 0,
        chunk_count: 0,
        created_at: now(),
        updated_at: now(),
        backend: 'mock',
        metadata: {},
      }
      collection = db.model.documents.collections.insert(newCollection)
    }

    // Parse multipart form data
    const formData = await request.formData()
    const uploadedFiles: File[] = []

    formData.forEach((value) => {
      if (value instanceof File) {
        uploadedFiles.push(value)
      }
    })

    if (uploadedFiles.length === 0) {
      return HttpResponse.json(
        { error: { code: 'NO_FILES', message: 'No files provided' } },
        { status: 400 }
      )
    }

    // Create file records and job
    const jobId = generateId()
    const fileIds: string[] = []
    const fileDetails: FileProgress[] = []

    for (const file of uploadedFiles) {
      const fileId = generateId()
      fileIds.push(fileId)

      const fileInfo: FileInfo = {
        file_id: fileId,
        file_name: file.name,
        collection_name: collectionName,
        status: 'uploading',
        file_size: file.size,
        chunk_count: 0,
        uploaded_at: now(),
        metadata: {},
      }

      const insertedFile = db.model.documents.files.insert(fileInfo)

      // Create relationship: collection -> file
      db.relate({
        source: collection,
        relationship: RelationType.BELONGS_TO,
        target: insertedFile,
      })

      fileDetails.push({
        file_id: fileId,
        file_name: file.name,
        status: 'uploading',
        progress_percent: 0,
      })
    }

    // Create ingestion job
    const job: IngestionJobStatus = {
      job_id: jobId,
      status: 'pending',
      submitted_at: now(),
      total_files: uploadedFiles.length,
      processed_files: 0,
      file_details: fileDetails,
      collection_name: collectionName,
      backend: 'mock',
      metadata: {},
    }

    const insertedJob = db.model.documents.jobs.insert(job)

    // Create relationship: collection -> job
    db.relate({
      source: collection,
      relationship: RelationType.BELONGS_TO,
      target: insertedJob,
    })

    // Start simulated processing
    jobProcessingState.set(jobId, {
      currentFileIndex: 0,
      currentPhase: 'uploading',
      startTime: Date.now(),
    })

    return HttpResponse.json(
      {
        job_id: jobId,
        file_ids: fileIds,
        message: 'Upload started',
      },
      { status: 202 }
    )
  }),

  // GET /v1/collections/:name/documents - List files
  http.get(`${baseUrl}/v1/collections/:name/documents`, async ({ params }) => {
    await delay(100)

    const db = getDb()
    const { name: collectionName } = params as { name: string }

    const collection = db.model.documents.collections.getById(collectionName)

    if (!collection) {
      // Return empty list if collection doesn't exist
      return HttpResponse.json({ files: [] })
    }

    // Get files using relationship query
    const collectionFiles = db.getRelated({
      source: collection,
      relationship: RelationType.BELONGS_TO,
      target: db.model.documents.files,
    })

    return HttpResponse.json({
      files: collectionFiles,
    })
  }),

  // DELETE /v1/collections/:name/documents - Delete files
  http.delete(`${baseUrl}/v1/collections/:name/documents`, async ({ params, request }) => {
    await delay(200)

    const db = getDb()
    const { name: collectionName } = params as { name: string }
    const body = (await request.json()) as { file_ids: string[] }
    const { file_ids } = body

    const collection = db.model.documents.collections.getById(collectionName)

    for (const fileId of file_ids) {
      const file = db.model.documents.files.getById(fileId)
      if (file && file.collection_name === collectionName) {
        if (collection) {
          // Update collection stats
          db.model.documents.collections.upsert({
            ...collection,
            file_count: Math.max(0, collection.file_count - 1),
            chunk_count: Math.max(0, collection.chunk_count - file.chunk_count),
            updated_at: now(),
          })
        }
        db.model.documents.files.remove(file)
      }
    }

    return new HttpResponse(null, { status: 204 })
  }),

  // --------------------------------------------------------------------------
  // Job Status (Polling)
  // --------------------------------------------------------------------------

  // GET /v1/documents/:jobId/status - Get job status
  http.get(`${baseUrl}/v1/documents/:jobId/status`, async ({ params }) => {
    // Small delay to simulate network
    await delay(50)

    const { jobId } = params as { jobId: string }

    // Update job progress based on elapsed time
    const job = updateJobProgress(jobId)

    if (!job) {
      return HttpResponse.json(
        { error: { code: 'NOT_FOUND', message: 'Job not found' } },
        { status: 404 }
      )
    }

    return HttpResponse.json(job)
  }),
]

// ============================================================================
// Utility for tests - reset state
// ============================================================================

export const resetDocumentMockState = () => {
  resetDatabase()
  jobProcessingState.clear()
}

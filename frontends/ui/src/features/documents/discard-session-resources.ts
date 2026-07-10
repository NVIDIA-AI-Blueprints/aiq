// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Tear down documents state and delete the backend collection for a chat session id.
 * Used when abandoning upload-only sessions (no user chat messages).
 */

import { createDocumentsClient } from '@/adapters/api'
import { removePersistedJobForCollection, unmarkSessionCollection } from './persistence'
import { UploadOrchestrator } from './orchestrator'
import { useDocumentsStore } from './store'

export const discardSessionDocumentsResources = (sessionId: string): void => {
  UploadOrchestrator.stopPollingIfCollection(sessionId)
  unmarkSessionCollection(sessionId)
  removePersistedJobForCollection(sessionId)

  const docs = useDocumentsStore.getState()
  docs.clearFilesForCollection(sessionId)
  if (docs.currentCollectionName === sessionId) {
    docs.setCurrentCollection(null)
    docs.setCollectionInfo(null)
  }

  void createDocumentsClient({}).deleteCollection(sessionId).catch((err) => {
    console.warn('Failed to delete documents collection for discarded session:', sessionId, err)
  })
}

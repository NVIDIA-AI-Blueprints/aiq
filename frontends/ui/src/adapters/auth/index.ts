// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Auth Adapters
 *
 * Client-safe authentication exports for use in features.
 * Server-only auth config must be imported from '@/adapters/auth/config'.
 */

// Session hooks (client-side)
export { useAuth } from './session'

// Types
export type { AuthState, AuthActions, AuthContext } from './types'

// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Auth Adapters
 *
 * Re-exports all authentication-related functionality for use in features.
 * Features should import from '@/adapters/auth' only.
 */

// Configuration
export { authOptions, validateAuthEnv, isAuthRequired, shouldUseSecureCookies } from './config'

// Session hooks (client-side)
export { useAuth } from './session'

// Types
export type { AuthState, AuthActions, AuthContext } from './types'

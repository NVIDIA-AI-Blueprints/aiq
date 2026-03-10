// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Auth Provider Registry (swap-point)
 *
 * This file is the SOLE file that changes when enabling or disabling
 * authentication. Everything else in the auth adapter layer (config.ts,
 * session.ts, types.ts, proxy.ts) is provider-agnostic.
 *
 * DEFAULT: Returns a null provider (auth disabled, "Default User" mode).
 *
 * TO ENABLE AUTH:
 *   1. Create a provider file in this directory (see ./auth-example.ts for a template)
 *   2. Replace getAuthProviderConfig() below to return your provider:
 *
 *        import { MyProvider, refreshMyToken } from './my-provider'
 *
 *        export const getAuthProviderConfig = (): AuthProviderConfig => ({
 *          provider: MyProvider,
 *          providerId: 'my-provider-id',
 *          refreshToken: refreshMyToken,
 *        })
 *
 *   3. Set REQUIRE_AUTH=true and provider-specific env vars
 */

import type { AuthProviderConfig } from './types'

export type { AuthProviderConfig, TokenRefreshResult } from './types'

/**
 * Returns the active auth provider configuration.
 * Default: null provider (authentication disabled).
 */
export const getAuthProviderConfig = (): AuthProviderConfig => ({
  provider: null,
  providerId: 'disabled-auth',
  refreshToken: async () => {
    throw new Error('No auth provider configured')
  },
})

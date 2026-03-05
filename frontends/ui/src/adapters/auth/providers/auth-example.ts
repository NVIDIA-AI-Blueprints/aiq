// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * InternalAuth OIDC Provider (reference implementation)
 *
 * A complete OIDC provider for private/internal identity providers.
 * This file is NOT imported by ./index.ts by default -- it exists as a
 * working, type-checked reference for anyone creating a new provider.
 *
 * To use this provider:
 *   1. Update ./index.ts to import and return it via getAuthProviderConfig()
 *   2. Set environment variables:
 *        REQUIRE_AUTH=true
 *        INTERNAL_AUTH_CLIENT_ID or INTERNAL_AUTH_CLIENT_ID_BROWSER
 *        INTERNAL_AUTH_CLIENT_SECRET
 *        INTERNAL_AUTH_ISSUER  (recommended -- enables OIDC auto-discovery)
 *   3. Optional env vars for manual endpoint configuration:
 *        INTERNAL_AUTH_AUTH_URL
 *        INTERNAL_AUTH_TOKEN_URL
 *        INTERNAL_AUTH_USERINFO_URL
 *        INTERNAL_AUTH_PROVIDER_ID  (override callback path, default: internalauth)
 *
 * Example ./index.ts when this provider is active:
 *
 *   import { InternalAuthProvider, getInternalAuthProviderId, refreshInternalAuthToken } from './internal-auth'
 *   import type { AuthProviderConfig } from './types'
 *
 *   export type { AuthProviderConfig, TokenRefreshResult } from './types'
 *
 *   export const getAuthProviderConfig = (): AuthProviderConfig => ({
 *     provider: InternalAuthProvider,
 *     providerId: getInternalAuthProviderId(),
 *     refreshToken: refreshInternalAuthToken,
 *   })
 */

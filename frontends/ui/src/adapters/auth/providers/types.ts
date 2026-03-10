// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Auth Provider Contract
 *
 * Defines the interface that any authentication provider must implement.
 * See ./auth-example.ts for a documentation template and implementation checklist.
 *
 * To add a new provider:
 *   1. Create a new file in this directory (e.g. my-provider.ts)
 *   2. Export a provider object and refresh function
 *   3. Update ./index.ts to import and return them via getAuthProviderConfig()
 */

/**
 * Result shape returned by a provider's token refresh function.
 * Follows the standard OAuth2 token response fields.
 */
export interface TokenRefreshResult {
  access_token: string
  id_token?: string
  expires_in: number
  refresh_token?: string
}

/**
 * Configuration returned by getAuthProviderConfig().
 *
 * - provider: The NextAuth-compatible provider object, or null when auth is disabled.
 * - providerId: The unique ID used in signIn(providerId) calls (must match provider.id).
 * - refreshToken: Function to refresh an expired access token using a refresh token.
 */
export interface AuthProviderConfig {
  provider: Record<string, unknown> | null
  providerId: string
  refreshToken: (refreshToken: string) => Promise<TokenRefreshResult>
}

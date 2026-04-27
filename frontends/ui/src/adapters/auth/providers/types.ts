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
 * Parameters passed to the onSignIn lifecycle hook.
 * These are the same objects NextAuth provides in its JWT callback
 * on the initial sign-in (when `account` and `user` are present).
 */
export interface SignInHookParams {
  /** The JWT being constructed (already populated with base token fields) */
  token: Record<string, unknown>
  /** The OAuth account object from the identity provider */
  account: Record<string, unknown>
  /** The user profile returned by the identity provider */
  user: Record<string, unknown>
}

/**
 * Parameters passed to the onSession lifecycle hook.
 * Called every time the NextAuth session callback fires (on every session check).
 */
export interface SessionHookParams {
  /** The session object being returned to the client */
  session: Record<string, unknown>
  /** The server-side JWT token (source of truth for all token data) */
  token: Record<string, unknown>
}

/**
 * Configuration returned by getAuthProviderConfig().
 *
 * - provider: The NextAuth-compatible provider object, or null when auth is disabled.
 * - providerId: The unique ID used in signIn(providerId) calls (must match provider.id).
 * - refreshToken: Function to refresh an expired access token using a refresh token.
 *
 * Optional lifecycle hooks allow providers to inject custom behavior (e.g. DL group
 * gating, custom claims) without replacing the entire config.ts file:
 *
 * - onSignIn: Enrich the JWT on initial sign-in (e.g. check group membership)
 * - onSession: Add provider-specific fields to the session object
 * - tokenRefreshBufferSeconds: Override the default refresh buffer
 * - requiredEnvVars: Additional env vars to check in validateAuthEnv()
 */
export interface AuthProviderConfig {
  provider: Record<string, unknown> | null
  providerId: string
  refreshToken: (refreshToken: string) => Promise<TokenRefreshResult>

  /**
   * Called after initial OAuth sign-in to enrich the JWT with provider-specific claims.
   * Return an object whose keys are merged into the JWT token. Core token
   * fields win on key collisions to avoid corrupting token rotation state.
   *
   * @example
   * ```ts
   * onSignIn: async ({ user }) => {
   *   const hasAccess = await checkGroupMembership(user.email)
   *   return { hasAccess, groupName: 'my-group' }
   * }
   * ```
   *
   * Throwing from this hook is treated as a provider integration failure:
   * the error is logged and the base JWT is returned. Return explicit claims
   * such as `{ hasAccess: false }` for intentional access denial.
   */
  onSignIn?: (params: SignInHookParams) => Promise<Record<string, unknown>>

  /**
   * Called during every session callback to surface provider-specific fields.
   * Return an object whose keys are merged into the session sent to the client.
   * Core session fields win on key collisions.
   *
   * @example
   * ```ts
   * onSession: ({ token }) => ({
   *   hasAccess: token.hasAccess ?? true,
   *   groupName: token.groupName,
   * })
   * ```
   */
  onSession?: (params: SessionHookParams) => Record<string, unknown>

  /**
   * Provider-specific token refresh buffer override (in seconds).
   * When set, takes precedence over the TOKEN_REFRESH_BUFFER_MINUTES env var.
   * Use this when the provider knows the optimal refresh timing for its token
   * lifetimes or long-running operations.
   */
  tokenRefreshBufferSeconds?: number

  /**
   * Additional environment variables required by this provider.
   * Checked by validateAuthEnv() alongside the base NEXTAUTH_URL/SECRET.
   *
   * @example ['MY_SSO_CLIENT_ID', 'MY_SSO_ISSUER']
   */
  requiredEnvVars?: string[]
}

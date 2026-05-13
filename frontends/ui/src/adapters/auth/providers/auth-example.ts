// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * InternalAuth OIDC Provider template
 *
 * This file is intentionally documentation-only. It is NOT imported by
 * `./index.ts`, and it does not export runnable code. Use it as a checklist
 * for creating your own provider file in this directory.
 *
 * To add a real provider:
 *   1. Create a new file in this directory (for example `my-sso.ts`)
 *   2. Export:
 *        - a NextAuth-compatible provider object
 *        - a provider ID string
 *        - a token refresh function matching `TokenRefreshResult`
 *   3. Update `./index.ts` to return those exports from
 *      `getAuthProviderConfig()`
 *
 * Typical env vars for an internal OIDC provider:
 *   - REQUIRE_AUTH=true
 *   - INTERNAL_AUTH_CLIENT_ID or INTERNAL_AUTH_CLIENT_ID_BROWSER
 *   - INTERNAL_AUTH_CLIENT_SECRET
 *   - INTERNAL_AUTH_ISSUER  (recommended -- enables OIDC auto-discovery)
 *
 * Optional env vars for manual endpoint configuration:
 *   - INTERNAL_AUTH_AUTH_URL
 *   - INTERNAL_AUTH_TOKEN_URL
 *   - INTERNAL_AUTH_USERINFO_URL
 *   - INTERNAL_AUTH_PROVIDER_ID  (override callback path, default: internalauth)
 *
 * LIFECYCLE HOOKS (optional):
 *
 *   onSignIn({ token, account, user }) → Promise<Record<string, unknown>>
 *     Called once after initial OAuth callback. Use to check group membership,
 *     enrich the JWT with custom claims, or gate access. Returned object is
 *     merged into the JWT. Throwing is logged and falls back to the base JWT;
 *     return explicit claims such as { hasAccess: false } to deny access.
 *
 *   onSession({ session, token }) → Record<string, unknown>
 *     Called on every session check. Use to surface provider-specific fields
 *     (e.g. hasAccess, groupName) to the client. Returned object is merged
 *     into the session.
 *
 *   tokenRefreshBufferSeconds: number
 *     Override the default TOKEN_REFRESH_BUFFER_MINUTES. Use when the provider
 *     knows the optimal refresh timing for its token lifetimes.
 *
 *   requiredEnvVars: string[]
 *     Additional env vars validated by validateAuthEnv() on startup.
 *
 * Example with hooks:
 *
 *   export const getAuthProviderConfig = (): AuthProviderConfig => ({
 *     provider: MyOIDCProvider,
 *     providerId: 'my-sso',
 *     refreshToken: refreshMyToken,
 *     tokenRefreshBufferSeconds: 30 * 60,
 *     requiredEnvVars: ['MY_SSO_CLIENT_ID'],
 *     onSignIn: async ({ user }) => {
 *       const hasAccess = await checkGroupMembership(user.email as string)
 *       return { hasAccess, groupName: process.env.MY_GROUP }
 *     },
 *     onSession: ({ token }) => ({
 *       hasAccess: token.hasAccess ?? true,
 *       groupName: token.groupName,
 *     }),
 *   })
 */

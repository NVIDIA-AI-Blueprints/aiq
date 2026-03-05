// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// ---------------------------------------------------------------------------
// InternalAuth OIDC Provider  (DISABLED — all code commented out)
// ---------------------------------------------------------------------------
//
// This file contains a complete InternalAuth OIDC provider for private/internal
// identity providers. It is disabled by default because the public aiq repo
// ships with authentication disabled (default user, no login required).
//
// TO ENABLE (e.g. for aiq-bp-internal deployments):
//   1. Uncomment all code below
//   2. Update ./index.ts to re-export the symbols from this file
//   3. Restore the provider imports and wiring in ../config.ts
//   4. Set environment variables:
//        AUTH_PROVIDER=internalauth
//        REQUIRE_AUTH=true
//        INTERNAL_AUTH_CLIENT_ID or INTERNAL_AUTH_CLIENT_ID_BROWSER
//        INTERNAL_AUTH_CLIENT_SECRET
//        INTERNAL_AUTH_ISSUER  (recommended — enables OIDC auto-discovery)
//   5. Optional env vars for manual endpoint configuration:
//        INTERNAL_AUTH_AUTH_URL
//        INTERNAL_AUTH_TOKEN_URL
//        INTERNAL_AUTH_USERINFO_URL
//        INTERNAL_AUTH_PROVIDER_ID  (override callback path, default: internalauth)
// ---------------------------------------------------------------------------

// import { type Profile } from 'next-auth'
//
// export const getInternalAuthClientId = (): string | undefined => {
//   return process.env.INTERNAL_AUTH_CLIENT_ID_BROWSER || process.env.INTERNAL_AUTH_CLIENT_ID
// }
//
// export const getInternalAuthProviderId = (): string => {
//   return process.env.INTERNAL_AUTH_PROVIDER_ID || 'internalauth'
// }
//
// const issuer = process.env.INTERNAL_AUTH_ISSUER
//
// export const InternalAuthProvider = {
//   id: getInternalAuthProviderId(),
//   name: 'InternalAuth',
//   type: 'oauth' as const,
//
//   wellKnown: issuer ? `${issuer}/.well-known/openid-configuration` : undefined,
//
//   authorization: {
//     url: process.env.INTERNAL_AUTH_AUTH_URL || (issuer ? `${issuer}/authorize` : ''),
//     params: {
//       scope: 'openid profile email',
//       response_type: 'code',
//       code_challenge_method: 'S256',
//     },
//   },
//
//   token: {
//     url: process.env.INTERNAL_AUTH_TOKEN_URL || (issuer ? `${issuer}/token` : ''),
//   },
//   userinfo: {
//     url: process.env.INTERNAL_AUTH_USERINFO_URL || (issuer ? `${issuer}/userinfo` : ''),
//   },
//
//   clientId: getInternalAuthClientId(),
//   clientSecret: process.env.INTERNAL_AUTH_CLIENT_SECRET || '',
//
//   checks: ['pkce', 'state'] as ('pkce' | 'state' | 'nonce')[],
//
//   // Keep ES256 because many internal IdPs issue ES256-signed ID tokens.
//   client: {
//     id_token_signed_response_alg: 'ES256',
//   },
//
//   idToken: true,
//
//   profile(profile: Profile & { sub: string; email: string; name: string; picture?: string }) {
//     return {
//       id: profile.sub,
//       email: profile.email,
//       name: profile.name,
//       image: profile.picture,
//     }
//   },
// }
//
// /**
//  * Refresh the access token using the InternalAuth token endpoint.
//  * Retries once after a short delay to handle transient network errors.
//  * Bails immediately on invalid_grant (revoked refresh token).
//  */
// export const refreshInternalAuthToken = async (
//   refreshToken: string
// ): Promise<{
//   access_token: string
//   id_token?: string
//   expires_in: number
//   refresh_token?: string
// }> => {
//   const tokenUrl = process.env.INTERNAL_AUTH_TOKEN_URL || (issuer ? `${issuer}/token` : '')
//   const maxAttempts = 2
//   let lastError: unknown
//
//   for (let attempt = 1; attempt <= maxAttempts; attempt++) {
//     try {
//       const response = await fetch(tokenUrl, {
//         method: 'POST',
//         headers: {
//           'Content-Type': 'application/x-www-form-urlencoded',
//         },
//         body: new URLSearchParams({
//           grant_type: 'refresh_token',
//           refresh_token: refreshToken,
//           client_id: getInternalAuthClientId() || '',
//           client_secret: process.env.INTERNAL_AUTH_CLIENT_SECRET || '',
//         }),
//       })
//
//       const refreshedTokens = await response.json()
//
//       if (!response.ok) {
//         if (refreshedTokens.error === 'invalid_grant') {
//           console.error('[Auth] Refresh token revoked (invalid_grant)')
//           throw refreshedTokens
//         }
//         throw refreshedTokens
//       }
//
//       return refreshedTokens
//     } catch (error) {
//       lastError = error
//       if ((error as { error?: string })?.error === 'invalid_grant') {
//         throw lastError
//       }
//       if (attempt < maxAttempts) {
//         console.warn(`[Auth] Token refresh attempt ${attempt} failed, retrying...`)
//         await new Promise((resolve) => setTimeout(resolve, 1000))
//       }
//     }
//   }
//
//   throw lastError
// }

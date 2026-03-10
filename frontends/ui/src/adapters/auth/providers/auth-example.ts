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
 */

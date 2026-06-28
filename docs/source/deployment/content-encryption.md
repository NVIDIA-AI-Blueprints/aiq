<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Async Final Report Encryption

AI-Q can encrypt async job final reports before they are persisted in
`job_info.output`. This is application-level envelope encryption for the
AI-Q async jobs API.

This feature is intentionally narrow in its first milestone. It protects only
the serialized final output payload returned by
`GET /v1/jobs/async/job/{job_id}/report`, such as `{"report": "..."}`.

## Scope and Limitations

Encrypted when enabled:

- `job_info.output` for jobs submitted through `/v1/jobs/async/submit` or
  `aiq_api.jobs.submit.submit_agent_job`.

Still plaintext:

- `job_events.event_data`, including tool events, artifact updates, heartbeat
  events, cancellation events, error events, and possible final-report
  duplicates emitted through events.
- Job status, ownership metadata, timestamps, event type, and other control
  plane fields.
- `job_info.error`.
- PostgreSQL notification payloads.
- `summaries.summary`.
- LangGraph checkpoints in `aiq_checkpoints`.
- Historical rows written before encryption was enabled.
- Inline CLI and local NeMo Agent Toolkit runs that do not use the AI-Q async
  API job runner.

Because events and checkpoints can contain equivalent research content, this
phase does not provide full database-level job-content confidentiality.

## Modes

Set `AIQ_CONTENT_ENCRYPTION` on every API and worker process.

| Mode | Behavior |
|------|----------|
| `off` | Default. Preserves existing plaintext behavior and never attempts to decrypt `aiqenc:` values. |
| `key` | Uses one operator-managed static 32-byte key to wrap per-job data encryption keys. Intended only for development, testing, or deployments that cannot use Vault. |
| `vault` | Uses HashiCorp Vault Transit to generate and wrap per-job data encryption keys. Recommended for production. |

Encrypted values are stored as `aiqenc:` envelopes. The envelope contains
non-secret metadata, the wrapped data encryption key, nonce, ciphertext, tag,
algorithm, key id, and an AAD hint that binds the value to
`job_info.output:{job_id}`.

## Static Key Configuration

Static key mode requires a base64 or base64url value that decodes to exactly
32 raw bytes.

```bash
AIQ_CONTENT_ENCRYPTION=key
AIQ_CONTENT_ENCRYPTION_KEY=<base64url-encoded-32-byte-key>
AIQ_CONTENT_ENCRYPTION_KEY_ID=<operator-managed-key-id>
```

`AIQ_CONTENT_ENCRYPTION_KEY_ID` is optional metadata. If omitted, envelopes use
`static-key` as the key id. The first implementation supports one active static
key only; rotation requires jobs encrypted with the previous key to expire or a
future rewrap/backfill process.

Invalid static-key configuration fails startup.

## Vault Transit Configuration

Vault mode uses AppRole authentication and Transit data keys. Token fallback is
not supported in the first implementation.

```bash
AIQ_CONTENT_ENCRYPTION=vault
VAULT_ADDR=<vault-address>
VAULT_ROLE_ID=<approle-role-id>
VAULT_SECRET_ID=<approle-secret-id>
AIQ_ENCRYPTION_TRANSIT_KEY=<transit-key-name>
VAULT_TRANSIT_MOUNT=<transit-mount>
AIQ_CONTENT_ENCRYPTION_KEY_ID=<logical-key-id>
```

`VAULT_TRANSIT_MOUNT` defaults to `transit` if omitted.
`AIQ_CONTENT_ENCRYPTION_KEY_ID` is optional; if omitted, envelopes use
`<transit-mount>/<transit-key-name>`.

Set `VAULT_NAMESPACE=<vault-namespace>` only when your Vault deployment
requires a namespace.

Missing Vault configuration fails startup. If Vault configuration is present
but Vault is temporarily unreachable, unauthorized, or otherwise operationally
unready, the API starts unhealthy instead of exiting.

The application relies on Vault Transit versioned ciphertext for decrypting
after Transit key rotation. Do not disable or destroy old Transit key versions
until corresponding encrypted jobs have expired or have been rewrapped by a
future migration process.

## Rollout Behavior

The first implementation is forward-only:

- New `job_info.output` writes are encrypted after enablement.
- Existing plaintext `job_info.output` rows are intentionally unreadable while
  `AIQ_CONTENT_ENCRYPTION=key` or `vault`.
- No historical plaintext backfill is included.
- No rewrap tooling is included.

Enable encryption only after operators accept that old plaintext final-report
rows cannot be read in encrypted modes until a future backfill exists.

## Health and Failure Behavior

`/health` includes encryption readiness. When encryption is configured but
unready, `/health` returns HTTP 503 and new async submissions are rejected with
HTTP 503.

Workers independently validate encryption before marking a job `RUNNING`. If
encryption is unavailable at worker startup, the job is marked `FAILURE` and
the agent does not run.

If final-report encryption or encrypted persistence fails after an agent has
completed, the job is marked `FAILURE`. The worker does not fall back to writing
plaintext output.

Report reads fail closed:

- Vault or crypto unavailability returns HTTP 503.
- Plaintext, malformed, or undecryptable `job_info.output` in encrypted mode
  returns HTTP 500.
- Job access is authorized before decryption is attempted.

## Cache

Decrypt paths use an in-memory plaintext data encryption key cache per process.
The default TTL is 15 minutes with a maximum of 1024 entries. Set
`AIQ_CONTENT_ENCRYPTION_DEK_CACHE_TTL_SECONDS=0` to disable this cache.

The readiness cache defaults to 60 seconds. Health checks and submit requests
reuse the cached state until it becomes stale. Set
`AIQ_CONTENT_ENCRYPTION_READINESS_TTL_SECONDS` to override the default.

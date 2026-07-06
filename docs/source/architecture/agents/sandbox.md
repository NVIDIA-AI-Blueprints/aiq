<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Deep Research Sandbox Notes

Deep research can optionally run DeepAgents `execute` calls through a sandbox provider
(Modal, OpenShell, or any registered provider). Modal creates a sandbox per job. The
experimental OpenShell path attaches to a pre-created named sandbox shared by its jobs;
job-scoped directories prevent filename collisions but are not a security boundary.

The sandbox is an internal execution detail. There are no sandbox-specific API
endpoints, and job-level auth remains responsible for submit, stream, status,
cancel, state, and report access. The one user-visible surface is the artifact
runtime (`.../job/{job_id}/artifacts`), which is also auth-scoped to the job.

> **Developer reference:** the full architecture, provider contract, config schema,
> artifact pipeline, and troubleshooting live next to the code in
> [`src/aiq_agent/agents/deep_researcher/sandbox/README.md`](../../../../src/aiq_agent/agents/deep_researcher/sandbox/README.md).

## Current Behavior

- Modal uses one sandbox per deep research job. OpenShell currently attaches jobs to
  the configured shared sandbox name and is intended for local, single-operator testing.
- Synchronous sandbox-enabled runs use an internal per-agent runtime ID.
- Providers are selected by config (`sandbox.provider` + `providers.<name>`); the
  provider is validated against the registry and gated by its declared capabilities.
  OpenShell policy is provisioned externally and is not verified when AI-Q attaches.
- Job IDs must satisfy each provider's object-name rules (Modal: 64 chars or fewer,
  alphanumeric plus dash/period/underscore).
- `timeout` bounds individual execution. Other lifecycle controls are provider-dependent.
- Files written inside the workdir are temporary scratch state. Durable text should
  be written through DeepAgents virtual paths such as `/shared/`; durable binaries
  (charts, CSVs) are captured by the artifact runtime.

## Artifact Storage

Metadata for generated files such as charts and CSVs is stored in SQL. File content can
also be stored in SQL, but object storage such as AWS S3 or MinIO is recommended for
production deployments. The selected artifact storage provider determines where the file
content is stored.

For configuration variables and examples, see [Docker Compose](../../deployment/docker-compose.md#artifact-storage)
and [Production Considerations](../../deployment/production.md#artifact-storage).

## Operational Notes

- High-concurrency Modal runs create one sandbox per job. OpenShell runs share the named
  sandbox and must not be used concurrently for mutually untrusted jobs. Optional submit-path
  caps (`AIQ_MAX_SANDBOXES_PER_PRINCIPAL` / `AIQ_MAX_SANDBOXES_GLOBAL`, default-off) bound
  concurrency/cost but do not provide filesystem isolation.
- Custom client-supplied job IDs must not be reused for a new job.
- The runtime closes provider sessions on success, failure, cancellation, and timeout.
  A named OpenShell sandbox persists when `delete_on_exit` is disabled.

## Current Safeguards

The following safeguards are in place:

- Explicit sandbox cleanup on success, failure, cancellation, and timeout.
- Idempotency-gated retry-on-stale-container handling.
- Artifact capture for generated charts/binaries (validate -> store -> serve/embed),
  with MIME-from-bytes spoof rejection, SVG sanitization, and an inline-render allowlist.
- Sandbox quota and concurrency controls, and artifact retention via job-expiry cleanup.
- Structured lifecycle logging for sandbox create, reuse, failure, and cleanup.

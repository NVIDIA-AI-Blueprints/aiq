<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Deep Research Sandbox Notes

Deep research can optionally run DeepAgents `execute` calls in a provider-neutral
sandbox (Modal, OpenShell, or any registered provider). Sandboxes are scoped to a
single async job: the sandbox name is the resolved job ID, so unrelated jobs never
share filesystem state.

The sandbox is an internal execution detail. There are no sandbox-specific API
endpoints, and job-level auth remains responsible for submit, stream, status,
cancel, state, and report access. The one user-visible surface is the artifact
runtime (`.../job/{job_id}/artifacts`), which is also auth-scoped to the job.

> **Developer reference:** the full architecture, provider contract, config schema,
> artifact pipeline, and troubleshooting live next to the code in
> [`src/aiq_agent/agents/deep_researcher/sandbox/README.md`](../../../../src/aiq_agent/agents/deep_researcher/sandbox/README.md).

## Current Behavior

- One sandbox name is used per deep research job when sandboxing is enabled; the
  name is the resolved job ID, and different jobs produce different names.
- Synchronous sandbox-enabled runs use an internal per-agent runtime ID.
- Providers are selected by config (`sandbox.provider` + `providers.<name>`); the
  provider is validated against the registry and gated by a fail-closed capability
  check (e.g. `block_network` requires `supports_network_policy`).
- Job IDs must satisfy each provider's object-name rules (Modal: 64 chars or fewer,
  alphanumeric plus dash/period/underscore).
- `timeout` and `idle_timeout` control sandbox lifetime.
- Files written inside the workdir are temporary scratch state. Durable text should
  be written through DeepAgents virtual paths such as `/shared/`; durable binaries
  (charts, CSVs) are captured by the artifact runtime.

## Operational Notes

- High concurrency creates one sandbox per concurrent sandbox-enabled job. Optional
  submit-path caps (`AIQ_MAX_SANDBOXES_PER_PRINCIPAL` / `AIQ_MAX_SANDBOXES_GLOBAL`,
  default-off) bound concurrency/cost.
- Custom client-supplied job IDs must not be reused for a new job.
- The runtime performs explicit cleanup (`close()` / `terminate()`) on job success,
  failure, cancellation, and timeout via the job runner's terminal path.

## Implemented Hardening

The following production hardening (formerly deferred) is now in place:

- Explicit sandbox cleanup on success, failure, cancellation, and timeout.
- Idempotency-gated retry-on-stale-container handling.
- Artifact capture for generated charts/binaries (validate -> store -> serve/embed),
  with MIME-from-bytes spoof rejection, SVG sanitization, and an inline-render allowlist.
- Sandbox quota and concurrency controls, and artifact retention via job-expiry cleanup.
- Structured lifecycle logging for sandbox create, reuse, failure, and cleanup.

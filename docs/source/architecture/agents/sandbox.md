<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Deep Research Sandbox Notes

Deep research can optionally run DeepAgents `execute` calls in an isolated
sandbox. AI-Q supports two providers:

- `modal`: remote Modal sandboxes, named by the resolved AI-Q job ID.
- `openshell`: local or remote NVIDIA OpenShell sandboxes through the
  `langchain-nvidia-openshell` DeepAgents adapter.

The sandbox is an internal execution detail. There are no sandbox-specific API
endpoints, and job-level auth remains responsible for submit, stream, status,
cancel, state, and report access.

## Current Behavior

- One sandbox backend is used per deep research job when sandboxing is enabled.
- Modal sandbox names use the resolved job ID.
- OpenShell SDK-created sandboxes are currently anonymous at the gateway layer;
  AI-Q still derives a stable local backend identity from
  `sandbox_name_prefix` and the resolved job ID.
- Synchronous sandbox-enabled runs use an internal per-agent runtime ID.
- Job IDs must be valid Modal object names: 64 characters or fewer, using only
  alphanumeric characters, dashes, periods, and underscores.
- Modal `timeout` and `idle_timeout` control sandbox lifetime.
- OpenShell `timeout` controls the adapter's default command timeout, while
  `ready_timeout_seconds` controls sandbox creation readiness.
- Files written inside the sandbox workdir are temporary scratch state.
- Durable results should be returned by the agent or written through DeepAgents
  virtual filesystem paths such as `/shared/`.

## Operational Notes

- High concurrency creates one Modal sandbox per concurrent sandbox-enabled job.
- If clients provide custom job IDs, they must not reuse a job ID for a new job.
  Reuse can attach the job to an existing Modal sandbox until Modal terminates it.
- Cancelled or failed jobs may leave sandbox scratch files until Modal terminates
  the sandbox according to timeout settings.
- If Modal removes a container mid-job, the job may fail and should be retried.
- OpenShell requires `openshell>=0.0.57,<0.1`, an active OpenShell gateway, and
  the `langchain-nvidia-openshell` package installed in the AI-Q environment.
- OpenShell `delete_on_exit` is honored when the Python sandbox context is
  explicitly closed; async job cleanup hooks should call the backend's `close`
  method when lifecycle cleanup is added.

## Deferred Hardening

Planned follow-up work for production deployments:

- Explicit sandbox cleanup on job success, failure, cancellation, and timeout.
- Broader retry taxonomy for provider-specific stale sandbox errors.
- Artifact capture rules for generated charts and binary outputs before cleanup.
- Sandbox quota and concurrency controls.
- Metrics and structured logs for sandbox create, reuse, failure, and cleanup.

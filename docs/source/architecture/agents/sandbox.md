<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Deep Research Sandbox Notes

Deep research can optionally run DeepAgents `execute` calls in a Modal sandbox.
In this release, sandboxes are scoped to a single async job: the Modal sandbox
name is the resolved job ID. This prevents unrelated jobs from sharing sandbox
filesystem state when each request receives a unique job ID.

The sandbox is an internal execution detail. There are no sandbox-specific API
endpoints, and job-level auth remains responsible for submit, stream, status,
cancel, state, and report access.

## Current Behavior

- One sandbox name is used per deep research job when sandboxing is enabled.
- The sandbox name is the resolved job ID.
- Different jobs produce different sandbox names.
- Synchronous sandbox-enabled runs use an internal per-agent runtime ID.
- Job IDs must be valid Modal object names: 64 characters or fewer, using only
  alphanumeric characters, dashes, periods, and underscores.
- Modal `timeout` and `idle_timeout` control sandbox lifetime.
- Files written inside the Modal workdir are temporary scratch state.
- Durable results should be returned by the agent or written through DeepAgents
  virtual filesystem paths such as `/shared/`.

## Operational Notes

- High concurrency creates one Modal sandbox per concurrent sandbox-enabled job.
- If clients provide custom job IDs, they must not reuse a job ID for a new job.
  Reuse can attach the job to an existing Modal sandbox until Modal terminates it.
- Cancelled or failed jobs may leave sandbox scratch files until Modal terminates
  the sandbox according to timeout settings.
- If Modal removes a container mid-job, the job may fail and should be retried.

## Deferred Hardening

Planned follow-up work for production deployments:

- Explicit sandbox cleanup on job success, failure, cancellation, and timeout.
- Retry-on-stale-container handling for Modal `NotFoundError`.
- Artifact capture rules for generated charts and binary outputs before cleanup.
- Sandbox quota and concurrency controls.
- Metrics and structured logs for sandbox create, reuse, failure, and cleanup.

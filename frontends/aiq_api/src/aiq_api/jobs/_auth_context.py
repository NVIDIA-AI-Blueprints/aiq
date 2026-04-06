# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Per-task auth token context for async jobs.

Uses a ContextVar so concurrent jobs in the same Dask worker process
each see their own token without cross-task leakage.

The token fetcher is registered once at import time. It returns the
token from the current task's context, or None if no token is set.
"""

from contextvars import ContextVar

from aiq_agent.auth import register_token_fetcher

job_auth_token: ContextVar[str | None] = ContextVar("job_auth_token", default=None)


def _job_token_fetcher() -> str | None:
    """Return the auth token for the current async task, if any."""
    return job_auth_token.get()


# Register once — the ContextVar ensures per-task isolation
register_token_fetcher(_job_token_fetcher, priority=5)

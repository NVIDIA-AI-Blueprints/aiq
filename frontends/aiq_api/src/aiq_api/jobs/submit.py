# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Job submission utilities.

Provides functions to submit agent jobs to the Dask cluster.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from sqlalchemy.exc import IntegrityError

from aiq_agent.auth import Principal
from aiq_agent.auth import get_current_principal
from aiq_api.auth import get_current_trace_tags
from aiq_api.mcp_auth.provider import principal_user_id

from ..registry import get_agent_config
from .access import _make_no_auth_principal
from .access import create_job_access
from .access import rollback_job_submission
from .runner import run_agent_job

logger = logging.getLogger(__name__)


class JobIdConflictError(RuntimeError):
    """Raised when a caller-supplied job_id collides with an existing job.

    Distinct from generic submission failures so callers can map it to HTTP 409
    instead of triggering the rollback path, which would delete the pre-existing
    (victim) job's durable state.
    """


class InternalAgentError(RuntimeError):
    """Raised when an internal-only (public=False) agent is submitted without opt-in.

    The submission helper is the real trust boundary; trusted internal callers must
    pass allow_internal=True explicitly rather than relying on every call site (and
    the HTTP route filter) to remember the gate.
    """


def _resolve_submission_principal(owner: str) -> Principal | None:
    """Resolve the best available principal for async job ownership.

    Used only when submit_agent_job is called programmatically without an
    explicit principal.  Verified middleware identity is preferred; falls back
    to a compatibility principal when auth is disabled.
    """
    principal = get_current_principal()
    if principal is not None:
        return principal

    if os.environ.get("REQUIRE_AUTH", "false").lower() == "true":
        return None

    return _make_no_auth_principal(owner)


def _current_conversation_id() -> str | None:
    """Best-effort read of the originating conversation id from the NAT context."""
    try:
        from nat.builder.context import ContextState

        return ContextState.get().conversation_id.get()
    except Exception:
        return None


def _get_parent_trace_context() -> tuple[
    str | None,  # parent_span_id
    str | None,  # parent_function_id
    str | None,  # parent_function_name
    str | None,  # parent_workflow_run_id
    int | str | None,  # parent_workflow_trace_id
    str | None,  # parent_conversation_id
    dict[str, str],  # request_trace_tags
]:
    """
    Extract trace context from current workflow for propagation to async jobs.

    This enables nested spans in Phoenix - the async job will appear as a child
    of the workflow that submitted it.

    Returns:
        Tuple of (parent_span_id, parent_function_id, parent_function_name,
                  parent_workflow_run_id, parent_workflow_trace_id, parent_conversation_id, request_trace_tags)
    """
    try:
        from nat.builder.context import ContextState
    except ImportError:
        return (None, None, None, None, None, None, {})

    context_state = ContextState.get()

    # Extract workflow-level context
    parent_workflow_run_id = context_state.workflow_run_id.get()
    parent_workflow_trace_id = context_state.workflow_trace_id.get()
    parent_conversation_id = context_state.conversation_id.get()

    # Extract span hierarchy context
    parent_span_id = None
    active_stack = context_state.active_span_id_stack.get()
    if active_stack and len(active_stack) > 1:
        parent_span_id = active_stack[1]

    parent_function_id = None
    parent_function_name = None
    active_function = context_state.active_function.get()
    if active_function and active_function.function_id != "root":
        parent_function_id = active_function.function_id
        parent_function_name = active_function.function_name

    return (
        parent_span_id,
        parent_function_id,
        parent_function_name,
        parent_workflow_run_id,
        parent_workflow_trace_id,
        parent_conversation_id,
        get_current_trace_tags(),
    )


async def submit_agent_job(
    agent_type: str,
    input_text: str,
    owner: str,
    principal: Principal | None = None,
    job_id: str | None = None,
    expiry_seconds: int = 86400,
    available_documents: list[dict] | None = None,
    data_sources: list[str] | None = None,
    auth_token: str | None = None,
    initial_files: dict[str, Any] | None = None,
    output_metadata: dict[str, Any] | None = None,
    allow_internal: bool = False,
) -> str:
    """
    Submit an agent job to the Dask cluster.

    This is the main entry point for submitting async jobs from application code.
    It looks up the agent configuration from the registry and submits the job.

    Args:
        agent_type: Agent type identifier (e.g., 'deep_researcher').
        input_text: The user's query/request.
        owner: Owner email for the job.
        principal: Verified principal that owns the job.
        job_id: Optional custom job ID.
        expiry_seconds: Job expiry time in seconds (default 24h).
        available_documents: Optional list of document dicts with file_name and summary.
        data_sources: Optional list of allowed data sources to enforce in the worker.
        auth_token: Optional auth token to propagate to the Dask worker for
            data sources that require authentication.
        initial_files: Optional DeepAgents virtual filesystem files to seed into worker state.
        output_metadata: Optional metadata persisted with the final job output.

    Returns:
        The job ID.

    Raises:
        KeyError: If agent_type is not registered.
        RuntimeError: If Dask scheduler is not configured.

    Example:
        job_id = await submit_agent_job(
            agent_type="deep_researcher",
            input_text="Research quantum computing",
            owner="user@example.com",
            available_documents=[{"file_name": "doc.pdf", "summary": "A research paper"}],
        )
    """
    from nat.front_ends.fastapi.async_jobs.job_store import JobStore

    # Get agent configuration from registry
    agent_config = get_agent_config(agent_type)

    # Enforce the internal-agent gate at the submission boundary (defense in depth):
    # internal-only agents may only be launched by trusted callers that opt in.
    if not agent_config.public and not allow_internal:
        raise InternalAgentError(f"Agent type is internal-only and cannot be submitted directly: {agent_type}")

    # @environment_variable NAT_DASK_SCHEDULER_ADDRESS
    # @category Server
    # @type str
    # @required true
    # Dask scheduler address for async job submission.
    scheduler_address = os.environ.get("NAT_DASK_SCHEDULER_ADDRESS")

    # @environment_variable NAT_JOB_STORE_DB_URL
    # @category Server
    # @type str
    # @default sqlite:///./data/jobs.db
    # @required false
    # Database URL for job persistence (SQLite or PostgreSQL).
    db_url = os.environ.get("NAT_JOB_STORE_DB_URL", "sqlite:///./data/jobs.db")

    # @environment_variable NAT_CONFIG_FILE
    # @category Server
    # @type str
    # @required false
    # Path to NAT workflow config file used by Dask workers.
    config_path = os.environ.get("NAT_CONFIG_FILE", "")

    # @environment_variable NAT_FASTAPI_LOG_LEVEL
    # @category Server
    # @type int
    # @default 20
    # @required false
    # Python logging level for FastAPI workers (10=DEBUG, 20=INFO, 30=WARNING).
    log_level = int(os.environ.get("NAT_FASTAPI_LOG_LEVEL", "20"))

    # @environment_variable NAT_USE_DASK_THREADS
    # @category Server
    # @type bool
    # @default 0
    # @required false
    # Use Dask thread pool instead of process pool for workers. Set to 1 to enable.
    use_threads = os.environ.get("NAT_USE_DASK_THREADS", "0") == "1"

    if not scheduler_address:
        raise RuntimeError("Async job submission requires NAT_DASK_SCHEDULER_ADDRESS to be set")

    # Auto-capture auth token if not explicitly provided
    if auth_token is None:
        from aiq_agent.auth import get_auth_token

        auth_token = get_auth_token()

    if principal is None:
        principal = _resolve_submission_principal(owner)
    if principal is None:
        raise RuntimeError("Verified current principal required for async job submission")

    # Preflight protected MCP sources before enqueue. The REST submit route also
    # does this (returning 409), but programmatic submitters — notably the chat
    # researcher's async deep-research path — call this directly and would otherwise
    # bypass the check, so this is the single chokepoint both paths share. Skipped
    # when no MCP auth provider is active in this process (nothing to enforce).
    from aiq_api.mcp_auth.active import get_active_mcp_auth_provider
    from aiq_api.mcp_auth.preflight import McpAuthRequiredError
    from aiq_api.mcp_auth.preflight import evaluate_mcp_auth

    mcp_provider = get_active_mcp_auth_provider()
    if mcp_provider is not None:
        block = await evaluate_mcp_auth(mcp_provider, principal, data_sources)
        if block is not None:
            raise McpAuthRequiredError(block)

    job_store = JobStore(scheduler_address=scheduler_address, db_url=db_url)
    resolved_job_id = job_store.ensure_job_id(job_id)
    loop = asyncio.get_running_loop()

    async def _rollback_partial_submission() -> None:
        """Best-effort cleanup of a job_info row we created before submission failed."""
        try:
            await loop.run_in_executor(None, rollback_job_submission, resolved_job_id, db_url)
            logger.warning(
                "Rolled back partial async job submission for %s. "
                "The Dask worker may still be running and should be investigated if it continues writing state.",
                resolved_job_id,
            )
        except Exception as cleanup_error:
            logger.warning(
                "Failed to roll back partial async job submission for %s: %s",
                resolved_job_id,
                cleanup_error,
            )

    try:
        await job_store.submit_job(
            job_id=resolved_job_id,
            expiry_seconds=expiry_seconds,
            job_fn=run_agent_job,
            job_args=[
                not use_threads,  # configure_logging
                log_level,
                scheduler_address,
                db_url,
                config_path,
                resolved_job_id,
                input_text,
                agent_config.class_path,
                agent_config.config_name,
                *_get_parent_trace_context(),
                available_documents,
                data_sources,
                auth_token,
                initial_files,
                output_metadata,
                principal_user_id(principal),
            ],
        )
    except IntegrityError as e:
        # A caller-supplied job_id collided with an existing job. NAT's _create_job
        # inserts job_info first, so the collision fails before any state of OURS is
        # created. The colliding job belongs to someone else — we must NOT run the
        # rollback path, which unconditionally deletes that job's info/events/access
        # rows. Surface a conflict so the route can return HTTP 409.
        logger.info("Rejected colliding job_id %s on async submit", resolved_job_id)
        raise JobIdConflictError(f"Job already exists: {resolved_job_id}") from e
    except Exception:
        # NAT's submit_job commits the job_info row before it hands the task to Dask,
        # so a post-commit failure (scheduler unreachable, serialization error,
        # Variable.set timeout) leaves an ownerless job_info row. Roll it back.
        await _rollback_partial_submission()
        raise

    # Conversation that originated this job (from the request's conversation-id), recorded so
    # report follow-up can default to "the last report in this conversation". None when the
    # client sent no conversation-id (e.g. a CLI that doesn't thread one) — then no linkage.
    submission_conversation_id = _current_conversation_id()
    try:
        await loop.run_in_executor(
            None, create_job_access, resolved_job_id, principal, db_url, submission_conversation_id, agent_type
        )
    except Exception:
        # We successfully created this job above, then ownership persistence failed;
        # roll back our own partial state. (Safe: this id was newly created by us.)
        await _rollback_partial_submission()
        raise

    logger.info(
        "Submitted %s job %s for owner %s (%s:%s)",
        agent_type,
        resolved_job_id,
        owner,
        principal.type,
        principal.sub,
    )
    return resolved_job_id


# Backwards compatibility alias
async def submit_deep_research_job(
    input_text: str,
    owner: str,
    job_id: str | None = None,
    expiry_seconds: int = 86400,
) -> str:
    """
    Submit a deep research job.

    Legacy function preserved for backwards compatibility.
    New code should use submit_agent_job(agent_type="deep_researcher", ...).
    """
    return await submit_agent_job(
        agent_type="deep_researcher",
        input_text=input_text,
        owner=owner,
        job_id=job_id,
        expiry_seconds=expiry_seconds,
    )

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

import logging
import os

from ..registry import get_agent_config
from .runner import run_agent_job

logger = logging.getLogger(__name__)


def _get_parent_trace_context() -> tuple[
    str | None,  # parent_span_id
    str | None,  # parent_function_id
    str | None,  # parent_function_name
    str | None,  # parent_workflow_run_id
    int | str | None,  # parent_workflow_trace_id
    str | None,  # parent_conversation_id
]:
    """
    Extract trace context from current workflow for propagation to async jobs.

    This enables nested spans in Phoenix - the async job will appear as a child
    of the workflow that submitted it.

    Returns:
        Tuple of (parent_span_id, parent_function_id, parent_function_name,
                  parent_workflow_run_id, parent_workflow_trace_id, parent_conversation_id)
    """
    try:
        from nat.builder.context import ContextState
    except ImportError:
        return (None, None, None, None, None, None)

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
    )


async def submit_agent_job(
    agent_type: str,
    input_text: str,
    owner: str,
    job_id: str | None = None,
    expiry_seconds: int = 86400,
    available_documents: list[dict] | None = None,
    data_sources: list[str] | None = None,
) -> str:
    """
    Submit an agent job to the Dask cluster.

    This is the main entry point for submitting async jobs from application code.
    It looks up the agent configuration from the registry and submits the job.

    Args:
        agent_type: Agent type identifier (e.g., 'deep_researcher').
        input_text: The user's query/request.
        owner: Owner email for the job.
        job_id: Optional custom job ID.
        expiry_seconds: Job expiry time in seconds (default 24h).
        available_documents: Optional list of document dicts with file_name and summary.
        data_sources: Optional list of allowed data sources to enforce in the worker.

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
    from nat.front_ends.fastapi.job_store import JobStore

    # Get agent configuration from registry
    agent_config = get_agent_config(agent_type)

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

    job_store = JobStore(scheduler_address=scheduler_address, db_url=db_url)
    resolved_job_id = job_store.ensure_job_id(job_id)

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
        ],
    )

    logger.info(
        "Submitted %s job %s for owner %s",
        agent_type,
        resolved_job_id,
        owner,
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

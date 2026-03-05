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
Agent-agnostic async job API routes.

Routes:
    GET  /v1/jobs/async/agents                            - List available agent types
    POST /v1/jobs/async/submit                            - Submit a new job for any agent
    GET  /v1/jobs/async/job/{job_id}                      - Get job status
    GET  /v1/jobs/async/job/{job_id}/stream               - SSE stream from beginning
    GET  /v1/jobs/async/job/{job_id}/stream/{last_event_id} - SSE stream from event ID
    POST /v1/jobs/async/job/{job_id}/cancel               - Cancel running job
    GET  /v1/jobs/async/job/{job_id}/state                - Get artifacts from event store
    GET  /v1/jobs/async/job/{job_id}/report               - Get final report
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from ..registry import AGENT_REGISTRY
from ..registry import get_agent_config

if TYPE_CHECKING:
    from nat.builder.workflow_builder import WorkflowBuilder
    from nat.front_ends.fastapi.fastapi_front_end_plugin_worker import FastApiFrontEndPluginWorker

logger = logging.getLogger(__name__)


class JobSubmitRequest(BaseModel):
    """Request to submit an async job."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "agent_type": "deep_researcher",
                    "input": "What are the latest advances in quantum computing?",
                    "job_id": None,
                    "expiry_seconds": 86400,
                }
            ]
        }
    )

    agent_type: str = Field(..., description="Agent type (e.g., 'deep_researcher')")
    input: str = Field(..., min_length=1, description="Input query for the agent")
    job_id: str | None = Field(
        None,
        pattern=r"^[a-zA-Z0-9_-]+$",
        max_length=64,
        description="Optional custom job ID (auto-generated if omitted)",
    )
    expiry_seconds: int | None = Field(
        None,
        ge=600,
        le=604800,
        description="Job expiry in seconds (default from config, max 7 days)",
    )


class JobStatusResponse(BaseModel):
    """Job status response."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_id": "abc123",
                    "status": "SUBMITTED",
                    "agent_type": "deep_researcher",
                    "error": None,
                    "created_at": "2026-02-12T10:30:00Z",
                }
            ]
        }
    )

    job_id: str = Field(..., description="Unique job identifier")
    status: str = Field(..., description="Current status (SUBMITTED, RUNNING, COMPLETED, FAILED, CANCELLED)")
    agent_type: str | None = Field(None, description="Agent type used for this job")
    error: str | None = Field(None, description="Error message if job failed")
    created_at: str | None = Field(None, description="Creation timestamp (ISO format)")


class JobStateResponse(BaseModel):
    """Job state response with artifacts."""

    job_id: str = Field(..., description="Unique job identifier")
    has_state: bool = Field(..., description="Whether state/artifacts are available")
    state: dict | None = Field(None, description="Internal job state")
    artifacts: dict | None = Field(None, description="Tool calls, outputs, and sources collected during execution")


class JobReportResponse(BaseModel):
    """Final report response."""

    job_id: str = Field(..., description="Unique job identifier")
    has_report: bool = Field(..., description="Whether the final report is available")
    report: str | None = Field(None, description="Final research report from the agent")


class AgentInfo(BaseModel):
    """Information about a registered agent."""

    agent_type: str = Field(..., description="Agent identifier used in submit requests")
    description: str = Field(..., description="Human-readable description of the agent")


class AgentListResponse(BaseModel):
    """List of available agents."""

    agents: list[AgentInfo] = Field(..., description="Registered agent types")


class DataSource(BaseModel):
    """Information about an available data source."""

    id: str = Field(..., description="Unique identifier for the data source")
    name: str = Field(..., description="Display name")
    description: str | None = Field(default=None, description="Human-readable description")


def _collect_tool_names(builder: WorkflowBuilder) -> set[str]:
    """Collect tool names from workflow functions that declare tools (for data source list)."""
    tool_names: set[str] = set()
    # intent_classifier (orchestration) and research agents may have tools; meta_chatter/depth_router no longer exist
    for fn_name in ("deep_research_agent", "shallow_research_agent", "intent_classifier"):
        try:
            fn_config = builder.get_function_config(fn_name)
        except (KeyError, ValueError):
            continue
        tools = getattr(fn_config, "tools", None)
        if not tools:
            continue
        for tool in tools:
            tool_names.add(getattr(tool, "name", str(tool)))
    return tool_names


async def register_job_routes(app: FastAPI, builder: WorkflowBuilder, worker: FastApiFrontEndPluginWorker) -> None:
    """
    Register agent-agnostic async job routes.

    Uses NAT's JobStore for job metadata and Dask for distributed execution.
    The /v1/data_sources endpoint is always registered regardless of Dask availability.
    """
    import logging as std_logging
    import os

    from nat.front_ends.fastapi.job_store import JobStatus

    from ..jobs import EventStore
    from ..jobs.runner import run_agent_job

    @app.get(
        "/v1/jobs/async/agents",
        response_model=AgentListResponse,
        tags=["async jobs"],
        summary="List available agents",
        description="Returns all registered agent types that can be used with the submit endpoint.",
    )
    async def list_agents() -> AgentListResponse:
        """List available agent types for async job submission."""
        agents = [
            AgentInfo(agent_type=agent_type, description=config.description)
            for agent_type, config in AGENT_REGISTRY.items()
        ]
        return AgentListResponse(agents=agents)

    @app.get(
        "/v1/data_sources",
        response_model=list[DataSource],
        tags=["data sources"],
        summary="List data sources",
    )
    async def list_data_sources() -> list[DataSource]:
        """List available data sources with metadata."""
        data_sources = [
            DataSource(
                id="web_search",
                name="Web Search",
                description="Search the web for real-time information.",
            )
        ]

        tool_names = _collect_tool_names(builder)

        knowledge_configured = any("knowledge" in name.lower() or name == "knowledge_search" for name in tool_names)
        if knowledge_configured:
            data_sources.append(
                DataSource(
                    id="knowledge_layer",
                    name="Knowledge Base",
                    description="Search uploaded documents and files.",
                )
            )

        return data_sources

    logger.info("Registered /v1/data_sources and /v1/jobs/async/agents routes")

    dask_available = getattr(worker, "_dask_available", False)
    job_store = getattr(worker, "_job_store", None)

    if not dask_available or not job_store:
        logger.warning(
            "Dask not available - async job submission routes require NAT_DASK_SCHEDULER_ADDRESS"
            " and NAT_JOB_STORE_DB_URL"
        )
        return

    scheduler_address = getattr(worker, "_scheduler_address", None) or os.environ.get("NAT_DASK_SCHEDULER_ADDRESS")
    db_url = getattr(worker, "_db_url", None) or os.environ.get("NAT_JOB_STORE_DB_URL", "sqlite:///./data/jobs.db")
    config_path = getattr(worker, "_config_file_path", None) or os.environ.get("NAT_CONFIG_FILE", "")
    log_level = getattr(worker, "_log_level", std_logging.INFO)
    use_threads = getattr(worker, "_use_dask_threads", False)

    if not config_path:
        logger.error("Config file path not available - NAT_CONFIG_FILE not set")
        return

    front_end_config = getattr(worker, "_front_end_config", None)
    default_expiry_seconds = getattr(front_end_config, "expiry_seconds", 86400) if front_end_config else 86400

    logger.info(
        "Registering async job routes: scheduler=%s, db=%s, expiry=%ds",
        scheduler_address,
        db_url[:50],
        default_expiry_seconds,
    )

    @app.get("/health", tags=["health"], summary="Health check")
    async def health_check():
        """Health check endpoint that validates DB connectivity."""
        from sqlalchemy import text

        from ..jobs import EventStore

        result = {"status": "ok", "dask_available": dask_available, "db": "ok"}

        # Check DB connectivity using any cached async engine
        try:
            cache = EventStore._async_engine_cache
            if cache:
                engine = next(iter(cache.values()))[0]
                async with engine.connect() as conn:
                    await asyncio.wait_for(conn.execute(text("SELECT 1")), timeout=3.0)
            else:
                result["db"] = "no_engine"
        except Exception:
            logger.warning("Health check DB ping failed", exc_info=True)
            result["status"] = "degraded"
            result["db"] = "unreachable"
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=503, content=result)

        return result

    @app.post(
        "/v1/jobs/async/submit",
        response_model=JobStatusResponse,
        tags=["async jobs"],
        summary="Submit a new async job",
        description=(
            "Submit a research query to a registered agent. Returns a job ID for tracking progress via SSE stream."
        ),
        responses={
            400: {"description": "Unknown agent type or invalid request"},
            503: {"description": "Dask scheduler not available"},
        },
    )
    async def submit_job(req: JobSubmitRequest, request: Request) -> JobStatusResponse:
        """Submit a new async job for deep research or other registered agents."""
        try:
            agent_config = get_agent_config(req.agent_type)
        except KeyError as e:
            raise HTTPException(400, str(e))

        resolved_job_id = job_store.ensure_job_id(req.job_id)
        expiry = req.expiry_seconds if req.expiry_seconds is not None else default_expiry_seconds

        job_args = [
            not use_threads,  # configure_logging
            log_level,
            scheduler_address,
            db_url,
            config_path,
            resolved_job_id,
            req.input,
            agent_config.class_path,
            agent_config.config_name,
            None,  # parent_span_id
            None,  # parent_function_id
            None,  # parent_function_name
            None,  # parent_workflow_run_id
            None,  # parent_workflow_trace_id
            None,  # parent_conversation_id
            None,  # available_documents
            None,  # data_sources
        ]

        job_id, _ = await job_store.submit_job(
            job_id=resolved_job_id,
            expiry_seconds=expiry,
            job_fn=run_agent_job,
            job_args=job_args,
        )

        logger.info("Submitted %s job %s (expiry=%ds)", req.agent_type, job_id, expiry)
        return JobStatusResponse(
            job_id=job_id,
            status=JobStatus.SUBMITTED.value,
            agent_type=req.agent_type,
        )

    @app.get(
        "/v1/jobs/async/job/{job_id}",
        response_model=JobStatusResponse,
        tags=["async jobs"],
        summary="Get job status",
        description="Get the current status of an async job by its ID.",
        responses={404: {"description": "Job not found"}},
    )
    async def get_job_status(job_id: str, request: Request) -> JobStatusResponse:
        """Get the current status of a job."""
        job = await job_store.get_job(job_id)
        if not job:
            raise HTTPException(404, f"Job not found: {job_id}")

        return JobStatusResponse(
            job_id=job_id,
            status=job.status,
            error=job.error,
            created_at=job.created_at.isoformat() if job.created_at else None,
        )

    @app.get(
        "/v1/jobs/async/job/{job_id}/stream",
        tags=["async jobs"],
        summary="Stream job events",
        description=(
            "Server-Sent Events (SSE) stream of job progress from the beginning."
            " Includes tool calls, intermediate results, and the final report."
        ),
        responses={404: {"description": "Job not found"}},
    )
    async def stream_job_events(job_id: str, request: Request) -> StreamingResponse:
        """SSE stream for job events from beginning."""
        job = await job_store.get_job(job_id)
        if not job:
            raise HTTPException(404, f"Job not found: {job_id}")

        return StreamingResponse(
            _sse_generator(job_store, job_id, db_url, start_event_id=0),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get(
        "/v1/jobs/async/job/{job_id}/stream/{last_event_id}",
        tags=["async jobs"],
        summary="Resume job event stream",
        description="Resume an SSE stream from a specific event ID. Use for reconnection after network interruption.",
        responses={404: {"description": "Job not found"}},
    )
    async def stream_job_events_from(job_id: str, last_event_id: int, request: Request) -> StreamingResponse:
        """SSE stream for job events from specific event ID (for reconnection)."""
        job = await job_store.get_job(job_id)
        if not job:
            raise HTTPException(404, f"Job not found: {job_id}")

        return StreamingResponse(
            _sse_generator(job_store, job_id, db_url, start_event_id=last_event_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post(
        "/v1/jobs/async/job/{job_id}/cancel",
        tags=["async jobs"],
        summary="Cancel a running job",
        description="Request cancellation of a running job. The job status will be set to INTERRUPTED.",
        responses={
            400: {"description": "Job is not in RUNNING state"},
            404: {"description": "Job not found"},
        },
    )
    async def cancel_job(job_id: str, request: Request) -> dict:
        """Cancel a running job."""
        job = await job_store.get_job(job_id)
        if not job:
            raise HTTPException(404, f"Job not found: {job_id}")

        if job.status != JobStatus.RUNNING.value:
            raise HTTPException(400, f"Job not running: {job_id} (status: {job.status})")

        await job_store.update_status(job_id, JobStatus.INTERRUPTED, error="cancelled by user")

        event_store = EventStore(db_url, job_id)
        event_store.store(
            {
                "type": "job.cancellation_requested",
                "data": {"reason": "cancelled by user"},
            }
        )

        task_cancelled = await _cancel_dask_task(scheduler_address, job_id)

        logger.info("Cancel requested for job %s: status updated, task_cancelled=%s", job_id, task_cancelled)

        return {"job_id": job_id, "status": JobStatus.INTERRUPTED.value, "task_cancelled": task_cancelled}

    @app.get(
        "/v1/jobs/async/job/{job_id}/state",
        response_model=JobStateResponse,
        tags=["async jobs"],
        summary="Get job artifacts",
        description="Get tool calls, outputs, and sources collected during job execution.",
        responses={404: {"description": "Job not found"}},
    )
    async def get_job_state(job_id: str, request: Request) -> JobStateResponse:
        """Get artifacts from event store."""
        job = await job_store.get_job(job_id)
        if not job:
            raise HTTPException(404, f"Job not found: {job_id}")

        artifacts = await _get_job_artifacts(db_url, job_id)
        return JobStateResponse(
            job_id=job_id,
            has_state=artifacts is not None,
            state=None,
            artifacts=artifacts,
        )

    @app.get(
        "/v1/jobs/async/job/{job_id}/report",
        response_model=JobReportResponse,
        tags=["async jobs"],
        summary="Get final report",
        description="Get the final research report from a completed job.",
        responses={404: {"description": "Job not found"}},
    )
    async def get_job_report(job_id: str, request: Request) -> JobReportResponse:
        """Get the final report from a completed job."""
        job = await job_store.get_job(job_id)
        if not job:
            raise HTTPException(404, f"Job not found: {job_id}")

        report = None
        if job.output:
            try:
                output = json.loads(job.output) if isinstance(job.output, str) else job.output
                report = output.get("report")
            except (json.JSONDecodeError, AttributeError):
                pass

        return JobReportResponse(job_id=job_id, has_report=bool(report), report=report)

    logger.info("Registered async job routes at /v1/jobs/async")

    # Ensure job_events table exists before reaper runs (reaper queries it via raw SQL;
    # table is otherwise created lazily on first EventStore write).
    EventStore._ensure_table_exists(db_url)

    # Start the ghost job reaper background task
    asyncio.create_task(_reap_ghost_jobs(job_store, db_url))

    # Start periodic cleanup of expired jobs (NAT's job_info table) and old events (job_events table).
    # NAT provides periodic_cleanup as a Dask task for job_info, but it must be explicitly submitted.
    # We also run a local asyncio task for job_events cleanup since NAT doesn't manage that table.
    _start_periodic_cleanup(job_store, scheduler_address, db_url, default_expiry_seconds, log_level, use_threads)


GHOST_JOB_TIMEOUT_SECONDS = 300  # 5 minutes without events = ghost job
GHOST_REAPER_INTERVAL_SECONDS = 60  # check every 60 seconds


def _find_stale_jobs(db_url: str, running_status: str) -> list[str]:
    """
    Sync helper to query for ghost jobs. Runs in a thread via run_in_executor
    to avoid blocking the async event loop with DB I/O.
    """
    from sqlalchemy import inspect
    from sqlalchemy import text

    from ..jobs import EventStore

    EventStore._ensure_table_exists(db_url)
    engine = EventStore._get_or_create_sync_engine(db_url)
    inspector = inspect(engine)
    if not inspector.has_table("job_events"):
        return []

    with engine.connect() as conn:
        if db_url.startswith("postgresql"):
            stale_query = text(
                "SELECT DISTINCT je.job_id FROM job_events je "
                "INNER JOIN job_info ji ON je.job_id = ji.job_id "
                "WHERE ji.status = :running_status "
                "GROUP BY je.job_id "
                "HAVING MAX(je.created_at) < NOW() - :timeout * INTERVAL '1 second'"
            )
            params = {"running_status": running_status, "timeout": GHOST_JOB_TIMEOUT_SECONDS}
        else:
            stale_query = text(
                "SELECT DISTINCT je.job_id FROM job_events je "
                "INNER JOIN job_info ji ON je.job_id = ji.job_id "
                "WHERE ji.status = :running_status "
                "GROUP BY je.job_id "
                "HAVING MAX(je.created_at) < datetime('now', :timeout_interval)"
            )
            params = {
                "running_status": running_status,
                "timeout_interval": f"-{GHOST_JOB_TIMEOUT_SECONDS} seconds",
            }

        result = conn.execute(stale_query, params)
        return [row[0] for row in result]


async def _reap_ghost_jobs(job_store, db_url: str) -> None:
    """
    Background task that periodically marks stale RUNNING jobs as FAILURE.

    A job is considered "ghost" if it has been RUNNING for over
    GHOST_JOB_TIMEOUT_SECONDS with no new events in the job_events table.
    This catches Dask worker crashes and OOM kills that bypass Python exception handling.
    """
    from nat.front_ends.fastapi.job_store import JobStatus

    from ..jobs import EventStore

    logger.info(
        "Ghost job reaper started (timeout=%ds, interval=%ds)",
        GHOST_JOB_TIMEOUT_SECONDS,
        GHOST_REAPER_INTERVAL_SECONDS,
    )

    loop = asyncio.get_running_loop()

    while True:
        try:
            await asyncio.sleep(GHOST_REAPER_INTERVAL_SECONDS)

            stale_job_ids = await loop.run_in_executor(None, _find_stale_jobs, db_url, JobStatus.RUNNING.value)

            for stale_job_id in stale_job_ids:
                logger.warning("Reaping ghost job %s (no events for %ds)", stale_job_id, GHOST_JOB_TIMEOUT_SECONDS)
                try:
                    await job_store.update_status(
                        stale_job_id,
                        JobStatus.FAILURE,
                        error="Job timed out (no heartbeat received from worker)",
                    )
                    event_store = EventStore(db_url, stale_job_id)
                    event_store.store(
                        {
                            "type": "job.error",
                            "data": {
                                "error": "Job timed out (no heartbeat received from worker)",
                                "error_type": "GhostJobTimeout",
                            },
                        }
                    )
                except Exception as e:
                    logger.warning("Failed to reap ghost job %s: %s", stale_job_id, e)

        except asyncio.CancelledError:
            logger.info("Ghost job reaper stopped")
            break
        except Exception as e:
            logger.warning("Ghost job reaper error: %s", e)


_cleanup_task: asyncio.Task | None = None
"""Module-level reference for graceful shutdown cancellation."""

# Advisory lock ID for PostgreSQL — ensures only one pod runs cleanup at a time.
# Arbitrary constant; change if it collides with another lock in your deployment.
_PG_ADVISORY_LOCK_ID = 0x41495143_4C45414E  # "AIQCLEAN" in hex


def _start_periodic_cleanup(
    job_store,
    scheduler_address: str,
    db_url: str,
    expiry_seconds: int,
    log_level: int,
    use_threads: bool,
) -> None:
    """
    Start periodic cleanup of expired jobs and old events.

    Submits NAT's periodic_cleanup as a Dask task (handles job_info expiry)
    and starts a local asyncio task for coordinated event cleanup.
    """
    global _cleanup_task

    # Cleanup interval: half the expiry time, clamped to [60s, 3600s]
    cleanup_interval = max(60, min(expiry_seconds // 2, 3600))

    # Submit NAT's periodic_cleanup as a long-running Dask task for job_info table
    try:
        from dask.distributed import fire_and_forget

        from nat.front_ends.fastapi.async_job import periodic_cleanup

        cleanup_future = job_store.dask_client.submit(
            periodic_cleanup,
            scheduler_address=scheduler_address,
            db_url=db_url,
            sleep_time_sec=cleanup_interval,
            configure_logging=not use_threads,
            log_level=log_level,
        )
        fire_and_forget(cleanup_future)
        logger.info(
            "Submitted periodic job cleanup task to Dask (interval=%ds, expiry=%ds)",
            cleanup_interval,
            expiry_seconds,
        )
    except Exception as e:
        logger.warning("Failed to submit periodic cleanup to Dask: %s", e)

    # Start local asyncio task for job_events table cleanup (NAT doesn't manage this table).
    # Uses pg_try_advisory_xact_lock on PostgreSQL so only one pod runs cleanup per cycle.
    # Cancel any previously-started task before overwriting the reference.
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()
    _cleanup_task = asyncio.create_task(_cleanup_old_events_loop(db_url, expiry_seconds, cleanup_interval))


async def stop_periodic_cleanup() -> None:
    """Cancel the event cleanup background task. Call from shutdown handler."""
    global _cleanup_task
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
        _cleanup_task = None
        logger.info("Event cleanup task cancelled")


async def _cleanup_old_events_loop(db_url: str, retention_seconds: int, interval_seconds: int) -> None:
    """
    Background task that periodically deletes old events from the job_events table
    and removes events for jobs already marked as expired in job_info.

    On PostgreSQL, uses pg_try_advisory_xact_lock so only one pod runs cleanup per cycle
    when multiple pods share the same database.
    """

    is_postgres = db_url.startswith("postgres")

    logger.info(
        "Event cleanup task started (retention=%ds, interval=%ds, advisory_lock=%s)",
        retention_seconds,
        interval_seconds,
        is_postgres,
    )

    # Run once immediately on startup to catch anything that aged out during downtime.
    try:
        await _run_event_cleanup(db_url, retention_seconds, is_postgres)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("Event cleanup startup run failed: %s", e)

    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await _run_event_cleanup(db_url, retention_seconds, is_postgres)
        except asyncio.CancelledError:
            logger.info("Event cleanup task stopped")
            break
        except Exception as e:
            logger.warning("Event cleanup error: %s", e)


async def _run_event_cleanup(db_url: str, retention_seconds: int, is_postgres: bool) -> None:
    """
    Execute one cleanup cycle: time-based event pruning + removal of events for expired jobs.

    On PostgreSQL, acquires a transaction-level advisory lock (pg_try_advisory_xact_lock)
    so concurrent pods skip the cycle rather than doing redundant work. The lock is
    automatically released on commit/rollback, avoiding leak risks.
    """
    from ..jobs import EventStore

    loop = asyncio.get_running_loop()

    def _do_cleanup() -> tuple[int, int]:
        from sqlalchemy import text

        engine = EventStore._get_or_create_sync_engine(db_url)

        with engine.connect() as conn:
            # On PostgreSQL, acquire a transaction-level advisory lock. If another pod
            # already holds it, skip this cycle. The lock is automatically released
            # on commit/rollback — no manual unlock needed.
            if is_postgres:
                locked = conn.execute(
                    text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
                    {"lock_id": _PG_ADVISORY_LOCK_ID},
                ).scalar()
                if not locked:
                    return (0, 0)

            # 1. Time-based: delete events older than retention period
            if is_postgres:
                result = conn.execute(
                    text("DELETE FROM job_events WHERE created_at < NOW() - :seconds * INTERVAL '1 second'"),
                    {"seconds": retention_seconds},
                )
            else:
                result = conn.execute(
                    text("DELETE FROM job_events WHERE created_at < datetime('now', :interval)"),
                    {"interval": f"-{retention_seconds} seconds"},
                )
            time_deleted = result.rowcount

            # 2. Coordinated: delete events for jobs already marked expired in job_info.
            # This catches events that haven't aged out yet but whose parent job is
            # already expired (e.g. short-lived jobs with long event retention).
            expired_result = conn.execute(
                text("DELETE FROM job_events WHERE job_id IN (SELECT job_id FROM job_info WHERE is_expired = true)")
            )
            expired_deleted = expired_result.rowcount

            conn.commit()
            return (time_deleted, expired_deleted)

    time_deleted, expired_deleted = await loop.run_in_executor(None, _do_cleanup)

    if time_deleted > 0 or expired_deleted > 0:
        logger.info(
            "Event cleanup: %d old events removed, %d events for expired jobs removed",
            time_deleted,
            expired_deleted,
        )


async def _cancel_dask_task(scheduler_address: str, job_id: str) -> bool:
    """
    Cancel a Dask task by job ID.

    Args:
        scheduler_address: Dask scheduler address.
        job_id: Job ID to cancel.

    Returns:
        True if task was cancelled, False otherwise.
    """
    try:
        from distributed import Client
        from distributed import Future
        from distributed import Variable

        async with Client(scheduler_address, asynchronous=True) as client:
            var = Variable(name=job_id, client=client)
            try:
                # Short timeout: variable may be unset if worker hasn't started or job already finished.
                future = await var.get(timeout=2)
                if isinstance(future, Future):
                    await client.cancel([future], asynchronous=True, force=True)
                    logger.info("Cancelled Dask task for job %s", job_id)
                    return True
            except (TimeoutError, asyncio.CancelledError) as e:
                logger.warning(
                    "Could not get Dask future for job %s (variable not set or wait cancelled): %s",
                    job_id,
                    type(e).__name__,
                )
            except Exception as e:
                logger.warning("Error getting Dask future for job %s: %s", job_id, e)
            finally:
                try:
                    var.delete()
                except (KeyError, RuntimeError):
                    pass
    except (ConnectionError, TimeoutError, OSError) as e:
        logger.warning("Failed to cancel Dask task for job %s: %s", job_id, e)
    except Exception as e:
        logger.warning("Unexpected error cancelling Dask task for job %s: %s", job_id, e)
    return False


def _extract_event_metadata(event: dict) -> tuple[dict, dict]:
    """Extract data and metadata from an event dict."""
    data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
    metadata = event.get("metadata", {}) if isinstance(event.get("metadata"), dict) else {}
    if not metadata and isinstance(data, dict):
        metadata = data.get("metadata", {}) or {}
    return data, metadata


def _process_tool_start(event: dict, data: dict, metadata: dict, tool_call_map: dict[str, dict]) -> None:
    """Process a tool.start event and add to tool_call_map."""
    tool_id = data.get("id", "")
    inner_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
    tool_call_map[tool_id] = {
        "id": tool_id,
        "name": data.get("name", ""),
        "input": inner_data.get("input"),
        "output": None,
        "status": "running",
        "workflow": metadata.get("workflow"),
        "timestamp": event.get("timestamp"),
    }


def _process_tool_end(event: dict, data: dict, metadata: dict, tool_call_map: dict[str, dict]) -> None:
    """Process a tool.end event and update tool_call_map."""
    tool_id = data.get("id", "")
    inner_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
    tool_output = inner_data.get("output")

    if tool_id in tool_call_map:
        tool_call_map[tool_id]["output"] = tool_output
        tool_call_map[tool_id]["status"] = "completed"
    else:
        tool_call_map[tool_id] = {
            "id": tool_id,
            "name": data.get("name", ""),
            "input": None,
            "output": tool_output,
            "status": "completed",
            "workflow": metadata.get("workflow"),
            "timestamp": event.get("timestamp"),
        }


def _normalize_url(url: str) -> str:
    """Normalize URL for consistent deduplication."""
    from urllib.parse import urlparse
    from urllib.parse import urlunparse

    try:
        parsed = urlparse(url)
        normalized_path = parsed.path.rstrip("/") if parsed.path != "/" else "/"
        return urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                normalized_path,
                parsed.params,
                parsed.query,
                "",
            )
        )
    except Exception:
        return url


def _is_valid_url(url: str) -> bool:
    """Check if string is a valid HTTP/HTTPS URL."""
    return bool(url and url.lower().startswith(("http://", "https://")))


def _process_artifact_update(
    event: dict,
    data: dict,
    metadata: dict,
    outputs: list[dict],
    sources_found: set[str],
    sources_cited: set[str],
) -> None:
    """Process an artifact.update event and add to outputs."""
    artifact_type = data.get("type")
    content = data.get("content")

    # Track citation sources and uses for accurate counts (with validation)
    if artifact_type == "citation_source":
        url = data.get("url") or content
        if _is_valid_url(url):
            sources_found.add(_normalize_url(url))
    elif artifact_type == "citation_use":
        url = data.get("url") or content
        if _is_valid_url(url):
            sources_cited.add(_normalize_url(url))

    if content:
        outputs.append(
            {
                "type": artifact_type,
                "content": content,
                "name": event.get("name"),
                "workflow": metadata.get("workflow"),
                "timestamp": event.get("timestamp"),
                **{k: v for k, v in data.items() if k not in ("type", "content")},
            }
        )


async def _get_job_artifacts(db_url: str, job_id: str) -> dict | None:
    """
    Extract artifacts from stored events.

    Returns a simplified structure with all tool calls, outputs, and source counts.
    Frontend categorizes tools by name (task=subagent, write_todos=middleware, etc.).

    Args:
        db_url: Database URL for event store.
        job_id: Job ID to fetch artifacts for.

    Returns:
        Dict with 'tools', 'outputs', and 'sources' (counts), or None if no artifacts found.
    """
    from ..jobs import EventStore

    try:
        events = await EventStore.get_events_async(db_url, job_id, 0, 10000)
        if not events:
            return None

        tool_call_map: dict[str, dict] = {}
        outputs: list[dict] = []
        sources_found: set[str] = set()
        sources_cited: set[str] = set()

        for event in events:
            event_type = event.get("type", "")
            data, metadata = _extract_event_metadata(event)

            if event_type == "tool.start":
                _process_tool_start(event, data, metadata, tool_call_map)
            elif event_type == "tool.end":
                _process_tool_end(event, data, metadata, tool_call_map)
            elif event_type == "artifact.update":
                _process_artifact_update(event, data, metadata, outputs, sources_found, sources_cited)

        tools = list(tool_call_map.values())
        result = {
            "tools": tools,
            "outputs": outputs,
            "sources": {
                "found": len(sources_found),
                "cited": len(sources_cited),
                "found_urls": list(sources_found),
                "cited_urls": list(sources_cited),
            },
        }
        return result if tools or outputs or sources_found else None

    except (KeyError, TypeError) as e:
        logger.warning("Failed to parse artifacts for job %s: %s", job_id, e)
        return None
    except Exception as e:
        logger.warning("Failed to get artifacts for job %s: %s", job_id, e)
        return None


async def _sse_generator(job_store, job_id: str, db_url: str, start_event_id: int = 0):
    """
    Route to appropriate SSE generator based on database type.

    PostgreSQL: Uses LISTEN/NOTIFY for real-time push-based events (sub-10ms latency).
    SQLite: Uses polling (0.5s interval) since SQLite doesn't support pub-sub.
    """
    from ..jobs import EventStore

    if EventStore.is_postgres(db_url):
        try:
            async for event in _sse_generator_postgres(job_store, job_id, db_url, start_event_id):
                yield event
        except Exception as e:
            logger.warning("Pub-sub failed, falling back to polling: %s", e)
            async for event in _sse_generator_polling(job_store, job_id, db_url, start_event_id):
                yield event
    else:
        async for event in _sse_generator_polling(job_store, job_id, db_url, start_event_id):
            yield event


async def _sse_generator_postgres(job_store, job_id: str, db_url: str, start_event_id: int = 0):
    """
    PostgreSQL pub-sub based SSE generator - near-instant event delivery.

    Uses asyncpg LISTEN/NOTIFY for real-time push-based events.
    Achieves sub-10ms latency compared to 500ms polling interval.
    """
    import asyncio

    import asyncpg

    from nat.front_ends.fastapi.job_store import JobStatus

    from ..jobs import EventStore
    from ..jobs import get_connection_manager

    connection_manager = get_connection_manager()
    last_status = None
    last_event_id = start_event_id
    sequence_id = start_event_id
    terminal_statuses = {JobStatus.SUCCESS.value, JobStatus.FAILURE.value, JobStatus.INTERRUPTED.value}
    is_reconnect = start_event_id > 0

    def format_sse(event_type: str, data: dict, event_id: int | None = None) -> str:
        nonlocal sequence_id
        if event_id is not None:
            sequence_id = event_id
        else:
            sequence_id += 1
        return f"id: {sequence_id}\nevent: {event_type}\ndata: {json.dumps(data)}\n\n"

    asyncpg_url = db_url.replace("+psycopg2", "").replace("+asyncpg", "").replace("postgresql://", "postgres://")
    channel = f"job_events_{job_id.replace('-', '_')}"

    logger.info(f"SSE pub-sub stream starting for job_id={job_id}, channel={channel}")

    conn = None
    notification_queue: asyncio.Queue = asyncio.Queue()

    def notification_handler(connection, pid, channel_name, payload):
        try:
            notification_queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("Notification queue full for job %s", job_id)

    try:
        conn = await asyncpg.connect(asyncpg_url)
        await conn.add_listener(channel, notification_handler)
        logger.info(f"SSE: Listening on channel {channel}")

        async with connection_manager.track_connection():
            job = await job_store.get_job(job_id)
            if not job:
                logger.warning(f"SSE pub-sub: Job {job_id} not found")
                yield format_sse("job.error", {"error": "Job not found"})
                return

            job_already_complete = job.status in terminal_statuses

            events = await EventStore.get_events_async(db_url, job_id, last_event_id, 10000)
            logger.info(
                f"SSE pub-sub: Fetched {len(events)} historical events for job {job_id} (after_id={last_event_id})"
            )

            for event in events:
                db_event_id = event.pop("_id", None)
                if db_event_id:
                    last_event_id = db_event_id
                event_type = event.pop("type", "event")
                yield format_sse(event_type, event, db_event_id)

            yield format_sse("stream.mode", {"mode": "pubsub", "channel": channel})

            # Reconciliation fetch: catch events that arrived while sending the historical batch.
            # The LISTEN handler may have queued notifications for some of these, but a direct
            # fetch ensures no gap between the historical batch and the live stream.
            reconcile_events = await EventStore.get_events_async(db_url, job_id, last_event_id, 1000)
            if reconcile_events:
                logger.info(f"SSE pub-sub: Reconciliation fetched {len(reconcile_events)} events for job {job_id}")
                for event in reconcile_events:
                    db_event_id = event.pop("_id", None)
                    if db_event_id:
                        last_event_id = db_event_id
                    event_type = event.pop("type", "event")
                    yield format_sse(event_type, event, db_event_id)

            if job_already_complete:
                last_status = job.status
                data = {"status": job.status}
                if job.error:
                    data["error"] = job.error
                if is_reconnect:
                    data["reconnected"] = True
                yield format_sse("job.status", data)
                logger.info(f"SSE pub-sub: Job {job_id} already complete, sent {len(events)} events")
                return

            while True:
                if connection_manager.is_shutting_down:
                    logger.info("SSE pub-sub stream closing for job %s due to server shutdown", job_id)
                    yield format_sse("job.shutdown", {"message": "Server shutting down"})
                    break

                try:
                    try:
                        payload = await asyncio.wait_for(notification_queue.get(), timeout=5.0)
                        notification_data = json.loads(payload)
                        event_id = notification_data.get("id")

                        if event_id and event_id > last_event_id:
                            event = await EventStore.get_event_by_id_async(db_url, event_id)
                            if event:
                                last_event_id = event_id
                                db_event_id = event.pop("_id", None)
                                event_type = event.pop("type", "event")
                                yield format_sse(event_type, event, db_event_id)
                    except TimeoutError:
                        pass

                    job = await job_store.get_job(job_id)
                    if not job:
                        logger.warning(f"SSE pub-sub: Job {job_id} not found")
                        yield format_sse("job.error", {"error": "Job not found"})
                        break

                    if job.status != last_status:
                        last_status = job.status
                        logger.info(f"SSE pub-sub: Job {job_id} status changed to {job.status}")
                        data = {"status": job.status}
                        if job.error:
                            data["error"] = job.error
                        if is_reconnect:
                            data["reconnected"] = True
                            is_reconnect = False
                        yield format_sse("job.status", data)

                    if job.status in terminal_statuses:
                        await asyncio.sleep(0.5)
                        while not notification_queue.empty():
                            try:
                                payload = notification_queue.get_nowait()
                                notification_data = json.loads(payload)
                                event_id = notification_data.get("id")
                                if event_id and event_id > last_event_id:
                                    event = await EventStore.get_event_by_id_async(db_url, event_id)
                                    if event:
                                        last_event_id = event_id
                                        db_event_id = event.pop("_id", None)
                                        event_type = event.pop("type", "event")
                                        yield format_sse(event_type, event, db_event_id)
                            except asyncio.QueueEmpty:
                                break
                        break

                except asyncio.CancelledError:
                    logger.info("SSE pub-sub stream cancelled for job %s", job_id)
                    break
                except Exception as e:
                    logger.exception("SSE pub-sub stream error for job %s: %s", job_id, e)
                    yield format_sse("job.error", {"error": "Internal server error"})
                    break

    finally:
        if conn:
            try:
                await conn.remove_listener(channel, notification_handler)
                await conn.close()
                logger.info(f"SSE pub-sub: Closed connection for job {job_id}")
            except Exception as e:
                logger.warning(f"SSE pub-sub: Error closing connection for job {job_id}: {e}")


async def _sse_generator_polling(job_store, job_id: str, db_url: str, start_event_id: int = 0):
    """
    Polling-based SSE generator for SQLite and fallback scenarios.

    Replays historical events as fast as possible, then switches to live polling mode.
    Live mode uses a 0.5s polling interval and is suitable for local development with SQLite.
    Supports reconnection via start_event_id - replays events after that ID without delay.
    Supports graceful shutdown via the SSE connection manager.
    """
    import asyncio

    from nat.front_ends.fastapi.job_store import JobStatus

    from ..jobs import EventStore
    from ..jobs import get_connection_manager

    connection_manager = get_connection_manager()
    last_status = None
    last_event_id = start_event_id
    sequence_id = start_event_id
    terminal_statuses = {JobStatus.SUCCESS.value, JobStatus.FAILURE.value, JobStatus.INTERRUPTED.value}
    is_reconnect = start_event_id > 0
    in_replay_mode = True
    replay_mode_announced = False

    def format_sse(event_type: str, data: dict, event_id: int | None = None) -> str:
        nonlocal sequence_id
        if event_id is not None:
            sequence_id = event_id
        else:
            sequence_id += 1
        return f"id: {sequence_id}\nevent: {event_type}\ndata: {json.dumps(data)}\n\n"

    logger.info(
        f"SSE polling stream starting for job_id={job_id}, start_event_id={start_event_id}, db_url={db_url[:50]}"
    )

    async with connection_manager.track_connection():
        yield format_sse("stream.mode", {"mode": "polling", "interval_ms": 500})

        while True:
            if connection_manager.is_shutting_down:
                logger.info("SSE stream closing for job %s due to server shutdown", job_id)
                yield format_sse("job.shutdown", {"message": "Server shutting down"})
                break

            try:
                job = await job_store.get_job(job_id)
                if not job:
                    logger.warning(f"SSE: Job {job_id} not found")
                    yield format_sse("job.error", {"error": "Job not found"})
                    break

                # Replay mode drains historical events quickly without wait delays.
                # Live mode returns to regular polling cadence.
                if in_replay_mode:
                    limit = 10000 if job.status in terminal_statuses else 1000
                else:
                    limit = 10000 if job.status in terminal_statuses else 100
                events = await EventStore.get_events_async(db_url, job_id, last_event_id, limit)

                if events:
                    logger.info(f"SSE: Fetched {len(events)} events for job {job_id} (after_id={last_event_id})")
                elif job.status in terminal_statuses:
                    logger.warning(f"SSE: No events found for completed job {job_id} (after_id={last_event_id})")

                for i, event in enumerate(events):
                    if connection_manager.is_shutting_down:
                        logger.info("SSE stream closing for job %s due to server shutdown (mid-batch)", job_id)
                        yield format_sse("job.shutdown", {"message": "Server shutting down"})
                        return

                    try:
                        db_event_id = event.pop("_id", None)
                        if db_event_id:
                            last_event_id = db_event_id
                        event_type = event.pop("type", "event")
                        sse_output = format_sse(event_type, event, db_event_id)
                        yield sse_output
                    except Exception as e:
                        logger.error(f"SSE: Failed to yield event {i} (id={db_event_id}): {e}", exc_info=True)

                # Transition to live mode after historical catch-up:
                # - no more events after current cursor, or
                # - fetched a partial replay batch (< limit), indicating we've reached the current tail.
                if in_replay_mode and (not events or len(events) < limit):
                    in_replay_mode = False
                    replay_mode_announced = True
                    logger.info(
                        "SSE: Replay complete for job %s at event_id=%s; switching to live mode", job_id, last_event_id
                    )
                    yield format_sse("stream.mode", {"mode": "live"})

                if job.status != last_status:
                    last_status = job.status
                    logger.info(f"SSE: Job {job_id} status changed to {job.status}")
                    data = {"status": job.status}
                    if job.error:
                        data["error"] = job.error
                    if is_reconnect:
                        data["reconnected"] = True
                        is_reconnect = False
                    yield format_sse("job.status", data)

                if job.status in terminal_statuses:
                    break

                # During replay we intentionally avoid polling delays so clients can catch up quickly.
                if in_replay_mode:
                    continue

                # If replay was completed in a prior iteration but stream.mode couldn't be emitted
                # (e.g., due to an exception path), emit it once before waiting.
                if not in_replay_mode and not replay_mode_announced:
                    replay_mode_announced = True
                    yield format_sse("stream.mode", {"mode": "live"})

                shutdown_signaled = await connection_manager.wait_or_shutdown(0.5)
                if shutdown_signaled:
                    logger.info("SSE stream closing for job %s due to server shutdown (during wait)", job_id)
                    yield format_sse("job.shutdown", {"message": "Server shutting down"})
                    break

            except asyncio.CancelledError:
                logger.info("SSE stream cancelled for job %s", job_id)
                break
            except Exception as e:
                logger.exception("SSE stream error for job %s: %s", job_id, e)
                yield format_sse("job.error", {"error": "Internal server error"})
                break

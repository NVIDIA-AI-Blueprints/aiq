# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Async job orchestration for the MCP tool surface.

``submit`` runs the intent classifier synchronously so the caller learns the
routing decision (shallow vs deep) and gets a poll-cadence hint. Actual research
runs in a background asyncio task that updates the shared Postgres job row on
completion. ``poll`` and ``get_final_report`` are principal-scoped so callers
cannot read jobs owned by a different principal. The public MCP server always
passes the same ``anonymous`` principal, so its effective access control is
possession of the unguessable job UUID rather than per-user isolation.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from contextlib import suppress
from contextvars import ContextVar
from typing import Any
from typing import Protocol

from aiq_agent.agents.chat_researcher.models import DepthDecision
from aiq_agent.agents.chat_researcher.models import IntentResult
from aiq_agent.common.logging_utils import log_identifier_ref

from .job_store import Job
from .job_store import JobDepth
from .job_store import JobStore
from .workflow_runner import WorkflowRunner

logger = logging.getLogger(__name__)


class CheckpointTodoReaderProtocol(Protocol):
    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def get_todos(self, thread_id: str) -> list[dict[str, str]]: ...


# Per-job context binding so the log handler below can attribute captured
# errors back to the job that triggered them. asyncio tasks inherit the
# context at create_task time, so the binding survives the awaits inside
# _run_job and the workflow call chain.
_current_job_id: ContextVar[str | None] = ContextVar("aiq_mcp_current_job_id", default=None)


class _WorkflowFailureCapture(logging.Handler):
    """Capture workflow-level errors that the agent layer swallows.

    The chat_researcher converts certain shallow_researcher failures (most
    notably ``EmptySourceRegistryError`` - research returned no verifiable
    citations) into a polite "please rephrase" string and yields that as the
    successful result. The end user then sees ``state="complete"`` with a
    cryptic message and no idea what actually went wrong.

    This handler watches ``aiq_agent`` log records during a job's run, and
    when it sees one of the swallowed exceptions, stashes the original
    message keyed by job_id. ``_run_job`` consumes the stash after the
    workflow returns and (if non-empty) marks the job ``state="failed"``
    with the real reason instead of the canned fallback text.

    Per-job isolation is via the ``_current_job_id`` ContextVar: concurrent
    jobs each see their own job_id thanks to asyncio's context-copy semantics.
    """

    _CAPTURED_EXCEPTIONS = ("EmptySourceRegistryError",)

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self._captures: dict[str, str] = {}

    def emit(self, record: logging.LogRecord) -> None:
        job_id = _current_job_id.get()
        if not job_id:
            return
        # Prefer the raw exception (logger.exception(...) sets exc_info).
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            if type(exc).__name__ in self._CAPTURED_EXCEPTIONS:
                self._captures[job_id] = f"{type(exc).__name__}: {exc}"
                return
        # Fallback: chat_researcher's downgraded warning when the exception
        # has already been caught upstream.
        # TODO(#3b): This fallback matches on the substring "no verifiable
        # sources" in the log message, which is brittle — it silently breaks if
        # the upstream wording changes. Prefer a structured signal (a dedicated
        # exception type added to _CAPTURED_EXCEPTIONS, or a stable error code /
        # log extra) over string matching. Tracked for follow-up; not changing
        # behavior here.
        msg = record.getMessage()
        if "no verifiable sources" in msg.lower() and job_id not in self._captures:
            self._captures[job_id] = (
                "Research produced no verifiable sources - the model answered "
                "without invoking search tools. Try rephrasing as a lookup that "
                "obviously requires web search."
            )

    def consume(self, job_id: str) -> str | None:
        return self._captures.pop(job_id, None)

    def discard(self, job_id: str) -> None:
        """Drop any capture for ``job_id`` without returning it.

        Called unconditionally when a job finishes so an entry stashed during a
        run that then took an exception/cancel path (which skips ``consume``)
        cannot linger for the process lifetime.
        """
        self._captures.pop(job_id, None)


_FAILURE_HANDLER = _WorkflowFailureCapture()
# Guard against double-install if jobs.py is re-imported.
_aiq_logger = logging.getLogger("aiq_agent")
if not any(isinstance(h, _WorkflowFailureCapture) for h in _aiq_logger.handlers):
    _aiq_logger.addHandler(_FAILURE_HANDLER)


_SHALLOW_FIRST_POLL_SECONDS = 5
_SHALLOW_NEXT_POLL_SECONDS = 3
_SHALLOW_ESTIMATED_SECONDS = 10

_DEEP_POLL_SECONDS = 180
_DEEP_FIRST_POLL_SECONDS = _DEEP_POLL_SECONDS
_DEEP_ESTIMATED_SECONDS = 180

_DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 30.0
_DEFAULT_TTL_SWEEP_INTERVAL_SECONDS = 300.0
_DEFAULT_STALE_JOB_AFTER_SECONDS = 10 * 60
_STALE_JOB_ERROR = (
    "Research task was interrupted before completion. Submit the query again if you still need the result."
)


class JobManager:
    def __init__(
        self,
        runner: WorkflowRunner,
        store: JobStore,
        *,
        checkpoint_todo_reader: CheckpointTodoReaderProtocol | None = None,
        runner_id: str | None = None,
        heartbeat_interval_seconds: float = _DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        ttl_sweep_interval_seconds: float = _DEFAULT_TTL_SWEEP_INTERVAL_SECONDS,
        stale_job_after_seconds: int = _DEFAULT_STALE_JOB_AFTER_SECONDS,
    ) -> None:
        self._runner = runner
        self._store = store
        self._checkpoint_todo_reader = checkpoint_todo_reader
        self._runner_id = runner_id or f"{socket.gethostname()}:{uuid.uuid4()}"
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._ttl_sweep_interval_seconds = ttl_sweep_interval_seconds
        self._stale_job_after_seconds = stale_job_after_seconds
        # Tracked by job_id so wait_for_completion can find the right task.
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._ttl_sweeper_task: asyncio.Task | None = None

    async def start(self) -> None:
        try:
            await self._store.init()
            if self._checkpoint_todo_reader is not None:
                # Reuse the job store's warm pool for checkpoint reads when both
                # sides support it, rather than opening a second pool against the
                # same database. Falls back to the reader's own pool otherwise.
                shared_pool = getattr(self._store, "pool", None)
                bind_pool = getattr(self._checkpoint_todo_reader, "bind_pool", None)
                if shared_pool is not None and bind_pool is not None:
                    bind_pool(shared_pool)
                await self._checkpoint_todo_reader.start()
            # Run reconciliation once at startup so a fresh/restarted pod immediately
            # reaps jobs orphaned by the pod that previously owned them.
            await self._reconcile_jobs()

            if self._ttl_sweep_interval_seconds > 0 and self._ttl_sweeper_task is None:
                self._ttl_sweeper_task = asyncio.create_task(
                    self._reconcile_jobs_periodically(),
                    name=f"aiq-mcp-reconciler-{self._runner_id}",
                )
        except Exception:
            if self._checkpoint_todo_reader is not None:
                await self._checkpoint_todo_reader.close()
            await self._store.close()
            raise

    async def stop(self) -> None:
        if self._ttl_sweeper_task is not None:
            self._ttl_sweeper_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._ttl_sweeper_task
            self._ttl_sweeper_task = None

        tasks = list(self._active_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            with suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks, return_exceptions=True)
        self._active_tasks.clear()
        try:
            if self._checkpoint_todo_reader is not None:
                await self._checkpoint_todo_reader.close()
        finally:
            await self._store.close()

    async def submit(self, query: str, principal: str) -> dict[str, Any]:
        """Classify depth synchronously; enqueue a background task to run the full orchestrator.

        Returns a dict that always includes `job_id`, `depth`, and `state`. For meta
        queries (greetings) the return also includes `result` (state="complete"). For
        shallow/deep the return additionally includes `estimated_duration_seconds` and
        `first_poll_after_seconds` (state="queued").
        """
        classification = await self._runner.classify(query)

        intent = _extract_intent(classification)
        depth = _extract_depth(classification)

        if intent == "meta":
            meta_text = _extract_meta_text(classification)
            result_text = meta_text or "I'm here to help."
            job_id = await self._store.create(
                principal=principal,
                query=query,
                depth="meta",
                state="complete",
                result=result_text,
            )
            return {
                "job_id": job_id,
                "depth": "meta",
                "state": "complete",
                "result": result_text,
            }

        job_id = await self._store.create(
            principal=principal,
            query=query,
            depth=depth,
            state="queued",
        )
        task = asyncio.create_task(
            self._run_job(job_id, query),
            name=f"aiq-mcp-job-{log_identifier_ref(job_id)}",
        )
        self._active_tasks[job_id] = task
        task.add_done_callback(lambda _t, jid=job_id: self._active_tasks.pop(jid, None))

        return {
            "job_id": job_id,
            "depth": depth,
            "state": "queued",
            "estimated_duration_seconds": _SHALLOW_ESTIMATED_SECONDS if depth == "shallow" else _DEEP_ESTIMATED_SECONDS,
            "first_poll_after_seconds": _SHALLOW_FIRST_POLL_SECONDS if depth == "shallow" else _DEEP_FIRST_POLL_SECONDS,
        }

    async def wait_for_completion(self, job_id: str, principal: str, timeout: float) -> dict[str, Any] | None:
        """Wait up to ``timeout`` seconds for a job to reach a terminal state.

        Returns the final-report-shaped dict (``state="complete"|"failed"``) if
        the job finishes within the timeout, or ``None`` if the timeout elapses. On
        timeout the background task is not cancelled; a later ``poll()`` will
        still find the eventual result.

        Returns the not-found shape if the capability is malformed, the job
        vanished from the store, or the generic principal does not match. The
        public MCP boundary always supplies the shared ``anonymous`` principal.
        """
        if not _is_capability_id(job_id):
            return _job_not_found()

        job = await self._store.get(job_id)
        if job is None or job.principal != principal:
            return _job_not_found()
        if job.state in ("complete", "failed"):
            return _render_final_report(job)

        task = self._active_tasks.get(job_id)
        if task is None:
            # Task not tracked locally, for example after a pod restart or when
            # another replica handles a poll. Caller will fall back to polling.
            return None

        try:
            # Shield prevents our timeout from cancelling the underlying task.
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except TimeoutError:
            return None

        job = await self._store.get(job_id)
        if job is None:
            return _job_not_found()
        return _render_final_report(job)

    async def _run_job(self, job_id: str, query: str) -> None:
        job_id_token = _current_job_id.set(job_id)
        job_ref = log_identifier_ref(job_id)
        heartbeat_task: asyncio.Task | None = None
        try:
            await self._store.mark_running(job_id, self._runner_id)
            heartbeat_task = asyncio.create_task(
                self._heartbeat_job(job_id),
                name=f"aiq-mcp-heartbeat-{job_ref}",
            )
            logger.info("Job %s: running workflow", job_ref)
            result = await self._runner.run_query(query, conversation_id=job_id)
            # If a swallowed workflow error was captured during the run, surface
            # it as the job's failure reason instead of the polite fallback text
            # the agent layer returned as ``result``.
            captured = _FAILURE_HANDLER.consume(job_id)
            if captured is not None:
                logger.info(
                    "Job %s: surfaced swallowed workflow error: %s",
                    job_ref,
                    captured.replace(job_id, job_ref),
                )
                await self._store.update(job_id, state="failed", error=captured)
            else:
                await self._store.update(job_id, state="complete", result=result)
                logger.info("Job %s: complete", job_ref)
        except asyncio.CancelledError:
            logger.info("Job %s: cancelled", job_ref)
            await self._store.update(job_id, state="failed", error="Research task was cancelled before completion.")
            raise
        except Exception as exc:  # noqa: BLE001 - we want to catch everything for jobs
            logger.error("Job %s failed (%s)", job_ref, type(exc).__name__)
            sanitized = _sanitize_error(exc)
            await self._store.update(job_id, state="failed", error=sanitized)
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat_task
            # Guarantee the capture entry is gone on every exit path. The
            # success path already consumed it above; the exception/cancel
            # paths skip that consume, so without this they would leak.
            _FAILURE_HANDLER.discard(job_id)
            _current_job_id.reset(job_id_token)

    async def _heartbeat_job(self, job_id: str) -> None:
        if self._heartbeat_interval_seconds <= 0:
            return
        while True:
            await asyncio.sleep(self._heartbeat_interval_seconds)
            await self._store.heartbeat(job_id, self._runner_id)

    async def _reconcile_jobs(self) -> None:
        """Reap orphaned jobs and prune expired ones.

        - ``mark_stale_running_failed`` fails any ``queued``/``running`` row whose
          heartbeat has gone silent past ``stale_job_after_seconds`` — these are
          jobs whose owning pod died, so the in-memory asyncio task is gone and
          the row would otherwise be stuck ``running`` forever.
        - ``delete_expired`` drops rows past their TTL.

        Runs once at startup and then on every periodic sweep so a stable
        multi-replica deployment reaps dead-pod jobs within one sweep interval,
        not only when some replica happens to restart.
        """
        marked = await self._store.mark_stale_running_failed(
            stale_after_seconds=self._stale_job_after_seconds,
            error=_STALE_JOB_ERROR,
        )
        if marked:
            logger.info("Marked %d stale MCP jobs as failed", marked)

        deleted = await self._store.delete_expired()
        if deleted:
            logger.info("Deleted %d expired MCP jobs", deleted)

    async def _reconcile_jobs_periodically(self) -> None:
        while True:
            await asyncio.sleep(self._ttl_sweep_interval_seconds)
            try:
                await self._reconcile_jobs()
            except Exception:  # noqa: BLE001 - background task should not kill the server
                logger.exception("Failed to reconcile MCP jobs")

    async def poll(self, job_id: str, principal: str) -> dict[str, Any]:
        if not _is_capability_id(job_id):
            return _job_not_found()

        job = await self._store.record_poll(job_id, principal)
        if job is None:
            return _job_not_found()
        if job.principal != principal:
            # Preserve the generic principal-scoping behavior in the schema.
            # Public MCP requests all use ``anonymous`` and therefore rely on
            # possession of job_id instead of this check for isolation.
            return _job_not_found()

        return await self._render_job_status_with_todos(job)

    async def get_final_report(self, job_id: str, principal: str) -> dict[str, Any]:
        if not _is_capability_id(job_id):
            return _job_not_found()

        job = await self._store.get(job_id)
        if job is None:
            return _job_not_found()
        if job.principal != principal:
            # See poll(): this remains for schema compatibility and generic use,
            # not as per-user isolation at the public MCP boundary.
            return _job_not_found()

        return _render_final_report(job)

    async def _render_job_status_with_todos(self, job: Job) -> dict[str, Any]:
        resp = _render_job_status(job)
        resp["todos"] = await self._read_checkpoint_todos(job)
        return resp

    async def _read_checkpoint_todos(self, job: Job) -> list[dict[str, str]]:
        if self._checkpoint_todo_reader is None or job.depth != "deep" or job.state == "queued":
            return []
        try:
            return await self._checkpoint_todo_reader.get_todos(job.job_id)
        except Exception as exc:
            logger.warning(
                "Failed to read checkpoint todos for job %s (%s)",
                log_identifier_ref(job.job_id),
                type(exc).__name__,
            )
            return []


def _is_capability_id(job_id: str) -> bool:
    """Return whether ``job_id`` is the canonical UUID form emitted by JobStore."""
    try:
        parsed = uuid.UUID(job_id)
    except (AttributeError, TypeError, ValueError):
        return False
    return str(parsed) == job_id


def _job_not_found() -> dict[str, str]:
    return {"state": "not_found", "error": "job_not_found"}


def _extract_depth(classification: dict[str, Any]) -> JobDepth:
    decision = classification.get("depth_decision")
    if isinstance(decision, DepthDecision):
        return decision.decision
    if isinstance(decision, dict) and decision.get("decision") in ("shallow", "deep"):
        return decision["decision"]
    return "shallow"


def _extract_intent(classification: dict[str, Any]) -> str:
    intent_obj = classification.get("user_intent")
    if isinstance(intent_obj, IntentResult):
        return intent_obj.intent
    if isinstance(intent_obj, dict):
        return intent_obj.get("intent", "research")
    return "research"


def _extract_meta_text(classification: dict[str, Any]) -> str | None:
    messages = classification.get("messages") or []
    if messages:
        last = messages[-1]
        content = getattr(last, "content", None)
        if isinstance(content, str) and content.strip():
            return content
    return None


def _sanitize_error(exc: Exception) -> str:
    return f"Research task failed ({type(exc).__name__}). Check server logs for details."


def _render_job_status(job: Job) -> dict[str, Any]:
    resp: dict[str, Any] = {"job_id": job.job_id, "depth": job.depth, "state": job.state}
    if job.state == "failed":
        resp["error"] = job.error
    elif job.state in ("queued", "running"):
        resp["next_poll_after_seconds"] = _next_poll_seconds(job)
    return resp


def _next_poll_seconds(job: Job) -> int:
    if job.depth == "shallow":
        return _SHALLOW_NEXT_POLL_SECONDS
    return _DEEP_POLL_SECONDS


def _render_final_report(job: Job) -> dict[str, Any]:
    if job.state in ("queued", "running"):
        return {
            "job_id": job.job_id,
            "depth": job.depth,
            "state": "not_ready",
            "error": "job_not_ready",
        }

    resp: dict[str, Any] = {"job_id": job.job_id, "depth": job.depth, "state": job.state}
    if job.state == "complete":
        resp["result"] = job.result
    elif job.state == "failed":
        resp["error"] = job.error
    return resp

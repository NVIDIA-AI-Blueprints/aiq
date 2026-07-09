# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Core asynchronous job-orchestration tests."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from aiq_agent.agents.chat_researcher.models import DepthDecision
from aiq_agent.agents.chat_researcher.models import IntentResult
from aiq_agent.common.logging_utils import log_identifier_ref
from aiq_mcp.job_store import Job
from aiq_mcp.jobs import _FAILURE_HANDLER
from aiq_mcp.jobs import JobManager


class _Runner:
    def __init__(
        self,
        *,
        depth: str = "shallow",
        intent: str = "research",
        gate: asyncio.Event | None = None,
        result: str = "research answer",
        log_no_sources: bool = False,
        raise_after_log: bool = False,
    ):
        self.depth = depth
        self.intent = intent
        self.gate = gate
        self.result = result
        self.log_no_sources = log_no_sources
        self.raise_after_log = raise_after_log
        self.run_calls: list[tuple[str, str]] = []

    async def classify(self, query: str) -> dict[str, Any]:
        del query
        result: dict[str, Any] = {
            "user_intent": IntentResult(intent=self.intent),
            "depth_decision": DepthDecision(decision=self.depth),
        }
        if self.intent == "meta":
            result["messages"] = [AIMessage(content="Hello from AI-Q")]
        return result

    async def run_query(self, query: str, *, conversation_id: str) -> str:
        self.run_calls.append((query, conversation_id))
        if self.gate is not None:
            await self.gate.wait()
        if self.log_no_sources:
            logging.getLogger("aiq_agent").warning("No verifiable sources were produced")
        if self.raise_after_log:
            raise RuntimeError("workflow failed after logging")
        return self.result


class _MemoryJobStore:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    async def init(self) -> None:
        return None

    async def close(self) -> None:
        return None

    @property
    def pool(self) -> None:
        return None

    async def create(
        self,
        *,
        principal: str,
        query: str,
        depth: str,
        state: str,
        result: str | None = None,
        ttl_seconds: int = 24 * 3600,
    ) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        self.jobs[job_id] = Job(
            job_id=job_id,
            principal=principal,
            query=query,
            depth=depth,  # type: ignore[arg-type]
            state=state,  # type: ignore[arg-type]
            result=result,
            error=None,
            poll_count=0,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        return job_id

    async def mark_running(self, job_id: str, runner_id: str) -> bool:
        job = self.jobs[job_id]
        if job.state != "queued":
            return False
        job.state = "running"
        job.runner_id = runner_id
        now = datetime.now(UTC)
        job.heartbeat_at = now
        job.updated_at = now
        return True

    async def heartbeat(self, job_id: str, runner_id: str) -> None:
        job = self.jobs[job_id]
        if job.runner_id == runner_id and job.state == "running":
            job.heartbeat_at = datetime.now(UTC)

    async def update(
        self,
        job_id: str,
        *,
        state: str | None = None,
        result: str | None = None,
        error: str | None = None,
        from_states: tuple[str, ...] | None = None,
        runner_id: str | None = None,
    ) -> bool:
        job = self.jobs[job_id]
        if from_states is not None and job.state not in from_states:
            return False
        if runner_id is not None and job.runner_id != runner_id:
            return False
        if state is not None:
            job.state = state  # type: ignore[assignment]
        if result is not None:
            job.result = result
        if error is not None:
            job.error = error
        job.updated_at = datetime.now(UTC)
        return True

    async def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    async def record_poll(self, job_id: str, principal: str) -> Job | None:
        job = self.jobs.get(job_id)
        if job is not None and job.principal == principal and job.state in ("queued", "running"):
            job.poll_count += 1
        return job

    async def delete_expired(self) -> int:
        now = datetime.now(UTC)
        expired = [job_id for job_id, job in self.jobs.items() if job.expires_at < now]
        for job_id in expired:
            del self.jobs[job_id]
        return len(expired)

    async def mark_stale_running_failed(self, *, stale_after_seconds: int, error: str) -> int:
        stale_before = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
        count = 0
        for job in self.jobs.values():
            last_seen = job.heartbeat_at or job.updated_at
            if job.state in ("queued", "running") and last_seen < stale_before:
                job.state = "failed"
                job.error = error
                count += 1
        return count


class _MemoryTodoReader:
    def __init__(self) -> None:
        self.todos_by_thread_id: dict[str, list[dict[str, str]]] = {}
        self.calls: list[str] = []
        self.raise_for_thread_ids: set[str] = set()
        self.started = False
        self.closed = False
        self.bound_pool: object | None = None

    def bind_pool(self, pool: object) -> None:
        self.bound_pool = pool

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True

    async def get_todos(self, thread_id: str) -> list[dict[str, str]]:
        self.calls.append(thread_id)
        if thread_id in self.raise_for_thread_ids:
            raise RuntimeError("checkpoint read failed")
        return [dict(todo) for todo in self.todos_by_thread_id.get(thread_id, [])]


def _manager(runner: _Runner) -> JobManager:
    return JobManager(
        runner,  # type: ignore[arg-type]
        _MemoryJobStore(),  # type: ignore[arg-type]
        heartbeat_interval_seconds=0,
        ttl_sweep_interval_seconds=0,
    )


@pytest.mark.asyncio
async def test_submit_accepts_target_models_and_completes_meta_inline() -> None:
    manager = _manager(_Runner(intent="meta"))
    await manager.start()
    try:
        result = await manager.submit("hello", "anonymous")
    finally:
        await manager.stop()

    assert result == {
        "job_id": result["job_id"],
        "depth": "meta",
        "state": "complete",
        "result": "Hello from AI-Q",
    }
    assert uuid.UUID(result["job_id"]).version == 4


@pytest.mark.asyncio
async def test_meta_submit_uses_exact_fallback_when_classifier_has_no_message() -> None:
    class _MetaWithoutMessage(_Runner):
        async def classify(self, query: str) -> dict[str, Any]:
            del query
            return {
                "user_intent": {"intent": "meta"},
                "depth_decision": {"decision": "shallow"},
                "messages": [],
            }

    manager = _manager(_MetaWithoutMessage())
    await manager.start()
    try:
        result = await manager.submit("hello", "anonymous")
    finally:
        await manager.stop()

    assert result == {
        "job_id": result["job_id"],
        "depth": "meta",
        "state": "complete",
        "result": "I'm here to help.",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("depth", "estimated_seconds", "first_poll_seconds"),
    [
        ("shallow", 10, 5),
        ("deep", 180, 180),
    ],
)
async def test_research_submit_exact_queued_contract(
    depth: str,
    estimated_seconds: int,
    first_poll_seconds: int,
) -> None:
    gate = asyncio.Event()
    manager = _manager(_Runner(depth=depth, gate=gate))
    await manager.start()
    try:
        result = await manager.submit("question", "anonymous")
        assert result == {
            "job_id": result["job_id"],
            "depth": depth,
            "state": "queued",
            "estimated_duration_seconds": estimated_seconds,
            "first_poll_after_seconds": first_poll_seconds,
        }
        assert uuid.UUID(result["job_id"]).version == 4
    finally:
        gate.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_invalid_classifier_shape_defaults_to_shallow_research() -> None:
    class _InvalidClassifier(_Runner):
        async def classify(self, query: str) -> dict[str, Any]:
            del query
            return {
                "user_intent": {"intent": "unexpected"},
                "depth_decision": {"decision": "unsupported"},
            }

    gate = asyncio.Event()
    manager = _manager(_InvalidClassifier(gate=gate))
    await manager.start()
    try:
        result = await manager.submit("question", "anonymous")
        assert result == {
            "job_id": result["job_id"],
            "depth": "shallow",
            "state": "queued",
            "estimated_duration_seconds": 10,
            "first_poll_after_seconds": 5,
        }
    finally:
        gate.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_deep_job_uses_job_id_as_conversation_and_fixed_poll_cadence() -> None:
    gate = asyncio.Event()
    runner = _Runner(depth="deep", gate=gate)
    manager = _manager(runner)
    await manager.start()
    try:
        submitted = await manager.submit("compare systems", "anonymous")
        job_id = submitted["job_id"]
        assert str(uuid.UUID(job_id)) == job_id
        assert uuid.UUID(job_id).version == 4

        poll = await manager.poll(job_id, "anonymous")
        assert poll["depth"] == "deep"
        assert poll["state"] in {"queued", "running"}
        assert poll["next_poll_after_seconds"] == 180

        assert await manager.poll(job_id, "different-principal") == {
            "state": "not_found",
            "error": "job_not_found",
        }

        gate.set()
        final = await manager.wait_for_completion(job_id, "anonymous", timeout=1)
    finally:
        await manager.stop()

    assert final == {
        "job_id": job_id,
        "depth": "deep",
        "state": "complete",
        "result": "research answer",
    }
    assert runner.run_calls == [("compare systems", job_id)]


@pytest.mark.asyncio
async def test_invalid_capability_ids_return_stable_not_found_shape() -> None:
    manager = _manager(_Runner())
    not_found = {"state": "not_found", "error": "job_not_found"}

    for job_id in (
        "",
        "not-a-uuid",
        "{00000000-0000-4000-8000-000000000001}",
        "ABCDEFAB-CDEF-4ABC-8DEF-ABCDEFABCDEF",
    ):
        assert await manager.wait_for_completion(job_id, "anonymous", timeout=0) == not_found
        assert await manager.poll(job_id, "anonymous") == not_found
        assert await manager.get_final_report(job_id, "anonymous") == not_found

    unknown_capability = str(uuid.uuid4())
    assert await manager.poll(unknown_capability, "anonymous") == not_found
    assert await manager.get_final_report(unknown_capability, "anonymous") == not_found


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("depth", "state", "checkpoint_todos", "expected_without_id", "expected_reader_calls"),
    [
        (
            "meta",
            "complete",
            [{"content": "ignored", "status": "completed"}],
            {"depth": "meta", "state": "complete", "todos": []},
            0,
        ),
        (
            "shallow",
            "queued",
            [{"content": "ignored", "status": "pending"}],
            {"depth": "shallow", "state": "queued", "next_poll_after_seconds": 3, "todos": []},
            0,
        ),
        (
            "shallow",
            "running",
            [{"content": "ignored", "status": "pending"}],
            {"depth": "shallow", "state": "running", "next_poll_after_seconds": 3, "todos": []},
            0,
        ),
        (
            "deep",
            "queued",
            [{"content": "not read yet", "status": "pending"}],
            {"depth": "deep", "state": "queued", "next_poll_after_seconds": 180, "todos": []},
            0,
        ),
        (
            "deep",
            "running",
            [{"content": "Gather sources", "status": "in_progress"}],
            {
                "depth": "deep",
                "state": "running",
                "next_poll_after_seconds": 180,
                "todos": [{"content": "Gather sources", "status": "in_progress"}],
            },
            1,
        ),
        (
            "shallow",
            "complete",
            [{"content": "ignored", "status": "completed"}],
            {"depth": "shallow", "state": "complete", "todos": []},
            0,
        ),
        (
            "deep",
            "complete",
            [{"content": "Draft report", "status": "completed"}],
            {
                "depth": "deep",
                "state": "complete",
                "todos": [{"content": "Draft report", "status": "completed"}],
            },
            1,
        ),
        (
            "shallow",
            "failed",
            [{"content": "ignored", "status": "completed"}],
            {"depth": "shallow", "state": "failed", "error": "workflow failed", "todos": []},
            0,
        ),
        (
            "deep",
            "failed",
            [{"content": "Gather sources", "status": "completed"}],
            {
                "depth": "deep",
                "state": "failed",
                "error": "workflow failed",
                "todos": [{"content": "Gather sources", "status": "completed"}],
            },
            1,
        ),
    ],
)
async def test_poll_exact_golden_contract_for_every_persisted_state(
    depth: str,
    state: str,
    checkpoint_todos: list[dict[str, str]],
    expected_without_id: dict[str, Any],
    expected_reader_calls: int,
) -> None:
    store = _MemoryJobStore()
    reader = _MemoryTodoReader()
    manager = JobManager(
        _Runner(),
        store,  # type: ignore[arg-type]
        checkpoint_todo_reader=reader,
        heartbeat_interval_seconds=0,
        ttl_sweep_interval_seconds=0,
    )
    job_id = await store.create(
        principal="anonymous",
        query="question",
        depth=depth,
        state=state,
        result="research answer" if state == "complete" else None,
    )
    if state == "failed":
        await store.update(job_id, error="workflow failed")
    reader.todos_by_thread_id[job_id] = checkpoint_todos

    assert await manager.poll(job_id, "anonymous") == {
        "job_id": job_id,
        **expected_without_id,
    }
    assert reader.calls == [job_id] * expected_reader_calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("depth", "state", "expected_without_id"),
    [
        (
            "shallow",
            "queued",
            {"depth": "shallow", "state": "not_ready", "error": "job_not_ready"},
        ),
        (
            "deep",
            "running",
            {"depth": "deep", "state": "not_ready", "error": "job_not_ready"},
        ),
        (
            "meta",
            "complete",
            {"depth": "meta", "state": "complete", "result": "research answer"},
        ),
        (
            "shallow",
            "complete",
            {"depth": "shallow", "state": "complete", "result": "research answer"},
        ),
        (
            "deep",
            "complete",
            {"depth": "deep", "state": "complete", "result": "research answer"},
        ),
        (
            "deep",
            "failed",
            {"depth": "deep", "state": "failed", "error": "workflow failed"},
        ),
    ],
)
async def test_final_report_exact_golden_contract_for_every_persisted_state(
    depth: str,
    state: str,
    expected_without_id: dict[str, Any],
) -> None:
    store = _MemoryJobStore()
    manager = JobManager(
        _Runner(),
        store,  # type: ignore[arg-type]
        heartbeat_interval_seconds=0,
        ttl_sweep_interval_seconds=0,
    )
    job_id = await store.create(
        principal="anonymous",
        query="question",
        depth=depth,
        state=state,
        result="research answer" if state == "complete" else None,
    )
    if state == "failed":
        await store.update(job_id, error="workflow failed")

    assert await manager.get_final_report(job_id, "anonymous") == {
        "job_id": job_id,
        **expected_without_id,
    }


@pytest.mark.asyncio
async def test_all_job_accessors_hide_wrong_principal_without_todo_read() -> None:
    store = _MemoryJobStore()
    reader = _MemoryTodoReader()
    manager = JobManager(
        _Runner(),
        store,  # type: ignore[arg-type]
        checkpoint_todo_reader=reader,
        heartbeat_interval_seconds=0,
        ttl_sweep_interval_seconds=0,
    )
    job_id = await store.create(
        principal="principal-a",
        query="question",
        depth="deep",
        state="complete",
        result="answer",
    )
    not_found = {"state": "not_found", "error": "job_not_found"}

    assert await manager.poll(job_id, "principal-b") == not_found
    assert await manager.get_final_report(job_id, "principal-b") == not_found
    assert await manager.wait_for_completion(job_id, "principal-b", timeout=0) == not_found
    assert reader.calls == []


@pytest.mark.asyncio
async def test_poll_fails_soft_when_checkpoint_todo_read_fails(caplog) -> None:
    store = _MemoryJobStore()
    reader = _MemoryTodoReader()
    manager = JobManager(
        _Runner(),
        store,  # type: ignore[arg-type]
        checkpoint_todo_reader=reader,
        heartbeat_interval_seconds=0,
        ttl_sweep_interval_seconds=0,
    )
    job_id = await store.create(
        principal="anonymous",
        query="question",
        depth="deep",
        state="complete",
        result="answer",
    )
    reader.raise_for_thread_ids.add(job_id)
    caplog.set_level(logging.WARNING, logger="aiq_mcp.jobs")

    assert await manager.poll(job_id, "anonymous") == {
        "job_id": job_id,
        "depth": "deep",
        "state": "complete",
        "todos": [],
    }
    assert reader.calls == [job_id]
    assert "Failed to read checkpoint todos" in caplog.text


@pytest.mark.asyncio
async def test_job_logs_use_opaque_reference_not_capability_uuid(caplog) -> None:
    manager = _manager(_Runner())
    caplog.set_level(logging.INFO, logger="aiq_mcp.jobs")
    await manager.start()
    try:
        submitted = await manager.submit("query", "anonymous")
        job_id = submitted["job_id"]
        task_name = manager._active_tasks[job_id].get_name()
        result = await manager.wait_for_completion(job_id, "anonymous", timeout=1)
    finally:
        await manager.stop()

    assert result is not None
    assert result["state"] == "complete"
    assert job_id not in caplog.text
    assert job_id not in task_name
    assert log_identifier_ref(job_id) in caplog.text


@pytest.mark.asyncio
async def test_workflow_exception_does_not_log_capability_uuid(caplog) -> None:
    class _CapabilityEchoingRunner(_Runner):
        async def run_query(self, query: str, *, conversation_id: str) -> str:
            del query
            raise RuntimeError(f"workflow failed for conversation {conversation_id}")

    manager = _manager(_CapabilityEchoingRunner())
    caplog.set_level(logging.ERROR, logger="aiq_mcp.jobs")
    await manager.start()
    try:
        submitted = await manager.submit("query", "anonymous")
        job_id = submitted["job_id"]
        result = await manager.wait_for_completion(job_id, "anonymous", timeout=1)
    finally:
        await manager.stop()

    assert result is not None
    assert result == {
        "job_id": job_id,
        "depth": "shallow",
        "state": "failed",
        "error": "Research task failed (RuntimeError). Check server logs for details.",
    }
    assert job_id not in caplog.text
    assert log_identifier_ref(job_id) in caplog.text
    assert "RuntimeError" in caplog.text
    assert job_id not in _FAILURE_HANDLER._captures


@pytest.mark.asyncio
async def test_failure_capture_does_not_leak_when_workflow_raises() -> None:
    manager = _manager(_Runner(log_no_sources=True, raise_after_log=True))
    await manager.start()
    try:
        submitted = await manager.submit("query", "anonymous")
        job_id = submitted["job_id"]
        report = await manager.wait_for_completion(job_id, "anonymous", timeout=1)
    finally:
        await manager.stop()

    assert report == {
        "job_id": job_id,
        "depth": "shallow",
        "state": "failed",
        "error": "Research task failed (RuntimeError). Check server logs for details.",
    }
    assert job_id not in _FAILURE_HANDLER._captures


@pytest.mark.asyncio
async def test_transient_heartbeat_failure_retries_without_exposing_details(caplog) -> None:
    class _TransientHeartbeatStore(_MemoryJobStore):
        def __init__(self) -> None:
            super().__init__()
            self.heartbeat_calls = 0
            self.recovered = asyncio.Event()

        async def heartbeat(self, job_id: str, runner_id: str) -> None:
            self.heartbeat_calls += 1
            if self.heartbeat_calls == 1:
                raise RuntimeError("postgresql://user:credential-sentinel@db/jobs")  # pragma: allowlist secret
            await super().heartbeat(job_id, runner_id)
            self.recovered.set()

    gate = asyncio.Event()
    store = _TransientHeartbeatStore()
    manager = JobManager(
        _Runner(gate=gate),  # type: ignore[arg-type]
        store,  # type: ignore[arg-type]
        runner_id="pod-a",
        heartbeat_interval_seconds=0.001,
        ttl_sweep_interval_seconds=0,
    )
    caplog.set_level(logging.WARNING, logger="aiq_mcp.jobs")
    await manager.start()
    try:
        submitted = await manager.submit("query", "anonymous")
        job_id = submitted["job_id"]
        await asyncio.wait_for(store.recovered.wait(), timeout=1)
        gate.set()
        report = await manager.wait_for_completion(job_id, "anonymous", timeout=1)
    finally:
        gate.set()
        await manager.stop()

    assert report == {
        "job_id": job_id,
        "depth": "shallow",
        "state": "complete",
        "result": "research answer",
    }
    assert store.heartbeat_calls >= 2
    assert "heartbeat write failed (RuntimeError); retrying" in caplog.text
    assert log_identifier_ref(job_id) in caplog.text
    assert job_id not in caplog.text
    assert "credential-sentinel" not in caplog.text


@pytest.mark.asyncio
async def test_unexpected_heartbeat_task_failure_cannot_skip_job_cleanup(caplog, monkeypatch) -> None:
    gate = asyncio.Event()
    heartbeat_failed = asyncio.Event()
    manager = _manager(_Runner(gate=gate, log_no_sources=True, raise_after_log=True))

    async def _fail_heartbeat(job_id: str) -> None:
        del job_id
        heartbeat_failed.set()
        raise RuntimeError("postgresql://user:heartbeat-secret@db/jobs")  # pragma: allowlist secret

    monkeypatch.setattr(manager, "_heartbeat_job", _fail_heartbeat)
    caplog.set_level(logging.WARNING, logger="aiq_mcp.jobs")
    await manager.start()
    try:
        submitted = await manager.submit("query", "anonymous")
        job_id = submitted["job_id"]
        await asyncio.wait_for(heartbeat_failed.wait(), timeout=1)
        gate.set()
        report = await manager.wait_for_completion(job_id, "anonymous", timeout=1)
    finally:
        gate.set()
        await manager.stop()

    assert report == {
        "job_id": job_id,
        "depth": "shallow",
        "state": "failed",
        "error": "Research task failed (RuntimeError). Check server logs for details.",
    }
    assert "heartbeat task exited unexpectedly (RuntimeError)" in caplog.text
    assert log_identifier_ref(job_id) in caplog.text
    assert job_id not in caplog.text
    assert "heartbeat-secret" not in caplog.text
    assert job_id not in _FAILURE_HANDLER._captures


@pytest.mark.asyncio
async def test_inline_timeout_does_not_cancel_background_job() -> None:
    gate = asyncio.Event()
    manager = _manager(_Runner(gate=gate))
    await manager.start()
    try:
        submitted = await manager.submit("query", "anonymous")
        job_id = submitted["job_id"]

        assert await manager.wait_for_completion(job_id, "anonymous", timeout=0.01) is None
        assert not manager._active_tasks[job_id].cancelled()
    finally:
        gate.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_background_completion_does_not_overwrite_terminal_state() -> None:
    gate = asyncio.Event()
    store = _MemoryJobStore()
    manager = JobManager(
        _Runner(gate=gate),  # type: ignore[arg-type]
        store,  # type: ignore[arg-type]
        runner_id="pod-a",
        heartbeat_interval_seconds=0,
        ttl_sweep_interval_seconds=0,
    )
    await manager.start()
    try:
        submitted = await manager.submit("query", "anonymous")
        job_id = submitted["job_id"]
        task = manager._active_tasks[job_id]

        for _ in range(100):
            job = await store.get(job_id)
            if job is not None and job.state == "running":
                break
            await asyncio.sleep(0)
        else:
            raise AssertionError("background job did not enter running state")

        assert await store.update(job_id, state="failed", error="reconciled failure") is True
        gate.set()
        await asyncio.wait_for(task, timeout=1)

        report = await manager.get_final_report(job_id, "anonymous")
    finally:
        gate.set()
        await manager.stop()

    assert report == {
        "job_id": job_id,
        "depth": "shallow",
        "state": "failed",
        "error": "reconciled failure",
    }


@pytest.mark.asyncio
async def test_final_report_returns_not_ready_without_poll_cadence() -> None:
    gate = asyncio.Event()
    manager = _manager(_Runner(gate=gate))
    await manager.start()
    try:
        submitted = await manager.submit("query", "anonymous")
        report = await manager.get_final_report(submitted["job_id"], "anonymous")
    finally:
        gate.set()
        await manager.stop()

    assert report == {
        "job_id": submitted["job_id"],
        "depth": "shallow",
        "state": "not_ready",
        "error": "job_not_ready",
    }


@pytest.mark.asyncio
async def test_checkpoint_reader_lifecycle_and_pool_sharing() -> None:
    sentinel_pool = object()

    class _StoreWithPool(_MemoryJobStore):
        @property
        def pool(self) -> object:
            return sentinel_pool

    reader = _MemoryTodoReader()
    manager = JobManager(
        _Runner(),  # type: ignore[arg-type]
        _StoreWithPool(),  # type: ignore[arg-type]
        checkpoint_todo_reader=reader,
        heartbeat_interval_seconds=0,
        ttl_sweep_interval_seconds=0,
    )

    await manager.start()
    await manager.stop()

    assert reader.bound_pool is sentinel_pool
    assert reader.started is True
    assert reader.closed is True


@pytest.mark.asyncio
async def test_deep_poll_includes_todos_and_remains_principal_scoped() -> None:
    gate = asyncio.Event()
    store = _MemoryJobStore()
    reader = _MemoryTodoReader()
    manager = JobManager(
        _Runner(depth="deep", gate=gate),  # type: ignore[arg-type]
        store,  # type: ignore[arg-type]
        checkpoint_todo_reader=reader,
        heartbeat_interval_seconds=0,
        ttl_sweep_interval_seconds=0,
    )
    await manager.start()
    try:
        submitted = await manager.submit("query", "anonymous")
        job_id = submitted["job_id"]
        reader.todos_by_thread_id[job_id] = [{"content": "Plan", "status": "in_progress"}]
        await asyncio.sleep(0)

        assert await manager.poll(job_id, "anonymous") == {
            "job_id": job_id,
            "depth": "deep",
            "state": "running",
            "next_poll_after_seconds": 180,
            "todos": [{"content": "Plan", "status": "in_progress"}],
        }
        assert await manager.poll(job_id, "different-principal") == {
            "state": "not_found",
            "error": "job_not_found",
        }
        assert reader.calls == [job_id]
    finally:
        gate.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_swallowed_workflow_failure_is_persisted_as_failed() -> None:
    manager = _manager(_Runner(log_no_sources=True))
    await manager.start()
    try:
        submitted = await manager.submit("query", "anonymous")
        report = await manager.wait_for_completion(submitted["job_id"], "anonymous", timeout=1)
    finally:
        await manager.stop()

    assert report == {
        "job_id": submitted["job_id"],
        "depth": "shallow",
        "state": "failed",
        "error": (
            "Research produced no verifiable sources - the model answered without invoking search tools. "
            "Try rephrasing as a lookup that obviously requires web search."
        ),
    }
    assert submitted["job_id"] not in _FAILURE_HANDLER._captures


@pytest.mark.asyncio
async def test_exception_info_workflow_failure_is_persisted_as_sanitized_failed(caplog) -> None:
    class EmptySourceRegistryError(RuntimeError):
        pass

    class _ExceptionLoggingRunner(_Runner):
        async def run_query(self, query: str, *, conversation_id: str) -> str:
            del query, conversation_id
            try:
                raise EmptySourceRegistryError("registry is empty")
            except EmptySourceRegistryError:
                logging.getLogger("aiq_agent").exception("agent swallowed source failure")
            return "fallback answer"

    caplog.set_level(logging.ERROR, logger="aiq_agent")
    manager = _manager(_ExceptionLoggingRunner())
    await manager.start()
    try:
        submitted = await manager.submit("query", "anonymous")
        job_id = submitted["job_id"]
        report = await manager.wait_for_completion(job_id, "anonymous", timeout=1)
        polled = await manager.poll(job_id, "anonymous")
        final_report = await manager.get_final_report(job_id, "anonymous")
    finally:
        await manager.stop()

    expected_error = "Research task failed (EmptySourceRegistryError). Check server logs for details."
    assert report == {
        "job_id": job_id,
        "depth": "shallow",
        "state": "failed",
        "error": expected_error,
    }
    assert polled == {
        "job_id": job_id,
        "depth": "shallow",
        "state": "failed",
        "error": expected_error,
        "todos": [],
    }
    assert final_report == report
    assert "registry is empty" in caplog.text
    assert "registry is empty" not in report["error"]
    assert "registry is empty" not in polled["error"]
    assert "registry is empty" not in final_report["error"]
    assert job_id not in _FAILURE_HANDLER._captures


def test_operational_reconciliation_defaults_are_frozen() -> None:
    manager = JobManager(_Runner(), _MemoryJobStore())  # type: ignore[arg-type]

    assert manager._heartbeat_interval_seconds == 30.0
    assert manager._ttl_sweep_interval_seconds == 300.0
    assert manager._stale_job_after_seconds == 600


@pytest.mark.asyncio
async def test_stop_cancels_active_job_and_persists_exact_failure() -> None:
    gate = asyncio.Event()
    store = _MemoryJobStore()
    manager = JobManager(
        _Runner(gate=gate),  # type: ignore[arg-type]
        store,  # type: ignore[arg-type]
        heartbeat_interval_seconds=0,
        ttl_sweep_interval_seconds=0,
    )
    await manager.start()
    submitted = await manager.submit("question", "anonymous")
    job_id = submitted["job_id"]
    await asyncio.sleep(0)

    await manager.stop()

    job = await store.get(job_id)
    assert job is not None
    assert job.state == "failed"
    assert job.error == "Research task was cancelled before completion."
    assert job_id not in _FAILURE_HANDLER._captures


@pytest.mark.asyncio
async def test_expired_job_is_deleted_and_becomes_not_found() -> None:
    store = _MemoryJobStore()
    job_id = await store.create(
        principal="anonymous",
        query="question",
        depth="deep",
        state="complete",
        result="answer",
        ttl_seconds=-1,
    )
    manager = JobManager(
        _Runner(),
        store,  # type: ignore[arg-type]
        heartbeat_interval_seconds=0,
        ttl_sweep_interval_seconds=0,
    )

    await manager.start()
    try:
        assert await manager.poll(job_id, "anonymous") == {
            "state": "not_found",
            "error": "job_not_found",
        }
        assert await manager.get_final_report(job_id, "anonymous") == {
            "state": "not_found",
            "error": "job_not_found",
        }
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_startup_reconciles_stale_jobs() -> None:
    store = _MemoryJobStore()
    job_id = await store.create(principal="anonymous", query="query", depth="deep", state="running")
    store.jobs[job_id].updated_at = datetime.now(UTC) - timedelta(hours=1)
    manager = JobManager(
        _Runner(),  # type: ignore[arg-type]
        store,  # type: ignore[arg-type]
        heartbeat_interval_seconds=0,
        ttl_sweep_interval_seconds=0,
        stale_job_after_seconds=60,
    )

    await manager.start()
    try:
        report = await manager.get_final_report(job_id, "anonymous")
    finally:
        await manager.stop()

    assert report == {
        "job_id": job_id,
        "depth": "deep",
        "state": "failed",
        "error": (
            "Research task was interrupted before completion. Submit the query again if you still need the result."
        ),
    }

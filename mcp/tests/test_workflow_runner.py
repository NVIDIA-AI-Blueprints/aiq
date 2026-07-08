# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""NAT 1.8 workflow-runner compatibility tests."""

import logging
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from aiq_agent.agents.chat_researcher.models import ChatResearcherState
from aiq_agent.common.logging_utils import log_identifier_ref
from aiq_mcp import workflow_runner as workflow_runner_module
from aiq_mcp.workflow_runner import WorkflowRunner
from nat.builder.context import Context


def test_run_query_requires_explicit_conversation_id(tmp_path) -> None:
    runner = WorkflowRunner(tmp_path / "config.yml")

    with pytest.raises(TypeError, match="conversation_id"):
        runner.run_query("query")  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_classify_invokes_target_intent_function(tmp_path) -> None:
    observed: dict[str, object] = {}

    class _IntentFunction:
        async def ainvoke(self, state: ChatResearcherState) -> dict[str, str]:
            observed["state"] = state
            return {"classification": "ok"}

    class _Builder:
        async def get_function(self, name: str) -> _IntentFunction:
            observed["function_name"] = name
            return _IntentFunction()

    runner = WorkflowRunner(tmp_path / "config.yml")
    runner._session_manager = SimpleNamespace(shared_builder=_Builder())

    assert await runner.classify("What is CUDA?") == {"classification": "ok"}
    assert observed["function_name"] == "intent_classifier"
    state = observed["state"]
    assert isinstance(state, ChatResearcherState)
    assert isinstance(state.messages[-1], HumanMessage)
    assert state.messages[-1].content == "What is CUDA?"


@pytest.mark.asyncio
async def test_start_and_stop_own_one_nat_workflow_lifecycle(monkeypatch, tmp_path) -> None:
    events: list[tuple[str, str]] = []
    session_manager = SimpleNamespace()

    @asynccontextmanager
    async def fake_load_workflow(config_file: str):
        events.append(("enter", config_file))
        try:
            yield session_manager
        finally:
            events.append(("exit", config_file))

    monkeypatch.setattr(workflow_runner_module, "load_workflow", fake_load_workflow)
    runner = WorkflowRunner(tmp_path / "config.yml")

    await runner.start()
    await runner.start()
    assert runner._session_manager is session_manager

    await runner.stop()
    await runner.stop()

    assert events == [
        ("enter", str(tmp_path / "config.yml")),
        ("exit", str(tmp_path / "config.yml")),
    ]


@pytest.mark.asyncio
async def test_run_query_scopes_restores_context_and_redacts_capability_log(tmp_path, caplog) -> None:
    observed: dict[str, str | None] = {}
    job_id = str(uuid.uuid4())

    class _Result:
        async def result(self, to_type: type[str]) -> str:
            observed["result_type"] = to_type.__name__
            observed["result_context"] = Context.get().conversation_id
            return "research answer"

    class _RunContext:
        async def __aenter__(self) -> _Result:
            return _Result()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class _Session:
        def run(self, query: str) -> _RunContext:
            observed["query"] = query
            observed["run_context"] = Context.get().conversation_id
            return _RunContext()

    class _SessionContext:
        async def __aenter__(self) -> _Session:
            return _Session()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class _SessionManager:
        def session(self, *, conversation_id: str) -> _SessionContext:
            observed["session_id"] = conversation_id
            observed["session_context"] = Context.get().conversation_id
            return _SessionContext()

    runner = WorkflowRunner(tmp_path / "config.yml")
    runner._session_manager = _SessionManager()  # type: ignore[assignment]
    caplog.set_level(logging.INFO, logger="aiq_mcp.workflow_runner")

    with Context.scope(conversation_id="outer"):
        assert await runner.run_query("query", conversation_id=job_id) == "research answer"
        assert Context.get().conversation_id == "outer"

    assert observed == {
        "session_id": job_id,
        "session_context": job_id,
        "query": "query",
        "run_context": job_id,
        "result_type": "str",
        "result_context": job_id,
    }
    assert job_id not in caplog.text
    assert log_identifier_ref(job_id) in caplog.text


@pytest.mark.asyncio
async def test_workflow_runner_closes_only_owned_checkpointers(monkeypatch, tmp_path) -> None:
    from aiq_agent import common as aiq_common

    closed: list[str] = []

    class _Connection:
        async def close(self) -> None:
            closed.append("connection")

    class _Pool:
        def close(self) -> None:
            closed.append("pool")

    preexisting = object()
    monkeypatch.setattr(
        aiq_common,
        "_checkpointers",
        {"preexisting": preexisting, "owned": SimpleNamespace(conn=_Connection())},
    )
    monkeypatch.setattr(aiq_common, "_postgres_pools", {"owned": _Pool()})

    runner = WorkflowRunner(tmp_path / "config.yml")
    runner._owned_checkpointer_keys = {"owned"}

    await runner._close_owned_checkpointers()

    assert closed == ["connection", "pool"]
    assert aiq_common._checkpointers == {"preexisting": preexisting}
    assert aiq_common._postgres_pools == {}
    assert runner._owned_checkpointer_keys == set()

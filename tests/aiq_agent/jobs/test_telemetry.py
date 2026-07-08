# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.outputs import ChatGeneration
from langchain_core.outputs import LLMResult

from nat.builder.context import Context
from nat.builder.context import ContextState
from nat.data_models.intermediate_step import IntermediateStepPayload
from nat.data_models.intermediate_step import IntermediateStepType
from nat.data_models.invocation_node import InvocationNode
from nat.utils.reactive.subject import Subject


@pytest.fixture
def telemetry_context():
    """Provide an isolated NAT event stream and span stack for callback tests."""
    state = ContextState.get()
    event_stream = Subject()
    tokens = [
        (state.event_stream, state.event_stream.set(event_stream)),
        (state.active_span_id_stack, state.active_span_id_stack.set(["root"])),
        (
            state.active_function,
            state.active_function.set(InvocationNode(function_name="deep_research_agent", function_id="job-1")),
        ),
        (state.workflow_run_id, state.workflow_run_id.set("job-1")),
        (state.workflow_trace_id, state.workflow_trace_id.set(0x1234)),
    ]
    manager = Context(state).intermediate_step_manager
    events = []
    event_stream.subscribe(events.append)

    yield state, manager, events

    for context_var, token in reversed(tokens):
        context_var.reset(token)


@pytest.mark.asyncio
async def test_agent_telemetry_nests_named_subagent_and_model_under_task(telemetry_context):
    """DeepAgents task -> named agent -> model must be an explicit NAT span hierarchy."""
    from aiq_api.jobs.telemetry import AgentLifecycleTelemetryCallback
    from aiq_api.jobs.telemetry import AIQLangchainProfilerHandler

    _, manager, events = telemetry_context
    task_id = UUID("00000000-0000-0000-0000-000000000001")
    agent_id = UUID("00000000-0000-0000-0000-000000000002")
    model_id = UUID("00000000-0000-0000-0000-000000000003")

    manager.push_intermediate_step(
        IntermediateStepPayload(
            UUID="job-1",
            event_type=IntermediateStepType.WORKFLOW_START,
            name="deep_research_agent",
        )
    )
    agent_callback = AgentLifecycleTelemetryCallback(manager)
    profiler_callback = AIQLangchainProfilerHandler()

    await profiler_callback.on_tool_start(
        {"name": "task"},
        "{'subagent_type': 'planner-agent'}",
        run_id=task_id,
        inputs={"subagent_type": "planner-agent"},
    )
    agent_callback.on_chain_start(
        None,
        inputs={"messages": [HumanMessage(content="plan the research")]},
        run_id=agent_id,
        parent_run_id=task_id,
        name="planner-agent",
        metadata={"lc_agent_name": "planner-agent"},
    )
    await profiler_callback.on_chat_model_start(
        {},
        [[HumanMessage(content="plan the research")]],
        run_id=model_id,
        parent_run_id=agent_id,
        metadata={"ls_model_name": "test-model"},
        invocation_params={},
    )

    starts = {event.UUID: event for event in events if event.event_state.value == "START"}
    assert starts[str(task_id)].payload.name == "task: planner-agent"
    assert starts[str(task_id)].parent_id == "job-1"
    assert starts[str(agent_id)].event_type == IntermediateStepType.WORKFLOW_START
    assert starts[str(agent_id)].payload.name == "planner-agent"
    assert starts[str(agent_id)].payload.metadata.provided_metadata["span_role"] == "agent"
    assert starts[str(agent_id)].parent_id == str(task_id)
    assert starts[str(model_id)].parent_id == str(agent_id)

    result = LLMResult(
        generations=[[ChatGeneration(message=AIMessage(content="plan complete"))]],
        llm_output={"model_name": "test-model"},
    )
    await profiler_callback.on_llm_end(result, run_id=model_id)
    agent_callback.on_chain_end({"messages": [AIMessage(content="plan complete")]}, run_id=agent_id)
    await profiler_callback.on_tool_end("plan complete", run_id=task_id, name="task")
    manager.push_intermediate_step(
        IntermediateStepPayload(
            UUID="job-1",
            event_type=IntermediateStepType.WORKFLOW_END,
            name="deep_research_agent",
        )
    )

    started_ids = {event.UUID for event in events if event.event_state.value == "START"}
    assert all(event.parent_id == "root" or event.parent_id in started_ids for event in events)
    assert manager.get_outstanding_step_count() == 0
    assert profiler_callback.step_manager.get_outstanding_step_count() == 0


@pytest.mark.asyncio
async def test_parallel_researcher_spans_share_batch_parent_without_sharing_identity(telemetry_context):
    """Concurrent researcher runs remain distinct children of one batch tool span."""
    from aiq_api.jobs.telemetry import AgentLifecycleTelemetryCallback
    from aiq_api.jobs.telemetry import AIQLangchainProfilerHandler

    _, manager, events = telemetry_context
    batch_id = UUID("00000000-0000-0000-0000-000000000010")
    researcher_ids = [
        UUID("00000000-0000-0000-0000-000000000011"),
        UUID("00000000-0000-0000-0000-000000000012"),
    ]

    manager.push_intermediate_step(
        IntermediateStepPayload(
            UUID="job-1",
            event_type=IntermediateStepType.WORKFLOW_START,
            name="deep_research_agent",
        )
    )
    agent_callback = AgentLifecycleTelemetryCallback(manager)
    profiler_callback = AIQLangchainProfilerHandler()
    await profiler_callback.on_tool_start(
        {"name": "run_research_batch"},
        "{}",
        run_id=batch_id,
        inputs={},
    )

    async def run_researcher(run_id: UUID) -> None:
        agent_callback.on_chain_start(
            None,
            inputs={},
            run_id=run_id,
            parent_run_id=batch_id,
            name="researcher-agent",
            metadata={"lc_agent_name": "researcher-agent"},
        )
        await asyncio.sleep(0)
        agent_callback.on_chain_end({}, run_id=run_id)

    await asyncio.gather(*(run_researcher(run_id) for run_id in researcher_ids))

    starts = {
        event.UUID: event
        for event in events
        if event.event_state.value == "START" and event.payload.name == "researcher-agent"
    }
    assert set(starts) == {str(run_id) for run_id in researcher_ids}
    assert {event.parent_id for event in starts.values()} == {str(batch_id)}


def test_agent_lifecycle_spans_do_not_capture_graph_state(telemetry_context):
    """Structural agent spans must not duplicate LangGraph state into telemetry."""
    from aiq_api.jobs.telemetry import AgentLifecycleTelemetryCallback

    _, manager, events = telemetry_context
    callback = AgentLifecycleTelemetryCallback(manager)
    run_id = UUID("00000000-0000-0000-0000-000000000020")

    callback.on_chain_start(
        None,
        inputs={"messages": [HumanMessage(content="sensitive input")]},
        run_id=run_id,
        name="researcher-agent",
        metadata={"lc_agent_name": "researcher-agent"},
    )
    callback.on_chain_end(
        {"messages": [AIMessage(content="sensitive output")]},
        run_id=run_id,
    )

    assert len(events) == 2
    assert all(event.payload.data is None for event in events)
    assert all("sensitive input" not in str(event.payload.metadata) for event in events)
    assert all("sensitive output" not in str(event.payload.metadata) for event in events)


@pytest.mark.parametrize(
    ("name", "metadata", "expected"),
    [
        ("general-purpose", {"lc_agent_name": "general-purpose"}, True),
        ("reviewer", {"lc_agent_name": "reviewer"}, True),
        ("agent", {"langgraph_node": "agent"}, False),
        ("model", {"lc_agent_name": "reviewer"}, False),
    ],
)
def test_agent_lifecycle_requires_matching_deepagents_identity(telemetry_context, name, metadata, expected):
    """Only the outer chain identified by DeepAgents metadata is an agent boundary."""
    from aiq_api.jobs.telemetry import AgentLifecycleTelemetryCallback

    _, manager, events = telemetry_context
    callback = AgentLifecycleTelemetryCallback(manager)
    run_id = UUID("00000000-0000-0000-0000-000000000030")

    callback.on_chain_start(None, inputs={}, run_id=run_id, name=name, metadata=metadata)
    callback.on_chain_end({}, run_id=run_id)

    assert [event.payload.name for event in events] == ([name, name] if expected else [])
    assert manager.get_outstanding_step_count() == 0


def test_aiq_profiler_context_replaces_and_restores_nat_profiler(telemetry_context):
    """AIQ must customize NAT's inherited profiler instead of installing a duplicate callback."""
    from aiq_api.jobs.telemetry import AIQLangchainProfilerHandler
    from aiq_api.jobs.telemetry import aiq_langchain_profiler_context
    from nat.plugins.langchain.callback_handler import LangchainProfilerHandler
    from nat.plugins.profiler.decorators.framework_wrapper import callback_handler_var

    nat_profiler = LangchainProfilerHandler()
    token = callback_handler_var.set(nat_profiler)
    try:
        with aiq_langchain_profiler_context() as aiq_profiler:
            assert isinstance(aiq_profiler, AIQLangchainProfilerHandler)
            assert callback_handler_var.get() is aiq_profiler
            assert callback_handler_var.get() is not nat_profiler

        assert callback_handler_var.get() is nat_profiler
    finally:
        callback_handler_var.reset(token)

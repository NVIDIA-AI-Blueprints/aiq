# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Runtime tests for the autonomous Data Science Agent."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool

from aiq_agent.agents.data_science import agent as agent_module
from aiq_agent.agents.data_science.agent import DataScienceAgent
from aiq_agent.agents.data_science.models import DataScienceAgentContext
from aiq_agent.agents.data_science.models import DataScienceAgentState
from aiq_agent.common import get_session_registry
from aiq_agent.common import render_prompt_template
from aiq_agent.common import reset_session_registry
from aiq_agent.common import set_session_registry
from aiq_agent.common.citation_verification import EmptySourceRegistryError
from aiq_agent.common.data_source_registry import populate_from_config
from aiq_agent.common.data_source_registry import reset_registry


def _tool(name: str = "gsf__text_to_sql") -> StructuredTool:
    async def invoke(question: str) -> str:
        """Return one test observation."""
        return question

    return StructuredTool.from_function(coroutine=invoke, name=name, description="Test data tool.")


def _agent(graph, monkeypatch, *, interaction_mode: str = "interactive") -> DataScienceAgent:
    monkeypatch.setattr(agent_module, "create_agent", MagicMock(return_value=graph))
    return DataScienceAgent(
        llm=MagicMock(),
        tools=[_tool()],
        recursion_limit=24,
        interaction_mode=interaction_mode,
    )


@pytest.fixture(autouse=True)
def _register_sources():
    reset_registry()
    populate_from_config(
        [
            {"id": "structured_data", "name": "GSF", "tools": ["gsf"]},
            {"id": "knowledge_layer", "name": "Knowledge", "tools": ["knowledge_search"]},
            {"id": "web_search", "name": "Web", "tools": ["web_search_tool"]},
        ],
        group_names={"gsf"},
    )
    try:
        yield
    finally:
        reset_registry()


@pytest.mark.asyncio
async def test_run_invokes_one_graph_with_full_history_and_preserves_state(monkeypatch):
    original = [HumanMessage(content="Rank users by GPU hours")]
    full_history = [
        *original,
        ToolMessage(
            content=('{"request_id":"gsf-1","sql":"SELECT user_id, SUM(gpu_hours)","rows":[["user_1",42]]}'),
            name="gsf__text_to_sql",
            tool_call_id="query-1",
        ),
        AIMessage(content="user_1 used 42 GPU-hours."),
    ]
    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value={"messages": full_history})
    state = DataScienceAgentState(
        messages=original,
        data_sources=["structured_data"],
        user_info={"tenant": "acme"},
    )

    result = await _agent(graph, monkeypatch).run(state)

    call = graph.ainvoke.await_args
    assert call.args[0] == {"messages": original}
    assert call.kwargs["config"] == {"recursion_limit": 24}
    assert call.kwargs["context"] == DataScienceAgentContext(user_info={"tenant": "acme"})
    assert result.messages[-1].content.startswith("user_1 used 42 GPU-hours [1].")
    assert "gsf__text_to_sql request gsf-1" in result.messages[-1].content
    assert result.data_sources == ["structured_data"]
    assert result.user_info == {"tenant": "acme"}


@pytest.mark.parametrize(
    "messages",
    [[], [HumanMessage(content=" \n\t ")], [AIMessage(content="Assistant-only status")]],
)
@pytest.mark.asyncio
async def test_run_rejects_missing_or_blank_human_question(messages, monkeypatch):
    graph = MagicMock()
    graph.ainvoke = AsyncMock()

    with pytest.raises(ValueError, match="at least one message|empty question"):
        await _agent(graph, monkeypatch).run(DataScienceAgentState(messages=messages))

    graph.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_run_installs_and_restores_request_local_registry(monkeypatch):
    original = [HumanMessage(content="Get one result")]

    async def invoke(*_args, **_kwargs):
        assert get_session_registry() is not None
        return {"messages": [*original, AIMessage(content="Done")]}

    graph = MagicMock()
    graph.ainvoke = AsyncMock(side_effect=invoke)
    outer_token = set_session_registry(None)
    try:
        with pytest.raises(EmptySourceRegistryError):
            await _agent(graph, monkeypatch).run(DataScienceAgentState(messages=original))
        assert get_session_registry() is None
    finally:
        reset_session_registry(outer_token)


@pytest.mark.asyncio
async def test_headless_run_retries_clarification_once_and_removes_internal_nudge(monkeypatch):
    original = [HumanMessage(content="Rank users by GPU usage")]
    observation = ToolMessage(
        content='{"request_id":"gsf-1","rows":[["user_1",42]]}',
        name="gsf__text_to_sql",
        tool_call_id="query-1",
    )
    graph = MagicMock()

    async def invoke(payload, **_kwargs):
        if graph.ainvoke.await_count == 1:
            return {
                "messages": [
                    *original,
                    observation,
                    AIMessage(content="Which time window should I use?"),
                ]
            }
        return {"messages": [*payload["messages"], AIMessage(content="user_1 used 42 GPU-hours.")]}

    graph.ainvoke = AsyncMock(side_effect=invoke)

    result = await _agent(graph, monkeypatch, interaction_mode="headless").run(DataScienceAgentState(messages=original))

    assert graph.ainvoke.await_count == 2
    retry_messages = graph.ainvoke.await_args_list[1].args[0]["messages"]
    assert retry_messages[-1].name == "aiq_headless_synthesis_retry"
    assert "No user interaction is available" in str(retry_messages[-1].content)
    assert all(message.name != "aiq_headless_synthesis_retry" for message in result.messages)
    assert "Which time window" not in str(result.messages[-1].content)
    assert str(result.messages[-1].content).startswith("user_1 used 42 GPU-hours [1].")


@pytest.mark.asyncio
async def test_headless_run_replaces_second_clarification_with_terminal_response(monkeypatch):
    original = [HumanMessage(content="Rank users")]
    observation = ToolMessage(
        content='{"request_id":"gsf-1","rows":[]}',
        name="gsf__text_to_sql",
        tool_call_id="query-1",
    )
    graph = MagicMock()

    async def invoke(payload, **_kwargs):
        return {
            "messages": [
                *payload["messages"],
                observation,
                AIMessage(content="Could you specify which metric I should use?"),
            ]
        }

    graph.ainvoke = AsyncMock(side_effect=invoke)

    result = await _agent(graph, monkeypatch, interaction_mode="headless").run(DataScienceAgentState(messages=original))

    assert graph.ainvoke.await_count == 2
    assert "could not complete the request non-interactively" in str(result.messages[-1].content)
    assert "?" not in str(result.messages[-1].content)


def test_constructor_passes_exact_tools_and_injected_middleware(monkeypatch):
    graph = MagicMock()
    create_agent = MagicMock(return_value=graph)
    custom_middleware = MagicMock(spec=AgentMiddleware)
    tools = [_tool("gsf__catalog_search"), _tool()]
    monkeypatch.setattr(agent_module, "create_agent", create_agent)

    agent = DataScienceAgent(
        llm=MagicMock(),
        tools=tools,
        recursion_limit=40,
        middleware=[custom_middleware],
    )

    call = create_agent.call_args
    assert call.kwargs["tools"] == tools
    assert call.kwargs["middleware"][1:] == [custom_middleware]
    assert call.kwargs["context_schema"] is DataScienceAgentContext
    assert call.kwargs["name"] == "data_science_agent"
    assert agent.graph is graph
    assert agent.source_tool_names == frozenset({"gsf__catalog_search", "gsf__text_to_sql"})
    assert agent.interaction_mode == "interactive"


def test_constructor_requires_explicit_unique_tools(monkeypatch):
    create_agent = MagicMock()
    monkeypatch.setattr(agent_module, "create_agent", create_agent)

    with pytest.raises(ValueError, match="no available data tools"):
        DataScienceAgent(llm=MagicMock(), tools=[])
    with pytest.raises(ValueError, match="duplicate tool names: gsf__text_to_sql"):
        DataScienceAgent(llm=MagicMock(), tools=[_tool(), _tool()])
    with pytest.raises(ValueError, match="at least four"):
        DataScienceAgent(llm=MagicMock(), tools=[_tool()], recursion_limit=3)
    with pytest.raises(ValueError, match="unsupported data-science interaction mode"):
        DataScienceAgent(llm=MagicMock(), tools=[_tool()], interaction_mode="batch")

    create_agent.assert_not_called()


def test_prompt_uses_public_aiq_tool_contracts():
    prompt = (agent_module.AGENT_DIR / "prompts" / "agent.j2").read_text()

    assert "`gsf__catalog_search`" in prompt
    assert "`gsf__text_to_sql`" in prompt
    assert "knowledge-search tool" in prompt
    assert "web search" in prompt
    assert "gsf__query" not in prompt
    assert "predictive" not in prompt
    assert 'interaction_mode == "headless"' in prompt
    assert "Never ask the user a follow-up question" in prompt


def test_prompt_renders_distinct_interaction_policies():
    template = (agent_module.AGENT_DIR / "prompts" / "agent.j2").read_text()
    common = {"tools": [], "user_info": None, "current_datetime": "2026-08-11T12:00:00-03:00"}

    interactive = render_prompt_template(template, interaction_mode="interactive", **common)
    headless = render_prompt_template(template, interaction_mode="headless", **common)

    assert "ask one concise clarification question" in interactive
    assert "Never ask the user a follow-up question" not in interactive
    assert "Never ask the user a follow-up question" in headless
    assert "ask one concise clarification question" not in headless


def test_gsf_calls_keep_distinct_request_receipts():
    from aiq_agent.agents.data_science.utils.reporting import capture_data_sources
    from aiq_agent.common.citation_verification import SourceRegistry

    registry = SourceRegistry()
    capture_data_sources(
        [
            ToolMessage(
                content='{"request_id":"request-1","sql":"SELECT 1","rows":[{"value":1}]}',
                name="gsf__text_to_sql",
                tool_call_id="call-1",
            ),
            ToolMessage(
                content='{"request_id":"request-1","sql":"SELECT 2","rows":[{"value":2}]}',
                name="gsf__text_to_sql",
                tool_call_id="call-2",
            ),
        ],
        registry=registry,
        eligible_tool_names=frozenset({"gsf__text_to_sql"}),
    )

    assert [source.citation_key for source in registry.all_sources()] == [
        "gsf__text_to_sql request request-1",
        "gsf__text_to_sql request request-1 (2)",
    ]

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for Data Science Agent NAT registration."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool

from aiq_agent.agents.chat_researcher.models import CatalogRoutingResponse
from aiq_agent.agents.chat_researcher.models import ChatResearcherState
from aiq_agent.agents.data_science import register as data_science_register
from aiq_agent.agents.data_science.models import DataScienceAgentState
from aiq_agent.common.citation_verification import EmptySourceRegistryError
from aiq_agent.common.data_source_registry import populate_from_config
from aiq_agent.common.data_source_registry import reset_registry


@tool
def _dummy_search(query: str) -> str:
    """Return a configured test result."""
    return query


def test_config_inherits_registry_tools_and_rejects_unknown_fields():
    config = data_science_register.DataScienceAgentConfig(llm="model")

    assert config.tools == []
    assert config.exclude_tools == []
    assert config.recursion_limit == 64
    assert config.interaction_mode == "interactive"
    assert config.response_mode == "standard"
    assert config.gsf_catalog_call_limit is None
    assert config.gsf_text_to_sql_call_limit is None
    assert config.gsf_cache_repeated_calls is True
    assert config.python_call_limit is None
    assert config.finalization_model_call_limit is None
    with pytest.raises(ValueError, match="models"):
        data_science_register.DataScienceAgentConfig(llm="model", models={"planner": "model"})
    with pytest.raises(ValueError, match="interaction_mode"):
        data_science_register.DataScienceAgentConfig(llm="model", interaction_mode="batch")
    with pytest.raises(ValueError, match="response_mode"):
        data_science_register.DataScienceAgentConfig(llm="model", response_mode="brief")


@pytest.mark.asyncio
async def test_registration_inherits_registry_refs_and_runs_selected_tools():
    reset_registry()
    populate_from_config(
        [{"id": "structured_data", "name": "GSF", "tools": ["gsf"]}],
        group_names={"gsf"},
    )
    builder = MagicMock()
    builder.get_tools = AsyncMock(return_value=[_dummy_search])
    builder.get_llm = AsyncMock(return_value=MagicMock())
    config = data_science_register.DataScienceAgentConfig(llm="model")

    registration = data_science_register.data_science_agent.__wrapped__(config, builder)
    with patch.object(data_science_register, "get_all_tool_refs", return_value=["gsf"]):
        function_info = await anext(registration)
    try:
        sentinel = DataScienceAgentState(
            messages=[HumanMessage(content="answer"), AIMessage(content="grounded")],
        )
        with patch.object(data_science_register.DataScienceAgent, "run", AsyncMock(return_value=sentinel)):
            result = await function_info.single_fn(DataScienceAgentState(messages=[HumanMessage(content="query")]))
    finally:
        await registration.aclose()
        reset_registry()

    builder.get_tools.assert_awaited_once_with(
        tool_names=["gsf"],
        wrapper_type=data_science_register.LLMFrameworkEnum.LANGCHAIN,
    )
    assert result is sentinel


@pytest.mark.asyncio
async def test_registration_passes_headless_mode_to_agent():
    reset_registry()
    populate_from_config(
        [{"id": "structured_data", "name": "GSF", "tools": ["gsf"]}],
        group_names={"gsf"},
    )
    builder = MagicMock()
    builder.get_tools = AsyncMock(return_value=[_dummy_search])
    builder.get_llm = AsyncMock(return_value=MagicMock())
    config = data_science_register.DataScienceAgentConfig(
        llm="model",
        interaction_mode="headless",
        response_mode="fdabench_choice",
        gsf_catalog_call_limit=2,
        gsf_text_to_sql_call_limit=6,
        python_call_limit=7,
        finalization_model_call_limit=28,
    )

    registration = data_science_register.data_science_agent.__wrapped__(config, builder)
    with (
        patch.object(data_science_register, "get_all_tool_refs", return_value=["gsf"]),
        patch.object(data_science_register, "DataScienceAgent") as agent_cls,
    ):
        function_info = await anext(registration)
    try:
        assert function_info is not None
        assert agent_cls.call_args.kwargs["interaction_mode"] == "headless"
        assert agent_cls.call_args.kwargs["response_mode"] == "fdabench_choice"
        assert agent_cls.call_args.kwargs["gsf_catalog_call_limit"] == 2
        assert agent_cls.call_args.kwargs["gsf_text_to_sql_call_limit"] == 6
        assert agent_cls.call_args.kwargs["python_call_limit"] == 7
        assert agent_cls.call_args.kwargs["finalization_model_call_limit"] == 28
    finally:
        await registration.aclose()
        reset_registry()


@pytest.mark.asyncio
async def test_direct_workflow_returns_typed_no_source_response():
    error = EmptySourceRegistryError(generated_answer="The backend returned no rows.")
    agent_fn = MagicMock()
    agent_fn.ainvoke = AsyncMock(side_effect=error)
    builder = MagicMock()
    builder.get_function = AsyncMock(return_value=agent_fn)
    config = data_science_register.DataScienceWorkflowConfig()

    registration = data_science_register.data_science_workflow.__wrapped__(config, builder)
    function_info = await anext(registration)
    try:
        response = await function_info.single_fn("Rank users")
    finally:
        await registration.aclose()

    builder.get_function.assert_awaited_once_with("data_science_agent")
    assert response.choices[0].message.content == error.public_response


@pytest.mark.asyncio
async def test_hybrid_adapter_maps_router_context_and_returns_only_final_response():
    catalog = CatalogRoutingResponse(
        request_id="catalog-1",
        coverage=0.75,
        candidates=[
            {
                "label": "ColumnAttribute",
                "attribute": "recognized_revenue",
                "term": "Revenue",
                "id": "attr:revenue",
            }
        ],
        uncovered_entities=["public market comparison"],
    )
    input_message = HumanMessage(content="Compare enterprise revenue with the public market")
    tool_message = ToolMessage(content="rows", tool_call_id="gsf-call-1", name="gsf__text_to_sql")
    final_message = AIMessage(content="Enterprise revenue increased relative to the public market.")
    agent_fn = MagicMock()
    agent_fn.ainvoke = AsyncMock(
        return_value=DataScienceAgentState(messages=[input_message, tool_message, final_message])
    )
    builder = MagicMock()
    builder.get_function = AsyncMock(return_value=agent_fn)
    config = data_science_register.DataScienceHybridAdapterConfig(agent="data_science_agent")

    registration = data_science_register.data_science_hybrid_adapter.__wrapped__(config, builder)
    function_info = await anext(registration)
    try:
        result = await function_info.single_fn(
            ChatResearcherState(
                messages=[input_message],
                data_sources=["structured_data", "web_search"],
                user_info={"tenant": "acme"},
                database_name="benchmark_db",
                catalog_context=catalog,
                catalog_request_id="catalog-1",
            )
        )
    finally:
        await registration.aclose()

    builder.get_function.assert_awaited_once_with(config.agent)
    invoked_state = agent_fn.ainvoke.await_args.args[0]
    assert invoked_state.messages == [input_message]
    assert invoked_state.data_sources == ["structured_data", "web_search"]
    assert invoked_state.user_info == {"tenant": "acme"}
    assert invoked_state.database_name == "benchmark_db"
    assert invoked_state.catalog_request_id == "catalog-1"
    assert invoked_state.catalog_context == catalog.model_dump(mode="json")
    assert result == {"messages": [final_message]}


@pytest.mark.asyncio
async def test_hybrid_adapter_rejects_missing_new_final_response():
    input_message = HumanMessage(content="Analyze revenue")
    agent_fn = MagicMock()
    agent_fn.ainvoke = AsyncMock(return_value=DataScienceAgentState(messages=[input_message]))
    builder = MagicMock()
    builder.get_function = AsyncMock(return_value=agent_fn)
    config = data_science_register.DataScienceHybridAdapterConfig(agent="data_science_agent")

    registration = data_science_register.data_science_hybrid_adapter.__wrapped__(config, builder)
    function_info = await anext(registration)
    try:
        with pytest.raises(RuntimeError, match="no final response"):
            await function_info.single_fn(ChatResearcherState(messages=[input_message]))
    finally:
        await registration.aclose()

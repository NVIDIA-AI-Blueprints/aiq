# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for Data Science Agent NAT registration."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

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
    assert config.analysis_workspace_call_limit is None
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
        analysis_workspace_call_limit=8,
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
        assert agent_cls.call_args.kwargs["analysis_workspace_call_limit"] == 8
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

    assert response.choices[0].message.content == error.public_response

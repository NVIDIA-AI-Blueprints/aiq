# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for shallow_researcher ``_run`` per-user-MCP handling (AIQ-002).

The standalone MCP image intentionally omits ``aiq_api`` (the per-user auth layer).
The per-user-MCP block must degrade gracefully when those imports fail — previously
its ``except`` clause referenced an exception type imported *inside* the failing
``try``, so a missing ``aiq_api`` raised ``UnboundLocalError`` and every shallow query
failed.
"""

import sys
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from aiq_agent.agents.shallow_researcher import register as shallow_register
from aiq_agent.agents.shallow_researcher.models import ShallowResearchAgentState


@tool
def _dummy_search(query: str) -> str:
    """Dummy search tool used to build the agent."""
    return f"result for {query}"


async def _build_run():
    """Build the register's real ``_run`` closure with a mocked NAT builder."""
    config = shallow_register.ShallowResearchAgentConfig(llm="llm_ref", tools=["dummy"])
    builder = MagicMock()
    builder.get_llm = AsyncMock(return_value=MagicMock())
    builder.get_tools = AsyncMock(return_value=[_dummy_search])
    agen = shallow_register.shallow_research_agent.__wrapped__(config, builder)
    fn_info = await agen.__anext__()
    return fn_info.single_fn, agen


# aiq_api and every submodule ``_run`` imports; setting each to ``None`` in
# sys.modules makes ``from aiq_api... import ...`` raise ImportError.
_AIQ_API_MODULES = [
    "aiq_api",
    "aiq_api.jobs",
    "aiq_api.jobs.access",
    "aiq_api.mcp_auth",
    "aiq_api.mcp_auth.provider",
    "aiq_api.mcp_auth.runtime_tools",
]


@pytest.mark.asyncio
async def test_shallow_run_skips_per_user_mcp_when_aiq_api_absent():
    """Without aiq_api (standalone MCP), ``_run`` skips per-user MCP and proceeds
    instead of raising UnboundLocalError."""
    run, agen = await _build_run()
    try:
        sentinel = ShallowResearchAgentState(messages=[HumanMessage(content="answered")])
        with (
            patch.dict(sys.modules, {m: None for m in _AIQ_API_MODULES}),
            patch.object(shallow_register, "ShallowResearcherAgent") as mock_agent_cls,
            patch("aiq_agent.common.validate_tool_availability", return_value=(True, 1, [])),
        ):
            mock_agent_cls.return_value.run = AsyncMock(return_value=sentinel)
            state = ShallowResearchAgentState(messages=[HumanMessage(content="What year was NVIDIA founded?")])
            result = await run(state)
        # Reached agent.run -> got past the per-user block without crashing.
        assert result is sentinel
    finally:
        await agen.aclose()


@pytest.mark.asyncio
async def test_shallow_run_surfaces_reconnect_when_source_unavailable():
    """With aiq_api present, an unresolvable per-user source yields a reconnect
    message rather than silently answering without it."""
    pytest.importorskip("aiq_api")
    from aiq_api.mcp_auth.runtime_tools import PerUserMcpSourceUnavailableError

    run, agen = await _build_run()
    try:
        with (
            patch("aiq_api.jobs.access.require_verified_principal", return_value=MagicMock()),
            patch("aiq_api.mcp_auth.provider.principal_user_id", return_value="user-1"),
            patch(
                "aiq_api.mcp_auth.runtime_tools.open_per_user_mcp_tools",
                AsyncMock(side_effect=PerUserMcpSourceUnavailableError(["google_drive"])),
            ),
        ):
            state = ShallowResearchAgentState(messages=[HumanMessage(content="summarize my drive doc")])
            result = await run(state)
        assert isinstance(result, ShallowResearchAgentState)
        content = result.messages[-1].content
        assert "google_drive" in content
        assert "Reconnect them in the data sources panel" in content
    finally:
        await agen.aclose()

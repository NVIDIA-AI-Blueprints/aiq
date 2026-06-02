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

"""Tests for source tool batch wrappers."""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool

from aiq_agent.agents.deep_researcher.custom_middleware import SourceRegistryMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import SourceToolConcurrencyLimiter
from aiq_agent.agents.deep_researcher.tools.source_tool_batching import build_batch_source_tools


@pytest.mark.asyncio
async def test_batch_wrapper_single_string_calls_original_once():
    calls: list[str] = []

    @tool
    async def search_tool(query: str) -> str:
        """Search a source."""
        calls.append(query)
        return f"result for {query}"

    result = build_batch_source_tools(
        [search_tool],
        source_tool_names={"search_tool"},
        limiter=SourceToolConcurrencyLimiter(2),
        max_batch_size=3,
    )

    wrapped = result.tools[0]
    output = await wrapped.ainvoke({"queries": "alpha"})

    assert wrapped.name == "search_tool"
    assert result.wrapped_tool_names == {"search_tool"}
    assert calls == ["alpha"]
    assert "## Query: alpha" in output
    assert "result for alpha" in output


@pytest.mark.asyncio
async def test_batch_wrapper_list_calls_original_once_per_item():
    calls: list[str] = []

    @tool
    async def search_tool(query: str) -> str:
        """Search a source."""
        calls.append(query)
        return f"https://example.test/{query}"

    result = build_batch_source_tools(
        [search_tool],
        source_tool_names={"search_tool"},
        limiter=SourceToolConcurrencyLimiter(3),
        max_batch_size=3,
    )

    output = await result.tools[0].ainvoke({"queries": ["alpha", "beta", "gamma"]})

    assert sorted(calls) == ["alpha", "beta", "gamma"]
    assert "## Query: alpha" in output
    assert "## Query: beta" in output
    assert "## Query: gamma" in output
    assert "https://example.test/beta" in output


@pytest.mark.asyncio
async def test_batch_wrapper_represents_partial_failures_per_item():
    calls: list[str] = []

    @tool
    async def search_tool(query: str) -> str:
        """Search a source."""
        calls.append(query)
        if query == "bad":
            raise RuntimeError("backend unavailable")
        return f"ok {query}"

    result = build_batch_source_tools(
        [search_tool],
        source_tool_names={"search_tool"},
        limiter=SourceToolConcurrencyLimiter(2),
        max_batch_size=3,
    )

    output = await result.tools[0].ainvoke({"queries": ["good", "bad"]})

    assert sorted(calls) == ["bad", "good"]
    assert "## Query: good" in output
    assert "ok good" in output
    assert "## Query: bad" in output
    assert "ERROR: backend unavailable" in output


@pytest.mark.asyncio
async def test_batch_wrapper_rejects_oversized_tool_batches_without_calling_original():
    calls: list[str] = []

    @tool
    async def search_tool(query: str) -> str:
        """Search a source."""
        calls.append(query)
        return query

    result = build_batch_source_tools(
        [search_tool],
        source_tool_names={"search_tool"},
        limiter=SourceToolConcurrencyLimiter(2),
        max_batch_size=1,
    )

    output = await result.tools[0].ainvoke({"queries": ["a", "b"]})

    assert calls == []
    assert "ERROR: search_tool accepts at most 1 queries per batch" in output


@pytest.mark.asyncio
async def test_source_registry_captures_urls_from_wrapped_tool_output():
    @tool
    async def search_tool(query: str) -> str:
        """Search a source."""
        return f"{query}: https://example.test/source"

    result = build_batch_source_tools(
        [search_tool],
        source_tool_names={"search_tool"},
        limiter=SourceToolConcurrencyLimiter(2),
        max_batch_size=2,
    )
    output = await result.tools[0].ainvoke({"queries": ["alpha"]})

    middleware = SourceRegistryMiddleware(source_tool_names={"search_tool"})
    request = MagicMock()
    request.tool_call = {"name": "search_tool"}
    handler = AsyncMock(return_value=ToolMessage(content=output, tool_call_id="tc1"))

    await middleware.awrap_tool_call(request, handler)

    sources = middleware.registry.all_sources()
    assert len(sources) == 1
    assert sources[0].url == "https://example.test/source"


def test_incompatible_multi_arg_source_tool_is_left_unchanged():
    @tool
    async def search_tool(query: str, limit: int) -> str:
        """Search a source."""
        return f"{query}:{limit}"

    result = build_batch_source_tools(
        [search_tool],
        source_tool_names={"search_tool"},
        limiter=SourceToolConcurrencyLimiter(2),
        max_batch_size=3,
    )

    assert result.tools == [search_tool]
    assert result.wrapped_tool_names == set()


@pytest.mark.asyncio
async def test_shared_limiter_caps_underlying_calls_across_wrapped_tools():
    active = 0
    max_seen = 0

    async def _recorded_result(query: str) -> str:
        nonlocal active, max_seen
        active += 1
        max_seen = max(max_seen, active)
        await asyncio.sleep(0.01)
        active -= 1
        return query

    @tool
    async def search_a(query: str) -> str:
        """Search source A."""
        return await _recorded_result(query)

    @tool
    async def search_b(query: str) -> str:
        """Search source B."""
        return await _recorded_result(query)

    limiter = SourceToolConcurrencyLimiter(1)
    result = build_batch_source_tools(
        [search_a, search_b],
        source_tool_names={"search_a", "search_b"},
        limiter=limiter,
        max_batch_size=3,
    )
    wrapped_tools = {wrapped.name: wrapped for wrapped in result.tools}

    await asyncio.gather(
        wrapped_tools["search_a"].ainvoke({"queries": ["a1", "a2"]}),
        wrapped_tools["search_b"].ainvoke({"queries": ["b1", "b2"]}),
    )

    assert max_seen == 1

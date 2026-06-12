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

"""Tests for researcher-facing source tool adapters."""

import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool

from aiq_agent.agents.deep_researcher.custom_middleware import SourceRegistryMiddleware
from aiq_agent.agents.deep_researcher.tools.source_tool_batching import SourceToolConcurrencyLimiter
from aiq_agent.agents.deep_researcher.tools.source_tool_batching import adapt_source_tools_for_research


@pytest.mark.asyncio
async def test_batch_wrapper_single_string_calls_original_once():
    calls: list[str] = []

    @tool
    async def search_tool(query: str) -> str:
        """Search a source."""
        calls.append(query)
        return f"result for {query}"

    result = adapt_source_tools_for_research(
        [search_tool],
        source_tool_names={"search_tool"},
        max_concurrent_source_tool_calls=2,
        max_batch_size=3,
    )

    wrapped = result[0]
    output = await wrapped.ainvoke({"queries": "alpha"})

    assert wrapped.name == "search_tool"
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

    result = adapt_source_tools_for_research(
        [search_tool],
        source_tool_names={"search_tool"},
        max_concurrent_source_tool_calls=3,
        max_batch_size=3,
    )

    output = await result[0].ainvoke({"queries": ["alpha", "beta", "gamma"]})

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

    result = adapt_source_tools_for_research(
        [search_tool],
        source_tool_names={"search_tool"},
        max_concurrent_source_tool_calls=2,
        max_batch_size=3,
    )

    output = await result[0].ainvoke({"queries": ["good", "bad"]})

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

    result = adapt_source_tools_for_research(
        [search_tool],
        source_tool_names={"search_tool"},
        max_concurrent_source_tool_calls=2,
        max_batch_size=1,
    )

    output = await result[0].ainvoke({"queries": ["a", "b"]})

    assert calls == []
    assert "ERROR: search_tool accepts at most 1 queries per batch" in output


@pytest.mark.asyncio
async def test_source_registry_captures_urls_from_wrapped_tool_output():
    @tool
    async def search_tool(query: str) -> str:
        """Search a source."""
        return f"{query}: https://example.test/source"

    result = adapt_source_tools_for_research(
        [search_tool],
        source_tool_names={"search_tool"},
        max_concurrent_source_tool_calls=2,
        max_batch_size=2,
    )
    output = await result[0].ainvoke({"queries": ["alpha"]})

    middleware = SourceRegistryMiddleware(source_tool_names={"search_tool"})
    request = MagicMock()
    request.tool_call = {"name": "search_tool"}
    handler = AsyncMock(return_value=ToolMessage(content=output, tool_call_id="tc1"))

    await middleware.awrap_tool_call(request, handler)

    sources = middleware.registry.all_sources()
    assert len(sources) == 1
    assert sources[0].url == "https://example.test/source"


@pytest.mark.asyncio
async def test_incompatible_multi_arg_source_tool_keeps_schema_and_is_throttled():
    @tool
    async def search_tool(query: str, limit: int) -> str:
        """Search a source."""
        return f"{query}:{limit}"

    result = adapt_source_tools_for_research(
        [search_tool],
        source_tool_names={"search_tool"},
        max_concurrent_source_tool_calls=2,
        max_batch_size=3,
    )
    wrapped = result[0]

    assert wrapped.name == "search_tool"
    assert wrapped.args == search_tool.args
    assert await wrapped.ainvoke({"query": "alpha", "limit": 5}) == "alpha:5"


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

    result = adapt_source_tools_for_research(
        [search_a, search_b],
        source_tool_names={"search_a", "search_b"},
        max_concurrent_source_tool_calls=1,
        max_batch_size=3,
    )
    wrapped_tools = {wrapped.name: wrapped for wrapped in result}

    await asyncio.gather(
        wrapped_tools["search_a"].ainvoke({"queries": ["a1", "a2"]}),
        wrapped_tools["search_b"].ainvoke({"queries": ["b1", "b2"]}),
    )

    assert max_seen == 1


@pytest.mark.asyncio
async def test_shared_limiter_caps_non_batchable_source_tools():
    active = 0
    max_seen = 0

    @tool
    async def search_tool(query: str, limit: int) -> str:
        """Search a source."""
        nonlocal active, max_seen
        active += 1
        max_seen = max(max_seen, active)
        await asyncio.sleep(0.01)
        active -= 1
        return f"{query}:{limit}"

    result = adapt_source_tools_for_research(
        [search_tool],
        source_tool_names={"search_tool"},
        max_concurrent_source_tool_calls=1,
        max_batch_size=3,
    )

    await asyncio.gather(*(result[0].ainvoke({"query": f"q{i}", "limit": i}) for i in range(3)))

    assert max_seen == 1


@pytest.mark.asyncio
async def test_limiter_caps_concurrent_blocks():
    limiter = SourceToolConcurrencyLimiter(1)
    active = 0
    max_seen = 0

    async def hold_slot():
        nonlocal active, max_seen
        async with limiter.limit():
            active += 1
            max_seen = max(max_seen, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(*(hold_slot() for _ in range(3)))

    assert max_seen == 1


@pytest.mark.asyncio
async def test_limiter_releases_after_exception():
    limiter = SourceToolConcurrencyLimiter(1)

    async def fail_with_slot():
        async with limiter.limit():
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await fail_with_slot()

    async with asyncio.timeout(0.1):
        async with limiter.limit():
            pass


@pytest.mark.asyncio
async def test_limiter_timeout_does_not_release_unacquired_slot():
    limiter = SourceToolConcurrencyLimiter(1, acquire_timeout=0.01)

    async with limiter.limit():
        with pytest.raises(TimeoutError, match="Timed out waiting for a source-tool concurrency slot"):
            async with limiter.limit():
                pass

        with pytest.raises(TimeoutError, match="Timed out waiting for a source-tool concurrency slot"):
            async with limiter.limit():
                pass

    async with asyncio.timeout(0.1):
        async with limiter.limit():
            pass


@pytest.mark.asyncio
async def test_limiter_releases_after_cancellation():
    limiter = SourceToolConcurrencyLimiter(1)

    async def hold_slot():
        async with limiter.limit():
            await asyncio.sleep(1)

    task = asyncio.create_task(hold_slot())
    await asyncio.sleep(0.01)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    async with asyncio.timeout(0.1):
        async with limiter.limit():
            pass

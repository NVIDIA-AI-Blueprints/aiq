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

"""Tests for the you_research NAT tool registration."""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr
from you_com.register import ResearchEffort
from you_com.register import YouResearchToolConfig
from you_com.register import you_research


@pytest.fixture
def mock_research(monkeypatch):
    captured = {}

    def factory(**kwargs):
        wrapper = MagicMock()
        wrapper.research_text_async = AsyncMock(
            return_value="## Answer\n\nSome research findings.\n\n[1] [Source Title](https://example.com)\n"
        )
        tool = MagicMock(api_wrapper=wrapper)
        captured["tool"] = tool
        captured["kwargs"] = kwargs
        return tool

    monkeypatch.setattr("you_com.register.YouResearchTool", factory)
    return captured


class TestYouResearchToolConfig:
    def test_defaults(self):
        config = YouResearchToolConfig()
        assert config.research_effort == ResearchEffort.standard
        assert config.api_key is None
        assert config.max_retries == 3
        assert config.timeout is None

    def test_inherits_from_function_base_config(self):
        from nat.data_models.function import FunctionBaseConfig

        assert issubclass(YouResearchToolConfig, FunctionBaseConfig)


class TestYouResearchStub:
    async def test_stub_when_no_api_key(self):
        config = YouResearchToolConfig()
        builder = MagicMock()

        async with you_research(config, builder) as info:
            result = await info.single_fn("anything")

        assert "YDC_API_KEY" in result
        assert "unavailable" in result.lower()


class TestYouResearchLive:
    async def test_config_api_key_used(self, mock_research, monkeypatch):
        config = YouResearchToolConfig(api_key=SecretStr("key-from-config"))
        builder = MagicMock()

        async with you_research(config, builder) as _:
            pass

        assert mock_research["kwargs"].get("api_wrapper", {}).get("ydc_api_key") == "key-from-config"

    async def test_successful_call_returns_markdown(self, mock_research, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouResearchToolConfig()
        builder = MagicMock()

        async with you_research(config, builder) as info:
            out = await info.single_fn("What is quantum computing?")

        assert "Answer" in out
        assert "research findings" in out

    async def test_empty_result_returns_error(self, mock_research, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouResearchToolConfig(max_retries=1)
        builder = MagicMock()

        async with you_research(config, builder) as info:
            mock_research["tool"].api_wrapper.research_text_async.return_value = ""
            out = await info.single_fn("q")

        assert "no results" in out.lower()

    async def test_retries_then_succeeds(self, mock_research, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        monkeypatch.setattr("you_com.register.asyncio.sleep", AsyncMock())
        config = YouResearchToolConfig(max_retries=3)
        builder = MagicMock()

        async with you_research(config, builder) as info:
            mock_research["tool"].api_wrapper.research_text_async.side_effect = [
                RuntimeError("transient"),
                "## Answer\n\nRecovered.\n",
            ]
            out = await info.single_fn("q")

        assert "Recovered" in out
        assert mock_research["tool"].api_wrapper.research_text_async.call_count == 2

    async def test_401_returns_friendly_message(self, mock_research, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        monkeypatch.setattr("you_com.register.asyncio.sleep", AsyncMock())
        config = YouResearchToolConfig(max_retries=2)
        builder = MagicMock()

        async with you_research(config, builder) as info:
            mock_research["tool"].api_wrapper.research_text_async.side_effect = RuntimeError("401 Unauthorized")
            out = await info.single_fn("q")

        assert "401" in out

    async def test_timeout_applied(self, mock_research, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouResearchToolConfig(max_retries=1, timeout=0.001)
        builder = MagicMock()

        async def _hang(_):
            await asyncio.sleep(10)

        async with you_research(config, builder) as info:
            mock_research["tool"].api_wrapper.research_text_async.side_effect = _hang
            out = await info.single_fn("q")

        assert "error" in out.lower()

    async def test_research_effort_passed_to_tool(self, mock_research, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouResearchToolConfig(research_effort=ResearchEffort.deep)
        builder = MagicMock()

        async with you_research(config, builder) as _:
            pass

        assert mock_research["kwargs"].get("api_wrapper", {}).get("research_effort") == "deep"

    async def test_cache_returns_same_result(self, mock_research, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouResearchToolConfig()
        builder = MagicMock()

        async with you_research(config, builder) as info:
            out1 = await info.single_fn("cached question")
            out2 = await info.single_fn("cached question")

        assert out1 == out2
        assert mock_research["tool"].api_wrapper.research_text_async.call_count == 1

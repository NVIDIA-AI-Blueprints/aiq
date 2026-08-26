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

"""Tests for the you_finance_research NAT tool registration."""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr
from you_com.register import ResearchEffort
from you_com.register import YouFinanceResearchToolConfig
from you_com.register import you_finance_research


@pytest.fixture
def mock_finance(monkeypatch):
    captured = {}

    def factory(**kwargs):
        wrapper = MagicMock()
        wrapper.finance_text_async = AsyncMock(return_value="## Answer\n\nSome financial insight.\n")
        tool = MagicMock(api_wrapper=wrapper)
        captured["tool"] = tool
        captured["kwargs"] = kwargs
        return tool

    monkeypatch.setattr("you_com.register.YouFinanceResearchTool", factory)
    return captured


class TestYouFinanceResearchToolConfig:
    def test_defaults(self):
        config = YouFinanceResearchToolConfig()
        assert config.research_effort == ResearchEffort.deep
        assert config.api_key is None
        assert config.max_retries == 3
        assert config.timeout is None

    def test_inherits_from_function_base_config(self):
        from nat.data_models.function import FunctionBaseConfig

        assert issubclass(YouFinanceResearchToolConfig, FunctionBaseConfig)

    def test_rejects_lite_effort(self):
        with pytest.raises(Exception, match="deep.*exhaustive|exhaustive.*deep"):
            YouFinanceResearchToolConfig(research_effort=ResearchEffort.lite)

    def test_rejects_standard_effort(self):
        with pytest.raises(Exception, match="deep.*exhaustive|exhaustive.*deep"):
            YouFinanceResearchToolConfig(research_effort=ResearchEffort.standard)


class TestYouFinanceResearchStub:
    async def test_stub_when_no_api_key(self):
        config = YouFinanceResearchToolConfig()
        builder = MagicMock()

        async with you_finance_research(config, builder) as info:
            result = await info.single_fn("anything")

        assert "YDC_API_KEY" in result
        assert "unavailable" in result.lower()


class TestYouFinanceResearchLive:
    async def test_config_api_key_used(self, mock_finance, monkeypatch):
        config = YouFinanceResearchToolConfig(api_key=SecretStr("key-from-config"))
        builder = MagicMock()

        async with you_finance_research(config, builder) as _:
            pass

        assert mock_finance["kwargs"].get("api_wrapper", {}).get("ydc_api_key") == "key-from-config"

    async def test_successful_call_returns_markdown(self, mock_finance, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouFinanceResearchToolConfig()
        builder = MagicMock()

        async with you_finance_research(config, builder) as info:
            out = await info.single_fn("What drove NVIDIA revenue growth?")

        assert "Answer" in out
        assert "financial insight" in out

    async def test_empty_result_returns_error(self, mock_finance, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouFinanceResearchToolConfig(max_retries=1)
        builder = MagicMock()

        async with you_finance_research(config, builder) as info:
            mock_finance["tool"].api_wrapper.finance_text_async.return_value = ""
            out = await info.single_fn("q")

        assert "no results" in out.lower()

    async def test_retries_then_succeeds(self, mock_finance, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        monkeypatch.setattr("you_com.register.asyncio.sleep", AsyncMock())
        config = YouFinanceResearchToolConfig(max_retries=3)
        builder = MagicMock()

        async with you_finance_research(config, builder) as info:
            mock_finance["tool"].api_wrapper.finance_text_async.side_effect = [
                RuntimeError("transient"),
                "## Answer\n\nRecovered.\n",
            ]
            out = await info.single_fn("q")

        assert "Recovered" in out
        assert mock_finance["tool"].api_wrapper.finance_text_async.call_count == 2

    async def test_401_returns_friendly_message(self, mock_finance, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        monkeypatch.setattr("you_com.register.asyncio.sleep", AsyncMock())
        config = YouFinanceResearchToolConfig(max_retries=2)
        builder = MagicMock()

        async with you_finance_research(config, builder) as info:
            mock_finance["tool"].api_wrapper.finance_text_async.side_effect = RuntimeError("401 Unauthorized")
            out = await info.single_fn("q")

        assert "401" in out

    async def test_timeout_applied(self, mock_finance, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouFinanceResearchToolConfig(max_retries=1, timeout=0.001)
        builder = MagicMock()

        async def _hang(_):
            await asyncio.sleep(10)

        async with you_finance_research(config, builder) as info:
            mock_finance["tool"].api_wrapper.finance_text_async.side_effect = _hang
            out = await info.single_fn("q")

        assert "error" in out.lower()

    async def test_research_effort_passed_to_tool(self, mock_finance, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouFinanceResearchToolConfig(research_effort=ResearchEffort.exhaustive)
        builder = MagicMock()

        async with you_finance_research(config, builder) as _:
            pass

        assert mock_finance["kwargs"].get("api_wrapper", {}).get("research_effort") == "exhaustive"

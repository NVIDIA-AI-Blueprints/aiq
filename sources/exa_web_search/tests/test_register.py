# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

"""Tests for the exa_web_search NAT registration."""

import os
import sys
import types
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from exa_web_search.register import ExaWebSearchToolConfig
from exa_web_search.register import exa_web_search
from pydantic import SecretStr


class _FakeResult:
    def __init__(self, url, title, text, highlights=None):
        self.url = url
        self.title = title
        self.text = text
        self.highlights = highlights


class _FakeResponse:
    def __init__(self, results):
        self.results = results


@pytest.fixture
def fake_langchain_exa(monkeypatch):
    """Install a fake `langchain_exa` module so tests never hit the network.

    Returns the shared ExaSearchResults instance the registration will create.
    """

    module = types.ModuleType("langchain_exa")
    instance = MagicMock()
    instance.ainvoke = AsyncMock()

    module.ExaSearchResults = MagicMock(return_value=instance)
    monkeypatch.setitem(sys.modules, "langchain_exa", module)
    return instance


@pytest.fixture(autouse=True)
def _reset_warn_flag():
    import exa_web_search.register as reg

    reg._missing_key_warned = False
    yield
    reg._missing_key_warned = False


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)


class TestExaWebSearchToolConfig:
    def test_defaults(self):
        config = ExaWebSearchToolConfig()
        assert config.max_results == 5
        assert config.api_key is None
        assert config.max_retries == 3
        assert config.search_type == "auto"
        assert config.full_text is False
        assert config.highlights is True
        assert config.max_content_length == 10000

    def test_all_fields(self):
        config = ExaWebSearchToolConfig(
            max_results=10,
            api_key=SecretStr("sk-test"),
            max_retries=1,
            search_type="deep",
            full_text=True,
            highlights=False,
            max_content_length=50,
        )
        assert config.max_results == 10
        assert config.api_key.get_secret_value() == "sk-test"
        assert config.max_retries == 1
        assert config.search_type == "deep"
        assert config.full_text is True
        assert config.highlights is False
        assert config.max_content_length == 50

    def test_inherits_from_function_base_config(self):
        from nat.data_models.function import FunctionBaseConfig

        assert issubclass(ExaWebSearchToolConfig, FunctionBaseConfig)


class TestExaWebSearchStub:
    async def test_stub_when_no_api_key(self):
        config = ExaWebSearchToolConfig()
        builder = MagicMock()

        async with exa_web_search(config, builder) as info:
            result = await info.single_fn("anything")

        assert "EXA_API_KEY" in result
        assert "unavailable" in result.lower()


class TestExaWebSearchLive:
    async def test_api_key_from_config_sets_env(self, fake_langchain_exa):
        fake_langchain_exa.ainvoke.return_value = _FakeResponse([_FakeResult("https://a.example", "A", "body a")])
        config = ExaWebSearchToolConfig(api_key=SecretStr("sk-from-config"))
        builder = MagicMock()

        async with exa_web_search(config, builder) as info:
            out = await info.single_fn("question")

        assert os.environ.get("EXA_API_KEY") == "sk-from-config"
        assert "https://a.example" in out
        assert "body a" in out

    async def test_successful_search_formats_documents(self, fake_langchain_exa, monkeypatch):
        monkeypatch.setenv("EXA_API_KEY", "sk-env")
        fake_langchain_exa.ainvoke.return_value = _FakeResponse(
            [
                _FakeResult("https://a.example", "Title A", "Body A"),
                _FakeResult("https://b.example", "Title B", "Body B"),
            ]
        )

        config = ExaWebSearchToolConfig(max_results=2)
        builder = MagicMock()
        async with exa_web_search(config, builder) as info:
            out = await info.single_fn("query")

        assert "Title A" in out
        assert "Title B" in out
        assert "Body A" in out
        assert "Body B" in out
        assert "---" in out
        fake_langchain_exa.ainvoke.assert_called_once()
        (payload,), _ = fake_langchain_exa.ainvoke.call_args
        assert payload["query"] == "query"
        assert payload["num_results"] == 2
        assert payload["type"] == "auto"
        assert payload["text_contents_options"] is False
        assert payload["highlights"] is True

    async def test_full_text_true_passes_text_contents_options_true(self, fake_langchain_exa, monkeypatch):
        monkeypatch.setenv("EXA_API_KEY", "sk-env")
        fake_langchain_exa.ainvoke.return_value = _FakeResponse([_FakeResult("https://a.example", "A", "full body")])

        config = ExaWebSearchToolConfig(full_text=True)
        builder = MagicMock()
        async with exa_web_search(config, builder) as info:
            out = await info.single_fn("q")

        (payload,), _ = fake_langchain_exa.ainvoke.call_args
        assert payload["text_contents_options"] is True
        assert payload["highlights"] is True
        assert "full body" in out

    async def test_highlights_rendered_when_text_absent(self, fake_langchain_exa, monkeypatch):
        monkeypatch.setenv("EXA_API_KEY", "sk-env")
        fake_langchain_exa.ainvoke.return_value = _FakeResponse(
            [
                _FakeResult("https://a.example", "A", "", highlights=["snippet one", "snippet two"]),
            ]
        )

        config = ExaWebSearchToolConfig()
        builder = MagicMock()
        async with exa_web_search(config, builder) as info:
            out = await info.single_fn("q")

        assert "snippet one" in out
        assert "snippet two" in out

    async def test_truncates_long_query(self, fake_langchain_exa, monkeypatch):
        monkeypatch.setenv("EXA_API_KEY", "sk-env")
        fake_langchain_exa.ainvoke.return_value = _FakeResponse([_FakeResult("u", "t", "body")])

        config = ExaWebSearchToolConfig()
        builder = MagicMock()
        long_q = "x" * 500
        async with exa_web_search(config, builder) as info:
            await info.single_fn(long_q)

        (payload,), _ = fake_langchain_exa.ainvoke.call_args
        assert len(payload["query"]) == 400
        assert payload["query"].endswith("...")

    async def test_truncates_content(self, fake_langchain_exa, monkeypatch):
        monkeypatch.setenv("EXA_API_KEY", "sk-env")
        fake_langchain_exa.ainvoke.return_value = _FakeResponse([_FakeResult("u", "t", "abcdefghijklmnop")])

        config = ExaWebSearchToolConfig(max_content_length=8)
        builder = MagicMock()
        async with exa_web_search(config, builder) as info:
            out = await info.single_fn("q")

        assert "abcde..." in out
        assert "abcdefghi" not in out

    async def test_empty_results_returns_error(self, fake_langchain_exa, monkeypatch):
        monkeypatch.setenv("EXA_API_KEY", "sk-env")
        fake_langchain_exa.ainvoke.return_value = _FakeResponse([])

        config = ExaWebSearchToolConfig(max_retries=1)
        builder = MagicMock()
        async with exa_web_search(config, builder) as info:
            out = await info.single_fn("q")

        assert "no results" in out.lower()

    async def test_string_response_raises_and_returns_error(self, fake_langchain_exa, monkeypatch):
        monkeypatch.setenv("EXA_API_KEY", "sk-env")
        monkeypatch.setattr("exa_web_search.register.asyncio.sleep", _no_sleep)
        fake_langchain_exa.ainvoke.return_value = "upstream error"

        config = ExaWebSearchToolConfig(max_retries=1)
        builder = MagicMock()
        async with exa_web_search(config, builder) as info:
            out = await info.single_fn("q")

        assert "upstream error" in out

    async def test_retries_then_succeeds(self, fake_langchain_exa, monkeypatch):
        monkeypatch.setenv("EXA_API_KEY", "sk-env")
        monkeypatch.setattr("exa_web_search.register.asyncio.sleep", _no_sleep)

        fake_langchain_exa.ainvoke.side_effect = [
            RuntimeError("transient"),
            _FakeResponse([_FakeResult("u", "t", "ok")]),
        ]

        config = ExaWebSearchToolConfig(max_retries=3)
        builder = MagicMock()
        async with exa_web_search(config, builder) as info:
            out = await info.single_fn("q")

        assert "ok" in out
        assert fake_langchain_exa.ainvoke.call_count == 2

    async def test_401_returns_friendly_message(self, fake_langchain_exa, monkeypatch):
        monkeypatch.setenv("EXA_API_KEY", "sk-env")
        monkeypatch.setattr("exa_web_search.register.asyncio.sleep", _no_sleep)
        fake_langchain_exa.ainvoke.side_effect = RuntimeError("401 Unauthorized")

        config = ExaWebSearchToolConfig(max_retries=2)
        builder = MagicMock()
        async with exa_web_search(config, builder) as info:
            out = await info.single_fn("q")

        assert "401" in out
        assert "EXA_API_KEY" in out


async def _no_sleep(_):
    return None

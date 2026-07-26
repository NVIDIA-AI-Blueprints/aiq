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

"""Tests for shared helpers and tool registration smoke tests."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr
from you_com.register import YouContentsToolConfig
from you_com.register import YouFinanceResearchToolConfig
from you_com.register import YouResearchToolConfig
from you_com.register import YouToolConfig
from you_com.register import YouWebSearchToolConfig
from you_com.register import _make_stub
from you_com.register import _resolve_api_key
from you_com.register import _run_with_retries
from you_com.register import _warn_missing_key_once


@pytest.fixture(autouse=True)
def _reset_warn_flag():
    import you_com.register as reg

    reg._missing_key_warned = False
    yield
    reg._missing_key_warned = False


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("YDC_API_KEY", raising=False)


# ---------------------------------------------------------------------------
# Registration smoke tests — guards that all three tools have the right name
# ---------------------------------------------------------------------------


class TestRegistrationNames:
    def test_web_search_name(self):
        assert YouWebSearchToolConfig._typed_model_name == "you_web_search"

    def test_finance_research_name(self):
        assert YouFinanceResearchToolConfig._typed_model_name == "you_finance_research"

    def test_research_name(self):
        assert YouResearchToolConfig._typed_model_name == "you_research"

    def test_contents_name(self):
        assert YouContentsToolConfig._typed_model_name == "you_contents"

    def test_base_config_not_registered(self):
        assert YouToolConfig._typed_model_name is None


# ---------------------------------------------------------------------------
# _resolve_api_key
# ---------------------------------------------------------------------------


class TestResolveApiKey:
    def test_returns_env_key_when_no_config_key(self, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "from-env")
        config = YouToolConfig()
        assert _resolve_api_key(config) == "from-env"

    def test_returns_config_key(self, monkeypatch):
        config = YouToolConfig(api_key=SecretStr("from-config"))
        assert _resolve_api_key(config) == "from-config"

    def test_config_key_takes_precedence_over_env(self, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "from-env")
        config = YouToolConfig(api_key=SecretStr("from-config"))
        assert _resolve_api_key(config) == "from-config"

    def test_returns_none_when_no_key(self):
        config = YouToolConfig()
        assert _resolve_api_key(config) is None


# ---------------------------------------------------------------------------
# _warn_missing_key_once
# ---------------------------------------------------------------------------


class TestWarnMissingKeyOnce:
    def test_warns_only_once(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="you_com.register"):
            _warn_missing_key_once("web search")
            _warn_missing_key_once("web search")

        assert sum(1 for r in caplog.records if "YDC_API_KEY" in r.message) == 1


# ---------------------------------------------------------------------------
# _make_stub
# ---------------------------------------------------------------------------


class TestMakeStub:
    async def test_stub_contains_label_and_unavailable(self):
        stub = _make_stub("Finance research")
        result = await stub.single_fn("anything")
        assert "Finance research" in result
        assert "unavailable" in result.lower()
        assert "YDC_API_KEY" in result

    async def test_stub_different_labels_produce_different_messages(self):
        web = _make_stub("Web search")
        finance = _make_stub("Finance research")
        web_result = await web.single_fn("q")
        finance_result = await finance.single_fn("q")
        assert "Web search" in web_result
        assert "Finance research" in finance_result
        assert web_result != finance_result


# ---------------------------------------------------------------------------
# _run_with_retries
# ---------------------------------------------------------------------------


class TestRunWithRetries:
    async def test_success_on_first_attempt(self):
        factory = AsyncMock(return_value="ok result")
        cache: dict = {}
        out = await _run_with_retries("T", factory, "q", max_retries=3, timeout=None, cache=cache)
        assert out == "ok result"
        assert cache["q"] == "ok result"

    async def test_cache_hit_skips_factory(self):
        factory = AsyncMock(return_value="fresh")
        cache = {"q": "cached"}
        out = await _run_with_retries("T", factory, "q", max_retries=3, timeout=None, cache=cache)
        assert out == "cached"
        factory.assert_not_called()

    async def test_retries_on_transient_error(self, monkeypatch):
        monkeypatch.setattr("you_com.register.asyncio.sleep", AsyncMock())
        factory = AsyncMock(side_effect=[RuntimeError("transient"), "recovered"])
        cache: dict = {}
        out = await _run_with_retries("T", factory, "q", max_retries=3, timeout=None, cache=cache)
        assert out == "recovered"
        assert factory.call_count == 2

    async def test_exhausted_retries_returns_error_string(self, monkeypatch):
        monkeypatch.setattr("you_com.register.asyncio.sleep", AsyncMock())
        factory = AsyncMock(side_effect=RuntimeError("boom"))
        cache: dict = {}
        out = await _run_with_retries("T", factory, "q", max_retries=2, timeout=None, cache=cache)
        assert "error" in out.lower()
        assert "boom" in out

    async def test_empty_result_returns_no_results_message(self, monkeypatch):
        monkeypatch.setattr("you_com.register.asyncio.sleep", AsyncMock())
        factory = AsyncMock(return_value="")
        cache: dict = {}
        out = await _run_with_retries("T", factory, "q", max_retries=1, timeout=None, cache=cache)
        assert "no results" in out.lower()
        assert out.startswith("Error: ")

    async def test_401_returns_friendly_message(self, monkeypatch):
        monkeypatch.setattr("you_com.register.asyncio.sleep", AsyncMock())
        factory = AsyncMock(side_effect=RuntimeError("401 Unauthorized"))
        cache: dict = {}
        out = await _run_with_retries("T", factory, "q", max_retries=1, timeout=None, cache=cache)
        assert "401" in out

    async def test_timeout_applied(self):
        async def _hang(_q):
            await asyncio.sleep(10)

        cache: dict = {}
        out = await _run_with_retries("T", _hang, "q", max_retries=1, timeout=0.001, cache=cache)
        assert "error" in out.lower()

    async def test_cache_evicts_oldest_when_full(self, monkeypatch):
        from you_com import register as reg

        original = reg._CACHE_MAX_SIZE
        monkeypatch.setattr(reg, "_CACHE_MAX_SIZE", 2)
        try:
            factory = AsyncMock(side_effect=["r1", "r2", "r3"])
            cache: dict = {}
            await _run_with_retries("T", factory, "q1", max_retries=1, timeout=None, cache=cache)
            await _run_with_retries("T", factory, "q2", max_retries=1, timeout=None, cache=cache)
            await _run_with_retries("T", factory, "q3", max_retries=1, timeout=None, cache=cache)
            assert "q1" not in cache
            assert "q2" in cache
            assert "q3" in cache
        finally:
            monkeypatch.setattr(reg, "_CACHE_MAX_SIZE", original)

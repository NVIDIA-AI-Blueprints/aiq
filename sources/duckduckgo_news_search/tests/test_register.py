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

"""Tests for DuckDuckGo news search registration."""

import sys
import types
from unittest.mock import MagicMock

from duckduckgo_news_search.register import DuckDuckGoNewsSearchToolConfig
from duckduckgo_news_search.register import duckduckgo_news_search

from nat.data_models.function import FunctionBaseConfig


class _FakeDDGS:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def news(self, query, **kwargs):
        self.calls.append((query, kwargs))
        if isinstance(self.results, Exception):
            raise self.results
        return self.results


def _install_fake_ddgs(monkeypatch, fake):
    module = types.ModuleType("ddgs")
    module.DDGS = MagicMock(return_value=fake)
    monkeypatch.setitem(sys.modules, "ddgs", module)
    return module


class TestDuckDuckGoNewsSearchToolConfig:
    def test_defaults(self):
        config = DuckDuckGoNewsSearchToolConfig()

        assert config.max_results == 5
        assert config.region == "us-en"
        assert config.safesearch == "moderate"
        assert config.timelimit == "w"
        assert config.timeout == 20.0
        assert config.max_retries == 2

    def test_inherits_from_function_base_config(self):
        assert issubclass(DuckDuckGoNewsSearchToolConfig, FunctionBaseConfig)


class TestDuckDuckGoNewsSearchLive:
    async def test_successful_search_formats_document_blocks(self, monkeypatch):
        fake = _FakeDDGS(
            [
                {
                    "title": "NVIDIA announces agent news",
                    "url": "https://example.test/news",
                    "body": "A short article snippet.",
                    "source": "Example News",
                    "date": "2026-06-01",
                }
            ]
        )
        _install_fake_ddgs(monkeypatch, fake)

        config = DuckDuckGoNewsSearchToolConfig(max_results=1, timelimit="d")
        builder = MagicMock()
        async with duckduckgo_news_search(config, builder) as info:
            output = await info.single_fn("AI agents")

        assert '<Document href="https://example.test/news">' in output
        assert "NVIDIA announces agent news" in output
        assert "<source>Example News</source>" in output
        assert "<date>2026-06-01</date>" in output
        assert fake.calls == [
            (
                "AI agents",
                {
                    "region": "us-en",
                    "safesearch": "moderate",
                    "max_results": 1,
                    "backend": "bing,duckduckgo,yahoo",
                    "timelimit": "d",
                },
            )
        ]

    async def test_empty_query_returns_error_without_calling_backend(self, monkeypatch):
        fake = _FakeDDGS([])
        _install_fake_ddgs(monkeypatch, fake)

        config = DuckDuckGoNewsSearchToolConfig()
        builder = MagicMock()
        async with duckduckgo_news_search(config, builder) as info:
            output = await info.single_fn("  ")

        assert output == "Error: query must be a non-empty string"
        assert fake.calls == []

    async def test_no_results_returns_clear_message(self, monkeypatch):
        fake = _FakeDDGS([])
        _install_fake_ddgs(monkeypatch, fake)

        config = DuckDuckGoNewsSearchToolConfig(max_retries=1)
        builder = MagicMock()
        async with duckduckgo_news_search(config, builder) as info:
            output = await info.single_fn("AI agents")

        assert output == "News search returned no results"

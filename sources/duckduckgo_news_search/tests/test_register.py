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

from ddgs.exceptions import DDGSException
from duckduckgo_news_search.register import DuckDuckGoNewsSearchToolConfig
from duckduckgo_news_search.register import _format_news_result
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
    exceptions_module = types.ModuleType("ddgs.exceptions")
    exceptions_module.DDGSException = DDGSException
    module.exceptions = exceptions_module
    monkeypatch.setitem(sys.modules, "ddgs", module)
    monkeypatch.setitem(sys.modules, "ddgs.exceptions", exceptions_module)
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


class TestFormatNewsResult:
    def test_escapes_document_fields(self):
        output = _format_news_result(
            {
                "title": 'NVIDIA <agents> & "news"',
                "url": 'https://example.test/news?q=<ai>&quote="yes"',
                "body": 'Body with <tag>, & ampersand, and "quotes".',
                "source": 'Example & "News" <Feed>',
                "date": '2026-06-01 <today> & "now"',
            }
        )

        assert '<Document href="https://example.test/news?q=&lt;ai&gt;&amp;quote=&quot;yes&quot;">' in output
        assert "NVIDIA &lt;agents&gt; &amp; &quot;news&quot;" in output
        assert "Body with &lt;tag&gt;, &amp; ampersand, and &quot;quotes&quot;." in output
        assert "<source>Example &amp; &quot;News&quot; &lt;Feed&gt;</source>" in output
        assert "<date>2026-06-01 &lt;today&gt; &amp; &quot;now&quot;</date>" in output


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

    async def test_ddgs_no_results_exception_returns_clear_message(self, monkeypatch):
        fake = _FakeDDGS(DDGSException("No results found."))
        _install_fake_ddgs(monkeypatch, fake)

        config = DuckDuckGoNewsSearchToolConfig(max_retries=1)
        builder = MagicMock()
        async with duckduckgo_news_search(config, builder) as info:
            output = await info.single_fn("AI agents")

        assert output == "News search returned no results"
        assert len(fake.calls) == 1

    async def test_timeout_triggers_retry(self, monkeypatch):
        fake = _FakeDDGS(Exception("Timeout"))
        _install_fake_ddgs(monkeypatch, fake)

        async def _no_sleep(_delay):
            return None

        monkeypatch.setattr("duckduckgo_news_search.register.asyncio.sleep", _no_sleep)

        config = DuckDuckGoNewsSearchToolConfig(timeout=0.01, max_retries=2)
        builder = MagicMock()
        async with duckduckgo_news_search(config, builder) as info:
            output = await info.single_fn("test")

        assert output == "Error: News search failed"
        assert "Timeout" not in output
        assert len(fake.calls) == 2

    async def test_special_characters_in_results_are_escaped(self, monkeypatch):
        fake = _FakeDDGS(
            [
                {
                    "title": '<script>alert("title")</script> & news',
                    "url": 'https://example.test/news?q=<script>&quote="yes"',
                    "body": '<script>alert("body")</script> & details > summary',
                }
            ]
        )
        _install_fake_ddgs(monkeypatch, fake)

        config = DuckDuckGoNewsSearchToolConfig()
        builder = MagicMock()
        async with duckduckgo_news_search(config, builder) as info:
            output = await info.single_fn("test")

        assert "<script>" not in output
        assert "</script>" not in output
        assert 'href="https://example.test/news?q=&lt;script&gt;&amp;quote=&quot;yes&quot;"' in output
        assert "&lt;script&gt;alert(&quot;title&quot;)&lt;/script&gt; &amp; news" in output
        assert "&lt;script&gt;alert(&quot;body&quot;)&lt;/script&gt; &amp; details &gt; summary" in output

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

"""Tests for the you_web_search NAT tool registration."""

import asyncio
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr
from you_com.register import FreshnessMode
from you_com.register import YouWebSearchToolConfig
from you_com.register import you_web_search

ADVERSARIAL_URL = 'https://example.com/pa\x00th?q="quoted"&next=<unsafe>&close=</Document>'
ADVERSARIAL_TITLE = 'Research\x00 & "Roadmap" <2026> </title>'
ADVERSARIAL_CONTENT = 'Evidence\x00 & "claims" <external> </Document> </title>'
SANITIZED_URL = 'https://example.com/path?q="quoted"&next=<unsafe>&close=</Document>'
SANITIZED_TITLE = 'Research & "Roadmap" <2026> </title>'
SANITIZED_CONTENT = 'Evidence & "claims" <external> </Document> </title>'


def _parse_document(output: str) -> tuple[ET.Element, ET.Element]:
    assert output.count("<Document ") == 1
    assert output.count("</Document>") == 1
    assert output.count("<title>") == 1
    assert output.count("</title>") == 1
    root = ET.fromstring(output)
    title = root.find("title")
    assert title is not None
    return root, title


def _make_doc(title="Title", url="https://example.com", description="", page_content="content", source=None):
    metadata = {"title": title, "url": url, "description": description}
    if source:
        metadata["source"] = source
    return SimpleNamespace(metadata=metadata, page_content=page_content)


@pytest.fixture
def mock_search(monkeypatch):
    captured = {}

    def factory(api_wrapper):
        wrapper = MagicMock()
        wrapper.results_async = AsyncMock(return_value=[])
        tool = MagicMock(api_wrapper=wrapper)
        captured["tool"] = tool
        captured["kwargs"] = api_wrapper
        return tool

    monkeypatch.setattr("you_com.register.YouSearchTool", factory)
    return captured


class TestYouWebSearchToolConfig:
    def test_defaults(self):
        config = YouWebSearchToolConfig()
        assert config.max_results == 10
        assert config.api_key is None
        assert config.max_retries == 3
        assert config.safesearch.value == "moderate"
        assert config.livecrawl_mode.value == "web"
        assert config.livecrawl_format.value == "markdown"
        assert config.freshness == FreshnessMode.off
        assert config.max_content_length == 50000
        assert config.include_news_results is False
        assert config.timeout is None

    def test_inherits_from_function_base_config(self):
        from nat.data_models.function import FunctionBaseConfig

        assert issubclass(YouWebSearchToolConfig, FunctionBaseConfig)


class TestYouWebSearchStub:
    async def test_stub_when_no_api_key(self):
        config = YouWebSearchToolConfig()
        builder = MagicMock()

        async with you_web_search(config, builder) as info:
            result = await info.single_fn("anything")

        assert "YDC_API_KEY" in result
        assert "unavailable" in result.lower()


class TestYouWebSearchLive:
    async def test_structurally_escapes_provider_fields(self, mock_search, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouWebSearchToolConfig()

        async with you_web_search(config, MagicMock()) as info:
            mock_search["tool"].api_wrapper.results_async.return_value = [
                _make_doc(ADVERSARIAL_TITLE, ADVERSARIAL_URL, page_content=ADVERSARIAL_CONTENT)
            ]
            output = await info.single_fn("query")

        document, title = _parse_document(output)
        assert document.attrib["href"] == SANITIZED_URL
        assert (title.text or "").strip("\n") == SANITIZED_TITLE
        assert (title.tail or "").strip("\n") == SANITIZED_CONTENT

    async def test_config_api_key_used(self, mock_search, monkeypatch):
        config = YouWebSearchToolConfig(api_key=SecretStr("key-from-config"))
        builder = MagicMock()

        async with you_web_search(config, builder) as _:
            pass

        assert mock_search["kwargs"].get("ydc_api_key") == "key-from-config"

    async def test_successful_search_formats_documents(self, mock_search, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouWebSearchToolConfig(max_results=2)
        builder = MagicMock()

        async with you_web_search(config, builder) as info:
            mock_search["tool"].api_wrapper.results_async.return_value = [
                _make_doc("Title A", "https://a.example", page_content="Body A"),
                _make_doc("Title B", "https://b.example", page_content="Body B"),
            ]
            out = await info.single_fn("query")

        assert "Title A" in out
        assert "Title B" in out
        assert "Body A" in out
        assert "Body B" in out
        assert "---" in out

    async def test_max_content_length_truncates(self, mock_search, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouWebSearchToolConfig(max_content_length=5)
        builder = MagicMock()

        async with you_web_search(config, builder) as info:
            mock_search["tool"].api_wrapper.results_async.return_value = [
                _make_doc(page_content="abcdefghijklmnop"),
            ]
            out = await info.single_fn("q")

        assert "abcde" in out
        assert "abcdefgh" not in out
        _, title = _parse_document(out)
        assert (title.tail or "").strip() == "abcde"

    async def test_zero_content_limit_omits_livecrawl_but_retains_description(self, mock_search, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouWebSearchToolConfig(max_content_length=0)

        async with you_web_search(config, MagicMock()) as info:
            mock_search["tool"].api_wrapper.results_async.return_value = [
                _make_doc(description="Description & <summary>", page_content=ADVERSARIAL_CONTENT)
            ]
            output = await info.single_fn("query")

        _, title = _parse_document(output)
        assert (title.tail or "").strip("\n") == "Description & <summary>"
        assert SANITIZED_CONTENT not in output

    async def test_none_content_limit_retains_unbounded_livecrawl(self, mock_search, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouWebSearchToolConfig(max_content_length=None)

        async with you_web_search(config, MagicMock()) as info:
            mock_search["tool"].api_wrapper.results_async.return_value = [_make_doc(page_content=ADVERSARIAL_CONTENT)]
            output = await info.single_fn("query")

        _, title = _parse_document(output)
        assert (title.tail or "").strip() == SANITIZED_CONTENT

    async def test_default_bounds_oversized_livecrawl_content(self, mock_search, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouWebSearchToolConfig(max_results=10)
        builder = MagicMock()

        async with you_web_search(config, builder) as info:
            mock_search["tool"].api_wrapper.results_async.return_value = [
                _make_doc(page_content="x" * 200_000) for _ in range(10)
            ]
            out = await info.single_fn("q")

        assert len(out) <= 10 * 50000 + 10_000

    async def test_news_source_filtered_by_default(self, mock_search, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouWebSearchToolConfig(include_news_results=False)
        builder = MagicMock()

        async with you_web_search(config, builder) as info:
            mock_search["tool"].api_wrapper.results_async.return_value = [
                _make_doc("Web", "https://web.example", page_content="web body"),
                _make_doc("News", "https://news.example", page_content="news body", source="news"),
            ]
            out = await info.single_fn("q")

        assert "https://web.example" in out
        assert "https://news.example" not in out

    async def test_include_news_results_keeps_news(self, mock_search, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouWebSearchToolConfig(include_news_results=True)
        builder = MagicMock()

        async with you_web_search(config, builder) as info:
            mock_search["tool"].api_wrapper.results_async.return_value = [
                _make_doc("Web", "https://web.example", page_content="web body"),
                _make_doc("News", "https://news.example", page_content="news body", source="news"),
            ]
            out = await info.single_fn("q")

        assert "https://web.example" in out
        assert "https://news.example" in out

    async def test_empty_results_returns_error(self, mock_search, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouWebSearchToolConfig(max_retries=1)
        builder = MagicMock()

        async with you_web_search(config, builder) as info:
            mock_search["tool"].api_wrapper.results_async.return_value = []
            out = await info.single_fn("q")

        assert "no results" in out.lower()

    async def test_retries_then_succeeds(self, mock_search, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        monkeypatch.setattr("you_com.register.asyncio.sleep", AsyncMock())
        config = YouWebSearchToolConfig(max_retries=3)
        builder = MagicMock()

        async with you_web_search(config, builder) as info:
            mock_search["tool"].api_wrapper.results_async.side_effect = [
                RuntimeError("transient"),
                [_make_doc("T", "https://a.example", page_content="ok")],
            ]
            out = await info.single_fn("q")

        assert "ok" in out
        assert mock_search["tool"].api_wrapper.results_async.call_count == 2

    async def test_401_returns_friendly_message(self, mock_search, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        sleep = AsyncMock()
        monkeypatch.setattr("you_com.register.asyncio.sleep", sleep)
        config = YouWebSearchToolConfig(max_retries=2)
        builder = MagicMock()

        async with you_web_search(config, builder) as info:
            mock_search["tool"].api_wrapper.results_async.side_effect = RuntimeError("401 Unauthorized")
            out = await info.single_fn("q")

        assert "401" in out
        assert mock_search["tool"].api_wrapper.results_async.call_count == 1
        sleep.assert_not_awaited()

    async def test_wrapper_kwargs_exclude_none_freshness(self, mock_search, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouWebSearchToolConfig()  # freshness=off → mapped to None before request
        builder = MagicMock()

        async with you_web_search(config, builder) as _:
            pass

        assert "freshness" not in mock_search["kwargs"]

    async def test_timeout_applied(self, mock_search, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouWebSearchToolConfig(max_retries=1, timeout=0.001)
        builder = MagicMock()

        async def _hang(_):
            await asyncio.sleep(10)

        async with you_web_search(config, builder) as info:
            mock_search["tool"].api_wrapper.results_async.side_effect = _hang
            out = await info.single_fn("q")

        assert "error" in out.lower()

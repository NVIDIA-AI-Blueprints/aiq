# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the Tavily web-search NAT registration."""

import re
import sys
import types
import xml.etree.ElementTree as ET
from html import unescape
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr
from tavily_web_search.register import TavilyWebSearchToolConfig
from tavily_web_search.register import tavily_web_search

ADVERSARIAL_URL = 'https://example.com/pa\x00th?q="quoted"&next=<unsafe>&close=</Document>'
ADVERSARIAL_TITLE = 'Research\x00 & "Roadmap" <2026> </title>'
ADVERSARIAL_CONTENT = 'Evidence\x00 & "claims" <external> </Document> </title>'
SANITIZED_URL = 'https://example.com/path?q="quoted"&next=<unsafe>&close=</Document>'
SANITIZED_TITLE = 'Research & "Roadmap" <2026> </title>'
SANITIZED_CONTENT = 'Evidence & "claims" <external> </Document> </title>'


def _assert_document(output: str, *, url: str, title: str, content: str) -> None:
    assert output.count("<Document ") == 1
    assert output.count("</Document>") == 1
    assert output.count("<title>") == 1
    assert output.count("</title>") == 1

    root = ET.fromstring(output)
    title_element = root.find("title")
    assert root.attrib["href"] == url
    assert title_element is not None
    assert (title_element.text or "").strip("\n") == title
    assert (title_element.tail or "").strip("\n") == content


@pytest.fixture
def fake_langchain_tavily(monkeypatch):
    module = types.ModuleType("langchain_tavily")
    instance = MagicMock()
    instance.ainvoke = AsyncMock()
    factory = MagicMock(return_value=instance)
    module.TavilySearch = factory
    monkeypatch.setitem(sys.modules, "langchain_tavily", module)
    return factory, instance


@pytest.fixture(autouse=True)
def _clear_key_and_warning(monkeypatch):
    from tavily_web_search import register

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    register._missing_key_warned = False
    yield
    register._missing_key_warned = False


class TestTavilyWebSearchToolConfig:
    def test_defaults(self):
        config = TavilyWebSearchToolConfig()

        assert config.include_answer == "advanced"
        assert config.max_results == 3
        assert config.max_content_length is None


class TestTavilyWebSearchStub:
    async def test_stub_when_no_api_key(self, fake_langchain_tavily):
        async with tavily_web_search(TavilyWebSearchToolConfig(), MagicMock()) as info:
            result = await info.single_fn("anything")

        assert "TAVILY_API_KEY" in result
        assert "unavailable" in result.lower()


class TestTavilyWebSearchLive:
    async def test_default_path_structurally_escapes_provider_fields(self, fake_langchain_tavily, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        factory, instance = fake_langchain_tavily
        instance.ainvoke.return_value = {
            "results": [
                {
                    "url": ADVERSARIAL_URL,
                    "title": ADVERSARIAL_TITLE,
                    "content": ADVERSARIAL_CONTENT,
                }
            ]
        }

        async with tavily_web_search(TavilyWebSearchToolConfig(), MagicMock()) as info:
            output = await info.single_fn("question")

        _assert_document(
            output,
            url=SANITIZED_URL,
            title=SANITIZED_TITLE,
            content=SANITIZED_CONTENT,
        )
        factory.assert_called_once_with(max_results=3, search_depth="basic", include_answer="advanced")
        instance.ainvoke.assert_awaited_once_with({"query": "question"})

    async def test_answer_payload_is_escaped(self, fake_langchain_tavily):
        factory, instance = fake_langchain_tavily
        answer = 'Answer\x00 & "claim" <external> </Answer>'
        sanitized_answer = 'Answer & "claim" <external> </Answer>'
        instance.ainvoke.return_value = {
            "answer": answer,
            "results": [{"url": "https://example.com", "title": "Title", "content": "Content"}],
        }

        async with tavily_web_search(TavilyWebSearchToolConfig(api_key=SecretStr("test-key")), MagicMock()) as info:
            output = await info.single_fn("question")

        assert output.count("<Answer>") == 1
        assert output.count("</Answer>") == 1
        match = re.search(r"<Answer>\n(.*?)\n</Answer>", output, re.DOTALL)
        assert match is not None
        assert unescape(match.group(1)) == sanitized_answer
        factory.assert_called_once()

    async def test_truncates_raw_content_before_escaping(self, fake_langchain_tavily, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        _, instance = fake_langchain_tavily
        instance.ainvoke.return_value = {
            "results": [{"url": "https://example.com", "title": "Title", "content": "a&b<cdefgh"}]
        }

        config = TavilyWebSearchToolConfig(max_content_length=7)
        async with tavily_web_search(config, MagicMock()) as info:
            output = await info.single_fn("question")

        _assert_document(output, url="https://example.com", title="Title", content="a&b<...")

    async def test_none_fields_become_empty_strings(self, fake_langchain_tavily, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        _, instance = fake_langchain_tavily
        instance.ainvoke.return_value = {"results": [{"url": None, "title": None, "content": None}]}

        async with tavily_web_search(TavilyWebSearchToolConfig(), MagicMock()) as info:
            output = await info.single_fn("question")

        _assert_document(output, url="", title="", content="")

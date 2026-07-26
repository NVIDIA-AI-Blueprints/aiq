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

"""Tests for the you_contents NAT tool registration."""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr
from pydantic import ValidationError
from you_com.register import ContentsFormat
from you_com.register import YouContentsToolConfig
from you_com.register import you_contents


def _make_doc(url: str, title: str, page_content: str = "") -> MagicMock:
    doc = MagicMock()
    doc.metadata = {"url": url, "title": title}
    doc.page_content = page_content
    return doc


@pytest.fixture
def mock_contents(monkeypatch):
    captured = {}

    def factory(api_wrapper):
        wrapper = MagicMock()
        wrapper.contents_async = AsyncMock(return_value=[])
        tool = MagicMock(api_wrapper=wrapper)
        captured["tool"] = tool
        captured["kwargs"] = api_wrapper
        return tool

    monkeypatch.setattr("you_com.register.YouContentsTool", factory)
    return captured


class TestYouContentsToolConfig:
    def test_defaults(self):
        config = YouContentsToolConfig()
        assert config.formats == [ContentsFormat.markdown, ContentsFormat.metadata]
        assert config.crawl_timeout is None
        assert config.api_key is None
        assert config.max_retries == 3
        assert config.timeout is None

    def test_inherits_from_function_base_config(self):
        from nat.data_models.function import FunctionBaseConfig

        assert issubclass(YouContentsToolConfig, FunctionBaseConfig)

    @pytest.mark.parametrize("bad", [0, -1, 61, 100])
    def test_crawl_timeout_out_of_range(self, bad):
        with pytest.raises(ValidationError):
            YouContentsToolConfig(crawl_timeout=bad)

    @pytest.mark.parametrize("good", [1, 30, 60])
    def test_crawl_timeout_valid(self, good):
        config = YouContentsToolConfig(crawl_timeout=good)
        assert config.crawl_timeout == good


class TestYouContentsStub:
    async def test_stub_when_no_api_key(self):
        config = YouContentsToolConfig()
        builder = MagicMock()

        async with you_contents(config, builder) as info:
            result = await info.single_fn(["https://example.com"])

        assert "YDC_API_KEY" in result
        assert "unavailable" in result.lower()


class TestYouContentsLive:
    async def test_config_api_key_used(self, mock_contents, monkeypatch):
        config = YouContentsToolConfig(api_key=SecretStr("key-from-config"))
        builder = MagicMock()

        async with you_contents(config, builder) as _:
            pass

        assert mock_contents["kwargs"].get("ydc_api_key") == "key-from-config"

    async def test_successful_call_returns_documents(self, mock_contents, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouContentsToolConfig()
        builder = MagicMock()

        async with you_contents(config, builder) as info:
            mock_contents["tool"].api_wrapper.contents_async.return_value = [
                _make_doc("https://example.com", "Example", "Some content here.")
            ]
            out = await info.single_fn(["https://example.com"])

        assert "https://example.com" in out
        assert "Some content here." in out

    async def test_empty_result_returns_error(self, mock_contents, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouContentsToolConfig(max_retries=1)
        builder = MagicMock()

        async with you_contents(config, builder) as info:
            mock_contents["tool"].api_wrapper.contents_async.return_value = []
            out = await info.single_fn(["https://example.com"])

        assert "no results" in out.lower()

    async def test_retries_then_succeeds(self, mock_contents, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        monkeypatch.setattr("you_com.register.asyncio.sleep", AsyncMock())
        config = YouContentsToolConfig(max_retries=3)
        builder = MagicMock()

        async with you_contents(config, builder) as info:
            mock_contents["tool"].api_wrapper.contents_async.side_effect = [
                RuntimeError("transient"),
                [_make_doc("https://example.com", "Example", "Recovered.")],
            ]
            out = await info.single_fn(["https://example.com"])

        assert "Recovered." in out
        assert mock_contents["tool"].api_wrapper.contents_async.call_count == 2

    async def test_401_returns_friendly_message(self, mock_contents, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        monkeypatch.setattr("you_com.register.asyncio.sleep", AsyncMock())
        config = YouContentsToolConfig(max_retries=2)
        builder = MagicMock()

        async with you_contents(config, builder) as info:
            mock_contents["tool"].api_wrapper.contents_async.side_effect = RuntimeError("401 Unauthorized")
            out = await info.single_fn(["https://example.com"])

        assert "401" in out

    async def test_timeout_applied(self, mock_contents, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouContentsToolConfig(max_retries=1, timeout=0.001)
        builder = MagicMock()

        async def _hang(*args, **kwargs):
            await asyncio.sleep(10)

        async with you_contents(config, builder) as info:
            mock_contents["tool"].api_wrapper.contents_async.side_effect = _hang
            out = await info.single_fn(["https://example.com"])

        assert "error" in out.lower()

    async def test_formats_passed_to_api(self, mock_contents, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouContentsToolConfig(formats=[ContentsFormat.html])
        builder = MagicMock()

        async with you_contents(config, builder) as info:
            mock_contents["tool"].api_wrapper.contents_async.return_value = [
                _make_doc("https://example.com", "Example", "<p>content</p>")
            ]
            await info.single_fn(["https://example.com"])

        _, call_kwargs = mock_contents["tool"].api_wrapper.contents_async.call_args
        assert call_kwargs.get("formats") == ["html"]

    async def test_cache_returns_same_result(self, mock_contents, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "test-key")
        config = YouContentsToolConfig()
        builder = MagicMock()

        async with you_contents(config, builder) as info:
            mock_contents["tool"].api_wrapper.contents_async.return_value = [
                _make_doc("https://example.com", "Example", "cached content")
            ]
            out1 = await info.single_fn(["https://example.com"])
            out2 = await info.single_fn(["https://example.com"])

        assert out1 == out2
        assert mock_contents["tool"].api_wrapper.contents_async.call_count == 1

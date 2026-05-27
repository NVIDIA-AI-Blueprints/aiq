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

"""Tests for the brave_web_search NAT registration."""

import os
import urllib.parse
from unittest.mock import MagicMock

import pytest
from brave_web_search.register import BRAVE_SEARCH_URL
from brave_web_search.register import BraveWebSearchToolConfig
from brave_web_search.register import brave_web_search
from pydantic import SecretStr
from pydantic import ValidationError


def _search_payload(results=None):
    return {
        "type": "search",
        "web": {
            "results": results if results is not None else [],
        },
    }


def _parse_query(url):
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.parse_qs(parsed.query)


async def _no_sleep(_):
    return None


class TestBraveWebSearchToolConfig:
    def test_defaults(self):
        config = BraveWebSearchToolConfig()
        assert config.max_results == 5
        assert config.api_key is None
        assert config.max_retries == 3
        assert config.country == "US"
        assert config.search_lang == "en"
        assert config.safesearch == "moderate"
        assert config.freshness is None
        assert config.timeout == 20.0
        assert config.max_content_length == 10000

    def test_all_fields(self):
        config = BraveWebSearchToolConfig(
            max_results=10,
            api_key=SecretStr("brave-token"),
            max_retries=1,
            country="GB",
            search_lang="en",
            safesearch="strict",
            freshness="pw",
            timeout=5.0,
            max_content_length=50,
        )
        assert config.max_results == 10
        assert config.api_key.get_secret_value() == "brave-token"
        assert config.max_retries == 1
        assert config.country == "GB"
        assert config.safesearch == "strict"
        assert config.freshness == "pw"
        assert config.timeout == 5.0
        assert config.max_content_length == 50

    def test_max_results_has_upper_bound(self):
        with pytest.raises(ValidationError):
            BraveWebSearchToolConfig(max_results=21)

    def test_inherits_from_function_base_config(self):
        from nat.data_models.function import FunctionBaseConfig

        assert issubclass(BraveWebSearchToolConfig, FunctionBaseConfig)


class TestBraveWebSearchStub:
    async def test_stub_when_no_api_key(self, monkeypatch):
        import brave_web_search.register as reg

        reg._missing_key_warned = False
        monkeypatch.delenv("BRAVE_API_KEY", raising=False)
        config = BraveWebSearchToolConfig()
        builder = MagicMock()

        async with brave_web_search(config, builder) as info:
            result = await info.single_fn("anything")

        assert "BRAVE_API_KEY" in result
        assert "unavailable" in result.lower()


class TestBraveWebSearchLive:
    async def test_api_key_from_config_sets_env(self, monkeypatch):
        fake_request = MagicMock(
            return_value=_search_payload(
                [
                    {
                        "url": "https://a.example",
                        "title": "A",
                        "description": "body a",
                    }
                ]
            )
        )
        monkeypatch.delenv("BRAVE_API_KEY", raising=False)
        monkeypatch.setattr("brave_web_search.register._http_get_json", fake_request)

        config = BraveWebSearchToolConfig(api_key=SecretStr("token-from-config"))
        builder = MagicMock()
        async with brave_web_search(config, builder) as info:
            out = await info.single_fn("question")

        assert os.environ.get("BRAVE_API_KEY") == "token-from-config"
        assert "https://a.example" in out
        assert "body a" in out

    async def test_successful_search_formats_documents(self, monkeypatch):
        fake_request = MagicMock(
            return_value=_search_payload(
                [
                    {
                        "url": "https://a.example",
                        "title": "Title A",
                        "description": "Body A",
                    },
                    {
                        "url": "https://b.example",
                        "title": "Title B",
                        "description": "Body B",
                        "extra_snippets": ["Extra B"],
                    },
                ]
            )
        )
        monkeypatch.setenv("BRAVE_API_KEY", "brave-env")
        monkeypatch.setattr("brave_web_search.register._http_get_json", fake_request)

        config = BraveWebSearchToolConfig(max_results=2, country="US", search_lang="en", freshness="pw")
        builder = MagicMock()
        async with brave_web_search(config, builder) as info:
            out = await info.single_fn("query")

        assert "Title A" in out
        assert "Title B" in out
        assert "Body A" in out
        assert "Extra B" in out
        assert "---" in out

        request_url, headers, timeout = fake_request.call_args.args
        assert request_url.startswith(BRAVE_SEARCH_URL)
        params = _parse_query(request_url)
        assert params["q"] == ["query"]
        assert params["count"] == ["2"]
        assert params["country"] == ["US"]
        assert params["search_lang"] == ["en"]
        assert params["safesearch"] == ["moderate"]
        assert params["freshness"] == ["pw"]
        assert params["text_decorations"] == ["false"]
        assert headers["X-Subscription-Token"] == "brave-env"
        assert timeout == 20.0

    async def test_truncates_long_query(self, monkeypatch):
        fake_request = MagicMock(return_value=_search_payload([{"url": "u", "title": "t", "description": "body"}]))
        monkeypatch.setenv("BRAVE_API_KEY", "brave-env")
        monkeypatch.setattr("brave_web_search.register._http_get_json", fake_request)

        config = BraveWebSearchToolConfig()
        builder = MagicMock()
        async with brave_web_search(config, builder) as info:
            await info.single_fn("x" * 500)

        params = _parse_query(fake_request.call_args.args[0])
        assert len(params["q"][0]) == 400
        assert params["q"][0].endswith("...")

    async def test_truncates_content(self, monkeypatch):
        fake_request = MagicMock(
            return_value=_search_payload([{"url": "u", "title": "t", "description": "abcdefghijklmnop"}])
        )
        monkeypatch.setenv("BRAVE_API_KEY", "brave-env")
        monkeypatch.setattr("brave_web_search.register._http_get_json", fake_request)

        config = BraveWebSearchToolConfig(max_content_length=8)
        builder = MagicMock()
        async with brave_web_search(config, builder) as info:
            out = await info.single_fn("q")

        assert "abcde..." in out
        assert "abcdefghi" not in out

    async def test_small_content_limit_does_not_exceed_requested_length(self, monkeypatch):
        fake_request = MagicMock(
            return_value=_search_payload([{"url": "u", "title": "t", "description": "abcdefghijklmnop"}])
        )
        monkeypatch.setenv("BRAVE_API_KEY", "brave-env")
        monkeypatch.setattr("brave_web_search.register._http_get_json", fake_request)

        config = BraveWebSearchToolConfig(max_content_length=2)
        builder = MagicMock()
        async with brave_web_search(config, builder) as info:
            out = await info.single_fn("q")

        assert "\n..\n</Document>" in out
        assert "abc" not in out

    async def test_escapes_document_fields(self, monkeypatch):
        fake_request = MagicMock(
            return_value=_search_payload(
                [
                    {
                        "url": 'https://a.example/?q="x"&n=1',
                        "title": "<Title & One>",
                        "description": "Body <tag> & value",
                    }
                ]
            )
        )
        monkeypatch.setenv("BRAVE_API_KEY", "brave-env")
        monkeypatch.setattr("brave_web_search.register._http_get_json", fake_request)

        config = BraveWebSearchToolConfig()
        builder = MagicMock()
        async with brave_web_search(config, builder) as info:
            out = await info.single_fn("q")

        assert 'href="https://a.example/?q=&quot;x&quot;&amp;n=1"' in out
        assert "&lt;Title &amp; One&gt;" in out
        assert "Body &lt;tag&gt; &amp; value" in out
        assert "<Title & One>" not in out

    async def test_empty_results_returns_error(self, monkeypatch):
        fake_request = MagicMock(return_value=_search_payload([]))
        monkeypatch.setenv("BRAVE_API_KEY", "brave-env")
        monkeypatch.setattr("brave_web_search.register._http_get_json", fake_request)

        config = BraveWebSearchToolConfig(max_retries=1)
        builder = MagicMock()
        async with brave_web_search(config, builder) as info:
            out = await info.single_fn("q")

        assert "no results" in out.lower()

    async def test_retries_then_succeeds(self, monkeypatch):
        fake_request = MagicMock(
            side_effect=[
                RuntimeError("transient"),
                _search_payload([{"url": "u", "title": "t", "description": "ok"}]),
            ]
        )
        monkeypatch.setenv("BRAVE_API_KEY", "brave-env")
        monkeypatch.setattr("brave_web_search.register._http_get_json", fake_request)
        monkeypatch.setattr("brave_web_search.register.asyncio.sleep", _no_sleep)

        config = BraveWebSearchToolConfig(max_retries=3)
        builder = MagicMock()
        async with brave_web_search(config, builder) as info:
            out = await info.single_fn("q")

        assert "ok" in out
        assert fake_request.call_count == 2

    async def test_401_returns_friendly_message(self, monkeypatch):
        fake_request = MagicMock(side_effect=RuntimeError("401 Unauthorized"))
        monkeypatch.setenv("BRAVE_API_KEY", "brave-env")
        monkeypatch.setattr("brave_web_search.register._http_get_json", fake_request)
        monkeypatch.setattr("brave_web_search.register.asyncio.sleep", _no_sleep)

        config = BraveWebSearchToolConfig(max_retries=2)
        builder = MagicMock()
        async with brave_web_search(config, builder) as info:
            out = await info.single_fn("q")

        assert "401" in out
        assert "BRAVE_API_KEY" in out

    async def test_429_returns_rate_limit_message(self, monkeypatch):
        fake_request = MagicMock(side_effect=RuntimeError("429 Too Many Requests"))
        monkeypatch.setenv("BRAVE_API_KEY", "brave-env")
        monkeypatch.setattr("brave_web_search.register._http_get_json", fake_request)
        monkeypatch.setattr("brave_web_search.register.asyncio.sleep", _no_sleep)

        config = BraveWebSearchToolConfig(max_retries=2)
        builder = MagicMock()
        async with brave_web_search(config, builder) as info:
            out = await info.single_fn("q")

        assert "rate limit" in out.lower()
        assert "Brave" in out

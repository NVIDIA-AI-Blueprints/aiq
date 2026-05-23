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

"""Tests for the tinyfish_web_search NAT registration."""

import os
import urllib.parse
from unittest.mock import MagicMock

from pydantic import SecretStr
from tinyfish_web_search.register import TINYFISH_SEARCH_URL
from tinyfish_web_search.register import TinyfishWebSearchToolConfig
from tinyfish_web_search.register import tinyfish_web_search


def _search_payload(results=None):
    return {
        "query": "query",
        "results": results if results is not None else [],
        "total_results": len(results or []),
        "page": 0,
    }


def _parse_query(url):
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.parse_qs(parsed.query)


async def _no_sleep(_):
    return None


class TestTinyfishWebSearchToolConfig:
    def test_defaults(self):
        config = TinyfishWebSearchToolConfig()
        assert config.max_results == 5
        assert config.api_key is None
        assert config.max_retries == 3
        assert config.location == "US"
        assert config.language == "en"
        assert config.page == 0
        assert config.timeout == 20.0
        assert config.max_content_length == 10000

    def test_all_fields(self):
        config = TinyfishWebSearchToolConfig(
            max_results=10,
            api_key=SecretStr("tinyfish-key"),
            max_retries=1,
            location="FR",
            language="fr",
            page=2,
            timeout=5.0,
            max_content_length=50,
        )
        assert config.max_results == 10
        assert config.api_key.get_secret_value() == "tinyfish-key"
        assert config.max_retries == 1
        assert config.location == "FR"
        assert config.language == "fr"
        assert config.page == 2
        assert config.timeout == 5.0
        assert config.max_content_length == 50

    def test_inherits_from_function_base_config(self):
        from nat.data_models.function import FunctionBaseConfig

        assert issubclass(TinyfishWebSearchToolConfig, FunctionBaseConfig)


class TestTinyfishWebSearchStub:
    async def test_stub_when_no_api_key(self, monkeypatch):
        import tinyfish_web_search.register as reg

        reg._missing_key_warned = False
        monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
        config = TinyfishWebSearchToolConfig()
        builder = MagicMock()

        async with tinyfish_web_search(config, builder) as info:
            result = await info.single_fn("anything")

        assert "TINYFISH_API_KEY" in result
        assert "unavailable" in result.lower()


class TestTinyfishWebSearchLive:
    async def test_api_key_from_config_sets_env(self, monkeypatch):
        fake_request = MagicMock(
            return_value=_search_payload(
                [
                    {
                        "url": "https://a.example",
                        "title": "A",
                        "snippet": "body a",
                    }
                ]
            )
        )
        monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
        monkeypatch.setattr("tinyfish_web_search.register._http_get_json", fake_request)

        config = TinyfishWebSearchToolConfig(api_key=SecretStr("key-from-config"))
        builder = MagicMock()
        async with tinyfish_web_search(config, builder) as info:
            out = await info.single_fn("question")

        assert os.environ.get("TINYFISH_API_KEY") == "key-from-config"
        assert "https://a.example" in out
        assert "body a" in out

    async def test_successful_search_formats_documents(self, monkeypatch):
        fake_request = MagicMock(
            return_value=_search_payload(
                [
                    {
                        "url": "https://a.example",
                        "title": "Title A",
                        "snippet": "Body A",
                        "site_name": "a.example",
                    },
                    {
                        "url": "https://b.example",
                        "title": "Title B",
                        "snippet": "Body B",
                        "site_name": "b.example",
                    },
                ]
            )
        )
        monkeypatch.setenv("TINYFISH_API_KEY", "tinyfish-env")
        monkeypatch.setattr("tinyfish_web_search.register._http_get_json", fake_request)

        config = TinyfishWebSearchToolConfig(max_results=2, location="FR", language="fr", page=2)
        builder = MagicMock()
        async with tinyfish_web_search(config, builder) as info:
            out = await info.single_fn("query")

        assert "Title A" in out
        assert "Title B" in out
        assert "Body A" in out
        assert "a.example" in out
        assert "---" in out

        request_url, headers, timeout = fake_request.call_args.args
        assert request_url.startswith(TINYFISH_SEARCH_URL)
        params = _parse_query(request_url)
        assert params["query"] == ["query"]
        assert params["location"] == ["FR"]
        assert params["language"] == ["fr"]
        assert params["page"] == ["2"]
        assert headers["X-API-Key"] == "tinyfish-env"
        assert timeout == 20.0

    async def test_limits_results_to_max_results(self, monkeypatch):
        fake_request = MagicMock(
            return_value=_search_payload(
                [
                    {"url": "https://a.example", "title": "A", "snippet": "A body"},
                    {"url": "https://b.example", "title": "B", "snippet": "B body"},
                ]
            )
        )
        monkeypatch.setenv("TINYFISH_API_KEY", "tinyfish-env")
        monkeypatch.setattr("tinyfish_web_search.register._http_get_json", fake_request)

        config = TinyfishWebSearchToolConfig(max_results=1)
        builder = MagicMock()
        async with tinyfish_web_search(config, builder) as info:
            out = await info.single_fn("q")

        assert "A body" in out
        assert "B body" not in out

    async def test_truncates_content(self, monkeypatch):
        fake_request = MagicMock(
            return_value=_search_payload([{"url": "u", "title": "t", "snippet": "abcdefghijklmnop"}])
        )
        monkeypatch.setenv("TINYFISH_API_KEY", "tinyfish-env")
        monkeypatch.setattr("tinyfish_web_search.register._http_get_json", fake_request)

        config = TinyfishWebSearchToolConfig(max_content_length=8)
        builder = MagicMock()
        async with tinyfish_web_search(config, builder) as info:
            out = await info.single_fn("q")

        assert "abcde..." in out
        assert "abcdefghi" not in out

    async def test_empty_results_returns_error(self, monkeypatch):
        fake_request = MagicMock(return_value=_search_payload([]))
        monkeypatch.setenv("TINYFISH_API_KEY", "tinyfish-env")
        monkeypatch.setattr("tinyfish_web_search.register._http_get_json", fake_request)

        config = TinyfishWebSearchToolConfig(max_retries=1)
        builder = MagicMock()
        async with tinyfish_web_search(config, builder) as info:
            out = await info.single_fn("q")

        assert "no results" in out.lower()

    async def test_retries_then_succeeds(self, monkeypatch):
        fake_request = MagicMock(
            side_effect=[
                RuntimeError("transient"),
                _search_payload([{"url": "u", "title": "t", "snippet": "ok"}]),
            ]
        )
        monkeypatch.setenv("TINYFISH_API_KEY", "tinyfish-env")
        monkeypatch.setattr("tinyfish_web_search.register._http_get_json", fake_request)
        monkeypatch.setattr("tinyfish_web_search.register.asyncio.sleep", _no_sleep)

        config = TinyfishWebSearchToolConfig(max_retries=3)
        builder = MagicMock()
        async with tinyfish_web_search(config, builder) as info:
            out = await info.single_fn("q")

        assert "ok" in out
        assert fake_request.call_count == 2

    async def test_401_returns_friendly_message(self, monkeypatch):
        fake_request = MagicMock(side_effect=RuntimeError("401 Unauthorized"))
        monkeypatch.setenv("TINYFISH_API_KEY", "tinyfish-env")
        monkeypatch.setattr("tinyfish_web_search.register._http_get_json", fake_request)
        monkeypatch.setattr("tinyfish_web_search.register.asyncio.sleep", _no_sleep)

        config = TinyfishWebSearchToolConfig(max_retries=2)
        builder = MagicMock()
        async with tinyfish_web_search(config, builder) as info:
            out = await info.single_fn("q")

        assert "401" in out
        assert "TINYFISH_API_KEY" in out

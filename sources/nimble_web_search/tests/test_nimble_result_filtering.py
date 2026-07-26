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

"""Tests for unresolvable-URL result filtering.

The live API intermittently returns results whose ``url`` is a redirect token
(e.g. ``/goto?url=...``) or empty instead of a resolvable link. The provider
drops such results and, when a response contains nothing usable, treats it as
transient so the retry loop re-queries rather than rendering documents that
break citation downstream.
"""

from unittest.mock import MagicMock

import pytest
from nimble_web_search.register import NimbleWebSearchToolConfig
from nimble_web_search.register import nimble_web_search


async def _no_sleep(_):
    return None


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("NIMBLE_API_KEY", "test-key-not-real")  # pragma: allowlist secret


async def _run_provider(config: NimbleWebSearchToolConfig, question: str) -> str:
    async with nimble_web_search(config, MagicMock()) as info:
        return await info.single_fn(question)


class TestUnresolvableUrlFiltering:
    async def test_mixed_response_renders_only_resolvable_results(
        self, fake_langchain_nimble, make_fake_document, assert_search_contract
    ):
        fake_langchain_nimble.ainvoke.return_value = [
            make_fake_document(url="/goto?url=CAESSwHuR6pN", title="Token", description="redirect token"),
            make_fake_document(url="https://example.com/a", title="A", description="fine"),
            make_fake_document(url="", title="Empty", description="no url at all"),
            make_fake_document(url="https://example.com/b", title="B", description="also fine"),
        ]

        result = await _run_provider(NimbleWebSearchToolConfig(), "q")

        blocks = assert_search_contract(result, max_results=5)
        assert len(blocks) == 2
        assert "example.com/a" in result and "example.com/b" in result
        assert "/goto?url=" not in result

    async def test_non_http_or_hostless_urls_are_filtered(
        self, fake_langchain_nimble, make_fake_document, assert_search_contract
    ):
        fake_langchain_nimble.ainvoke.return_value = [
            make_fake_document(url="javascript:alert(1)", title="Script", description="invalid scheme"),
            make_fake_document(url="example.com/no-scheme", title="No scheme", description="relative URL"),
            make_fake_document(url="ftp://example.com/file", title="FTP", description="invalid scheme"),
            make_fake_document(url="https:///missing-host", title="No host", description="invalid absolute URL"),
            make_fake_document(url="https://example.com/ok", title="OK", description="valid URL"),
        ]

        result = await _run_provider(NimbleWebSearchToolConfig(), "q")

        blocks = assert_search_contract(result, max_results=5)
        assert len(blocks) == 1
        assert "https://example.com/ok" in result
        assert "javascript:" not in result
        assert "ftp://" not in result

    async def test_all_unresolvable_response_is_retried(
        self, fake_langchain_nimble, make_fake_document, assert_search_contract, monkeypatch
    ):
        monkeypatch.setattr("nimble_web_search.register.asyncio.sleep", _no_sleep)
        fake_langchain_nimble.ainvoke.side_effect = [
            [make_fake_document(url="/goto?url=abc", title="T1", description="d")],
            [make_fake_document(url="https://example.com/ok", title="OK", description="d")],
        ]

        result = await _run_provider(NimbleWebSearchToolConfig(max_retries=3), "q")

        assert_search_contract(result, max_results=5)
        assert fake_langchain_nimble.ainvoke.call_count == 2

    async def test_all_unresolvable_on_every_attempt_returns_error(
        self, fake_langchain_nimble, make_fake_document, monkeypatch
    ):
        monkeypatch.setattr("nimble_web_search.register.asyncio.sleep", _no_sleep)
        fake_langchain_nimble.ainvoke.return_value = [
            make_fake_document(url="/goto?url=abc", title="T", description="d"),
        ]

        config = NimbleWebSearchToolConfig(max_retries=2)
        result = await _run_provider(config, "q")

        assert result.startswith("Error:")
        assert "resolvable URLs" in result
        assert fake_langchain_nimble.ainvoke.call_count == config.max_retries

    async def test_truly_empty_response_still_short_circuits(self, fake_langchain_nimble, monkeypatch):
        """An empty result list stays a non-retried sentinel (unchanged behavior)."""
        monkeypatch.setattr("nimble_web_search.register.asyncio.sleep", _no_sleep)
        fake_langchain_nimble.ainvoke.return_value = []

        result = await _run_provider(NimbleWebSearchToolConfig(max_retries=3), "q")

        assert result == "Search returned no results"
        assert fake_langchain_nimble.ainvoke.call_count == 1

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

"""Recorded-response replay tests — the credential-free test-mode path.

Each file in ``fixtures/`` is a real ``NimbleSearchRetriever.ainvoke`` response
captured at the SDK boundary and redacted by construction (only the result
fields the provider consumes are kept; no headers, no auth material — see
``fixtures/README.md``). Replaying them through the registered function
exercises the full provider pipeline — config, retry wrapper, rendering,
truncation, escaping — deterministically, with no network and no key.

These tests certify the same structural output contract as the key-gated live
integration test (``test_nimble_live_integration.py``), via the shared
``assert_search_contract`` fixture.
"""

from unittest.mock import MagicMock

import pytest
from nimble_web_search.register import NimbleWebSearchToolConfig
from nimble_web_search.register import nimble_web_search


@pytest.fixture(autouse=True)
def _replay_env(monkeypatch):
    """Replay never talks to the network; a placeholder key satisfies registration."""
    monkeypatch.setenv("NIMBLE_API_KEY", "test-key-not-real")  # pragma: allowlist secret


async def _run_provider(config: NimbleWebSearchToolConfig, question: str) -> str:
    async with nimble_web_search(config, MagicMock()) as info:
        return await info.single_fn(question)


class TestRecordedReplay:
    @pytest.mark.parametrize("fixture_name", ["recorded_lite_response.json", "recorded_deep_response.json"])
    async def test_recorded_response_meets_output_contract(
        self, fixture_name, fake_langchain_nimble, load_recorded_fixture, assert_search_contract
    ):
        payload, documents = load_recorded_fixture(fixture_name)
        fake_langchain_nimble.ainvoke.return_value = documents
        config = NimbleWebSearchToolConfig(**payload["_config"])

        result = await _run_provider(config, payload["_query"])

        blocks = assert_search_contract(result, config.max_results)
        assert len(blocks) == len(documents)

    async def test_lite_fixture_renders_description_fallback(
        self, fake_langchain_nimble, load_recorded_fixture, extract_document_blocks
    ):
        """lite results carry no page_content; the renderer must fall back to the description."""
        payload, documents = load_recorded_fixture("recorded_lite_response.json")
        assert any(not doc.page_content for doc in documents), "fixture no longer covers the lite fallback"
        fake_langchain_nimble.ainvoke.return_value = documents

        result = await _run_provider(NimbleWebSearchToolConfig(**payload["_config"]), payload["_query"])

        for block, doc in zip(extract_document_blocks(result), documents, strict=True):
            if not doc.page_content and doc.metadata["description"]:
                assert doc.metadata["description"][:40] in block

    async def test_body_containing_separator_sequence_yields_exact_block_count(
        self, fake_langchain_nimble, make_fake_document, assert_search_contract
    ):
        """Synthetic (not recorded): deep-mode markdown content can contain the
        ``\\n\\n---\\n\\n`` joiner sequence itself; whole-block extraction must
        still count documents exactly rather than mis-slicing on separators.
        """
        documents = [
            make_fake_document(
                url="https://example.com/a",
                title="A",
                page_content="intro\n\n---\n\n[Release Notes](notes/index.html)\n:   description text",
            ),
            make_fake_document(url="https://example.com/b", title="B", description="plain snippet"),
        ]
        fake_langchain_nimble.ainvoke.return_value = documents

        result = await _run_provider(NimbleWebSearchToolConfig(), "q")

        blocks = assert_search_contract(result, max_results=5)
        assert len(blocks) == 2

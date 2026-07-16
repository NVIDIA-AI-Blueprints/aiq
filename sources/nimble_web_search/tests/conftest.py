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

"""Shared fixtures and output-contract helpers for nimble_web_search tests.

The assertion helper exposed here defines the provider's structural output
contract once, so the recorded-response replay tests and the key-gated live
integration test certify exactly the same success criteria. Everything is
exposed as pytest fixtures (not module imports) so the test modules work under
any pytest import mode.
"""

import json
import re
import sys
import types
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Whole-block extraction rather than splitting on the "\n\n---\n\n" joiner:
# deep-mode page_content is markdown that can itself contain that byte
# sequence (horizontal rules), which would make separator-splitting mis-slice
# a document into fragments. Extracting <Document ...>...</Document> spans is
# unambiguous because the renderer html-escapes all interior fields, so no
# raw '<'/'>' can appear inside a block.
_DOCUMENT_BLOCK_RE = re.compile(r'<Document href="[^"]*">.*?</Document>', re.DOTALL)
_DOCUMENT_HEAD_RE = re.compile(r'<Document href="(?P<href>[^"]*)">\n<title>\n(?P<title>.*?)\n</title>\n', re.DOTALL)


class FakeDocument:
    """Mimic a langchain ``Document`` just enough for the provider's renderer."""

    def __init__(self, url="", title="", page_content="", description="", position=1):
        self.page_content = page_content
        self.metadata = {
            "url": url,
            "title": title,
            "description": description,
            "position": position,
            "entity_type": "OrganicResult",
        }


def _extract_blocks(result: str) -> list[str]:
    return _DOCUMENT_BLOCK_RE.findall(result)


def _assert_search_contract(result: str, max_results: int) -> list[str]:
    """Assert the provider's structural output contract; return the blocks.

    These are the provider's CI success criteria:

    1. ``result`` is a non-empty string that is neither a provider ``Error:``
       message nor the ``Search returned no results`` sentinel.
    2. It contains between 1 and ``max_results`` ``<Document>`` blocks.
    3. Every block has a non-empty http(s) ``href`` and a non-empty title.
    4. Every block parses as XML (the renderer html-escapes all interior
       fields, so a well-formed response must parse).
    5. At least one block has non-empty body content (individual results may
       legitimately have an empty description, so "all bodies non-empty"
       would be flaky).
    """
    assert isinstance(result, str) and result.strip(), "empty result"
    assert not result.startswith("Error:"), f"provider returned an error: {result[:200]}"
    assert result != "Search returned no results"

    blocks = _extract_blocks(result)
    assert 1 <= len(blocks) <= max_results, f"expected 1..{max_results} <Document> blocks, got {len(blocks)}"

    bodies = []
    for block in blocks:
        head = _DOCUMENT_HEAD_RE.match(block)
        assert head is not None, f"malformed <Document> head: {block[:120]!r}"
        href = head.group("href")
        assert href.startswith(("http://", "https://")), f"non-http(s) href: {href!r}"
        assert head.group("title").strip(), "empty title"
        element = ET.fromstring(block)
        body = (element.text or "") + "".join(child.tail or "" for child in element)
        bodies.append(body.strip())
    assert any(bodies), "every block had an empty body"
    return blocks


@pytest.fixture
def fake_langchain_nimble(monkeypatch):
    """Install a fake ``langchain_nimble`` module so tests never hit the network.

    Returns the shared ``NimbleSearchRetriever`` instance the registration
    will create; set ``instance.ainvoke.return_value`` to control results.
    """
    module = types.ModuleType("langchain_nimble")
    instance = MagicMock()
    instance.ainvoke = AsyncMock()
    module.NimbleSearchRetriever = MagicMock(return_value=instance)
    monkeypatch.setitem(sys.modules, "langchain_nimble", module)
    return instance


@pytest.fixture
def assert_search_contract():
    """The structural output-contract assertion shared by replay + live tests."""
    return _assert_search_contract


@pytest.fixture
def extract_document_blocks():
    """Whole-block ``<Document>`` extraction helper."""
    return _extract_blocks


@pytest.fixture
def make_fake_document():
    """Factory for renderer-compatible fake documents."""
    return FakeDocument


@pytest.fixture
def load_recorded_fixture():
    """Load a recorded SDK-boundary fixture: name -> (payload, documents)."""

    def _load(name: str):
        with (FIXTURES_DIR / name).open(encoding="utf-8") as fh:
            payload = json.load(fh)
        documents = [
            FakeDocument(
                url=doc["metadata"].get("url", ""),
                title=doc["metadata"].get("title", ""),
                description=doc["metadata"].get("description", ""),
                page_content=doc.get("page_content", ""),
                position=doc["metadata"].get("position", 1),
            )
            for doc in payload["documents"]
        ]
        return payload, documents

    return _load

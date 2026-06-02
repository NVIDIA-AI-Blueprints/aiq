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

"""Tests for deep research source routing helpers."""

import json

import pytest
from langchain_core.tools import tool

from aiq_agent.agents.deep_researcher.tools.source_routing import source_catalog_payload
from aiq_agent.common.data_source_registry import populate_from_config
from aiq_agent.common.data_source_registry import reset_registry


@tool
def web_search_tool(query: str) -> str:
    """Search the web."""
    return query


@tool
def knowledge_search(query: str) -> str:
    """Search uploaded documents."""
    return query


@tool
def duckduckgo_news_search_tool(query: str) -> str:
    """Search recent news."""
    return query


@tool
def helper_tool(value: str) -> str:
    """Unmapped helper tool."""
    return value


def _write_domain_catalog(tmp_path):
    catalog_path = tmp_path / "domains.yml"
    catalog_path.write_text(
        """
default_domain_id: general_research
domains:
  - domain_id: general_research
    domain_name: General Research
    description: General factual research.
    preferred_source_ids:
      - knowledge_layer
      - web_search
    fallback_source_ids:
      - web_search
    is_default: true
  - domain_id: scholarly_technical
    domain_name: Scholarly and Technical Research
    description: Paper-heavy and technical questions.
    preferred_source_ids:
      - academic_search
      - paper_search
      - web_search
      - knowledge_layer
    fallback_source_ids:
      - web_search
  - domain_id: current_news
    domain_name: Current News
    description: Recent events and announcements.
    preferred_source_ids:
      - news_search
      - web_search
    fallback_source_ids:
      - web_search
""",
        encoding="utf-8",
    )
    return catalog_path


@pytest.fixture(autouse=True)
def _registry():
    reset_registry()
    populate_from_config(
        [
            {
                "id": "web_search",
                "name": "Web Search",
                "description": "Search the web.",
                "tools": ["web_search_tool"],
            },
            {
                "id": "knowledge_layer",
                "name": "Knowledge Base",
                "description": "Search uploaded files.",
                "tools": ["knowledge_search"],
            },
            {
                "id": "news_search",
                "name": "News Search",
                "description": "Search recent news.",
                "tools": ["duckduckgo_news_search_tool"],
            },
        ]
    )
    yield
    reset_registry()


def test_source_catalog_groups_runtime_tools_by_configured_source(tmp_path):
    payload = source_catalog_payload(
        [
            web_search_tool,
            knowledge_search,
            duckduckgo_news_search_tool,
            helper_tool,
        ],
        domain_catalog_path=_write_domain_catalog(tmp_path),
    )

    sources = {entry["source_id"]: entry for entry in payload["available_sources"]}
    assert set(sources) == {"web_search", "knowledge_layer", "news_search"}
    assert sources["web_search"]["tools"][0]["name"] == "web_search_tool"
    assert sources["knowledge_layer"]["tools"][0]["name"] == "knowledge_search"
    assert sources["news_search"]["tools"][0]["name"] == "duckduckgo_news_search_tool"
    assert payload["unmapped_runtime_tools"] == ["helper_tool"]
    assert payload["default_domain_id"] == "general_research"


def test_source_catalog_respects_explicit_source_selection(tmp_path):
    payload = source_catalog_payload(
        [
            web_search_tool,
            knowledge_search,
            duckduckgo_news_search_tool,
        ],
        allowed_source_ids=["news_search"],
        domain_catalog_path=_write_domain_catalog(tmp_path),
    )

    assert payload["routing_mode"] == "explicit_user_sources"
    assert [entry["source_id"] for entry in payload["available_sources"]] == ["news_search"]
    current_news = next(domain for domain in payload["domains"] if domain["domain_id"] == "current_news")
    assert current_news["preferred_source_ids"] == ["news_search"]
    assert current_news["fallback_source_ids"] == []


def test_source_catalog_tool_payload_is_json_serializable(tmp_path):
    payload = source_catalog_payload(
        [web_search_tool, duckduckgo_news_search_tool],
        domain_catalog_path=_write_domain_catalog(tmp_path),
    )
    decoded = json.loads(json.dumps(payload))

    scholarly = next(domain for domain in decoded["domains"] if domain["domain_id"] == "scholarly_technical")
    assert "academic_search" in scholarly["unavailable_source_ids"]
    assert "paper_search" in scholarly["unavailable_source_ids"]
    assert decoded["default_fallback_source_ids"] == ["web_search"]


def test_source_catalog_allows_no_domain_catalog():
    payload = source_catalog_payload([web_search_tool])

    assert payload["domains"] == []
    assert payload["default_domain_id"] is None

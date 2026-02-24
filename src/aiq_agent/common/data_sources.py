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

"""Shared utilities for data source handling across agents."""

import logging
from typing import Any

from langchain_core.messages import BaseMessage

# Default to web_search when no data sources specified
DEFAULT_DATA_SOURCES: list[str] = ["web_search"]

logger = logging.getLogger(__name__)


def parse_data_sources(raw: Any) -> list[str] | None:
    """Parse data sources from various input formats.

    Args:
        raw: Can be None, a list of strings, or a comma-separated string.

    Returns:
        - None if input is None (not specified, use all tools)
        - Empty list [] if input was explicitly empty (no tools)
        - List of data source IDs if specified
    """
    if raw is None:
        return None
    if isinstance(raw, list):
        if len(raw) == 0:
            return []
        parsed = [str(value).strip() for value in raw]
        return [value for value in parsed if value] or []
    if isinstance(raw, str):
        if not raw.strip():
            return []
        parsed = [value.strip() for value in raw.split(",")]
        return [value for value in parsed if value] or []
    return None


def filter_tools_by_sources(tools: list[Any], data_sources: list[str] | None) -> list[Any]:
    """Filter tools based on selected data sources.

    Knowledge tools are only included when 'knowledge_layer' is in data_sources.

    Args:
        tools: List of LangChain tools.
        data_sources: List of selected data source IDs, or None for all.

    Returns:
        Filtered list of tools matching the selected data sources.
    """
    if data_sources is None:
        return tools

    normalized = {source.lower() for source in data_sources}
    include_web_search = "web_search" in normalized
    include_knowledge = "knowledge_layer" in normalized

    filtered = []
    for tool in tools:
        name = getattr(tool, "name", "")
        name_lower = name.lower()

        if "web" in name_lower or "tavily" in name_lower:
            if include_web_search:
                filtered.append(tool)
        elif "knowledge" in name_lower or "document" in name_lower or "internal" in name_lower:
            if include_knowledge:
                filtered.append(tool)
        else:
            filtered.append(tool)

    return filtered


def extract_messages_and_sources(payload: Any) -> tuple[list[BaseMessage], list[str] | None]:
    """Extract messages and data sources from a payload.

    Args:
        payload: Can be a dict with 'payload' key, a dict with 'messages', or a list.

    Returns:
        Tuple of (messages, data_sources).

    Raises:
        ValueError: If payload format is invalid.
    """
    if isinstance(payload, dict):
        if "payload" in payload and isinstance(payload["payload"], dict):
            payload = payload["payload"]
        messages = payload.get("messages")
        if isinstance(messages, list):
            return messages, parse_data_sources(payload.get("data_sources"))
    if isinstance(payload, list):
        return payload, None
    raise ValueError("Invalid payload format: expected dict with 'messages' or list")


def format_data_source_tools(data_sources: list[str]) -> list[dict[str, str]]:
    """Format data sources as tool info for meta chatter.

    Knowledge tools are only included when 'knowledge_layer' is in data_sources.

    Args:
        data_sources: List of data source IDs.

    Returns:
        List of tool info dicts with 'name' and 'description'.
    """
    tools_info: list[dict[str, str]] = []

    for source in data_sources:
        if source == "web_search":
            tools_info.append({"name": "web_search", "description": "Search the web for real-time information."})
        else:
            tools_info.append({"name": "knowledge_search", "description": "Search uploaded documents and files."})

    return tools_info

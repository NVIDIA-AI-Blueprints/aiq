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

import asyncio
import logging
import os
from typing import Any

import aiohttp
from pydantic import Field
from pydantic import SecretStr

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)

YOU_DEEP_SEARCH_API_URL = "https://api.you.com/v1/deep_search"


async def _fetch_results(
    api_key: str, query: str, search_effort: str, timeout: int, max_retries: int
) -> dict[str, Any]:
    """Make async POST request to You.com Deep Search API with retry."""
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "query": query,
        "search_effort": search_effort,
    }
    client_timeout = aiohttp.ClientTimeout(total=timeout)

    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.post(YOU_DEEP_SEARCH_API_URL, headers=headers, json=payload) as response:
                    if response.status != 200:
                        text = await response.text()
                        raise Exception(f"You.com Deep Search API error: {response.status} - {text[:200]}")
                    return await response.json()
        except Exception as e:
            logger.warning("You.com deep search attempt %d failed: %s", attempt + 1, e)
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** (attempt + 1))


def _format_as_xml(data: dict[str, Any]) -> str:
    """Convert You.com Deep Search API response dict into <Document> XML format."""
    docs = []

    answer = data.get("answer", "")
    if answer:
        docs.append(
            '<Document href="deep_search" source="you_deep_search">\n'
            "<title>\nDeep Analysis\n</title>\n"
            f"<answer>\n{answer}\n</answer>\n"
            "</Document>"
        )

    for result in data.get("results", []):
        url = result.get("url", "")
        title = result.get("title", "")
        snippets = result.get("snippets", [])
        content = "\n".join(snippets)
        docs.append(
            f'<Document href="{url}" source="you_deep_search">\n<title>\n{title}\n</title>\n{content}\n</Document>'
        )

    return "\n\n---\n\n".join(docs)


class YouComWebSearchToolConfig(FunctionBaseConfig, name="you_com_web_search"):
    """
    You.com Deep Search tool. Searches the web using the You.com Deep Search API
    and returns results in <Document> XML format.
    Requires a YOU_API_KEY environment variable or api_key config.
    """

    api_key: SecretStr | None = Field(default=None, description="The API key for the You.com service")
    search_effort: str = Field(
        default="medium",
        description='Search depth: "low" (fast), "medium" (balanced), "high" (thorough).',
    )
    max_retries: int = Field(default=3, description="Maximum number of retries")
    timeout: int = Field(default=2000, description="Request timeout in seconds")


@register_function(config_type=YouComWebSearchToolConfig)
async def you_com_web_search(tool_config: YouComWebSearchToolConfig, builder: Builder):
    """Register You.com Deep Search tool."""

    if not os.environ.get("YOU_API_KEY") and tool_config.api_key:
        os.environ["YOU_API_KEY"] = tool_config.api_key.get_secret_value()

    api_key = os.environ.get("YOU_API_KEY")
    if not api_key:
        raise ValueError("YOU_API_KEY not found. Please set it in environment or config.")

    search_effort = tool_config.search_effort
    max_retries = tool_config.max_retries
    timeout = tool_config.timeout

    max_result_chars = 8000  # TODO: move to YouComWebSearchToolConfig

    async def _you_com_web_search(query: str) -> str:
        """Searches the web using You.com Deep Search and returns relevant documents.

        Returns a synthesized analysis plus source documents in <Document> XML format.
        Results are tagged with source="you_deep_search".

        Args:
            query (str): The search query to investigate.

        Returns:
            str: Search results as XML documents.
        """
        data = await _fetch_results(api_key, query, search_effort, timeout, max_retries)
        result = _format_as_xml(data)
        if len(result) > max_result_chars:
            result = result[:max_result_chars]
        return result

    yield FunctionInfo.from_fn(
        _you_com_web_search,
        description=_you_com_web_search.__doc__,
    )

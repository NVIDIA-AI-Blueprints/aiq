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

"""You.com Deep Search tool using the You.com Deep Search API.

This module contains the NAT-independent YouDeepSearchTool class.
The Deep Search API performs server-side deep analysis and returns
comprehensive answers with cited sources.
"""

import asyncio
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

YOU_DEEP_SEARCH_API_URL = "https://api.you.com/v1/deep_search"


class YouDeepSearchTool:
    """
    You.com Deep Search tool for comprehensive research queries.

    Uses the You.com Deep Search API which performs server-side deep analysis
    and returns a comprehensive answer with cited sources.

    This class is NAT-independent and receives all dependencies via constructor.

    Example:
        >>> tool = YouDeepSearchTool(api_key="your-api-key")
        >>> result = await tool.search("Compare CUDA vs OpenCL for ML workloads")
    """

    def __init__(
        self,
        api_key: str,
        *,
        max_retries: int = 3,
        search_effort: str = "medium",
        timeout: int = 2000,
    ) -> None:
        """
        Initialize the You.com Deep Search tool.

        Args:
            api_key: API key for You.com Deep Search API.
            max_retries: Maximum retry attempts with exponential backoff (default 3).
            search_effort: Search depth — "low" (fast), "medium" (balanced), "high" (thorough).
            timeout: Request timeout in seconds (default 2000). Deep searches can take
                a long time for complex queries.
        """
        self.api_key = api_key
        self.max_retries = max_retries
        self.search_effort = search_effort
        self.timeout = timeout

    async def _fetch_results(self, query: str) -> dict[str, Any]:
        """Make async POST request to You.com Deep Search API."""
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "search_effort": self.search_effort,
        }
        timeout = aiohttp.ClientTimeout(total=self.timeout)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(YOU_DEEP_SEARCH_API_URL, headers=headers, json=payload) as response:
                if response.status != 200:
                    text = await response.text()
                    raise Exception(f"You.com Deep Search API error: {response.status} - {text[:200]}")
                return await response.json()

    @staticmethod
    def _format_results(data: dict[str, Any]) -> str:
        """Format Deep Search API response into structured output."""
        answer = data.get("answer", "")
        results = data.get("results", [])

        formatted = ""
        if answer:
            formatted += f"ANSWER:\n{answer}\n\n"

        for i, result in enumerate(results, start=1):
            url = result.get("url", "Unknown URL")
            title = result.get("title") or "Untitled Source"
            snippets = result.get("snippets", [])
            content = "\n- ".join(snippets) if snippets else "No excerpts available."

            formatted += f"\n--- SOURCE {i}: {title} ---\n"
            formatted += f"URL: {url}\n\n"
            formatted += f"SUMMARY:\n{content}\n\n"
            formatted += "-" * 80 + "\n"

        return formatted if formatted else "Deep search returned no results"

    async def search(self, question: str) -> str:
        """
        Perform deep search on You.com for the given question.

        Retries with exponential backoff on failure.

        Args:
            question: The research query string.

        Returns:
            Formatted string with comprehensive answer and cited sources.
        """
        for attempt in range(self.max_retries):
            try:
                data = await self._fetch_results(question)
                return self._format_results(data)
            except Exception as e:
                logger.warning(f"You.com deep search attempt {attempt + 1} failed: {e}")
                if attempt == self.max_retries - 1:
                    return f"Deep search error: {e}"
                await asyncio.sleep(2**attempt)

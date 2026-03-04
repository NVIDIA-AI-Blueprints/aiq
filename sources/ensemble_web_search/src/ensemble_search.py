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

"""Ensemble web search tool combining You.com Deep Search and Tavily.

Fires both backends in parallel via asyncio.gather() and merges results
into a unified <Document> XML format for consistent downstream consumption.
"""

import asyncio
import logging
from typing import Any

from .you_deep_web_search import YouDeepSearchTool

logger = logging.getLogger(__name__)


class EnsembleSearchTool:
    """
    Ensemble search tool that combines You.com Deep Search and Tavily.

    Calls both backends in parallel and merges results into consistent
    <Document> XML format with source attribution. Provides graceful
    degradation — if one backend fails, the other's results are still returned.

    Example:
        >>> tool = EnsembleSearchTool(
        ...     you_api_key=you_api,
        ...     tavily_api_key=tavily_api,
        ... )
        >>> result = await tool.search("Compare CUDA vs OpenCL for ML workloads")
    """

    def __init__(
        self,
        you_api_key: str,
        tavily_api_key: str,
        *,
        search_effort: str = "medium",
        tavily_max_results: int = 5,
        tavily_advanced: bool = True,
        max_retries: int = 5,
        timeout: int = 2000,
    ) -> None:
        self.tavily_api_key = tavily_api_key
        self.tavily_max_results = tavily_max_results
        self.tavily_advanced = tavily_advanced
        self.max_retries = max_retries

        self._deep_search = YouDeepSearchTool(
            api_key=you_api_key,
            max_retries=max_retries,
            search_effort=search_effort,
            timeout=timeout,
        )

    async def _run_deep_search(self, question: str) -> dict[str, Any]:
        """Run You.com Deep Search with retry logic, returning raw API dict."""
        for attempt in range(self.max_retries):
            try:
                return await self._deep_search._fetch_results(question)
            except Exception:
                if attempt == self.max_retries - 1:
                    raise
                await asyncio.sleep(2 ** (attempt + 1))

    async def _run_tavily(self, question: str) -> dict[str, Any]:
        """Run Tavily search with retry logic."""
        from langchain_tavily import TavilySearch

        # Tavily API requires queries under 400 characters
        query = question[:397] + "..." if len(question) > 400 else question

        tavily = TavilySearch(
            max_results=self.tavily_max_results,
            search_depth="advanced" if self.tavily_advanced else "basic",
            include_answer="advanced",
            tavily_api_key=self.tavily_api_key,
        )

        for attempt in range(self.max_retries):
            try:
                result = await tavily.ainvoke({"query": query})
                if isinstance(result, str):
                    raise Exception(f"Tavily returned error: {result}")
                if not isinstance(result, dict):
                    raise Exception(f"Tavily returned unexpected type: {type(result).__name__}")
                if "error" in result:
                    raise Exception(f"Tavily error: {result['error']}")
                return result
            except Exception:
                if attempt == self.max_retries - 1:
                    raise
                await asyncio.sleep(2 ** (attempt + 1))

    @staticmethod
    def _format_deep_search_as_xml(data: dict[str, Any]) -> str:
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

    @staticmethod
    def _format_tavily_as_xml(tavily_result: dict[str, Any]) -> str:
        """Convert Tavily search results into <Document> XML format."""
        answer_text = ""
        if tavily_result.get("answer"):
            answer_text = f"<Answer>\n{tavily_result['answer']}\n</Answer>\n\n---\n\n"

        web_search_results = "\n\n---\n\n".join(
            [
                f'<Document href="{doc["url"]}" source="tavily">\n'
                f"<title>\n{doc.get('title', '')}\n</title>\n"
                f"{doc['content']}\n</Document>"
                for doc in tavily_result.get("results", [])
            ]
        )
        combined = answer_text + web_search_results
        return combined if combined else ""

    async def search(self, question: str) -> str:
        """
        Search using both You.com Deep Search and Tavily in parallel.

        Returns merged results in consistent <Document> XML format.
        Gracefully degrades if one backend fails.

        Args:
            question: The search query string.

        Returns:
            Merged search results with source attribution.
        """
        deep_task = self._run_deep_search(question)
        tavily_task = self._run_tavily(question)

        results = await asyncio.gather(deep_task, tavily_task, return_exceptions=True)

        deep_result = results[0]
        tavily_result = results[1]

        deep_ok = not isinstance(deep_result, BaseException)
        tavily_ok = not isinstance(tavily_result, BaseException)

        if not deep_ok:
            logger.warning("Deep Search failed: %s", deep_result)
        if not tavily_ok:
            logger.warning("Tavily failed: %s", tavily_result)

        if not deep_ok and not tavily_ok:
            return f"Both search backends failed.\nDeep Search: {deep_result}\nTavily: {tavily_result}"

        parts = []

        if deep_ok and isinstance(deep_result, dict):
            deep_xml = self._format_deep_search_as_xml(deep_result)
            if deep_xml:
                parts.append(deep_xml)
        elif not deep_ok:
            parts.append(f"<!-- Deep Search unavailable: {deep_result} -->")

        if tavily_ok and isinstance(tavily_result, dict):
            tavily_xml = self._format_tavily_as_xml(tavily_result)
            if tavily_xml:
                parts.append(tavily_xml)
        elif not tavily_ok:
            parts.append(f"<!-- Tavily unavailable: {tavily_result} -->")

        return "\n\n---\n\n".join(parts) if parts else "Search returned no results"

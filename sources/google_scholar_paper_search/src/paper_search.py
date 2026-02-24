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
"""Paper search tool using Serper (Google Scholar).

This module contains the NAT-independent PaperSearchTool class.
"""

import asyncio
import logging
import math
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

SERPER_API_URL = "https://google.serper.dev/scholar"


class PaperSearchTool:
    """
    Paper search tool for academic papers using Google Scholar (Serper).

    This class is NAT-independent and receives all dependencies via constructor.

    Example:
        >>> tool = PaperSearchTool(
        ...     serper_api_key="your-api-key",
        ...     timeout=30,
        ...     max_results=10,
        ... )
        >>> result = await tool.search("machine learning transformers")
    """

    def __init__(
        self,
        serper_api_key: str,
        *,
        timeout: int = 30,
        max_results: int = 10,
    ) -> None:
        """
        Initialize the paper search tool.

        Args:
            serper_api_key: API key for Serper (Google Scholar).
            timeout: Timeout in seconds for search requests (default 30).
            max_results: Maximum number of search results to return (default 10).
        """
        self.serper_api_key = serper_api_key
        self.timeout = timeout
        self.max_results = max_results

    async def _fetch_serper_page(
        self,
        query: str,
        num: int,
        offset: int,
        start_year: str | None,
        end_year: str | None,
    ) -> dict[str, Any]:
        """Fetch a single page from Serper."""
        payload: dict[str, Any] = {
            "q": query,
            "num": min(num, 20),  # API limit per request
            "start": offset,
        }

        if start_year:
            payload["as_ylo"] = start_year
        if end_year:
            payload["as_yhi"] = end_year

        headers = {
            "X-API-KEY": self.serper_api_key,
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                SERPER_API_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    raise Exception(f"Serper API error: {response.status} - {text}")
                return await response.json()

    async def _search_serper(
        self,
        query: str,
        year: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Perform search using Serper (Google Scholar)."""
        start_year = None
        end_year = None
        if year:
            if "-" in year:
                parts = year.split("-")
                if len(parts) == 2:
                    start_year = parts[0] if parts[0] else None
                    end_year = parts[1] if parts[1] else None
            else:
                start_year = year
                end_year = year

        # Limit max results for Serper (cost control and API limits)
        limit = min(limit, 50)

        # Calculate pagination
        page_size = 10  # Serper default/typical
        total_pages = math.ceil(limit / page_size)

        tasks = []
        for page in range(total_pages):
            current_limit = min(page_size, limit - (page * page_size))
            if current_limit <= 0:
                break

            tasks.append(
                self._fetch_serper_page(
                    query,
                    current_limit,
                    page * page_size,
                    start_year,
                    end_year,
                )
            )

        page_results = await asyncio.gather(*tasks)

        all_papers = []
        for result in page_results:
            if result.get("organic"):
                all_papers.extend(result["organic"])

        return all_papers[:limit]

    @staticmethod
    def format_results(results: list[dict[str, Any]]) -> str:
        """Format Serper (Google Scholar) results."""
        if not results:
            return "No papers found via Google Scholar."

        formatted_papers = []
        for i, paper in enumerate(results, 1):
            title = paper.get("title", "Unknown Title")
            year = paper.get("year", "Unknown Year")
            snippet = paper.get("snippet", "")
            link = paper.get("link", "")
            pub_info = paper.get("publicationInfo", "")
            citations = paper.get("citedBy", 0)

            paper_str = (
                f"{i}. **{title}** ({year})\n"
                f"   - **Publication**: {pub_info}\n"
                f"   - **Citations**: {citations}\n"
                f"   - **Snippet**: {snippet}\n"
                f"   - **Link**: {link}"
            )
            formatted_papers.append(paper_str)

        return "\n\n".join(formatted_papers)

    async def search(
        self,
        query: str,
        year: str | None = None,
    ) -> str:
        """
        Search for peer-reviewed academic papers and scientific publications.

        This method returns papers from Google Scholar with citations, abstracts,
        and links for research queries requiring authoritative, scholarly sources
        including: scientific concepts, algorithms, methodologies, technical
        foundations, theoretical frameworks, empirical studies, and peer-reviewed
        evidence.

        Args:
            query: The search query string.
            year: Optional year or year range (e.g., "2023" or "2020-2023").

        Returns:
            Formatted string with search results.
        """
        if not query:
            return "Error: 'query' argument is required"

        if year is not None and not isinstance(year, str):
            year = str(year)

        logger.info(f"Paper search (serper) for: {query}")

        try:
            results = await self._search_serper(query, year, self.max_results)
            return self.format_results(results)

        except TimeoutError:
            logger.error(f"Paper search timed out for query: {query}")
            return f"Paper search timed out after {self.timeout}s for query: {query}"
        except Exception as e:
            logger.error(f"Paper search failed: {e}")
            return f"Paper search failed: {str(e)}"

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
"""Paper search tool using Google Scholar via Serper, SerpAPI, or SearchAPI.

This module contains the NAT-independent PaperSearchTool class. The provider
is selected at construction time; each provider's raw response is normalized
into a common shape consumed by ``format_results``.
"""

import asyncio
import logging
import math
import re
from enum import StrEnum
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

SERPER_API_URL = "https://google.serper.dev/scholar"
SERPAPI_API_URL = "https://serpapi.com/search"
SEARCHAPI_API_URL = "https://www.searchapi.io/api/v1/search"

# Matches a 4-digit year (19xx or 20xx) inside a publication summary string.
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


class PaperSearchProvider(StrEnum):
    """Supported Google Scholar search providers."""

    SERPER = "serper"
    SERPAPI = "serpapi"
    SEARCHAPI = "searchapi"


class PaperSearchTool:
    """Paper search tool for academic papers using Google Scholar.

    The ``provider`` argument selects which backend API to use. All providers
    return results normalized to the same shape so ``format_results`` and the
    rest of the pipeline are provider-agnostic.

    This class is NAT-independent and receives all dependencies via constructor.

    Example:
        >>> # Serper (default, backward compatible)
        >>> tool = PaperSearchTool(serper_api_key="your-key")
        >>>
        >>> # SerpAPI
        >>> tool = PaperSearchTool(
        ...     provider="serpapi",
        ...     serpapi_api_key="your-key",
        ... )
        >>>
        >>> # SearchAPI
        >>> tool = PaperSearchTool(
        ...     provider="searchapi",
        ...     searchapi_api_key="your-key",
        ... )
        >>> result = await tool.search("machine learning transformers")
    """

    def __init__(
        self,
        serper_api_key: str | None = None,
        *,
        provider: str | PaperSearchProvider = PaperSearchProvider.SERPER,
        serpapi_api_key: str | None = None,
        searchapi_api_key: str | None = None,
        timeout: int = 30,
        max_results: int = 10,
    ) -> None:
        """Initialize the paper search tool.

        Args:
            serper_api_key: API key for Serper. Kept as the first positional
                argument for backward compatibility; required when
                ``provider="serper"``.
            provider: Which backend to use — ``"serper"``, ``"serpapi"``, or
                ``"searchapi"``. Defaults to ``"serper"``.
            serpapi_api_key: API key for SerpAPI (required when provider is serpapi).
            searchapi_api_key: API key for SearchAPI (required when provider is searchapi).
            timeout: Timeout in seconds for search requests (default 30).
            max_results: Maximum number of search results to return (default 10).
        """
        self.provider = PaperSearchProvider(provider)
        self.serper_api_key = serper_api_key
        self.serpapi_api_key = serpapi_api_key
        self.searchapi_api_key = searchapi_api_key
        self.timeout = timeout
        self.max_results = max_results

    # ── Public API ──
    async def search(
        self,
        query: str,
        year: str | None = None,
    ) -> str:
        """Search for peer-reviewed academic papers and scientific publications.

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

        logger.info(f"Paper search ({self.provider.value}) for: {query}")

        try:
            if self.provider is PaperSearchProvider.SERPER:
                results = await self._search_serper(query, year, self.max_results)
            elif self.provider is PaperSearchProvider.SERPAPI:
                results = await self._search_serpapi(query, year, self.max_results)
            elif self.provider is PaperSearchProvider.SEARCHAPI:
                results = await self._search_searchapi(query, year, self.max_results)
            else:  # pragma: no cover - exhausted by enum
                raise ValueError(f"Unsupported provider: {self.provider}")
            return self.format_results(results)

        except TimeoutError:
            logger.error(f"Paper search timed out for query: {query}")
            return f"Paper search timed out after {self.timeout}s for query: {query}"
        except Exception:
            logger.exception("Paper search failed for provider '%s'", self.provider.value)
            return f"Paper search failed: unable to fetch results from {self.provider.value}."

    @staticmethod
    def format_results(results: list[dict[str, Any]]) -> str:
        """Format normalized Google Scholar results.

        Expects each dict to have the keys: ``title``, ``year``, ``snippet``,
        ``link``, ``publicationInfo``, ``citedBy``. All provider responses are
        normalized to this shape before reaching here.
        """
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

    # ── Shared helpers ──
    @staticmethod
    def _parse_year_range(year: str | None) -> tuple[str | None, str | None]:
        """Parse a year argument into a ``(start_year, end_year)`` tuple.

        Accepts a single year (``"2023"``) or a range (``"2020-2023"``,
        ``"-2023"``, ``"2020-"``).
        """
        if not year:
            return None, None
        if "-" in year:
            parts = year.split("-")
            if len(parts) == 2:
                start_year = parts[0] if parts[0] else None
                end_year = parts[1] if parts[1] else None
                return start_year, end_year
        return year, year

    @staticmethod
    def _extract_year(publication_info: Any) -> str:
        """Extract a 4-digit year from a publication summary string.

        SerpAPI and SearchAPI embed the year inside the publication summary
        (e.g. ``"JL Harper - ..., 1977 - cabdirect.org"``). Serper returns
        a clean ``year`` field, so this is only used for the other two.
        """
        if not isinstance(publication_info, str):
            return "Unknown Year"
        match = _YEAR_RE.search(publication_info)
        return match.group(1) if match else "Unknown Year"

    # ── Serper (POST, X-API-KEY header) ──
    async def _fetch_serper_page(
        self,
        query: str,
        num: int,
        offset: int,
        start_year: str | None,
        end_year: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "q": query,
            "num": min(num, 20),
            "start": offset,
        }

        if start_year:
            payload["as_ylo"] = start_year
        if end_year:
            payload["as_yhi"] = end_year

        headers = {
            "X-API-KEY": self.serper_api_key or "",
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
                    raise RuntimeError(f"Serper API error: HTTP {response.status}")
                return await response.json()

    async def _search_serper(
        self,
        query: str,
        year: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Perform search using Serper (Google Scholar).

        Serper already returns the normalized shape (``title``, ``year``,
        ``snippet``, ``link``, ``publicationInfo``, ``citedBy``), so results
        are returned as-is.
        """
        start_year, end_year = self._parse_year_range(year)

        limit = min(limit, 50)

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

    # ── SerpAPI (GET, api_key query param, start offset) ──
    async def _fetch_serpapi_page(
        self,
        query: str,
        num: int,
        offset: int,
        start_year: str | None,
        end_year: str | None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "engine": "google_scholar",
            "q": query,
            "num": min(num, 20),
            "start": offset,
            "api_key": self.serpapi_api_key or "",
        }

        if start_year:
            params["as_ylo"] = start_year
        if end_year:
            params["as_yhi"] = end_year

        async with aiohttp.ClientSession() as session:
            async with session.get(
                SERPAPI_API_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status != 200:
                    raise RuntimeError(f"SerpAPI error: HTTP {response.status}")
                return await response.json()

    async def _search_serpapi(
        self,
        query: str,
        year: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        start_year, end_year = self._parse_year_range(year)
        limit = min(limit, 50)

        page_size = 10
        total_pages = math.ceil(limit / page_size)

        tasks = []
        for page in range(total_pages):
            current_limit = min(page_size, limit - (page * page_size))
            if current_limit <= 0:
                break
            tasks.append(
                self._fetch_serpapi_page(
                    query,
                    current_limit,
                    page * page_size,
                    start_year,
                    end_year,
                )
            )

        page_results = await asyncio.gather(*tasks)
        raw = []
        for result in page_results:
            raw.extend(result.get("organic_results", []))
        return self._normalize_serpapi(raw)[:limit]

    @staticmethod
    def _normalize_serpapi(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        for paper in results:
            pub_info = paper.get("publication_info", {}) or {}
            summary = pub_info.get("summary", "")
            inline_links = paper.get("inline_links", {}) or {}
            cited_by = inline_links.get("cited_by", {}) or {}
            normalized.append(
                {
                    "title": paper.get("title", "Unknown Title"),
                    "year": PaperSearchTool._extract_year(summary),
                    "snippet": paper.get("snippet", ""),
                    "link": paper.get("link", ""),
                    "publicationInfo": summary,
                    "citedBy": cited_by.get("total", 0),
                }
            )
        return normalized

    # ── SearchAPI (GET, api_key query param, 1-based page) ──
    async def _fetch_searchapi_page(
        self,
        query: str,
        num: int,
        page: int,
        start_year: str | None,
        end_year: str | None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "engine": "google_scholar",
            "q": query,
            "num": min(num, 20),
            "page": page,
            "api_key": self.searchapi_api_key or "",
        }

        if start_year:
            params["as_ylo"] = start_year
        if end_year:
            params["as_yhi"] = end_year

        async with aiohttp.ClientSession() as session:
            async with session.get(
                SEARCHAPI_API_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status != 200:
                    raise RuntimeError(f"SearchAPI error: HTTP {response.status}")
                return await response.json()

    async def _search_searchapi(
        self,
        query: str,
        year: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        start_year, end_year = self._parse_year_range(year)
        limit = min(limit, 50)

        page_size = 10
        total_pages = math.ceil(limit / page_size)

        tasks = []
        for page_idx in range(total_pages):
            current_limit = min(page_size, limit - (page_idx * page_size))
            if current_limit <= 0:
                break
            # SearchAPI pages are 1-based
            tasks.append(
                self._fetch_searchapi_page(
                    query,
                    current_limit,
                    page_idx + 1,
                    start_year,
                    end_year,
                )
            )

        page_results = await asyncio.gather(*tasks)
        raw = []
        for result in page_results:
            raw.extend(result.get("organic_results", []))
        return self._normalize_searchapi(raw)[:limit]

    @staticmethod
    def _normalize_searchapi(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        for paper in results:
            pub_info = paper.get("publication", "") or ""
            inline_links = paper.get("inline_links", {}) or {}
            cited_by = inline_links.get("cited_by", {}) or {}
            normalized.append(
                {
                    "title": paper.get("title", "Unknown Title"),
                    "year": PaperSearchTool._extract_year(pub_info),
                    "snippet": paper.get("snippet", ""),
                    "link": paper.get("link", ""),
                    "publicationInfo": pub_info,
                    "citedBy": cited_by.get("total", 0),
                }
            )
        return normalized

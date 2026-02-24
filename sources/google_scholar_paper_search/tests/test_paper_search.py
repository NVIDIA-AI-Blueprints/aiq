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

"""Tests for PaperSearchTool class."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from google_scholar_paper_search.paper_search import PaperSearchTool


class TestPaperSearchToolInit:
    """Tests for PaperSearchTool initialization."""

    def test_init_with_required_params(self):
        """Test initialization with required parameters."""
        tool = PaperSearchTool(serper_api_key="test-key")

        assert tool.serper_api_key == "test-key"
        assert tool.timeout == 30  # default
        assert tool.max_results == 10  # default

    def test_init_with_all_params(self):
        """Test initialization with all parameters."""
        tool = PaperSearchTool(
            serper_api_key="test-key",
            timeout=60,
            max_results=20,
        )

        assert tool.serper_api_key == "test-key"
        assert tool.timeout == 60
        assert tool.max_results == 20

    def test_init_with_custom_timeout(self):
        """Test initialization with custom timeout."""
        tool = PaperSearchTool(serper_api_key="test-key", timeout=120)

        assert tool.timeout == 120

    def test_init_with_custom_max_results(self):
        """Test initialization with custom max_results."""
        tool = PaperSearchTool(serper_api_key="test-key", max_results=50)

        assert tool.max_results == 50


class TestFormatResults:
    """Tests for format_results static method."""

    def test_format_results_empty_list(self):
        """Test formatting empty results returns appropriate message."""
        result = PaperSearchTool.format_results([])

        assert result == "No papers found via Google Scholar."

    def test_format_results_single_paper(self, sample_papers):
        """Test formatting a single paper."""
        result = PaperSearchTool.format_results([sample_papers[0]])

        assert "1. **Test Paper 1** (2023)" in result
        assert "**Publication**: Test Journal" in result
        assert "**Citations**: 100" in result
        assert "**Snippet**: This is a test snippet." in result
        assert "**Link**: https://example.com/paper1" in result

    def test_format_results_multiple_papers(self, sample_papers):
        """Test formatting multiple papers."""
        result = PaperSearchTool.format_results(sample_papers)

        assert "1. **Test Paper 1** (2023)" in result
        assert "2. **Test Paper 2** (2024)" in result
        assert "\n\n" in result  # Papers should be separated

    def test_format_results_missing_fields(self):
        """Test formatting papers with missing fields uses defaults."""
        papers = [{"title": "Only Title"}]
        result = PaperSearchTool.format_results(papers)

        assert "1. **Only Title** (Unknown Year)" in result
        assert "**Publication**: " in result
        assert "**Citations**: 0" in result

    def test_format_results_all_fields_missing(self):
        """Test formatting papers with all fields missing."""
        papers = [{}]
        result = PaperSearchTool.format_results(papers)

        assert "1. **Unknown Title** (Unknown Year)" in result


class TestSearch:
    """Tests for search method."""

    @pytest.mark.asyncio
    async def test_search_empty_query(self, paper_search_tool):
        """Test search with empty query returns error."""
        result = await paper_search_tool.search("")

        assert result == "Error: 'query' argument is required"

    @pytest.mark.asyncio
    async def test_search_success(self, paper_search_tool, sample_serper_response):
        """Test successful search with mocked API response."""
        with patch.object(
            paper_search_tool,
            "_search_serper",
            new_callable=AsyncMock,
            return_value=sample_serper_response["organic"],
        ):
            result = await paper_search_tool.search("transformers")

        assert "Attention Is All You Need" in result
        assert "BERT" in result

    @pytest.mark.asyncio
    async def test_search_with_year(self, paper_search_tool, sample_serper_response):
        """Test search with year filter."""
        mock_search = AsyncMock(return_value=sample_serper_response["organic"])
        with patch.object(paper_search_tool, "_search_serper", mock_search):
            await paper_search_tool.search("transformers", year="2023")

        mock_search.assert_called_once_with("transformers", "2023", 10)

    @pytest.mark.asyncio
    async def test_search_timeout_error(self, paper_search_tool):
        """Test search handles timeout error gracefully."""
        with patch.object(
            paper_search_tool,
            "_search_serper",
            new_callable=AsyncMock,
            side_effect=TimeoutError("Request timed out"),
        ):
            result = await paper_search_tool.search("test query")

        assert "Paper search timed out" in result
        assert "30s" in result

    @pytest.mark.asyncio
    async def test_search_general_exception(self, paper_search_tool):
        """Test search handles general exceptions gracefully."""
        with patch.object(
            paper_search_tool,
            "_search_serper",
            new_callable=AsyncMock,
            side_effect=Exception("API Error"),
        ):
            result = await paper_search_tool.search("test query")

        assert "Paper search failed" in result
        assert "API Error" in result

    @pytest.mark.asyncio
    async def test_search_with_integer_year(self, paper_search_tool, sample_serper_response):
        """Test search handles integer year by converting to string."""
        mock_search = AsyncMock(return_value=sample_serper_response["organic"])
        with patch.object(paper_search_tool, "_search_serper", mock_search):
            await paper_search_tool.search("transformers", year=2023)

        mock_search.assert_called_once_with("transformers", "2023", 10)


class TestSearchSerper:
    """Tests for _search_serper internal method."""

    @pytest.mark.asyncio
    async def test_year_parsing_single_year(self, paper_search_tool):
        """Test year parsing for single year."""
        with patch.object(
            paper_search_tool,
            "_fetch_serper_page",
            new_callable=AsyncMock,
            return_value={"organic": []},
        ) as mock_fetch:
            await paper_search_tool._search_serper(  # noqa: SLF001
                "query", year="2023", limit=10
            )

        mock_fetch.assert_called_once()
        call_args = mock_fetch.call_args
        # start_year and end_year should both be "2023"
        assert call_args[0][3] == "2023"  # start_year
        assert call_args[0][4] == "2023"  # end_year

    @pytest.mark.asyncio
    async def test_year_parsing_range(self, paper_search_tool):
        """Test year parsing for year range."""
        with patch.object(
            paper_search_tool,
            "_fetch_serper_page",
            new_callable=AsyncMock,
            return_value={"organic": []},
        ) as mock_fetch:
            await paper_search_tool._search_serper(  # noqa: SLF001
                "query", year="2020-2023", limit=10
            )

        mock_fetch.assert_called_once()
        call_args = mock_fetch.call_args
        assert call_args[0][3] == "2020"  # start_year
        assert call_args[0][4] == "2023"  # end_year

    @pytest.mark.asyncio
    async def test_year_parsing_open_start(self, paper_search_tool):
        """Test year parsing for open start range."""
        with patch.object(
            paper_search_tool,
            "_fetch_serper_page",
            new_callable=AsyncMock,
            return_value={"organic": []},
        ) as mock_fetch:
            await paper_search_tool._search_serper(  # noqa: SLF001
                "query", year="-2023", limit=10
            )

        mock_fetch.assert_called_once()
        call_args = mock_fetch.call_args
        assert call_args[0][3] is None  # start_year
        assert call_args[0][4] == "2023"  # end_year

    @pytest.mark.asyncio
    async def test_year_parsing_open_end(self, paper_search_tool):
        """Test year parsing for open end range."""
        with patch.object(
            paper_search_tool,
            "_fetch_serper_page",
            new_callable=AsyncMock,
            return_value={"organic": []},
        ) as mock_fetch:
            await paper_search_tool._search_serper(  # noqa: SLF001
                "query", year="2020-", limit=10
            )

        mock_fetch.assert_called_once()
        call_args = mock_fetch.call_args
        assert call_args[0][3] == "2020"  # start_year
        assert call_args[0][4] is None  # end_year

    @pytest.mark.asyncio
    async def test_limit_capped_at_50(self, paper_search_tool):
        """Test that limit is capped at 50."""
        with patch.object(
            paper_search_tool,
            "_fetch_serper_page",
            new_callable=AsyncMock,
            return_value={"organic": []},
        ):
            result = await paper_search_tool._search_serper(  # noqa: SLF001
                "query", limit=100
            )

        assert result == []  # Empty since mocked

    @pytest.mark.asyncio
    async def test_pagination_multiple_pages(self, paper_search_tool):
        """Test pagination for results requiring multiple pages."""
        with patch.object(
            paper_search_tool,
            "_fetch_serper_page",
            new_callable=AsyncMock,
            return_value={"organic": [{"title": "Paper"}]},
        ) as mock_fetch:
            await paper_search_tool._search_serper(  # noqa: SLF001
                "query", limit=25
            )

        # 25 results / 10 per page = 3 pages
        assert mock_fetch.call_count == 3

    @pytest.mark.asyncio
    async def test_aggregates_results_from_pages(self, paper_search_tool):
        """Test that results from multiple pages are aggregated."""
        page1 = {"organic": [{"title": "Paper 1"}, {"title": "Paper 2"}]}
        page2 = {"organic": [{"title": "Paper 3"}]}

        with patch.object(
            paper_search_tool,
            "_fetch_serper_page",
            new_callable=AsyncMock,
            side_effect=[page1, page2],
        ):
            result = await paper_search_tool._search_serper(  # noqa: SLF001
                "query", limit=20
            )

        assert len(result) == 3
        assert result[0]["title"] == "Paper 1"
        assert result[2]["title"] == "Paper 3"


class TestFetchSerperPage:
    """Tests for _fetch_serper_page internal method."""

    @pytest.mark.asyncio
    async def test_fetch_builds_correct_payload(self, paper_search_tool):
        """Test that fetch builds correct API payload."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"organic": []})

        mock_session = MagicMock()
        mock_context = MagicMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(),
        )
        mock_session.post = MagicMock(return_value=mock_context)

        with patch("aiohttp.ClientSession") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_client.return_value.__aexit__ = AsyncMock()

            await paper_search_tool._fetch_serper_page(  # noqa: SLF001
                query="test query",
                num=10,
                offset=0,
                start_year="2020",
                end_year="2023",
            )

        # Verify post was called with correct arguments
        mock_session.post.assert_called_once()
        call_kwargs = mock_session.post.call_args[1]
        payload = call_kwargs["json"]

        assert payload["q"] == "test query"
        assert payload["num"] == 10
        assert payload["start"] == 0
        assert payload["as_ylo"] == "2020"
        assert payload["as_yhi"] == "2023"

    @pytest.mark.asyncio
    async def test_fetch_num_capped_at_20(self, paper_search_tool):
        """Test that num parameter is capped at 20 (API limit)."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"organic": []})

        mock_session = MagicMock()
        mock_context = MagicMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(),
        )
        mock_session.post = MagicMock(return_value=mock_context)

        with patch("aiohttp.ClientSession") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_client.return_value.__aexit__ = AsyncMock()

            await paper_search_tool._fetch_serper_page(  # noqa: SLF001
                query="test",
                num=50,  # More than limit
                offset=0,
                start_year=None,
                end_year=None,
            )

        call_kwargs = mock_session.post.call_args[1]
        payload = call_kwargs["json"]
        assert payload["num"] == 20  # Should be capped

    @pytest.mark.asyncio
    async def test_fetch_no_year_params_when_none(self, paper_search_tool):
        """Test that year params are not included when None."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"organic": []})

        mock_session = MagicMock()
        mock_context = MagicMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(),
        )
        mock_session.post = MagicMock(return_value=mock_context)

        with patch("aiohttp.ClientSession") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_client.return_value.__aexit__ = AsyncMock()

            await paper_search_tool._fetch_serper_page(  # noqa: SLF001
                query="test",
                num=10,
                offset=0,
                start_year=None,
                end_year=None,
            )

        call_kwargs = mock_session.post.call_args[1]
        payload = call_kwargs["json"]
        assert "as_ylo" not in payload
        assert "as_yhi" not in payload

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

"""Register a tool that opens HTTP(S) pages through Tavily Extract.

The adapter does not forward ``query`` because extraction must remain complete before local windowing. It also
detects soft 404 pages and handles the ``AttributeError`` raised by ``langchain_tavily`` for string error payloads.
"""

import asyncio
import logging
import os
import re
from urllib.parse import urlparse

from pydantic import BaseModel
from pydantic import Field
from pydantic import SecretStr

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

from .formatting import FetchedPage
from .formatting import compact
from .formatting import parse_fetched_pages
from .formatting import render_page_section
from .formatting import render_result
from .formatting import render_skipped_section
from .formatting import select_window

logger = logging.getLogger(__name__)

_missing_key_warned = False
_registered_parsers: set[str] = set()

_SOFT_404_MARKERS = (
    "page not found",
    "404 not found",
    "page cannot be found",
    "page could not be found",
    "page you requested could not be found",
    "page doesn't exist",
    "page does not exist",
    "no longer exists",
    "error 404",
)
_SOFT_404_MAX_CHARS = 6000


class FetchUrlInput(BaseModel):
    """Model-facing input schema for exact URLs and local content windowing."""

    urls: list[str] = Field(
        ...,
        description=(
            "Exact, complete URLs to open, for example "
            "['https://www.iea.nl/sites/default/files/ICILS_2023_report.pdf']. NOT search "
            "keywords - every item must start with http:// or https://. Pass several URLs to open "
            "them in one call."
        ),
    )
    query: str | None = Field(
        default=None,
        description=(
            "Optional. What you are looking for on these pages, for example 'table 2.2 computer "
            "literacy by country'. Used ONLY to choose which part of a long page to show you. It "
            "does not search the web and does not change which pages are opened."
        ),
    )
    start_line: int = Field(
        default=0,
        ge=0,
        description=(
            "Optional. Line number to resume from when continuing a page that was truncated; the "
            "truncation note tells you which line to pass. Applies to every URL in this call."
        ),
    )


class TavilyWebFetchToolConfig(FunctionBaseConfig, name="tavily_web_fetch"):
    """Configuration for opening web pages with Tavily Extract."""

    max_urls_per_call: int = Field(default=4, ge=1, description="Maximum URLs accepted in one call")
    max_chars_per_page: int = Field(
        default=10000,
        ge=500,
        description=(
            "Maximum characters shown per page. This is a prompt-context budget, not a download "
            "limit: pages are extracted in full and then windowed."
        ),
    )
    max_chars_per_call: int = Field(
        default=24000,
        ge=500,
        description="Maximum characters shown across all URLs in one call, spent in request order.",
    )
    extract_depth: str = Field(
        default="advanced",
        description="Tavily extraction depth: 'basic' or 'advanced'.",
    )
    timeout_seconds: int = Field(default=30, ge=1, description="Per-call extraction timeout")
    api_key: SecretStr | None = Field(default=None, description="API key for the Tavily service")


def _validate_url(candidate: str) -> tuple[str, str]:
    """Return a normalized HTTP(S) URL or a model-facing validation error."""
    text = (candidate or "").strip()
    if not text:
        return "", "Empty URL. Pass a complete address starting with http:// or https://."

    parsed = urlparse(text)
    # Check the scheme first so non-web schemes receive an explicit refusal rather than search guidance.
    if parsed.scheme and parsed.scheme not in ("http", "https", "www"):
        return "", (
            f"Only http:// and https:// URLs can be opened (got '{parsed.scheme}://'). This tool reads web pages only."
        )
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "", (
            f'"{text[:120]}" is not a URL. This tool opens pages you already have the address for; '
            "use web_search_tool to find one first, then pass the URL it returns."
        )
    return text, ""


def _looks_like_soft_404(text: str) -> bool:
    """Return whether short extracted content resembles a soft 404 page."""
    if not text or len(text) > _SOFT_404_MAX_CHARS:
        return False
    lowered = re.sub(r"\s+", " ", text.lower())
    return any(marker in lowered for marker in _SOFT_404_MARKERS)


def _page_from_result(requested: str, result: dict) -> FetchedPage:
    """Build a fetched page from one Tavily result."""
    text = compact((result.get("raw_content") or "").strip())
    final_url = (result.get("url") or requested).strip()
    title = (result.get("title") or "").strip()

    if not text:
        return FetchedPage(
            url=requested,
            status="failed",
            reason="Could not read this page: the extractor returned no content for it.",
        )
    if _looks_like_soft_404(text):
        return FetchedPage(
            url=requested,
            final_url=final_url,
            title=title,
            text=text,
            status="suspect",
            reason=(
                "[Caution: this looks like a 'page not found' page rather than the document you "
                "asked for. Do not cite it. Search for the current location of this page instead.]"
            ),
        )
    return FetchedPage(url=requested, final_url=final_url, title=title, text=text, status="ok")


def _normalize(url: str) -> str:
    """Return a URL comparison key tolerant of trailing slashes."""
    return url.strip().rstrip("/").lower()


async def _extract(tool, urls: list[str], *, extract_depth: str, timeout_seconds: int) -> tuple[list[dict], str]:
    """Call Tavily Extract without relevance filtering and return results or an error."""
    try:
        # Do not forward query: local windowing must operate on the complete extraction so misses are recoverable.
        payload = {"urls": urls, "extract_depth": extract_depth}
        response = await asyncio.wait_for(tool.ainvoke(payload), timeout=timeout_seconds)
    except TimeoutError:
        return [], f"the extraction service did not respond within {timeout_seconds} seconds"
    except AttributeError:
        # langchain_tavily calls .get() on bare string errors instead of returning them.
        return [], "the extraction service returned an error response"
    except Exception as exc:  # noqa: BLE001 - tools return errors rather than raising into the agent
        logger.warning("tavily_web_fetch extraction failed: %s", type(exc).__name__)
        return [], f"the extraction request failed ({type(exc).__name__})"

    if isinstance(response, str):
        return [], "the extraction service returned an error response"
    if not isinstance(response, dict) or response.get("error"):
        return [], "the extraction service returned an error response"
    results = response.get("results")
    return (results if isinstance(results, list) else []), ""


@register_function(config_type=TavilyWebFetchToolConfig)
async def tavily_web_fetch(tool_config: TavilyWebFetchToolConfig, builder: Builder):
    """Register the Tavily web fetch tool with NAT."""
    from langchain_tavily import TavilyExtract

    if not os.environ.get("TAVILY_API_KEY") and tool_config.api_key:
        os.environ["TAVILY_API_KEY"] = tool_config.api_key.get_secret_value()

    tool_name = tool_config.type
    try:
        tool_name = tool_config.name or tool_config.type
    except AttributeError:  # pragma: no cover - older NAT config shapes
        pass

    if not os.environ.get("TAVILY_API_KEY"):
        global _missing_key_warned
        if not _missing_key_warned:
            logger.warning("TAVILY_API_KEY not found. Page fetching will return an error until the key is configured.")
            _missing_key_warned = True

        async def _fetch_url_stub(urls: list[str], query: str | None = None, start_line: int = 0) -> str:
            """Page fetch tool (unavailable - missing TAVILY_API_KEY)."""
            return (
                "Error: Page fetching is unavailable because TAVILY_API_KEY is not set. "
                "Set the key and restart the application."
            )

        yield FunctionInfo.from_fn(
            _fetch_url_stub,
            input_schema=FetchUrlInput,
            description=_fetch_url_stub.__doc__,
        )
        return

    # Replace the generic URL scraper so outbound links do not become sources the agent never read.
    if tool_name not in _registered_parsers:
        try:
            from aiq_agent.common.citation_verification import register_source_parser

            register_source_parser(
                lambda name, registered_name=tool_name.lower(): name == registered_name, parse_fetched_pages
            )
            _registered_parsers.add(tool_name)
        except ImportError:  # pragma: no cover - package used outside an AI-Q install
            logger.debug("aiq_agent not importable; skipping source-parser registration")

    extractor = TavilyExtract(extract_depth=tool_config.extract_depth)

    async def _fetch_url(urls: list[str], query: str | None = None, start_line: int = 0) -> str:
        """Opens web pages you already have the URL for and returns their text.

        This is a READER, not a FINDER. Give it exact URLs to read full page content instead of
        truncated search snippets.

        USE THIS TOOL WHEN:
        - The question supplies a URL or names a specific page, report, filing, table, or PDF.
        - A search result looks relevant and you need its exact numbers, rows, dates, or wording.

        DO NOT USE THIS TOOL WHEN:
        - You do not have a URL. Call web_search_tool first, then open the result.
        - You would pass keywords, a question, or a site name instead of a URL.

        Search finds pages; fetch_url_tool opens a selected page. The normal loop is search, pick
        a URL, then fetch it.

        Examples:
            urls=["https://pmc.ncbi.nlm.nih.gov/articles/PMC9506306/"]
            web_search_tool("ICILS 2023 report") -> URL; then pass that URL with query="table 2.2"
            WRONG: urls=["maple syrup production by state 2017"]

        Args:
            urls: Exact, complete URLs to open. Not search terms.
            query: Optional text used only to select a window within long pages.
            start_line: Optional line from which to continue a truncated page.

        Returns:
            One section per URL with page text or a reason the page could not be read.
        """
        requested = list(urls or [])
        if not requested:
            return (
                "Error: No URLs provided. Pass one or more exact URLs, for example "
                "urls=['https://www.example.gov/report']. To find a URL first, use web_search_tool."
            )
        if len(requested) > tool_config.max_urls_per_call:
            return (
                f"Error: {tool_name} accepts at most {tool_config.max_urls_per_call} URLs per call; "
                f"received {len(requested)}. Split them across calls, most important first."
            )

        valid: list[str] = []
        pages: dict[str, FetchedPage] = {}
        for candidate in requested:
            normalized, reason = _validate_url(candidate)
            if reason:
                pages[candidate] = FetchedPage(url=candidate, status="failed", reason=reason)
            else:
                valid.append(normalized)

        if valid:
            results, error = await _extract(
                extractor,
                valid,
                extract_depth=tool_config.extract_depth,
                timeout_seconds=tool_config.timeout_seconds,
            )
            by_url = {_normalize(str(item.get("url", ""))): item for item in results if isinstance(item, dict)}
            for url in valid:
                match = by_url.get(_normalize(url))
                if match is not None:
                    pages[url] = _page_from_result(url, match)
                elif error:
                    pages[url] = FetchedPage(url=url, status="failed", reason=f"Could not read this page: {error}.")
                else:
                    pages[url] = FetchedPage(
                        url=url,
                        status="failed",
                        reason=(
                            "Could not read this page: the extractor returned nothing for this URL. "
                            "It may be unreachable, blocked, or not a readable document."
                        ),
                    )

        sections: list[str] = []
        remaining = tool_config.max_chars_per_call
        any_success = False
        for candidate in requested:
            page = pages.get(candidate) or pages.get((candidate or "").strip())
            if page is None:  # pragma: no cover - every requested URL receives a result above
                continue
            if page.status == "failed":
                sections.append(render_page_section(page, None, tool_name=tool_name))
                continue

            any_success = True
            budget = min(tool_config.max_chars_per_page, remaining)
            if budget <= 0:
                sections.append(render_skipped_section(page, max_chars_per_call=tool_config.max_chars_per_call))
                continue
            window = select_window(page.text, max_chars=budget, query=query or "", start_line=start_line)
            remaining -= window.shown_chars
            sections.append(render_page_section(page, window, tool_name=tool_name))

        if not any_success:
            # The prefix keeps a wholly failed fetch non-citable and feeds the source-tool circuit breaker.
            reasons = "\n".join(
                f"- {page.url}: {page.reason}" for page in (pages.get(url) for url in requested) if page
            )
            return f"Error: none of the requested URLs could be read.\n{reasons}"

        return render_result(sections)

    yield FunctionInfo.from_fn(
        _fetch_url,
        input_schema=FetchUrlInput,
        description=_fetch_url.__doc__,
    )

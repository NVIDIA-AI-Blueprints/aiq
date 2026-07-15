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
import enum
import logging
import os
from collections.abc import Callable
from collections.abc import Coroutine
from typing import Any

from langchain_youdotcom import YouContentsTool
from langchain_youdotcom import YouFinanceResearchTool
from langchain_youdotcom import YouResearchTool
from langchain_youdotcom import YouSearchTool
from pydantic import Field
from pydantic import SecretStr
from pydantic import field_validator

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)

_missing_key_warned = False

_CACHE_MAX_SIZE = 500

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SafesearchMode(enum.Enum):
    off = "off"
    moderate = "moderate"
    strict = "strict"


class LivecrawlMode(enum.Enum):
    off = "off"
    web = "web"
    news = "news"
    all = "all"


class LivecrawlFormat(enum.Enum):
    off = "off"
    markdown = "markdown"
    html = "html"


class FreshnessMode(enum.Enum):
    off = "off"
    day = "day"
    week = "week"
    month = "month"
    year = "year"


class ContentsFormat(enum.Enum):
    markdown = "markdown"
    html = "html"
    metadata = "metadata"


class ResearchEffort(enum.Enum):
    lite = "lite"
    standard = "standard"
    deep = "deep"
    exhaustive = "exhaustive"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _resolve_api_key(tool_config: "YouToolConfig") -> str | None:
    return tool_config.api_key.get_secret_value() if tool_config.api_key else os.environ.get("YDC_API_KEY")


def _warn_missing_key_once(tool_desc: str) -> None:
    # Process-once by design: all You.com tools share one key, so one warning is enough.
    global _missing_key_warned
    if not _missing_key_warned:
        logger.warning(
            "YDC_API_KEY not found. The %s tool will be registered but will "
            "return an error when called. To enable: set YDC_API_KEY in your environment, "
            ".env file, or specify api_key in your workflow config.",
            tool_desc,
        )
        _missing_key_warned = True


def _stub_message(label: str) -> str:
    return (
        f"Error: {label} is unavailable because YDC_API_KEY is not set.\n"
        "To enable this tool:\n"
        "1. Get an API key from https://you.com/docs/quickstart\n"
        "2. Set the API key in your environment or in your .env file\n"
        "3. Restart the application"
    )


def _make_stub(label: str) -> FunctionInfo:
    """Return a FunctionInfo that reports the tool is unavailable due to missing key."""

    async def _stub(question: str) -> str:
        return _stub_message(label)

    _stub.__doc__ = f"{label} (unavailable - missing YDC_API_KEY)."
    return FunctionInfo.from_fn(_stub, description=_stub.__doc__)


async def _run_with_retries(
    label: str,
    coro_factory: Callable[[str], Coroutine[Any, Any, str]],
    question: str,
    *,
    max_retries: int,
    timeout: float | None,
    cache: dict[str, str],
) -> str:
    """Execute coro_factory(question) with caching, timeout, and exponential-backoff retry.

    timeout is per-attempt, not end-to-end. Worst-case wall time: timeout * max_retries + backoff.
    """
    if question in cache:
        logger.debug("Cache hit for query: %s", question[:80])
        return cache[question]

    for attempt in range(max_retries):
        try:
            coro = coro_factory(question)
            result = await (asyncio.wait_for(coro, timeout=timeout) if timeout else coro)
            if not result or not str(result).strip():
                raise ValueError(f"{label} returned no results.")

            if len(cache) >= _CACHE_MAX_SIZE:
                cache.pop(next(iter(cache)))
            cache[question] = result
            return result

        except Exception as e:
            if attempt == max_retries - 1:
                error_msg = str(e)
                if isinstance(e, ValueError):
                    return f"Error: {error_msg}"
                if "401" in error_msg or "Unauthorized" in error_msg:
                    return (
                        f"Error: {label} failed due to invalid API key (401 Unauthorized).\n"
                        "Please check your YDC_API_KEY and ensure it is valid.\n"
                    )
                return f"Error: {label} failed after {max_retries} attempts: {error_msg}"
            await asyncio.sleep(2**attempt)


# ---------------------------------------------------------------------------
# Shared base config
# ---------------------------------------------------------------------------


class YouToolConfig(FunctionBaseConfig):
    """Base config shared by all You.com tools. Not registered directly."""

    api_key: SecretStr | None = Field(default=None, description="The API key for the You.com service")
    max_retries: int = Field(default=3, ge=1, description="Maximum number of retries for the request")
    timeout: float | None = Field(
        default=None,
        description="Timeout in seconds per attempt. None means no timeout.",
    )


# ---------------------------------------------------------------------------
# Tool configs
# ---------------------------------------------------------------------------


class YouWebSearchToolConfig(YouToolConfig, name="you_web_search"):
    """
    Tool that retrieves relevant search results from web search (using You.com) for the given question.
    Uses LangChain's YouSearchAPIWrapper. Requires a YDC_API_KEY environment variable or api_key config.
    """

    max_results: int = Field(default=10, ge=1, le=100, description="Maximum number of search results to return")
    safesearch: SafesearchMode = Field(
        default=SafesearchMode.moderate, description="Safesearch filter: 'off', 'moderate', or 'strict'"
    )
    livecrawl_mode: LivecrawlMode = Field(
        default=LivecrawlMode.web,
        description="If you want to retrieve page contents and the format to retrieve in: "
        "'off', 'web', 'news', or 'all'",
    )
    livecrawl_format: LivecrawlFormat = Field(
        default=LivecrawlFormat.markdown,
        description="What format you want to retrieve content in: 'off', 'markdown', 'html'",
    )
    freshness: FreshnessMode = Field(
        default=FreshnessMode.off,
        description="Restrict your search to a certain freshness: 'off', 'day', 'week', 'month', 'year'",
    )
    max_content_length: int | None = Field(
        default=50000,
        ge=0,
        description="If set, truncates each livecrawl result to specified amount of characters. "
        "Can be used to reduce token usage. Defaults to 50000 to bound context size; "
        "set to None for unbounded livecrawl content. "
        "Titles and descriptions always remain fully in tact, only livecrawl content is truncated.",
    )
    include_news_results: bool = Field(
        default=False,
        description="Whether or not you want to include news results. If False, filter out documents whose "
        "metadata 'source' is 'news'.",
    )


_FINANCE_RESEARCH_EFFORTS = {ResearchEffort.deep, ResearchEffort.exhaustive}


class YouFinanceResearchToolConfig(YouToolConfig, name="you_finance_research"):
    """
    Tool that answers financial questions using the You.com Finance Research API.
    Searches a finance-optimized index (SEC filings, earnings, equity prices, macro
    indicators) and returns a cited markdown response. Requires YDC_API_KEY.
    """

    research_effort: ResearchEffort = Field(
        default=ResearchEffort.deep,
        description="Research depth: 'deep' (faster) or 'exhaustive' (up to 300s)",
    )

    @field_validator("research_effort")
    @classmethod
    def _finance_effort_must_be_deep_or_exhaustive(cls, v: ResearchEffort) -> ResearchEffort:
        if v not in _FINANCE_RESEARCH_EFFORTS:
            raise ValueError(f"Finance research only supports 'deep' or 'exhaustive', got '{v.value}'")
        return v


class YouContentsToolConfig(YouToolConfig, name="you_contents"):
    """
    Tool that extracts clean content from URLs using the You.com Contents API.
    Pass up to 10 URLs and receive their full page content as Markdown, HTML, or metadata.
    Requires YDC_API_KEY.
    """

    formats: list[ContentsFormat] = Field(
        default=[ContentsFormat.markdown, ContentsFormat.metadata],
        description="Content formats to return: 'markdown', 'html', 'metadata'",
    )
    crawl_timeout: float | None = Field(
        default=None,
        ge=1,
        le=60,
        description="Per-URL crawl timeout in seconds (1-60). Increase for JavaScript-heavy pages.",
    )


class YouResearchToolConfig(YouToolConfig, name="you_research"):
    """
    Tool that answers open-domain questions using the You.com Research API.
    Synthesizes a cited markdown answer from live web sources. Requires YDC_API_KEY.
    """

    research_effort: ResearchEffort = Field(
        default=ResearchEffort.standard,
        description="Research depth: 'lite', 'standard', 'deep', or 'exhaustive' (slower, more thorough)",
    )


# ---------------------------------------------------------------------------
# Tool registrations
# ---------------------------------------------------------------------------


@register_function(config_type=YouWebSearchToolConfig)
async def you_web_search(tool_config: YouWebSearchToolConfig, builder: Builder):
    api_key = _resolve_api_key(tool_config)

    if not api_key:
        _warn_missing_key_once("web search")
        yield _make_stub("Web search")
        return

    livecrawl_mode = (
        None if tool_config.livecrawl_mode.value == LivecrawlMode.off.value else tool_config.livecrawl_mode.value
    )
    livecrawl_format = (
        None if tool_config.livecrawl_format.value == LivecrawlFormat.off.value else tool_config.livecrawl_format.value
    )
    freshness = None if tool_config.freshness == FreshnessMode.off else tool_config.freshness.value
    wrapper_kwargs = {
        k: v
        for k, v in {
            "ydc_api_key": api_key,
            "count": tool_config.max_results,
            "livecrawl": livecrawl_mode,
            "livecrawl_formats": livecrawl_format,
            "freshness": freshness,
            "safesearch": tool_config.safesearch.value,
        }.items()
        if v is not None
    }
    you_search_tool = YouSearchTool(api_wrapper=wrapper_kwargs)

    _cache: dict[str, str] = {}

    def _format_documents(search_docs) -> list[str]:
        formatted_results = []
        for doc in search_docs:
            if not tool_config.include_news_results and doc.metadata.get("source") == "news":
                continue
            title = doc.metadata.get("title", "")
            url = doc.metadata.get("url", "")
            description = doc.metadata.get("description", "")
            content = doc.page_content
            if content:
                if tool_config.max_content_length:
                    content = content[: tool_config.max_content_length]
                formatted_results.append(
                    f'<Document href="{url}">\n<title>\n{title}\n</title>\n{description}\n{content}\n</Document>'
                )
            else:
                formatted_results.append(
                    f'<Document href="{url}">\n<title>\n{title}\n</title>\n{description}\n</Document>'
                )
        return formatted_results

    async def _fetch(question: str) -> str:
        coro = you_search_tool.api_wrapper.results_async(question)
        docs = await (asyncio.wait_for(coro, timeout=tool_config.timeout) if tool_config.timeout else coro)
        if not docs:
            raise ValueError("Search returned no results.")
        formatted = _format_documents(docs)
        if not formatted:
            raise ValueError("Search returned results but failed to format.")
        return "\n\n---\n\n".join(formatted)

    async def _you_web_search(question: str) -> str:
        """Retrieves relevant contexts from web search (using You.com) for the given question.

        Args:
            question (str): The question to be answered.

        Returns:
            str: The web search results containing relevant documents and their URLs.
        """
        return await _run_with_retries(
            "Web search",
            _fetch,
            question,
            max_retries=tool_config.max_retries,
            timeout=None,  # timeout applied inside _fetch
            cache=_cache,
        )

    yield FunctionInfo.from_fn(_you_web_search, description=_you_web_search.__doc__)


@register_function(config_type=YouFinanceResearchToolConfig)
async def you_finance_research(tool_config: YouFinanceResearchToolConfig, builder: Builder):
    api_key = _resolve_api_key(tool_config)

    if not api_key:
        _warn_missing_key_once("finance research")
        yield _make_stub("Finance research")
        return

    finance_tool = YouFinanceResearchTool(
        api_wrapper={
            "ydc_api_key": api_key,
            "research_effort": tool_config.research_effort.value,
        }
    )
    _cache: dict[str, str] = {}

    async def _you_finance_research(question: str) -> str:
        """Answers financial questions using the You.com Finance Research API.

        Searches a finance-optimized index covering SEC filings, earnings, equity
        prices, macro indicators, and financial news. Returns a cited markdown response.

        Args:
            question (str): The financial question to research.

        Returns:
            str: Markdown answer with cited sources.
        """
        return await _run_with_retries(
            "Finance research",
            finance_tool.api_wrapper.finance_text_async,
            question,
            max_retries=tool_config.max_retries,
            timeout=tool_config.timeout,
            cache=_cache,
        )

    yield FunctionInfo.from_fn(_you_finance_research, description=_you_finance_research.__doc__)


@register_function(config_type=YouResearchToolConfig)
async def you_research(tool_config: YouResearchToolConfig, builder: Builder):
    api_key = _resolve_api_key(tool_config)

    if not api_key:
        _warn_missing_key_once("research")
        yield _make_stub("Research")
        return

    research_tool = YouResearchTool(
        api_wrapper={
            "ydc_api_key": api_key,
            "research_effort": tool_config.research_effort.value,
        }
    )
    _cache: dict[str, str] = {}

    async def _you_research(question: str) -> str:
        """Answers open-domain questions using the You.com Research API.

        Synthesizes a cited markdown answer from live web sources.

        Args:
            question (str): The question to research.

        Returns:
            str: Markdown answer with cited sources.
        """
        return await _run_with_retries(
            "Research",
            research_tool.api_wrapper.research_text_async,
            question,
            max_retries=tool_config.max_retries,
            timeout=tool_config.timeout,
            cache=_cache,
        )

    yield FunctionInfo.from_fn(_you_research, description=_you_research.__doc__)


@register_function(config_type=YouContentsToolConfig)
async def you_contents(tool_config: YouContentsToolConfig, builder: Builder):
    api_key = _resolve_api_key(tool_config)

    if not api_key:
        _warn_missing_key_once("contents")

        async def _stub(urls: list[str]) -> str:
            return _stub_message("Contents API")

        _stub.__doc__ = "Contents API (unavailable - missing YDC_API_KEY)."
        yield FunctionInfo.from_fn(_stub, description=_stub.__doc__)
        return

    contents_tool = YouContentsTool(api_wrapper={"ydc_api_key": api_key})
    _cache: dict[str, str] = {}

    async def _you_contents(urls: list[str]) -> str:
        """Extracts clean content from web pages using the You.com Contents API.

        Fetches up to 10 URLs in parallel and returns their content as Markdown,
        HTML, or metadata — ready for LLM consumption, no HTML parsing required.

        Args:
            urls (list[str]): List of URLs to extract content from (max 10).

        Returns:
            str: Extracted page contents formatted as Documents.
        """

        async def _fetch(_cache_key: str) -> str:
            formats = [f.value for f in tool_config.formats]
            docs = await contents_tool.api_wrapper.contents_async(
                urls,
                formats=formats,
                crawl_timeout=tool_config.crawl_timeout,
            )
            if not docs:
                raise ValueError("Contents API returned no results.")

            parts = []
            for doc in docs:
                url = doc.metadata.get("url", "")
                title = doc.metadata.get("title", "")
                parts.append(f'<Document href="{url}">\n<title>\n{title}\n</title>\n{doc.page_content}\n</Document>')
            return "\n\n---\n\n".join(parts)

        return await _run_with_retries(
            "Contents API",
            _fetch,
            str(sorted(urls)),
            max_retries=tool_config.max_retries,
            timeout=tool_config.timeout,
            cache=_cache,
        )

    yield FunctionInfo.from_fn(_you_contents, description=_you_contents.__doc__)

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

import asyncio
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import AsyncGenerator
from typing import Literal

from pydantic import Field
from pydantic import SecretStr

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

_missing_key_warned = False


class BraveWebSearchToolConfig(FunctionBaseConfig, name="brave_web_search"):
    """
    Tool that retrieves relevant contexts from web search (using Brave Search) for the given question.
    Requires a BRAVE_API_KEY environment variable or api_key config.
    """

    max_results: int = Field(default=5, ge=1, le=20, description="Maximum number of web results to return")
    api_key: SecretStr | None = Field(default=None, description="The subscription token for Brave Search API")
    max_retries: int = Field(default=3, ge=1, description="Maximum number of retries for the search request")
    country: str = Field(default="US", description="Two-character country code for search results")
    search_lang: str = Field(default="en", description="Language code for search results")
    safesearch: Literal["off", "moderate", "strict"] = Field(
        default="moderate",
        description="Adult-content filtering mode",
    )
    freshness: str | None = Field(
        default=None,
        description="Optional page-age filter such as pd, pw, pm, py, or YYYY-MM-DDtoYYYY-MM-DD",
    )
    timeout: float = Field(default=20.0, gt=0, description="HTTP request timeout in seconds")
    max_content_length: int | None = Field(
        default=10000,
        description="Max characters per result snippet. If set, truncates each result to reduce token usage.",
    )


def _http_get_json(url: str, headers: dict[str, str], timeout: float) -> dict:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{e.code} {e.reason}: {error_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(str(e.reason)) from e

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        raise ValueError("Search returned invalid JSON") from e

    if not isinstance(payload, dict):
        raise ValueError(f"Search returned unexpected response type: {type(payload).__name__}")
    return payload


def _truncate_content(content: str, max_content_length: int | None) -> str:
    if max_content_length and len(content) > max_content_length:
        return content[: max_content_length - 3] + "..."
    return content


def _render_document(result: dict, max_content_length: int | None) -> str:
    url = result.get("url", "") or ""
    title = result.get("title", "") or ""
    snippets: list[str] = []
    description = result.get("description") or result.get("snippet") or ""
    if description:
        snippets.append(str(description))
    extra_snippets = result.get("extra_snippets") or []
    if isinstance(extra_snippets, list):
        snippets.extend(str(snippet) for snippet in extra_snippets if snippet)
    body = _truncate_content("\n".join(snippets), max_content_length)
    return f'<Document href="{url}">\n<title>\n{title}\n</title>\n{body}\n</Document>'


@register_function(config_type=BraveWebSearchToolConfig)
async def brave_web_search(
    tool_config: BraveWebSearchToolConfig,
    builder: Builder,
) -> AsyncGenerator[FunctionInfo, None]:
    """Register the Brave Search API web search tool with NAT."""

    if not os.environ.get("BRAVE_API_KEY") and tool_config.api_key:
        os.environ["BRAVE_API_KEY"] = tool_config.api_key.get_secret_value()

    if not os.environ.get("BRAVE_API_KEY"):
        global _missing_key_warned
        if not _missing_key_warned:
            logger.warning(
                "BRAVE_API_KEY not found. The Brave web search tool will be registered but will "
                "return an error when called. To enable: set BRAVE_API_KEY in your environment, "
                ".env file, or specify api_key in your workflow config."
            )
            _missing_key_warned = True

        async def _brave_web_search_stub(question: str) -> str:
            """Brave web search tool (unavailable - missing BRAVE_API_KEY)."""
            return (
                "Error: Brave web search is unavailable because BRAVE_API_KEY is not set.\n"
                "To enable this tool:\n"
                "1. Get a subscription token from https://api.search.brave.com/\n"
                "2. Set the API key in your environment or in your .env file\n"
                "3. Restart the application"
            )

        yield FunctionInfo.from_fn(
            _brave_web_search_stub,
            description=_brave_web_search_stub.__doc__,
        )
        return

    async def _brave_web_search(question: str) -> str:
        """Retrieves relevant contexts from web search (using Brave Search) for the given question.

        Args:
            question (str): The question to be answered. Will be truncated to 400 characters if longer.

        Returns:
            str: The web search results containing relevant documents and their URLs.
        """
        if len(question) > 400:
            question = question[:397] + "..."

        params = {
            "q": question,
            "count": str(tool_config.max_results),
            "country": tool_config.country,
            "search_lang": tool_config.search_lang,
            "safesearch": tool_config.safesearch,
            "text_decorations": "false",
            "spellcheck": "true",
        }
        if tool_config.freshness:
            params["freshness"] = tool_config.freshness

        url = f"{BRAVE_SEARCH_URL}?{urllib.parse.urlencode(params)}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "aiq-brave-web-search/1.0",
            "X-Subscription-Token": os.environ["BRAVE_API_KEY"],
        }

        for attempt in range(tool_config.max_retries):
            try:
                payload = await asyncio.to_thread(_http_get_json, url, headers, tool_config.timeout)
                web_payload = payload.get("web") or {}
                results = web_payload.get("results") if isinstance(web_payload, dict) else None
                if not isinstance(results, list):
                    raise ValueError("Search returned no web results")
                if not results:
                    raise ValueError("Search returned no results")

                web_search_results = "\n\n---\n\n".join(
                    _render_document(result, tool_config.max_content_length)
                    for result in results[: tool_config.max_results]
                    if isinstance(result, dict)
                )
                return web_search_results if web_search_results else "Search returned no results"

            except Exception as e:
                if attempt == tool_config.max_retries - 1:
                    error_msg = str(e)
                    if isinstance(e, ValueError):
                        return error_msg
                    if "401" in error_msg or "Unauthorized" in error_msg:
                        return (
                            "Error: Brave web search failed due to invalid API key (401 Unauthorized).\n"
                            "Please check your BRAVE_API_KEY and ensure it is valid.\n"
                        )
                    if "429" in error_msg:
                        return "Error: Brave web search failed because the Brave Search API rate limit was exceeded.\n"
                    return f"Error: Brave web search failed - {error_msg}"
                await asyncio.sleep(2**attempt)

        return "Error: Search failed after all retries"

    yield FunctionInfo.from_fn(
        _brave_web_search,
        description=_brave_web_search.__doc__,
    )

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

from pydantic import Field
from pydantic import SecretStr

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)

TINYFISH_SEARCH_URL = "https://api.search.tinyfish.ai"

_missing_key_warned = False


class TinyfishWebSearchToolConfig(FunctionBaseConfig, name="tinyfish_web_search"):
    """
    Tool that retrieves relevant contexts from web search (using TinyFish Search) for the given question.
    Requires a TINYFISH_API_KEY environment variable or api_key config.
    """

    max_results: int = Field(default=5, ge=1, description="Maximum number of search results to return")
    api_key: SecretStr | None = Field(default=None, description="The API key for the TinyFish service")
    max_retries: int = Field(default=3, ge=1, description="Maximum number of retries for the search request")
    location: str = Field(default="US", description="Country code for geo-targeted results")
    language: str = Field(default="en", description="Language code for result language")
    page: int = Field(default=0, ge=0, le=10, description="Search result page number, starting from 0")
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
    site_name = result.get("site_name") or ""
    snippet = result.get("snippet") or result.get("description") or ""
    body_parts = [str(part) for part in (site_name, snippet) if part]
    body = _truncate_content("\n".join(body_parts), max_content_length)
    return f'<Document href="{url}">\n<title>\n{title}\n</title>\n{body}\n</Document>'


@register_function(config_type=TinyfishWebSearchToolConfig)
async def tinyfish_web_search(
    tool_config: TinyfishWebSearchToolConfig,
    builder: Builder,
) -> AsyncGenerator[FunctionInfo, None]:
    """Register the TinyFish Search API web search tool with NAT."""

    if not os.environ.get("TINYFISH_API_KEY") and tool_config.api_key:
        os.environ["TINYFISH_API_KEY"] = tool_config.api_key.get_secret_value()

    if not os.environ.get("TINYFISH_API_KEY"):
        global _missing_key_warned
        if not _missing_key_warned:
            logger.warning(
                "TINYFISH_API_KEY not found. The TinyFish web search tool will be registered but will "
                "return an error when called. To enable: set TINYFISH_API_KEY in your environment, "
                ".env file, or specify api_key in your workflow config."
            )
            _missing_key_warned = True

        async def _tinyfish_web_search_stub(question: str) -> str:
            """TinyFish web search tool (unavailable - missing TINYFISH_API_KEY)."""
            return (
                "Error: TinyFish web search is unavailable because TINYFISH_API_KEY is not set.\n"
                "To enable this tool:\n"
                "1. Get an API key from https://agent.tinyfish.ai/api-keys\n"
                "2. Set the API key in your environment or in your .env file\n"
                "3. Restart the application"
            )

        yield FunctionInfo.from_fn(
            _tinyfish_web_search_stub,
            description=_tinyfish_web_search_stub.__doc__,
        )
        return

    async def _tinyfish_web_search(question: str) -> str:
        """Retrieves relevant contexts from web search (using TinyFish Search) for the given question.

        Args:
            question (str): The question to be answered.

        Returns:
            str: The web search results containing relevant documents and their URLs.
        """
        params = {
            "query": question,
            "location": tool_config.location,
            "language": tool_config.language,
            "page": str(tool_config.page),
        }

        url = f"{TINYFISH_SEARCH_URL}?{urllib.parse.urlencode(params)}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "aiq-tinyfish-web-search/1.0",
            "X-API-Key": os.environ["TINYFISH_API_KEY"],
        }

        for attempt in range(tool_config.max_retries):
            try:
                payload = await asyncio.to_thread(_http_get_json, url, headers, tool_config.timeout)
                results = payload.get("results")
                if not isinstance(results, list):
                    raise ValueError("Search returned no results")
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
                            "Error: TinyFish web search failed due to invalid API key (401 Unauthorized).\n"
                            "Please check your TINYFISH_API_KEY and ensure it is valid.\n"
                        )
                    if "429" in error_msg:
                        return (
                            "Error: TinyFish web search failed because the TinyFish Search API "
                            "rate limit was exceeded.\n"
                        )
                    return f"Error: TinyFish web search failed - {error_msg}"
                await asyncio.sleep(2**attempt)

        return "Error: Search failed after all retries"

    yield FunctionInfo.from_fn(
        _tinyfish_web_search,
        description=_tinyfish_web_search.__doc__,
    )

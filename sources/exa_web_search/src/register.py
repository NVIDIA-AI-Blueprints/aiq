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
from collections.abc import AsyncGenerator
from typing import Literal

from pydantic import Field
from pydantic import SecretStr

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)

_missing_key_warned = False


class ExaWebSearchToolConfig(FunctionBaseConfig, name="exa_web_search"):
    """
    Tool that retrieves relevant contexts from web search (using Exa) for the given question.
    Requires an EXA_API_KEY environment variable or api_key config.
    """

    max_results: int = Field(default=5, description="Maximum number of search results to return")
    api_key: SecretStr | None = Field(default=None, description="The API key for the Exa service")
    max_retries: int = Field(default=3, description="Maximum number of retries for the search request")
    search_type: Literal["auto", "deep", "fast"] = Field(
        default="auto",
        description="Exa search type: 'auto', 'deep', or 'fast'",
    )
    full_text: bool = Field(
        default=False,
        description=(
            "Whether to return full page text for each result. Defaults to False because full text is "
            "expensive in tokens; when False, only highlights and metadata are returned. Set to True to "
            "include full page text (optionally capped by `max_content_length`)."
        ),
    )
    highlights: bool = Field(
        default=True,
        description=(
            "Whether to return highlighted snippets for each result. Highlights are token-efficient and "
            "enabled by default; they are used as the result body when `full_text` is False."
        ),
    )
    max_content_length: int | None = Field(
        default=10000,
        description=(
            "Max characters per result's full page text. Only applied when `full_text=True`; truncates "
            "each result to reduce token usage. Set to None to disable truncation."
        ),
    )


@register_function(config_type=ExaWebSearchToolConfig)
async def exa_web_search(
    tool_config: ExaWebSearchToolConfig,
    builder: Builder,
) -> AsyncGenerator[FunctionInfo, None]:
    """Register the Exa web search tool with NAT.

    Wraps `langchain_exa.ExaSearchResults` in a NAT function so agents can
    query the Exa API. If `EXA_API_KEY` is not available (via environment or
    `tool_config.api_key`), a stub function is registered that returns an
    informative error instead of failing at import time.

    Args:
        tool_config: Configuration controlling result count, retries, search
            type, text inclusion, and optional content truncation.
        builder: NAT builder handle (unused; accepted for interface parity).

    Yields:
        A `FunctionInfo` wrapping either the live Exa search callable or the
        missing-key stub.
    """
    from langchain_exa import ExaSearchResults

    if not os.environ.get("EXA_API_KEY") and tool_config.api_key:
        os.environ["EXA_API_KEY"] = tool_config.api_key.get_secret_value()

    if not os.environ.get("EXA_API_KEY"):
        global _missing_key_warned
        if not _missing_key_warned:
            logger.warning(
                "EXA_API_KEY not found. The web search tool will be registered but will "
                "return an error when called. To enable: set EXA_API_KEY in your environment, "
                ".env file, or specify api_key in your workflow config."
            )
            _missing_key_warned = True

        async def _exa_web_search_stub(question: str) -> str:
            """Web search tool (unavailable - missing EXA_API_KEY)."""
            return (
                "Error: Exa web search is unavailable because EXA_API_KEY is not set.\n"
                "To enable this tool:\n"
                "1. Get an API key from https://exa.ai/\n"
                "2. Set the API key in your environment or in your .env file\n"
                "3. Restart the application"
            )

        yield FunctionInfo.from_fn(
            _exa_web_search_stub,
            description=_exa_web_search_stub.__doc__,
        )
        return

    exa_search = ExaSearchResults()

    async def _exa_web_search(question: str) -> str:
        """Retrieves relevant contexts from web search (using Exa) for the given question.

        Args:
            question (str): The question to be answered. Will be truncated to 400 characters if longer.

        Returns:
            str: The web search results containing relevant documents and their URLs.
        """
        if len(question) > 400:
            question = question[:397] + "..."

        def _truncate_content(content: str) -> str:
            if tool_config.max_content_length and len(content) > tool_config.max_content_length:
                return content[: tool_config.max_content_length - 3] + "..."
            return content

        for attempt in range(tool_config.max_retries):
            try:
                response = await exa_search.ainvoke(
                    {
                        "query": question,
                        "num_results": tool_config.max_results,
                        "type": tool_config.search_type,
                        "text_contents_options": tool_config.full_text,
                        "highlights": tool_config.highlights,
                    }
                )

                if isinstance(response, str):
                    raise ValueError(f"Search returned an error: {response}")

                results = getattr(response, "results", None)
                if results is None and isinstance(response, dict):
                    results = response.get("results")

                if not results:
                    raise ValueError("Search returned no results")

                def _render(doc) -> str:
                    url = getattr(doc, "url", "") or ""
                    title = getattr(doc, "title", "") or ""
                    text = _truncate_content(getattr(doc, "text", "") or "")
                    highlights_list = getattr(doc, "highlights", None) or []
                    body = text if text else "\n".join(highlights_list)
                    return f'<Document href="{url}">\n<title>\n{title}\n</title>\n{body}\n</Document>'

                web_search_results = "\n\n---\n\n".join(_render(doc) for doc in results)
                return web_search_results if web_search_results else "Search returned no results"

            except Exception as e:
                if attempt == tool_config.max_retries - 1:
                    error_msg = str(e)
                    if isinstance(e, ValueError):
                        return error_msg
                    if "401" in error_msg or "Unauthorized" in error_msg:
                        return (
                            "Error: Web search failed due to invalid API key (401 Unauthorized).\n"
                            "Please check your EXA_API_KEY and ensure it is valid.\n"
                        )
                    return f"Error: Web search failed - {error_msg}"
                await asyncio.sleep(2**attempt)

        return "Error: Search failed after all retries"

    yield FunctionInfo.from_fn(
        _exa_web_search,
        description=_exa_web_search.__doc__,
    )

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

from pydantic import Field
from pydantic import SecretStr

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)

# Track if we've already warned about missing API key to avoid duplicate warnings
_missing_key_warned = False


class TavilyWebSearchToolConfig(FunctionBaseConfig, name="tavily_web_search"):
    """
    Tool that retrieves relevant contexts from web search (using Tavily) for the given question.
    Requires a TAVILY_API_KEY environment variable or api_key config.
    """

    include_answer: str = Field(default="advanced", description="Whether to include answers in the search results")
    max_results: int = Field(default=3, description="Maximum number of search results to return")
    api_key: SecretStr | None = Field(default=None, description="The API key for the Tavily service")
    max_retries: int = Field(default=3, description="Maximum number of retries for the search request")
    advanced_search: bool = Field(default=False, description="Whether to use advanced search")
    max_content_length: int | None = Field(
        default=None,
        description="Max characters per result content. If set, truncates each result to reduce token usage.",
    )


@register_function(config_type=TavilyWebSearchToolConfig)
async def tavily_web_search(tool_config: TavilyWebSearchToolConfig, builder: Builder):
    from langchain_tavily import TavilySearch

    if not os.environ.get("TAVILY_API_KEY") and tool_config.api_key:
        os.environ["TAVILY_API_KEY"] = tool_config.api_key.get_secret_value()

    # Check if API key is available
    if not os.environ.get("TAVILY_API_KEY"):
        # Log warning only once to avoid duplicate warnings when multiple tools use Tavily
        global _missing_key_warned
        if not _missing_key_warned:
            logger.warning(
                "TAVILY_API_KEY not found. The web search tool will be registered but will "
                "return an error when called. To enable: set TAVILY_API_KEY in your environment, "
                ".env file, or specify api_key in your workflow config."
            )
            _missing_key_warned = True

        # Yield a stub function that returns an error message
        async def _tavily_web_search_stub(question: str) -> str:
            """Web search tool (unavailable - missing TAVILY_API_KEY)."""
            return (
                "Error: Web search is unavailable because TAVILY_API_KEY is not set.\n"
                "To enable this tool:\n"
                "1. Get an API key from https://tavily.com/\n"
                "2. Set the API key in your environment or in your .env file\n"
                "3. Restart the application"
            )

        yield FunctionInfo.from_fn(
            _tavily_web_search_stub,
            description=_tavily_web_search_stub.__doc__,
        )
        return

    async def _tavily_web_search(question: str) -> str:
        """Retrieves relevant contexts from web search (using Tavily) for the given question.

        Args:
            question (str): The question to be answered. Will be truncated to 400 characters if longer.

        Returns:
            str: The web search results containing relevant documents and their URLs.
        """
        # Tavily API requires queries under 400 characters
        if len(question) > 400:
            question = question[:397] + "..."

        tavily_search = TavilySearch(
            max_results=tool_config.max_results,
            search_depth="advanced" if tool_config.advanced_search else "basic",
            include_answer=tool_config.include_answer,
        )

        def _truncate_content(content: str) -> str:
            """Truncate content if max_content_length is set."""
            if tool_config.max_content_length and len(content) > tool_config.max_content_length:
                return content[: tool_config.max_content_length - 3] + "..."
            return content

        for attempt in range(tool_config.max_retries):
            try:
                search_docs = await tavily_search.ainvoke({"query": question})
                # Handle cases where response is not a dict (e.g., error string from API)
                if isinstance(search_docs, str):
                    raise ValueError(f"Search returned an error: {search_docs}")

                if not isinstance(search_docs, dict):
                    raise ValueError(f"Search returned unexpected response type: {type(search_docs).__name__}")

                # Handle error responses from TavilySearch
                if "error" in search_docs:
                    raise ValueError(f"Search error: {search_docs['error']}")

                if "results" not in search_docs:
                    raise ValueError("Search returned no results")

                results = search_docs.get("results", [])
                if not isinstance(results, list):
                    raise ValueError(f"Tavily API returned unexpected results format: {type(results)}")

                answer_text = ""
                if search_docs.get("answer"):
                    answer_text = f"<Answer>\n{search_docs['answer']}\n</Answer>\n\n---\n\n"

                web_search_results = "\n\n---\n\n".join(
                    [
                        f'<Document href="{doc.get("url", "")}">\n'
                        f"<title>\n{doc.get('title')}\n</title>\n"
                        f"{_truncate_content(doc.get('content') or '')}\n</Document>"
                        for doc in results
                    ]
                )
                combined = answer_text + web_search_results
                return combined if combined else "Search returned no results"

            except Exception as e:
                if attempt == tool_config.max_retries - 1:
                    # On final attempt, return a user-friendly error message
                    error_msg = str(e)
                    if isinstance(e, ValueError):
                        return error_msg
                    if "401" in error_msg or "Unauthorized" in error_msg:
                        return (
                            "Error: Web search failed due to invalid API key (401 Unauthorized).\n"
                            "Please check your TAVILY_API_KEY and ensure it is valid.\n"
                        )
                    elif "error" in error_msg.lower():
                        return f"Error: Web search failed - {error_msg}"
                    else:
                        return f"Error: Web search failed - {error_msg}"
                await asyncio.sleep(2**attempt)

    yield FunctionInfo.from_fn(
        _tavily_web_search,
        description=_tavily_web_search.__doc__,
    )

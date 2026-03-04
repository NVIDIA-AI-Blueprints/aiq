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
import os

from pydantic import Field
from pydantic import SecretStr

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig


class TavilyWebSearchToolConfig(FunctionBaseConfig, name="tavily_web_search"):
    """
    Tool that retrieves relevant contexts from web search (using Tavily) for the given query.
    Requires a TAVILY_API_KEY environment variable or api_key config.
    """

    include_answer: str = Field(default="advanced", description="Whether to include answers in the search results")
    max_results: int = Field(default=3, description="Maximum number of search results to return")
    api_key: SecretStr | None = Field(default=None, description="The API key for the Tavily service")
    max_retries: int = Field(default=3, description="Maximum number of retries for the search request")
    advanced_search: bool = Field(default=True, description="Whether to use advanced search")


@register_function(config_type=TavilyWebSearchToolConfig)
async def tavily_web_search(tool_config: TavilyWebSearchToolConfig, builder: Builder):
    from langchain_tavily import TavilySearch

    if not os.environ.get("TAVILY_API_KEY") and tool_config.api_key:
        os.environ["TAVILY_API_KEY"] = tool_config.api_key.get_secret_value()

    async def _tavily_web_search(query: str) -> str:
        """Retrieves relevant contexts from web search (using Tavily) for the given query.

        Args:
            query (str): The search query. Will be truncated to 400 characters if longer.

        Returns:
            str: The web search results containing relevant documents and their URLs.
        """
        # Tavily API requires queries under 400 characters
        if len(query) > 400:
            query = query[:397] + "..."

        tavily_search = TavilySearch(
            max_results=tool_config.max_results,
            search_depth="advanced" if tool_config.advanced_search else "basic",
            include_answer=tool_config.include_answer,
        )

        for attempt in range(tool_config.max_retries):
            try:
                search_docs = await tavily_search.ainvoke({"query": query})

                # Handle cases where response is not a dict (e.g., error string from API)
                if isinstance(search_docs, str):
                    return f"Search returned an error: {search_docs}"

                if not isinstance(search_docs, dict):
                    return f"Search returned unexpected response type: {type(search_docs).__name__}"

                # Handle error responses from TavilySearch
                if "error" in search_docs:
                    return f"Search error: {search_docs['error']}"

                if "results" not in search_docs:
                    return "Search returned no results"

                answer_text = ""
                if search_docs.get("answer"):
                    answer_text = f"<Answer>\n{search_docs['answer']}\n</Answer>\n\n---\n\n"

                web_search_results = "\n\n---\n\n".join(
                    [
                        f'<Document href="{doc["url"]}">\n'
                        f"<title>\n{doc.get('title')}\n</title>\n"
                        f"{doc['content']}\n</Document>"
                        for doc in search_docs["results"]
                    ]
                )
                combined = answer_text + web_search_results
                return combined if combined else "Search returned no results"
            except Exception:
                if attempt == tool_config.max_retries - 1:
                    raise
                await asyncio.sleep(2**attempt)

    yield FunctionInfo.from_fn(
        _tavily_web_search,
        description=_tavily_web_search.__doc__,
    )

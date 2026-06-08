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

"""NAT register function for the reranked search tool.

Queries multiple search tools in parallel, parses their individual results,
and reranks them using BM25, dense embedding similarity, or cross-encoder scoring.
"""

# from __future__ import annotations

import asyncio
import logging

from langchain_core.documents import Document
from langchain_nvidia_ai_endpoints import NVIDIARerank
from pydantic import BaseModel
from pydantic import Field
from pydantic import create_model

from aiq_agent.common import SOURCE_DELIMITER
from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)


class RerankedSearchConfig(FunctionBaseConfig, name="reranked_search"):
    """Search across multiple tools and rerank the combined results.

    Calls every tool listed in *search_tools* with the same query, splits each
    tool's output into individual items, scores them against the query, and
    returns the top-k results as a formatted string.
    """

    top_k: int = Field(default=5, description="Number of results to return after reranking.")
    search_tools: list[str] = Field(
        default_factory=list,
        description=("Names of search tool instances to fan out to (e.g. ['web_search_tool', 'paper_search_tool'])."),
    )

    cross_encoder_model: str = Field(
        description="Cross-encoder model identifier (e.g. nv-rerank-qa-mistral-4b:1).",
    )

    timeout_seconds: float = Field(
        default=30.0,
        description="Per-tool timeout in seconds.",
    )


@register_function(config_type=RerankedSearchConfig)
async def reranked_search(config: RerankedSearchConfig, builder: Builder):
    """
    A cross-encoder feeds the query–document pair together into a single model pass and outputs a
    relevance score directly.  This is more accurate but slower per document.

    Uses `langchain-nvidia-ai-endpoints` (`NVIDIARerank`).  Expects `NVIDIA_API_KEY` in the environment.
    """
    compressor = NVIDIARerank(model=config.cross_encoder_model, top_n=config.top_k)

    # Resolve tool callables at registration time.
    tool_fns: dict[str, object] = {}
    for name in config.search_tools:
        try:
            tool_fns[name] = await builder.get_function(name)
        except Exception:
            logger.warning("could not add tool '%s' to reranked_search — skipping", name)

    if len(tool_fns) == 0:
        logger.warning("reranked_search: no search tools added; tool will return empty results.")

    async def _call_tool(name: str, fn: object, query: BaseModel) -> list[str]:
        """Call a single search tool and parse its output into results."""
        try:
            raw: str = await asyncio.wait_for(fn.ainvoke(query), timeout=config.timeout_seconds)
            results_with_answer: list[str] = raw.split(SOURCE_DELIMITER)
            results: list[str] = []
            # We don't want an "answer" section in the results, so we filter it out.
            for result in results_with_answer:
                if not result.startswith("<Answer>"):
                    results.append(result)
            if len(results) == 1:
                logger.warning("SOURCE_DELIMITER not found in tool '%s' output", name)
            return results
        except TimeoutError:
            logger.warning("tool '%s' timed out after %.0fs", name, config.timeout_seconds)
            return []
        except Exception:
            logger.exception("tool '%s' failed", name)
            return []

    RerankedSearchInput = create_model(
        "RerankedSearchInput",
        overall_query=(str, Field(description="The overarching search query for this reranked search request.")),
        **{name: (fn.input_schema, ...) for name, fn in tool_fns.items()},
    )

    # the query parameter is a pydantic model. It's a nested structure, dynamically
    # created above based on search tools' input schemas.
    async def _reranked_search(input: RerankedSearchInput) -> str:
        """Search across multiple data sources and return results reranked by relevance.

        Fans out the query to all configured search tools in parallel, merges
        results, and reranks them so the most relevant items appear first.

        Args:
            query (str): The search query.

        Returns:
            str: Reranked search results formatted for LLM consumption.
        """
        # Fan out to all tools concurrently.
        coros = [_call_tool(name, fn, input.__getattribute__(name)) for name, fn in tool_fns.items()]
        per_tool_results = await asyncio.gather(*coros)

        all_results = []
        for results in per_tool_results:
            all_results.extend(results)
        logger.info(f"{len(all_results)} results found across all search tools.")

        if not all_results:
            return "No results found across any search tool."

        # Rerank. Use the overall_query for reranking purposes.
        documents = [Document(page_content=r) for r in all_results]
        reranked_docs = await compressor.acompress_documents(query=input.overall_query, documents=documents)
        ranked_contents: list[str] = [doc.page_content for doc in reranked_docs]

        return f"Top {len(ranked_contents)} results ranked by relevance:\n" + SOURCE_DELIMITER.join(ranked_contents)

    yield FunctionInfo.from_fn(
        _reranked_search,
        description=_reranked_search.__doc__,
    )

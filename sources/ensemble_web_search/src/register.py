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

import os

from pydantic import Field
from pydantic import SecretStr

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

from .ensemble_search import EnsembleSearchTool


class EnsembleWebSearchToolConfig(FunctionBaseConfig, name="ensemble_web_search"):
    """
    Ensemble search tool that combines You.com Deep Search and Tavily in parallel.
    Returns unified <Document> XML results from both backends with source attribution.
    Requires YOU_API_KEY and TAVILY_API_KEY environment variables or config.
    """

    you_api_key: SecretStr | None = Field(default=None, description="The API key for the You.com service")
    tavily_api_key: SecretStr | None = Field(default=None, description="The API key for the Tavily service")
    search_effort: str = Field(
        default="medium",
        description='You.com Deep Search depth: "low" (fast), "medium" (balanced), "high" (thorough).',
    )
    tavily_max_results: int = Field(default=5, description="Maximum number of Tavily search results")
    tavily_advanced: bool = Field(default=True, description="Use Tavily advanced search depth")
    max_retries: int = Field(default=5, description="Maximum number of retries per backend")
    timeout: int = Field(default=2000, description="You.com Deep Search timeout in seconds")


@register_function(config_type=EnsembleWebSearchToolConfig)
async def ensemble_web_search(tool_config: EnsembleWebSearchToolConfig, builder: Builder):
    """Register ensemble web search tool (You.com Deep Search + Tavily)."""

    if not os.environ.get("YOU_API_KEY") and tool_config.you_api_key:
        os.environ["YOU_API_KEY"] = tool_config.you_api_key.get_secret_value()
    if not os.environ.get("TAVILY_API_KEY") and tool_config.tavily_api_key:
        os.environ["TAVILY_API_KEY"] = tool_config.tavily_api_key.get_secret_value()

    you_api_key = os.environ.get("YOU_API_KEY")
    if not you_api_key:
        raise ValueError("YOU_API_KEY not found. Please set it in environment or config.")
    tavily_api_key = os.environ.get("TAVILY_API_KEY")
    if not tavily_api_key:
        raise ValueError("TAVILY_API_KEY not found. Please set it in environment or config.")

    tool = EnsembleSearchTool(
        you_api_key=you_api_key,
        tavily_api_key=tavily_api_key,
        search_effort=tool_config.search_effort,
        tavily_max_results=tool_config.tavily_max_results,
        tavily_advanced=tool_config.tavily_advanced,
        max_retries=tool_config.max_retries,
        timeout=tool_config.timeout,
    )

    async def _ensemble_web_search(query: str) -> str:
        """Searches the web using both You.com Deep Search and Tavily in parallel.

        Returns results from both backends in unified <Document> XML format.
        Deep Search provides a comprehensive synthesized analysis; Tavily provides
        raw web documents. Use both to cross-reference and verify findings.
        Results are tagged with source="you_deep_search" or source="tavily".

        Args:
            query (str): The search query to investigate.

        Returns:
            str: Merged search results from both backends as XML documents.
        """
        return await tool.search(query)

    yield FunctionInfo.from_fn(
        _ensemble_web_search,
        description=_ensemble_web_search.__doc__,
    )

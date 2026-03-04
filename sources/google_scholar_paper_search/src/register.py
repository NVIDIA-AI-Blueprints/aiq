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

"""NAT register function for Google Scholar paper search tool."""

import os

from pydantic import Field
from pydantic import SecretStr

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

from .paper_search import PaperSearchTool


class PaperSearchToolConfig(FunctionBaseConfig, name="paper_search"):
    """
    Configuration for the paper search tool.

    Tool that searches for academic papers using Google Scholar (Serper).
    Requires a SERPER_API_KEY environment variable or config.
    """

    timeout: int = Field(
        default=30,
        description="Timeout in seconds for the search requests",
    )
    max_results: int = Field(
        default=10,
        description="Maximum number of search results to return",
    )
    serper_api_key: SecretStr | None = Field(
        default=None,
        description="The API key for Serper (Google Scholar)",
    )


@register_function(config_type=PaperSearchToolConfig)
async def paper_search(tool_config: PaperSearchToolConfig, builder: Builder):
    """Register paper search tool using Google Scholar (Serper)."""
    # Set environment variable if provided in config
    if not os.environ.get("SERPER_API_KEY") and tool_config.serper_api_key:
        os.environ["SERPER_API_KEY"] = tool_config.serper_api_key.get_secret_value()

    serper_api_key = os.environ.get("SERPER_API_KEY")
    if not serper_api_key:
        raise ValueError("SERPER_API_KEY not found. Please set it in environment or config.")

    # Create the NAT-independent tool instance
    tool = PaperSearchTool(
        serper_api_key=serper_api_key,
        timeout=tool_config.timeout,
        max_results=tool_config.max_results,
    )

    async def _paper_search(
        query: str,
        year: str | int | None = None,
    ) -> str:
        """Searches for peer-reviewed academic papers and scientific publications.

        This tool returns papers from Google Scholar with citations, abstracts,
        and links for research queries requiring authoritative, scholarly sources
        including: scientific concepts, algorithms, methodologies, technical
        foundations, theoretical frameworks, empirical studies, and peer-reviewed
        evidence.
        """
        if isinstance(year, int):
            year = str(year)
        return await tool.search(query, year)

    yield FunctionInfo.from_fn(
        _paper_search,
        description=_paper_search.__doc__,
    )

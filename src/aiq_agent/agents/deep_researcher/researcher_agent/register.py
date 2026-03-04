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

"""NAT register function for researcher agent."""

import logging

from pydantic import Field

from aiq_agent.common import VerboseTraceCallback
from aiq_agent.common import is_verbose
from nat.builder.builder import Builder
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.component_ref import FunctionGroupRef
from nat.data_models.component_ref import FunctionRef
from nat.data_models.component_ref import LLMRef
from nat.data_models.function import FunctionBaseConfig

from .agent import ResearcherAgentImpl

logger = logging.getLogger(__name__)


class ResearcherAgentConfig(FunctionBaseConfig, name="researcher_agent"):
    """Configuration for the researcher agent.

    The researcher agent dispatches to 5 analytical specialists:
    1. Evidence Gatherer: facts, statistics, specific numbers
    2. Mechanism Explorer: causal explanations, "why/how"
    3. Comparator: head-to-head data, benchmarks, rankings
    4. Critic: counterarguments, limitations, failure cases
    5. Horizon Scanner: recent developments, trends, predictions
    """

    llm: LLMRef = Field(..., description="LLM for coordinator and all sub-researchers")
    rewriter_llm: LLMRef | None = Field(
        default=None,
        description="Optional LLM for brief refinement.",
    )
    tools: list[FunctionRef | FunctionGroupRef] = Field(
        default_factory=list,
        description="Search tools available to sub-researchers",
    )
    verbose: bool = Field(default=True)
    timeout: int = Field(default=1200, description="Timeout in seconds. 0 = no timeout.")
    description: str = Field(
        default="Multi-specialist research: evidence, mechanisms, comparisons, critique, trends",
        description="Tool description visible to the orchestrator LLM",
    )


@register_function(config_type=ResearcherAgentConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def researcher_agent(config: ResearcherAgentConfig, builder: Builder):
    """Researcher agent that can be used as a tool by the orchestrator."""
    llm = await builder.get_llm(config.llm, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
    search_tools = await builder.get_tools(tool_names=config.tools, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

    rewriter_llm = None
    if config.rewriter_llm:
        rewriter_llm = await builder.get_llm(config.rewriter_llm, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

    verbose = is_verbose(config.verbose)
    callbacks = [VerboseTraceCallback()] if verbose else []

    agent = ResearcherAgentImpl(
        llm=llm,
        tools=search_tools,
        rewriter_llm=rewriter_llm,
        verbose=verbose,
        callbacks=callbacks,
        timeout=config.timeout,
    )

    async def _run(query: str) -> str:
        """Research the given topic using specialist sub-researchers.

        Args:
            query: A focused research brief describing what information is needed,
                   what depth is expected, and what a good answer looks like.

        Returns:
            A unified research brief with synthesized findings, inline citations,
            and a merged Sources section.
        """
        return await agent.run(query)

    yield FunctionInfo.from_fn(_run, description=config.description)

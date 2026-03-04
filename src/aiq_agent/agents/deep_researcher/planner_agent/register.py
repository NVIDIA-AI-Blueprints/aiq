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

"""NAT register function for planner agent."""

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

from .agent import PlannerAgentImpl

logger = logging.getLogger(__name__)


class PlannerAgentConfig(FunctionBaseConfig, name="planner_agent"):
    """Configuration for the planner agent.

    The planner agent runs two sequential phases:
    1. Scout: landscape discovery (broad search, term clarity, assumption surfacing)
    2. Architect: structure design (TOC, diverse queries, constraints)
    """

    llm: LLMRef = Field(..., description="LLM for planner coordinator and sub-planners")
    tools: list[FunctionRef | FunctionGroupRef] = Field(
        default_factory=list,
        description="Search tools available to sub-planners (e.g., ensemble_web_search, paper_search)",
    )
    verbose: bool = Field(default=True)
    timeout: int = Field(default=1800, description="Timeout in seconds. 0 = no timeout.")
    description: str = Field(
        default="Two-phase research planning: landscape discovery then structural design",
        description="Tool description visible to the orchestrator LLM",
    )


@register_function(config_type=PlannerAgentConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def planner_agent(config: PlannerAgentConfig, builder: Builder):
    """Planner agent that can be used as a tool by the orchestrator."""
    llm = await builder.get_llm(config.llm, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
    search_tools = await builder.get_tools(tool_names=config.tools, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

    verbose = is_verbose(config.verbose)
    callbacks = [VerboseTraceCallback()] if verbose else []

    agent = PlannerAgentImpl(
        llm=llm,
        tools=search_tools,
        verbose=verbose,
        callbacks=callbacks,
        timeout=config.timeout,
    )

    async def _run(query: str) -> str:
        """Create a research plan for the given query.

        Args:
            query: The user's research request to plan for.

        Returns:
            A JSON string containing the complete research plan with task analysis,
            TOC, constraints, and queries.
        """
        return await agent.run(query)

    yield FunctionInfo.from_fn(_run, description=config.description)

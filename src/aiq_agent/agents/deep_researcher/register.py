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

"""NAT register function for deep research agent (orchestrator).

The orchestrator receives planner_agent and researcher_agent as tools via
builder.get_tools(). These are independent @register_function NAT functions
configured in YAML.
"""

import logging

from langchain_core.messages import HumanMessage
from pydantic import Field

from aiq_agent.common import LLMProvider
from aiq_agent.common import LLMRole
from aiq_agent.common import VerboseTraceCallback
from aiq_agent.common import _create_chat_response
from aiq_agent.common import filter_tools_by_sources
from aiq_agent.common import is_verbose
from nat.builder.builder import Builder
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.component_ref import FunctionGroupRef
from nat.data_models.component_ref import FunctionRef
from nat.data_models.component_ref import LLMRef
from nat.data_models.function import FunctionBaseConfig

from .agent import DeepResearcherAgent
from .models import DeepResearchAgentState

logger = logging.getLogger(__name__)


class DeepResearchAgentConfig(FunctionBaseConfig, name="deep_research_agent"):
    """Configuration for the deep research agent (orchestrator).

    The orchestrator's tools list should include planner_agent and researcher_agent
    as FunctionRef entries. These are resolved by builder.get_tools() into
    StructuredTool objects that the orchestrator LLM can call directly.
    """

    orchestrator_llm: LLMRef = Field(..., description="LLM for the orchestrator")
    rewriter_llm: LLMRef | None = Field(
        default=None,
        description="Optional LLM for post-report refinement.",
    )
    tools: list[FunctionRef | FunctionGroupRef] = Field(
        default_factory=list,
        description="Tools for the orchestrator — should include planner_agent and researcher_agent",
    )
    max_loops: int = Field(default=2)
    verbose: bool = Field(default=True)
    timeout: int = Field(default=600, description="Per-question timeout in seconds. 0 = no timeout.")


@register_function(config_type=DeepResearchAgentConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def deep_research_agent(config: DeepResearchAgentConfig, builder: Builder):
    """Deep research agent using three-tier architecture."""
    # Get all tools — includes planner_agent and researcher_agent as StructuredTools
    tools = await builder.get_tools(tool_names=config.tools, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
    llm = await builder.get_llm(config.orchestrator_llm, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

    rewriter_llm = None
    if config.rewriter_llm:
        rewriter_llm = await builder.get_llm(config.rewriter_llm, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

    provider = LLMProvider()
    provider.set_default(llm)
    provider.configure(LLMRole.ORCHESTRATOR, llm)

    verbose = is_verbose(config.verbose)
    callbacks = [VerboseTraceCallback()] if verbose else []

    agent = DeepResearcherAgent(
        llm_provider=provider,
        tools=tools,
        rewriter_llm=rewriter_llm,
        max_loops=config.max_loops,
        verbose=verbose,
        callbacks=callbacks,
        timeout=config.timeout,
    )

    async def _run(state: DeepResearchAgentState) -> DeepResearchAgentState:
        """Run deep research with a list of messages or payload."""
        data_sources = state.data_sources
        selected_tools = filter_tools_by_sources(tools, data_sources)
        active_agent = agent
        if data_sources is not None and selected_tools != tools:
            active_agent = DeepResearcherAgent(
                llm_provider=provider,
                tools=selected_tools,
                max_loops=config.max_loops,
                verbose=verbose,
                callbacks=callbacks,
                timeout=config.timeout,
            )
        elif data_sources is not None and not selected_tools:
            logger.warning("Deep research received data_sources with no matching tools")

        result = await active_agent.run(state)
        return result

    yield FunctionInfo.from_fn(_run, description="Deep research agent for comprehensive multi-phase research.")


########################################################
# Deep Research Workflow (Wrapper for Evaluation)
########################################################
class DeepResearchWorkflowConfig(FunctionBaseConfig, name="deep_research_workflow"):
    """Configuration for the deep research workflow wrapper.

    This wrapper accepts a string query and converts it to messages
    for the deep_research_agent. Use this as the workflow for evaluation.
    """

    pass


@register_function(config_type=DeepResearchWorkflowConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def deep_research_workflow(config: DeepResearchWorkflowConfig, builder: Builder):
    """Wrapper workflow that accepts string queries for evaluation."""
    deep_research_agent_fn = await builder.get_function("deep_research_agent")

    async def _run(query: str) -> str:
        """Run deep research on a query string."""
        state = DeepResearchAgentState(messages=[HumanMessage(content=query)])
        result = await deep_research_agent_fn.ainvoke(state)
        response_content = result.messages[-1].content
        return _create_chat_response(response_content, response_id="research_response")

    yield FunctionInfo.from_fn(_run, description="Deep research workflow for evaluation (accepts string query).")

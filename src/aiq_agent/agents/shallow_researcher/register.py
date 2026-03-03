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

"""NAT register function for shallow research agent."""

import logging

from langchain_core.messages import HumanMessage
from pydantic import Field

from aiq_agent.common import LLMProvider
from aiq_agent.common import VerboseTraceCallback
from aiq_agent.common import _create_chat_response
from aiq_agent.common import filter_tools_by_sources
from aiq_agent.common import is_verbose
from nat.builder.builder import Builder
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.api_server import ChatResponse
from nat.data_models.component_ref import FunctionGroupRef
from nat.data_models.component_ref import FunctionRef
from nat.data_models.component_ref import LLMRef
from nat.data_models.function import FunctionBaseConfig

from .agent import ShallowResearcherAgent
from .models import ShallowResearchAgentState

logger = logging.getLogger(__name__)


class ShallowResearchAgentConfig(FunctionBaseConfig, name="shallow_research_agent"):
    """Configuration for the shallow research agent."""

    llm: LLMRef = Field(..., description="LLM to use")
    tools: list[FunctionRef | FunctionGroupRef] = Field(default_factory=list, description="Tools to use")
    max_llm_turns: int = Field(default=10, description="Maximum number of LLM turns")
    max_tool_iterations: int = Field(default=5, description="Maximum tool-calling iterations before forcing synthesis")
    verbose: bool = Field(default=False, description="Whether to enable verbose logging")


@register_function(config_type=ShallowResearchAgentConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def shallow_research_agent(config: ShallowResearchAgentConfig, builder: Builder):
    """Shallow research agent with tool-calling capabilities."""
    llm = await builder.get_llm(config.llm, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
    tools = await builder.get_tools(tool_names=config.tools, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

    provider = LLMProvider()
    provider.set_default(llm)

    verbose = is_verbose(config.verbose)
    callbacks = [VerboseTraceCallback()] if verbose else []

    agent = ShallowResearcherAgent(
        llm_provider=provider,
        tools=tools,
        max_llm_turns=config.max_llm_turns,
        max_tool_iterations=config.max_tool_iterations,
        callbacks=callbacks,
    )

    async def _run(state: ShallowResearchAgentState) -> ShallowResearchAgentState:
        try:
            data_sources = state.data_sources
            selected_tools = filter_tools_by_sources(tools, data_sources)
            active_agent = agent
            if data_sources is not None and selected_tools != tools:
                active_agent = ShallowResearcherAgent(
                    llm_provider=provider,
                    tools=selected_tools,
                    max_llm_turns=config.max_llm_turns,
                    max_tool_iterations=config.max_tool_iterations,
                    callbacks=callbacks,
                )
            elif data_sources is not None and not selected_tools:
                logger.warning("Shallow research received data_sources with no matching tools")

            # Validate tool availability before starting shallow research
            # At least one tool must be available
            # This prevents the agent from trying to reason about unavailable tools
            # Check selected_tools directly - they already reflect data_sources filtering
            from aiq_agent.common import format_tool_unavailability_error
            from aiq_agent.common import validate_tool_availability

            is_valid, _, unavailable_tools = validate_tool_availability(
                selected_tools, research_type="shallow research"
            )

            # Fail if no tools are available
            if not is_valid:
                error_msg = format_tool_unavailability_error("shallow research", unavailable_tools)

                # Return error state with error message - this prevents the agent from running
                from langchain_core.messages import AIMessage

                error_state = ShallowResearchAgentState(messages=state.messages + [AIMessage(content=error_msg)])
                return error_state

            result = await active_agent.run(state)
            return result
        except Exception:
            logger.exception("Error in shallow research execution.")
            raise

    yield FunctionInfo.from_fn(_run, description="Shallow research agent for fast, bounded research.")


########################################################
# Shallow Research Workflow (Wrapper for Evaluation)
########################################################
class ShallowResearchWorkflowConfig(FunctionBaseConfig, name="shallow_research_workflow"):
    """Configuration for the shallow research workflow wrapper.

    This wrapper accepts a string query and converts it to messages
    for the shallow_research_agent. Use this as the workflow for evaluation.
    """

    pass


@register_function(config_type=ShallowResearchWorkflowConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def shallow_research_workflow(config: ShallowResearchWorkflowConfig, builder: Builder):
    """Wrapper workflow that accepts string queries for evaluation."""
    shallow_research_agent_fn = await builder.get_function("shallow_research_agent")

    async def _run(query: str) -> ChatResponse:
        """Run shallow research on a query string."""
        result = await shallow_research_agent_fn.ainvoke(
            ShallowResearchAgentState(messages=[HumanMessage(content=query)])
        )
        response_content = result.messages[-1].content
        return _create_chat_response(response_content, response_id="research_response")

    yield FunctionInfo.from_fn(_run, description="Shallow research workflow for evaluation (accepts string query).")

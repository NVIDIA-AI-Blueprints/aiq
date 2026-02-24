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

"""
NAT register function for the clarifier agent.

This module provides the NAT plugin registration for the ClarifierAgent,
allowing it to be used as a function in NAT workflows. The agent handles
interactive clarification dialogs for deep research queries.

Configuration example in YAML:
    functions:
      clarifier_agent:
        _type: clarifier_agent
        llm: my_llm
        tools:
          - web_search_tool
        max_turns: 3
        verbose: true
"""

import logging

from pydantic import Field

from aiq_agent.common import LLMProvider
from aiq_agent.common import VerboseTraceCallback
from aiq_agent.common import filter_tools_by_sources
from aiq_agent.common import is_verbose
from nat.builder.builder import Builder
from nat.builder.context import Context
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.component_ref import FunctionGroupRef
from nat.data_models.component_ref import FunctionRef
from nat.data_models.component_ref import LLMRef
from nat.data_models.function import FunctionBaseConfig
from nat.data_models.interactive import HumanPromptText

from .agent import ClarifierAgent
from .models import ClarifierAgentState
from .models import ClarifierResult
from .utils import extract_user_response

logger = logging.getLogger(__name__)


class ClarifierConfig(FunctionBaseConfig, name="clarifier_agent"):
    """
    Configuration for the clarifier agent NAT function.

    Attributes:
        llm: Reference to the LLM to use for generating clarification questions.
        tools: List of tool references for context gathering (e.g., web search).
        max_turns: Maximum number of clarification Q&A turns before auto-completing.
        enable_plan_approval: Whether to enable plan preview and approval after clarification.
        max_plan_iterations: Maximum number of plan feedback iterations before auto-approving.
        log_response_max_chars: Maximum characters to log from LLM responses.
        verbose: Whether to enable verbose logging with VerboseTraceCallback.
    """

    llm: LLMRef = Field(..., description="LLM to use for generating questions")
    planner_llm: LLMRef | None = Field(
        default=None,
        description="LLM to use for plan generation. If not specified, uses the main llm.",
    )
    tools: list[FunctionRef | FunctionGroupRef] = Field(
        default_factory=list,
        description="Tools available for clarification context",
    )
    max_turns: int = Field(
        default=3,
        description="Maximum number of clarification Q&A turns",
    )
    enable_plan_approval: bool = Field(
        default=False,
        description="Whether to enable plan preview and approval after clarification",
    )
    max_plan_iterations: int = Field(
        default=10,
        description="Maximum number of plan feedback iterations before auto-approving",
    )
    log_response_max_chars: int = Field(
        default=2000,
        description="Max characters to log from LLM responses",
    )
    verbose: bool = Field(
        default=False,
        description="Whether to enable verbose logging",
    )


@register_function(config_type=ClarifierConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def clarifier_agent(config: ClarifierConfig, builder: Builder):
    """
    NAT function for interactive clarification dialog.

    This function creates and configures a ClarifierAgent instance that handles
    multi-turn clarification dialogs for deep research queries. It uses the
    research_clarification.j2 prompt to ask focused questions and refine the
    research scope before the actual research begins.

    The function:
    1. Obtains the LLM and tools from the NAT builder
    2. Creates a user prompt callback that uses NAT's user interaction manager
    3. Instantiates the ClarifierAgent with the configured parameters
    4. Yields a FunctionInfo that accepts messages and returns updated state

    Args:
        config: ClarifierConfig with LLM reference, tools, and settings.
        builder: NAT Builder for obtaining LLM and tool instances.

    Yields:
        FunctionInfo: A callable that accepts ClarifierAgentState or list[BaseMessage]
            and returns ClarifierAgentState with the clarification dialog results.
    """
    llm = await builder.get_llm(
        config.llm,
        wrapper_type=LLMFrameworkEnum.LANGCHAIN,
    )
    planner_llm = None
    if config.planner_llm is not None:
        planner_llm = await builder.get_llm(
            config.planner_llm,
            wrapper_type=LLMFrameworkEnum.LANGCHAIN,
        )
    tools = await builder.get_tools(
        tool_names=config.tools,
        wrapper_type=LLMFrameworkEnum.LANGCHAIN,
    )

    provider = LLMProvider()
    provider.set_default(llm)

    verbose = is_verbose(config.verbose)
    callbacks = [VerboseTraceCallback(log_reasoning=True, max_chars=config.log_response_max_chars)] if verbose else []

    async def user_prompt_callback(question: str) -> str:
        """
        NAT-specific callback for prompting user input.

        Uses NAT's Context and user_interaction_manager to display the
        clarification question and collect the user's response.

        Args:
            question: The clarification question to display to the user.

        Returns:
            The user's response text, extracted from the NAT response object.
        """
        nat_context = Context.get()
        user_input_manager = nat_context.user_interaction_manager

        prompt = HumanPromptText(
            text=question,
            required=True,
            placeholder="Please provide more details...",
        )
        response = await user_input_manager.prompt_user_input(prompt)
        return extract_user_response(response)

    agent = ClarifierAgent(
        llm_provider=provider,
        tools=tools,
        user_prompt_callback=user_prompt_callback,
        max_turns=config.max_turns,
        enable_plan_approval=config.enable_plan_approval,
        max_plan_iterations=config.max_plan_iterations,
        planner_llm=planner_llm,
        log_response_max_chars=config.log_response_max_chars,
        verbose=verbose,
        callbacks=callbacks,
    )

    async def _run(state: ClarifierAgentState) -> ClarifierResult:
        """Run the clarification dialog on the provided chat history.

        Args:
            state: ClarifierAgentState with conversation messages.

        Returns:
            ClarifierResult with clarification log and plan approval details.
        """
        data_sources = state.data_sources
        selected_tools = filter_tools_by_sources(tools, data_sources)
        active_agent = agent
        if data_sources is not None and selected_tools != tools:
            active_agent = ClarifierAgent(
                llm_provider=provider,
                tools=selected_tools,
                user_prompt_callback=user_prompt_callback,
                max_turns=config.max_turns,
                enable_plan_approval=config.enable_plan_approval,
                max_plan_iterations=config.max_plan_iterations,
                planner_llm=planner_llm,
                log_response_max_chars=config.log_response_max_chars,
                verbose=verbose,
                callbacks=callbacks,
            )
        elif data_sources is not None and not selected_tools:
            logger.warning("Clarifier received data_sources with no matching tools")
        return await active_agent.run(state)

    yield FunctionInfo.from_fn(
        _run,
        description=(
            "Handles interactive clarification dialog with users "
            "for deep research queries. Asks follow-up questions and refines the research "
            "scope, constraints, and requirements before planning begins."
        ),
    )

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

"""NAT register function for deep research agent."""

import logging

from langchain_core.messages import HumanMessage
from pydantic import Field

from aiq_agent.common import LLMProvider
from aiq_agent.common import LLMRole
from aiq_agent.common import VerboseTraceCallback
from aiq_agent.common import _create_chat_response
from aiq_agent.common import all_mapped_tools_filtered_out
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

from .agent import DEFAULT_MAX_CONCURRENT_SOURCE_TOOL_CALLS
from .agent import DEFAULT_MAX_RESEARCH_CONCURRENCY
from .agent import DEFAULT_MAX_SOURCE_TOOL_BATCH_SIZE
from .agent import DeepResearcherAgent
from .deepagents_runtime import SandboxConfig
from .deepagents_runtime import SkillsConfig
from .models import DeepResearchAgentState

logger = logging.getLogger(__name__)


class DeepResearchAgentConfig(FunctionBaseConfig, name="deep_research_agent"):
    """Configuration for the deep research agent."""

    orchestrator_llm: LLMRef = Field(..., description="LLM for orchestrator")
    source_router_llm: LLMRef | None = Field(default=None, description="LLM for source-router subagent")
    researcher_llm: LLMRef | None = Field(default=None, description="LLM for researcher")
    planner_llm: LLMRef | None = Field(default=None, description="LLM for planner")
    writer_llm: LLMRef | None = Field(default=None, description="LLM for final writer/synthesis subagent")
    tools: list[FunctionRef | FunctionGroupRef] = Field(
        default_factory=list,
        description="Explicit tool list. Empty = inherit all from data_source_registry.",
    )
    exclude_tools: list[str] = Field(
        default_factory=list,
        description="Tool names to exclude when inheriting from registry.",
    )
    verbose: bool = Field(default=True)
    domain_catalog_path: str | None = Field(
        default=None,
        description="Optional YAML/JSON domain catalog path for source-router-agent.",
    )
    enable_source_router: bool = Field(
        default=True,
        description="Enable the advisory source-router-agent before planning.",
    )
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    sandbox: SandboxConfig | None = Field(
        default=None,
        description="Optional DeepAgents sandbox backend for execute support.",
    )
    max_research_concurrency: int = Field(
        default=DEFAULT_MAX_RESEARCH_CONCURRENCY,
        ge=1,
        description="Maximum ResearchQuery items accepted and run concurrently per run_research_batch call.",
    )
    max_concurrent_source_tool_calls: int = Field(
        default=DEFAULT_MAX_CONCURRENT_SOURCE_TOOL_CALLS,
        ge=1,
        description="Shared maximum concurrent source-tool calls across researcher workers.",
    )
    max_source_tool_batch_size: int = Field(
        default=DEFAULT_MAX_SOURCE_TOOL_BATCH_SIZE,
        ge=1,
        description="Maximum concrete inputs accepted by batch-capable source tool wrappers.",
    )


@register_function(config_type=DeepResearchAgentConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def deep_research_agent(config: DeepResearchAgentConfig, builder: Builder):
    """Deep research agent using multi-phase workflow."""
    if config.tools:
        tool_refs = config.tools
    else:
        from aiq_agent.common import get_all_tool_refs

        tool_refs = get_all_tool_refs()

    tools = await builder.get_tools(tool_names=tool_refs, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

    if config.exclude_tools:
        excluded = set(config.exclude_tools)
        tools = [t for t in tools if getattr(t, "name", "") not in excluded]

    from aiq_agent.common import validate_tool_availability

    is_valid, available_count, unavailable = validate_tool_availability(
        tools,
        research_type="deep research",
    )
    if not is_valid:
        logger.warning(
            "Startup check: no tools available for deep research. "
            "All queries will fail until at least one tool is properly configured.",
        )

    llm = await builder.get_llm(config.orchestrator_llm, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

    provider = LLMProvider()
    provider.set_default(llm)

    provider.configure(LLMRole.ORCHESTRATOR, llm)
    if config.source_router_llm:
        source_router_llm = await builder.get_llm(config.source_router_llm, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
        provider.configure(LLMRole.ROUTER, source_router_llm)
    if config.researcher_llm:
        researcher_llm = await builder.get_llm(config.researcher_llm, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
        provider.configure(LLMRole.RESEARCHER, researcher_llm)
    if config.planner_llm:
        planner_llm = await builder.get_llm(config.planner_llm, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
        provider.configure(LLMRole.PLANNER, planner_llm)
    if config.writer_llm:
        writer_llm = await builder.get_llm(config.writer_llm, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
        provider.configure(LLMRole.REPORT_WRITER, writer_llm)

    verbose = is_verbose(config.verbose)
    callbacks = [VerboseTraceCallback()] if verbose else []

    agent = DeepResearcherAgent(
        llm_provider=provider,
        tools=tools,
        verbose=verbose,
        callbacks=callbacks,
        domain_catalog_path=config.domain_catalog_path,
        enable_source_router=config.enable_source_router,
        skills=config.skills,
        sandbox=config.sandbox,
        max_research_concurrency=config.max_research_concurrency,
        max_concurrent_source_tool_calls=config.max_concurrent_source_tool_calls,
        max_source_tool_batch_size=config.max_source_tool_batch_size,
    )

    async def _run(state: DeepResearchAgentState) -> DeepResearchAgentState:
        """Run deep research with a list of messages or payload."""
        try:
            data_sources = state.data_sources
            selected_tools = filter_tools_by_sources(tools, data_sources)
            active_agent = agent
            if config.sandbox is not None or (data_sources is not None and selected_tools != tools):
                # Scope the Modal sandbox to the async job_id when one is in
                # NAT context (set by aiq_api/jobs/runner.py). Falls back to a
                # per-request uuid in DeepAgentsRuntime when None.
                job_id: str | None = None
                try:
                    from nat.builder.context import Context

                    job_id = Context.get().workflow_run_id
                except Exception:  # noqa: BLE001 - Context may be unavailable in sync/eval paths
                    job_id = None
                active_agent = DeepResearcherAgent(
                    llm_provider=provider,
                    tools=selected_tools,
                    verbose=verbose,
                    callbacks=callbacks,
                    domain_catalog_path=config.domain_catalog_path,
                    enable_source_router=config.enable_source_router,
                    skills=config.skills,
                    sandbox=config.sandbox,
                    job_id=job_id,
                    max_research_concurrency=config.max_research_concurrency,
                    max_concurrent_source_tool_calls=config.max_concurrent_source_tool_calls,
                    max_source_tool_batch_size=config.max_source_tool_batch_size,
                )

            if all_mapped_tools_filtered_out(tools, selected_tools, data_sources):
                logger.warning("Deep research received data_sources with no matching tools")

            # Validate tool availability before starting deep research
            # At least one tool must be available
            # This prevents the agent from trying to reason about unavailable tools
            # Check selected_tools directly - they already reflect data_sources filtering
            from aiq_agent.common import format_user_facing_tool_error
            from aiq_agent.common import validate_tool_availability

            is_valid, _, unavailable_tools = validate_tool_availability(selected_tools, research_type="deep research")

            # Fail if no tools are available
            if not is_valid:
                error_msg = format_user_facing_tool_error("deep research", unavailable_tools)

                # Return error state with error message - this prevents the agent from running
                from langchain_core.messages import AIMessage

                error_state = DeepResearchAgentState(messages=state.messages + [AIMessage(content=error_msg)])
                return error_state

            result = await active_agent.run(state)
            return result
        except Exception:
            logger.exception("Error in deep research execution")
            raise

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
    workflow_id = config.name or config.type

    async def _run(query: str) -> ChatResponse:
        """Run deep research on a query string."""
        state = DeepResearchAgentState(messages=[HumanMessage(content=query)])
        result = await deep_research_agent_fn.ainvoke(state)
        response_content = result.messages[-1].content
        return _create_chat_response(response_content, response_id="research_response", model=workflow_id)

    yield FunctionInfo.from_fn(_run, description="Deep research workflow for evaluation (accepts string query).")

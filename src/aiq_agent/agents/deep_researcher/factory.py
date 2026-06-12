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

"""Graph and middleware factory for the deep researcher agent and its subagents."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from deepagents import create_deep_agent
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.skills import SkillsMiddleware
from deepagents.middleware.summarization import create_summarization_middleware
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware
from langchain.agents.middleware import ToolRetryMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_core.tools import tool
from langgraph.store.memory import InMemoryStore

from aiq_agent.common import LLMProvider
from aiq_agent.common import LLMRole
from aiq_agent.common import render_prompt_template

from .custom_middleware import EmptyContentFixMiddleware
from .custom_middleware import SourceRegistryMiddleware
from .custom_middleware import ToolNameSanitizationMiddleware
from .custom_middleware import ToolResultPruningMiddleware
from .deepagents_runtime import DeepAgentsRuntime
from .models import DeepResearchAgentState
from .models import ResearchNotes
from .models import ResearchPlan
from .tools.research import build_research_batch_tool
from .tools.source_registry import build_get_verified_sources_tool
from .tools.source_routing import build_lookup_source_catalog_tool
from .tools.source_tool_batching import adapt_source_tools_for_research

logger = logging.getLogger(__name__)

FILESYSTEM_TOOL_NAMES = {
    "edit_file",
    "grep",
    "glob",
    "ls",
    "read_file",
    "write_file",
}


@tool
def think(thought: str) -> str:
    """Use this tool to reason through decisions, verify constraints, or plan next steps."""
    return "Thought recorded."


@dataclass(frozen=True)
class DeepResearchToolSet:
    """Tool groupings used by the deep researcher graph and subagents."""

    source_tool_names: set[str]
    tools_info: list[dict[str, str]]
    helper_tools: list[BaseTool]
    all_tools: list[BaseTool]
    research_source_tools: list[BaseTool]
    researcher_tools: list[BaseTool]
    writer_tools: list[BaseTool]


@dataclass(frozen=True)
class DeepResearchMiddlewareSet:
    """Middleware stacks used by the deep researcher graph and subagents."""

    researcher: list[Any]
    planner: list[Any]
    writer: list[Any]
    orchestrator: list[Any]


def build_deep_research_tool_set(
    tools: Sequence[BaseTool],
    *,
    source_registry_middleware: SourceRegistryMiddleware,
    max_concurrent_source_tool_calls: int,
    max_source_tool_batch_size: int,
) -> DeepResearchToolSet:
    """Build helper, researcher, writer, and source tool groupings."""
    source_tool_names = {tool.name for tool in tools}
    helper_tools = [think, build_get_verified_sources_tool(source_registry_middleware)]
    research_source_tools = adapt_source_tools_for_research(
        list(tools),
        source_tool_names=source_tool_names,
        max_concurrent_source_tool_calls=max_concurrent_source_tool_calls,
        max_batch_size=max_source_tool_batch_size,
    )
    return DeepResearchToolSet(
        source_tool_names=source_tool_names,
        tools_info=[{"name": tool.name, "description": tool.description} for tool in tools],
        helper_tools=helper_tools,
        all_tools=[*helper_tools, *tools],
        research_source_tools=research_source_tools,
        researcher_tools=[*helper_tools, *research_source_tools],
        writer_tools=list(helper_tools),
    )


def build_common_middleware(
    *,
    tool_set: DeepResearchToolSet,
    source_registry_middleware: SourceRegistryMiddleware,
    extra_valid_tool_names: Sequence[str] = (),
) -> list[Any]:
    """Build the shared middleware stack with agent-specific valid tool names."""
    valid_tool_names = {tool.name for tool in [*tool_set.all_tools, *tool_set.researcher_tools]}
    valid_tool_names.update(FILESYSTEM_TOOL_NAMES)
    valid_tool_names.update(extra_valid_tool_names)
    return [
        EmptyContentFixMiddleware(),
        ToolNameSanitizationMiddleware(valid_tool_names=sorted(valid_tool_names)),
        ToolRetryMiddleware(max_retries=3, backoff_factor=2.0, initial_delay=1.0),
        source_registry_middleware,
        ToolResultPruningMiddleware(keep_last_n=10, max_chars=2000),
        ModelRetryMiddleware(max_retries=2, backoff_factor=2.0, initial_delay=1.0),
    ]


def build_source_router_middleware(*, extra_valid_tool_names: Sequence[str] = ()) -> list[Any]:
    """Build minimal middleware for the source-router-agent."""
    return [
        EmptyContentFixMiddleware(),
        ToolNameSanitizationMiddleware(valid_tool_names=sorted({"write_file", *extra_valid_tool_names})),
        ToolRetryMiddleware(max_retries=3, backoff_factor=2.0, initial_delay=1.0),
        ModelRetryMiddleware(max_retries=2, backoff_factor=2.0, initial_delay=1.0),
    ]


def build_deep_research_middleware_set(
    *,
    tool_set: DeepResearchToolSet,
    source_registry_middleware: SourceRegistryMiddleware,
) -> DeepResearchMiddlewareSet:
    """Build researcher, writer, and orchestrator middleware stacks."""
    return DeepResearchMiddlewareSet(
        researcher=build_common_middleware(
            tool_set=tool_set,
            source_registry_middleware=source_registry_middleware,
        ),
        planner=build_common_middleware(
            tool_set=tool_set,
            source_registry_middleware=source_registry_middleware,
        ),
        writer=build_common_middleware(
            tool_set=tool_set,
            source_registry_middleware=source_registry_middleware,
        ),
        orchestrator=build_common_middleware(
            tool_set=tool_set,
            source_registry_middleware=source_registry_middleware,
            extra_valid_tool_names=["run_research_batch"],
        ),
    )


def _available_documents(state: DeepResearchAgentState) -> list[dict[str, Any]]:
    return [doc.model_dump() for doc in (state.available_documents or [])]


def build_researcher_runtime_middleware(
    *,
    researcher_model: BaseChatModel,
    shared_middleware: list[Any],
    skill_sources: list[str] | None = None,
    backend: Any = None,
) -> list[Any]:
    """Build DeepAgents runtime middleware for one isolated researcher worker."""
    middleware: list[Any] = []
    if skill_sources:
        middleware.append(SkillsMiddleware(backend=backend, sources=skill_sources))
    middleware.extend(
        [
            FilesystemMiddleware(backend=backend),
            create_summarization_middleware(researcher_model, backend),
            PatchToolCallsMiddleware(),
            *shared_middleware,
        ]
    )
    return middleware


def build_researcher_runnable(
    *,
    researcher_model: BaseChatModel,
    researcher_tools: list[BaseTool],
    researcher_middleware: list[Any],
    system_prompt: str,
    skill_sources: list[str] | None = None,
    backend: Any = None,
) -> Any:
    """Build the reusable single-query researcher runnable."""
    return create_agent(
        model=researcher_model,
        tools=researcher_tools,
        system_prompt=system_prompt,
        middleware=build_researcher_runtime_middleware(
            researcher_model=researcher_model,
            shared_middleware=researcher_middleware,
            skill_sources=skill_sources,
            backend=backend,
        ),
        response_format=ResearchNotes,
    )


def build_deep_research_subagents(
    *,
    llm_provider: LLMProvider,
    state: DeepResearchAgentState,
    prompts: dict[str, str],
    tools: Sequence[BaseTool],
    runtime: DeepAgentsRuntime,
    tool_set: DeepResearchToolSet,
    middleware_set: DeepResearchMiddlewareSet,
    domain_catalog_path: str | None,
    current_datetime: str,
    max_research_concurrency: int,
    enable_source_router: bool = True,
) -> list[dict[str, Any]]:
    """Build all DeepAgents subagent specs."""
    subagents: list[dict[str, Any]] = []
    if enable_source_router:
        source_catalog_tool = build_lookup_source_catalog_tool(
            tools,
            allowed_source_ids=state.data_sources,
            domain_catalog_path=domain_catalog_path,
        )
        source_router_subagent: dict[str, Any] = {
            "name": "source-router-agent",
            "description": (
                "Source router - chooses an advisory domain route and configured source set before detailed planning"
            ),
            "system_prompt": render_prompt_template(
                prompts["source_router"],
                current_datetime=current_datetime,
                user_info=state.user_info,
                clarifier_result=state.clarifier_result,
                available_documents=_available_documents(state),
            ),
            "tools": [source_catalog_tool],
            "model": llm_provider.get(LLMRole.ROUTER),
            "middleware": build_source_router_middleware(extra_valid_tool_names=[source_catalog_tool.name]),
        }
        subagents.append(source_router_subagent)
    writer_agent: dict[str, Any] = {
        "name": "writer-agent",
        "description": (
            "Final synthesis writer - reads the plan and research notes, then returns "
            "a cited Markdown answer in the requested output shape"
        ),
        "system_prompt": render_prompt_template(
            prompts["writer"],
            current_datetime=current_datetime,
            user_info=state.user_info,
            available_documents=_available_documents(state),
        ),
        "tools": tool_set.writer_tools,
        "model": llm_provider.get(LLMRole.REPORT_WRITER),
        "middleware": middleware_set.writer,
    }
    planner_subagent: dict[str, Any] = {
        "name": "planner-agent",
        "description": (
            "Content-driven research planning - iteratively builds evidence-grounded "
            "answer strategies through interleaved search and planning"
        ),
        "system_prompt": render_prompt_template(
            prompts["planner"],
            current_datetime=current_datetime,
            user_info=state.user_info,
            tools=tool_set.tools_info,
            available_documents=_available_documents(state),
            enable_source_router=enable_source_router,
            max_research_concurrency=max_research_concurrency,
        ),
        "tools": tool_set.researcher_tools,
        "model": llm_provider.get(LLMRole.PLANNER),
        "middleware": middleware_set.planner,
        "response_format": ResearchPlan,
    }
    writer_skill_sources = runtime.skill_sources_for("writer-agent")
    if writer_skill_sources is not None:
        writer_agent["skills"] = writer_skill_sources
    subagents.extend([planner_subagent, writer_agent])
    return subagents


def build_deep_research_graph(
    *,
    llm_provider: LLMProvider,
    state: DeepResearchAgentState,
    prompts: dict[str, str],
    tools: Sequence[BaseTool],
    runtime: DeepAgentsRuntime,
    tool_set: DeepResearchToolSet,
    middleware_set: DeepResearchMiddlewareSet,
    source_registry_middleware: SourceRegistryMiddleware,
    callbacks: list[Any],
    domain_catalog_path: str | None,
    max_research_concurrency: int,
    enable_source_router: bool = True,
) -> Any:
    """Build the full DeepAgents graph for one deep research run."""
    current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    backend = runtime.backend
    researcher_model = llm_provider.get(LLMRole.RESEARCHER)
    researcher_runnable = build_researcher_runnable(
        researcher_model=researcher_model,
        researcher_tools=tool_set.researcher_tools,
        system_prompt=render_prompt_template(
            prompts["researcher"],
            current_datetime=current_datetime,
            user_info=state.user_info,
            available_documents=_available_documents(state),
            tools=tool_set.tools_info,
        ),
        researcher_middleware=middleware_set.researcher,
        skill_sources=runtime.skill_sources_for("researcher"),
        backend=backend,
    )
    research_batch_tool = build_research_batch_tool(
        researcher_runnable=researcher_runnable,
        backend=backend,
        callbacks=callbacks,
        max_research_concurrency=max_research_concurrency,
        source_registry_middleware=source_registry_middleware,
    )

    agent = create_deep_agent(
        model=llm_provider.get(LLMRole.ORCHESTRATOR),
        tools=[*tool_set.helper_tools, research_batch_tool],
        system_prompt=render_prompt_template(
            prompts["orchestrator"],
            current_datetime=current_datetime,
            user_info=state.user_info,
            clarifier_result=state.clarifier_result,
            available_documents=_available_documents(state),
            tools=tool_set.tools_info,
            enable_source_router=enable_source_router,
            max_research_concurrency=max_research_concurrency,
        ),
        subagents=build_deep_research_subagents(
            llm_provider=llm_provider,
            state=state,
            prompts=prompts,
            tools=tools,
            runtime=runtime,
            tool_set=tool_set,
            middleware_set=middleware_set,
            domain_catalog_path=domain_catalog_path,
            enable_source_router=enable_source_router,
            current_datetime=current_datetime,
            max_research_concurrency=max_research_concurrency,
        ),
        store=InMemoryStore(),
        middleware=middleware_set.orchestrator,
        backend=backend,
    )
    return agent.with_config({"recursion_limit": 2000})

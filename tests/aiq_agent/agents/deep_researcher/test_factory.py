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

"""Tests for deep researcher graph and middleware factory helpers."""

from unittest.mock import MagicMock
from unittest.mock import patch

from langchain.agents.middleware import AgentMiddleware
from langchain_core.tools import tool

from aiq_agent.agents.deep_researcher.custom_middleware import SourceRegistryMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import ToolNameSanitizationMiddleware
from aiq_agent.agents.deep_researcher.deepagents_runtime import DeepAgentsRuntime
from aiq_agent.agents.deep_researcher.deepagents_runtime import SkillsConfig
from aiq_agent.agents.deep_researcher.factory import build_deep_research_middleware_set
from aiq_agent.agents.deep_researcher.factory import build_deep_research_subagents
from aiq_agent.agents.deep_researcher.factory import build_deep_research_tool_set
from aiq_agent.agents.deep_researcher.factory import build_researcher_runnable
from aiq_agent.agents.deep_researcher.models import DeepResearchAgentState
from aiq_agent.agents.deep_researcher.models import ResearchNotes
from aiq_agent.agents.deep_researcher.models import ResearchPlan
from aiq_agent.agents.deep_researcher.models import SourceRoutingPlan
from aiq_agent.common import LLMProvider
from aiq_agent.common import LLMRole


@tool
def web_search_tool(query: str) -> str:
    """Search the web for information."""
    return f"Results for: {query}"


def _llm_provider() -> LLMProvider:
    llm = MagicMock()
    provider = LLMProvider()
    provider.set_default(llm)
    provider.configure(LLMRole.ROUTER, llm)
    provider.configure(LLMRole.PLANNER, llm)
    provider.configure(LLMRole.RESEARCHER, llm)
    provider.configure(LLMRole.EVIDENCE_JUDGE, llm)
    provider.configure(LLMRole.REPORT_WRITER, llm)
    provider.configure(LLMRole.ORCHESTRATOR, llm)
    return provider


def _prompts() -> dict[str, str]:
    return {
        "source_router": "router {{ current_datetime }}",
        "planner": "planner {% for tool in tools %}{{ tool.name }} {% endfor %}",
        "researcher": "researcher",
        "orchestrator": "orchestrator",
        "evidence_judge": "judge {{ current_datetime }} /shared/evidence_judgments.json",
        "writer": "writer",
    }


def _tool_set_and_middleware() -> tuple[SourceRegistryMiddleware, object, object]:
    registry = SourceRegistryMiddleware(source_tool_names={web_search_tool.name})
    tool_set = build_deep_research_tool_set(
        [web_search_tool],
        source_registry_middleware=registry,
        max_concurrent_source_tool_calls=2,
        max_source_tool_batch_size=3,
    )
    middleware_set = build_deep_research_middleware_set(
        tool_set=tool_set,
        source_registry_middleware=registry,
    )
    return registry, tool_set, middleware_set


def _tool_names(tools) -> list[str]:
    return [tool.name for tool in tools]


def _sanitizer(middleware: list[object]) -> ToolNameSanitizationMiddleware:
    return next(item for item in middleware if isinstance(item, ToolNameSanitizationMiddleware))


def test_tool_set_keeps_helper_researcher_and_writer_tools_separate():
    """Factory tool grouping keeps source tools away from writer-only helpers."""
    _, tool_set, _ = _tool_set_and_middleware()

    assert tool_set.source_tool_names == {"web_search_tool"}
    assert _tool_names(tool_set.helper_tools) == ["think", "get_verified_sources"]
    assert _tool_names(tool_set.writer_tools) == ["think", "get_verified_sources"]
    assert "web_search_tool" in _tool_names(tool_set.researcher_tools)
    assert "web_search_tool" not in _tool_names(tool_set.writer_tools)


def test_middleware_set_adds_orchestrator_batch_tool_name():
    """The orchestrator sanitizer accepts run_research_batch while shared stacks accept source tools."""
    registry, tool_set, middleware_set = _tool_set_and_middleware()

    researcher_sanitizer = _sanitizer(middleware_set.researcher)
    judge_sanitizer = _sanitizer(middleware_set.evidence_judge)
    orchestrator_sanitizer = _sanitizer(middleware_set.orchestrator)
    assert "web_search_tool" in researcher_sanitizer.valid_tool_names
    assert "edit_file" in judge_sanitizer.valid_tool_names
    assert "read_file" in researcher_sanitizer.valid_tool_names
    assert "write_file" in researcher_sanitizer.valid_tool_names
    assert "run_research_batch" not in researcher_sanitizer.valid_tool_names
    assert "run_research_batch" in orchestrator_sanitizer.valid_tool_names
    assert registry in middleware_set.researcher
    assert registry in middleware_set.evidence_judge
    assert tool_set.writer_tools != tool_set.researcher_tools


def test_subagents_route_tools_and_writer_skills():
    """Source-router excludes source tools, planner receives them, and writer receives configured skills."""
    _, tool_set, middleware_set = _tool_set_and_middleware()
    runtime = DeepAgentsRuntime(
        skills=SkillsConfig(
            enabled=True,
            default_sources=(),
            agent_sources={"writer-agent": ("/skills/synthesis/",)},
        )
    )

    subagents = build_deep_research_subagents(
        llm_provider=_llm_provider(),
        state=DeepResearchAgentState(messages=[]),
        prompts=_prompts(),
        tools=[web_search_tool],
        runtime=runtime,
        tool_set=tool_set,
        middleware_set=middleware_set,
        domain_catalog_path=None,
        current_datetime="2026-06-03 12:00:00",
    )

    by_name = {subagent["name"]: subagent for subagent in subagents}
    assert by_name["source-router-agent"]["response_format"] is SourceRoutingPlan
    assert _tool_names(by_name["source-router-agent"]["tools"]) == ["think", "lookup_source_catalog"]
    assert "web_search_tool" not in _tool_names(by_name["source-router-agent"]["tools"])
    assert by_name["planner-agent"]["response_format"] is ResearchPlan
    assert "web_search_tool" in _tool_names(by_name["planner-agent"]["tools"])
    assert "response_format" not in by_name["evidence-judge-agent"]
    assert _tool_names(by_name["evidence-judge-agent"]["tools"]) == ["think", "get_verified_sources"]
    assert by_name["evidence-judge-agent"]["middleware"] is middleware_set.evidence_judge
    assert "/shared/evidence_judgments.json" in by_name["evidence-judge-agent"]["system_prompt"]
    assert _tool_names(by_name["writer-agent"]["tools"]) == ["think", "get_verified_sources"]
    assert by_name["writer-agent"]["skills"] == ["/skills/synthesis/"]


def test_researcher_runnable_uses_rendered_prompt_and_runtime_middleware():
    """Researcher runnable construction stays behavior-compatible but has a smaller interface."""

    class FakeSummarizationMiddleware(AgentMiddleware):
        pass

    researcher_agent = MagicMock()
    researcher_model = MagicMock()
    shared_middleware = [MagicMock(name="shared_middleware")]
    backend = MagicMock()

    with (
        patch(
            "aiq_agent.agents.deep_researcher.factory.create_summarization_middleware",
            return_value=FakeSummarizationMiddleware(),
        ),
        patch(
            "aiq_agent.agents.deep_researcher.factory.create_agent",
            return_value=researcher_agent,
        ) as create,
    ):
        result = build_researcher_runnable(
            researcher_model=researcher_model,
            researcher_tools=[web_search_tool],
            system_prompt="rendered researcher prompt",
            researcher_middleware=shared_middleware,
            skill_sources=["/skills/research-sandbox/"],
            backend=backend,
        )

    kwargs = create.call_args.kwargs
    middleware_names = [item.__class__.__name__ for item in kwargs["middleware"]]
    assert result is researcher_agent
    assert kwargs["model"] is researcher_model
    assert kwargs["tools"] == [web_search_tool]
    assert kwargs["system_prompt"] == "rendered researcher prompt"
    assert kwargs["response_format"] is ResearchNotes
    assert "TodoListMiddleware" in middleware_names
    assert "SkillsMiddleware" in middleware_names
    assert "FilesystemMiddleware" in middleware_names
    assert "FakeSummarizationMiddleware" in middleware_names
    assert "PatchToolCallsMiddleware" in middleware_names
    assert kwargs["middleware"][-1] is shared_middleware[0]

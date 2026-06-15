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

"""Tests for the DeepResearcherAgent."""

import asyncio
import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from deepagents.backends.protocol import FileUploadResponse
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool

from aiq_agent.agents.deep_researcher.models import DeepResearchAgentState
from aiq_agent.agents.deep_researcher.models import ResearchNotes
from aiq_agent.agents.deep_researcher.models import ResearchPlan
from aiq_agent.agents.deep_researcher.models import ResearchQuery
from aiq_agent.agents.deep_researcher.tools.research import build_research_batch_tool
from aiq_agent.agents.deep_researcher.tools.research import researcher_invoke_state
from aiq_agent.common import LLMProvider
from aiq_agent.common import LLMRole
from aiq_agent.common.citation_verification import SourceEntry


@tool
def web_search_tool(query: str) -> str:
    """Search the web for information."""
    return f"Results for: {query}"


def output_markdown_file(markdown: str | None = None) -> dict:
    """Return virtual filesystem content for /shared/output.md."""
    return {
        "/shared/output.md": {
            "content": markdown or "Deep research answer [1].\n\n## Sources\n[1] Example: https://example.com",
            "encoding": "utf-8",
        }
    }


@pytest.fixture(autouse=True)
def mock_research_summarization_middleware():
    """Avoid requiring a concrete BaseChatModel for researcher runnable construction tests."""

    class FakeSummarizationMiddleware(AgentMiddleware):
        pass

    researcher_runnable = MagicMock(name="researcher_runnable")
    researcher_runnable.ainvoke = AsyncMock()
    with (
        patch(
            "aiq_agent.agents.deep_researcher.factory.create_summarization_middleware",
            return_value=FakeSummarizationMiddleware(),
        ) as summarization,
        patch(
            "aiq_agent.agents.deep_researcher.factory.create_agent",
            return_value=researcher_runnable,
        ) as create_researcher,
    ):
        yield {"summarization": summarization, "create_researcher": create_researcher}


class TestDeepResearcherAgent:
    """Tests for the DeepResearcherAgent class."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM."""
        llm = MagicMock()
        llm.ainvoke = AsyncMock()
        llm.bind_tools = MagicMock(return_value=llm)
        return llm

    @pytest.fixture
    def mock_llm_provider(self, mock_llm):
        """Create a mock LLM provider."""
        provider = LLMProvider()
        provider.set_default(mock_llm)
        provider.configure(LLMRole.ORCHESTRATOR, mock_llm)
        provider.configure(LLMRole.ROUTER, mock_llm)
        provider.configure(LLMRole.PLANNER, mock_llm)
        provider.configure(LLMRole.RESEARCHER, mock_llm)
        provider.configure(LLMRole.REPORT_WRITER, mock_llm)
        provider.get = MagicMock(wraps=provider.get)
        return provider

    @pytest.fixture
    def real_tool(self):
        """Create a real LangChain tool."""
        return web_search_tool

    def _build_batch_tool(self, agent, researcher_runnable, backend=None):
        return build_research_batch_tool(
            researcher_runnable=researcher_runnable,
            backend=backend,
            callbacks=agent.callbacks,
            max_research_concurrency=agent.max_research_concurrency,
            source_registry_middleware=agent.source_registry_middleware,
        )

    def _structured_notes_response(self, query_topic: str = "Research Topic"):
        return {
            "structured_response": {
                "query_topic": query_topic,
                "target_components": ["overview"],
                "summary": "A useful note.",
                "findings": [
                    {
                        "claim": "A fact.",
                        "evidence": "Evidence from https://example.test/source.",
                        "source_ids": [1],
                        "confidence": "high",
                        "caveats": [],
                    }
                ],
                "gaps": [],
                "sources": [
                    {
                        "id": 1,
                        "title": "Source",
                        "source_type": "url",
                        "locator": "https://example.test/source",
                    }
                ],
                "narrative_notes": "Useful narrative notes.",
                "language": "English",
            }
        }

    @pytest.fixture
    def mock_create_deep_agent(self):
        """Create a mock for create_deep_agent (deepagents)."""
        mock_agent = MagicMock()
        mock_agent.with_config = MagicMock(return_value=mock_agent)
        mock_agent.ainvoke = AsyncMock(
            return_value={
                "messages": [AIMessage(content="Deep research answer")],
                "files": output_markdown_file(),
            }
        )
        return mock_agent

    def test_init_with_defaults(self, mock_llm_provider, real_tool, mock_create_deep_agent):
        """Test DeepResearcherAgent initialization with defaults."""
        with patch(
            "aiq_agent.agents.deep_researcher.factory.create_deep_agent",
            return_value=mock_create_deep_agent,
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )

            assert agent.llm_provider == mock_llm_provider
            assert len(agent.tools) == 1
            assert agent.verbose is True
            assert agent.callbacks == []
            assert agent.deepagents_runtime.skill_sources_for("orchestrator") is None
            assert agent.enable_source_router is True

    def test_init_with_custom_settings(self, mock_llm_provider, real_tool, mock_create_deep_agent):
        """Test DeepResearcherAgent initialization with custom settings."""
        with patch("aiq_agent.agents.deep_researcher.factory.create_deep_agent", return_value=mock_create_deep_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent
            from aiq_agent.agents.deep_researcher.deepagents_runtime import SandboxConfig
            from aiq_agent.agents.deep_researcher.deepagents_runtime import SkillsConfig

            callbacks = [MagicMock()]
            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
                verbose=False,
                callbacks=callbacks,
                skills=SkillsConfig.enabled_builtin(),
                sandbox=SandboxConfig(app_name="custom-aiq"),
                domain_catalog_path="configs/domain_catalogs/deep_research_domain_catalog.yml",
                enable_source_router=False,
                max_research_concurrency=2,
                max_concurrent_source_tool_calls=3,
                max_source_tool_batch_size=4,
            )

            assert agent.verbose is False
            assert agent.callbacks == callbacks
            assert agent.max_research_concurrency == 2
            assert agent.max_concurrent_source_tool_calls == 3
            assert agent.max_source_tool_batch_size == 4
            assert agent.domain_catalog_path == "configs/domain_catalogs/deep_research_domain_catalog.yml"
            assert agent.enable_source_router is False
            assert agent.deepagents_runtime.skill_sources_for("orchestrator") is None
            assert agent.deepagents_runtime.skill_sources_for("researcher") == ["/skills/"]

    def test_sandbox_config_rejects_unsupported_provider(self):
        """Unsupported sandbox providers fail early with a clear error."""
        from aiq_agent.agents.deep_researcher.deepagents_runtime import SandboxConfig

        with pytest.raises(ValueError, match="Unsupported sandbox provider"):
            SandboxConfig(provider="not-modal")

    def test_register_uses_runtime_config_models(self):
        """NAT config uses the same skills and sandbox models as runtime."""
        from aiq_agent.agents.deep_researcher.deepagents_runtime import SandboxConfig
        from aiq_agent.agents.deep_researcher.deepagents_runtime import SkillsConfig
        from aiq_agent.agents.deep_researcher.register import DeepResearchAgentConfig

        config = DeepResearchAgentConfig(
            orchestrator_llm="llm",
            source_router_llm="source-router-llm",
            writer_llm="writer-llm",
            skills=SkillsConfig(enabled=True),
            sandbox=SandboxConfig(app_name="custom-aiq", python_packages=["matplotlib", "pillow"]),
            max_research_concurrency=2,
            max_concurrent_source_tool_calls=3,
            max_source_tool_batch_size=4,
            domain_catalog_path="configs/domain_catalogs/deep_research_domain_catalog.yml",
            enable_source_router=False,
        )

        assert config.skills.enabled is True
        assert config.source_router_llm == "source-router-llm"
        assert config.writer_llm == "writer-llm"
        assert config.domain_catalog_path == "configs/domain_catalogs/deep_research_domain_catalog.yml"
        assert config.max_research_concurrency == 2
        assert config.max_concurrent_source_tool_calls == 3
        assert config.max_source_tool_batch_size == 4
        assert config.enable_source_router is False
        assert config.skills.agent_sources == {}
        assert config.sandbox is not None
        assert config.sandbox.provider == "modal"
        assert config.sandbox.app_name == "custom-aiq"
        assert config.sandbox.python_packages == ("matplotlib", "pillow")

    def test_modal_sandbox_name_is_job_id(self):
        """Modal sandbox names use the resolved job ID directly."""
        from aiq_agent.agents.deep_researcher.deepagents_runtime import _validate_modal_sandbox_name

        assert _validate_modal_sandbox_name("job-123") == "job-123"

    def test_modal_sandbox_name_rejects_invalid_job_id(self):
        """Invalid custom job IDs fail before creating a Modal sandbox."""
        from aiq_agent.agents.deep_researcher.deepagents_runtime import _validate_modal_sandbox_name

        with pytest.raises(ValueError, match="valid Modal sandbox name"):
            _validate_modal_sandbox_name("bad/job/id")

    def test_init_without_tools(self, mock_llm_provider, mock_create_deep_agent):
        """Test DeepResearcherAgent initialization without tools."""
        with patch("aiq_agent.agents.deep_researcher.factory.create_deep_agent", return_value=mock_create_deep_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=None,
            )

            assert agent.tools == []

    def test_load_prompts(self, mock_llm_provider, real_tool, mock_create_deep_agent):
        """Test _load_prompts loads all required prompts."""
        with patch("aiq_agent.agents.deep_researcher.factory.create_deep_agent", return_value=mock_create_deep_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )

            # Should have planner, researcher, orchestrator, and writer prompts
            assert "planner" in agent._prompts
            assert "researcher" in agent._prompts
            assert "orchestrator" in agent._prompts
            assert "writer" in agent._prompts
            assert "source_router" in agent._prompts

    def test_prepare_state_preloads_builtin_skill_files(self, mock_llm_provider, real_tool):
        """Built-in skills are added to state so StateBackend can discover them."""
        from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent
        from aiq_agent.agents.deep_researcher.deepagents_runtime import SkillsConfig

        agent = DeepResearcherAgent(
            llm_provider=mock_llm_provider,
            tools=[real_tool],
            skills=SkillsConfig.enabled_builtin(),
        )
        state = DeepResearchAgentState(
            messages=[],
            files={"/existing.txt": {"content": "keep", "encoding": "utf-8"}},
        )
        mock_skill_files = {
            "/mock-skill/SKILL.md": {
                "content": "name: mock-skill\n",
                "encoding": "utf-8",
                "created_at": "2026-01-01T00:00:00",
                "modified_at": "2026-01-01T00:00:00",
            }
        }

        with patch(
            "aiq_agent.agents.deep_researcher.deepagents_runtime._builtin_skill_state_files",
            return_value=mock_skill_files,
        ):
            prepared = agent.deepagents_runtime.prepare_state(state)

        assert prepared.files["/existing.txt"]["content"] == "keep"
        for path, file_data in mock_skill_files.items():
            assert prepared.files[path] == file_data

    def test_build_orchestrator_passes_skills_to_writer_only(
        self,
        mock_llm_provider,
        real_tool,
        mock_create_deep_agent,
    ):
        """Only writer-agent receives synthesis skills when configured that way."""
        with (
            patch(
                "aiq_agent.agents.deep_researcher.factory.create_deep_agent",
                return_value=mock_create_deep_agent,
            ) as create,
            patch(
                "aiq_agent.agents.deep_researcher.factory.create_agent",
                return_value=mock_create_deep_agent,
            ) as create_researcher,
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent
            from aiq_agent.agents.deep_researcher.deepagents_runtime import BUILTIN_SKILL_SOURCE
            from aiq_agent.agents.deep_researcher.deepagents_runtime import SkillsConfig

            synthesis_skill_source = f"{BUILTIN_SKILL_SOURCE}synthesis/"
            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
                skills=SkillsConfig(
                    enabled=True,
                    agent_sources={
                        "writer-agent": (synthesis_skill_source,),
                    },
                ),
            )
            state = DeepResearchAgentState(messages=[HumanMessage(content="Compare revenue growth")])

            agent._build_orchestrator_agent(state)

            assert create.call_count == 1
            assert create_researcher.call_count == 1
            researcher_kwargs = create_researcher.call_args.kwargs
            kwargs = create.call_args.kwargs
            assert researcher_kwargs["response_format"] is ResearchNotes
            researcher_middleware = researcher_kwargs["middleware"]
            assert researcher_middleware is not agent.researcher_middleware
            assert not any(m.__class__.__name__ == "TodoListMiddleware" for m in researcher_middleware)
            researcher_skills = [m for m in researcher_middleware if m.__class__.__name__ == "SkillsMiddleware"]
            assert researcher_skills == []
            assert any(m.__class__.__name__ == "FilesystemMiddleware" for m in researcher_middleware)
            assert any(m.__class__.__name__ == "PatchToolCallsMiddleware" for m in researcher_middleware)
            assert all(m in researcher_middleware for m in agent.researcher_middleware)
            assert "skills" not in researcher_kwargs
            assert "backend" not in researcher_kwargs
            assert kwargs["middleware"] is agent.orchestrator_middleware
            assert "If a Skills System section is present" not in researcher_kwargs["system_prompt"]
            assert "data-table-analysis" not in researcher_kwargs["system_prompt"]
            assert "/shared/plan.json" in researcher_kwargs["system_prompt"]
            assert "read_file" in researcher_kwargs["system_prompt"]
            assert "SKILL.md" in researcher_kwargs["system_prompt"]
            assert "ResearchQuery.target_components" in researcher_kwargs["system_prompt"]
            assert "Evidence judgment" in researcher_kwargs["system_prompt"]
            assert "Do not call `write_file` or `edit_file`" in researcher_kwargs["system_prompt"]
            assert "write_file` filesystem tool exactly once" not in researcher_kwargs["system_prompt"]
            assert "After the `write_file` tool returns" not in researcher_kwargs["system_prompt"]
            assert "Default source budget per ResearchQuery" in researcher_kwargs["system_prompt"]
            assert "one primary source-tool call" in researcher_kwargs["system_prompt"]
            assert "at most one fallback or corroboration call" in researcher_kwargs["system_prompt"]
            assert "at most one extra targeted follow-up" in researcher_kwargs["system_prompt"]
            assert "Do not run every possible source angle" in researcher_kwargs["system_prompt"]
            assert "skills" not in kwargs
            assert not callable(kwargs["backend"])
            assert [tool.name for tool in kwargs["tools"]] == [
                "think",
                "get_verified_sources",
                "run_research_batch",
            ]
            assert real_tool.name not in {tool.name for tool in kwargs["tools"]}
            assert "Available Skills:" not in kwargs["system_prompt"]
            assert "Use read_file to load the relevant SKILL.md BEFORE writing any code" not in kwargs["system_prompt"]
            assert 'execute("python /workspace/[name].py")' not in kwargs["system_prompt"]
            assert "read_writer_context" not in kwargs["system_prompt"]
            assert "Shell commands cannot see `/shared/`" in kwargs["system_prompt"]
            assert "to /shared/output.md" in kwargs["system_prompt"]
            assert "returns only a short completion marker" in kwargs["system_prompt"]
            assert "do not echo the full Markdown" in kwargs["system_prompt"]
            assert (
                "Never call `source-router-agent` and `planner-agent` in the same assistant turn"
                in kwargs["system_prompt"]
            )
            assert "Only after the source-router-agent tool result has returned" in kwargs["system_prompt"]
            assert "at most 6 full ResearchQuery objects per call" in kwargs["system_prompt"]
            assert "all needed queries in one call when there are 6 or fewer" in kwargs["system_prompt"]
            assert "fewest ordered batches" in kwargs["system_prompt"]
            assert "do not create smaller curated waves" in kwargs["system_prompt"]
            assert "Never repeat a covered query" in kwargs["system_prompt"]
            assert "revise only the invalid, failed, or missing ResearchQuery objects" in kwargs["system_prompt"]
            assert "max_batch_research_queries" not in kwargs["system_prompt"]
            assert "data-table-analysis" not in kwargs["system_prompt"]
            subagents = {subagent["name"]: subagent for subagent in kwargs["subagents"]}
            assert set(subagents) == {"source-router-agent", "planner-agent", "writer-agent"}
            assert "response_format" not in subagents["source-router-agent"]
            assert "skills" not in subagents["source-router-agent"]
            assert {tool.name for tool in subagents["source-router-agent"]["tools"]} == {"lookup_source_catalog"}
            assert "write_todos" in subagents["source-router-agent"]["system_prompt"]
            assert "Use at most two tool calls total" in subagents["source-router-agent"]["system_prompt"]
            assert real_tool.name not in {tool.name for tool in subagents["source-router-agent"]["tools"]}
            assert subagents["planner-agent"]["response_format"] is ResearchPlan
            assert "skills" not in subagents["planner-agent"]
            assert real_tool.name in {tool.name for tool in subagents["planner-agent"]["tools"]}
            assert "response_format" not in subagents["writer-agent"]
            assert subagents["writer-agent"]["tools"] == agent.writer_tools
            assert real_tool.name not in {tool.name for tool in subagents["writer-agent"]["tools"]}
            assert subagents["writer-agent"]["middleware"] is agent.writer_middleware
            assert subagents["writer-agent"]["skills"] == [synthesis_skill_source]
            assert "/skills/synthesis/" not in subagents["writer-agent"]["system_prompt"]
            assert "read_writer_context" not in subagents["writer-agent"]["system_prompt"]
            assert "/shared/plan.json" in subagents["writer-agent"]["system_prompt"]
            assert "Skill Use" not in subagents["writer-agent"]["system_prompt"]
            assert "Required Skill Use" not in subagents["writer-agent"]["system_prompt"]
            assert "General Cross-Synthesis Guidance" in subagents["writer-agent"]["system_prompt"]
            assert "Retain useful detail" in subagents["writer-agent"]["system_prompt"]
            assert "Point out meaningful conflicts" in subagents["writer-agent"]["system_prompt"]
            assert "Use tables when the evidence has comparable entities" in subagents["writer-agent"]["system_prompt"]
            assert "do not mechanically mirror them as final headings" in subagents["writer-agent"]["system_prompt"]
            assert "coherent analytical narrative" in subagents["writer-agent"]["system_prompt"]
            assert "Use bullets sparingly" in subagents["writer-agent"]["system_prompt"]
            assert "/shared/evidence_judgments.json" not in subagents["writer-agent"]["system_prompt"]
            assert "ResearchNotes.evidence_judgment" in subagents["writer-agent"]["system_prompt"]
            assert (
                "high-score/high-confidence notes are synthesis anchors" in subagents["writer-agent"]["system_prompt"]
            )
            assert "default compact mode" in subagents["writer-agent"]["system_prompt"]
            assert 'get_verified_sources(mode="full")' in subagents["writer-agent"]["system_prompt"]
            assert "Wrote /shared/output.md" in subagents["writer-agent"]["system_prompt"]
            assert "Do not return the full Markdown" in subagents["writer-agent"]["system_prompt"]
            assert "Do not use `edit_file` or repeated search-and-replace" in subagents["writer-agent"]["system_prompt"]
            assert "Final Output Grading Rubric" not in subagents["writer-agent"]["system_prompt"]
            assert "rubric" not in subagents["writer-agent"]["system_prompt"].lower()
            assert "long-form-report-writer" not in subagents["writer-agent"]["system_prompt"]
            assert "prediction-report-writer" not in subagents["writer-agent"]["system_prompt"]
            assert "answer_strategy.answer_type" in subagents["writer-agent"]["system_prompt"]
            assert "answer_strategy.title" in subagents["writer-agent"]["system_prompt"]
            assert "answer_strategy.required_components" in subagents["writer-agent"]["system_prompt"]
            for removed_field in ("assembly_instruction", "selection_mode", "expected_count", "options"):
                assert removed_field not in subagents["writer-agent"]["system_prompt"]
            planner_prompt = subagents["planner-agent"]["system_prompt"]
            assert "Skills System" not in planner_prompt
            assert "run_research_batch" in planner_prompt
            assert "subqueries" in planner_prompt
            assert "researcher agent" not in planner_prompt
            assert "data-table-analysis" not in planner_prompt
            assert "answer_strategy" in planner_prompt
            assert "Dynamic Discovery Budget" in planner_prompt
            assert "Do not turn planning into full evidence gathering" in planner_prompt
            assert "configured batch concurrency of 6" in planner_prompt
            assert "Thorough evidence gathering is essential" not in planner_prompt
            assert "Table of Contents" not in planner_prompt
            assert "/shared/source_routing.json" in planner_prompt
            assert "Do not call `ls` and `read_file` for `/shared/source_routing.json` in the same assistant turn" in (
                planner_prompt
            )
            assert "continue planning without source-routing guidance" in planner_prompt
            assert "all highest-priority routed recommendations' exact `tool_names`" in planner_prompt
            for removed_field in ("assembly_instruction", "selection_mode", "expected_count", "options"):
                assert removed_field not in planner_prompt

    def test_build_orchestrator_omits_skills_when_disabled(
        self,
        mock_llm_provider,
        real_tool,
        mock_create_deep_agent,
    ):
        """Default deep research runs do not add SkillsMiddleware."""
        with (
            patch(
                "aiq_agent.agents.deep_researcher.factory.create_deep_agent",
                return_value=mock_create_deep_agent,
            ) as create,
            patch(
                "aiq_agent.agents.deep_researcher.factory.create_agent",
                return_value=mock_create_deep_agent,
            ) as create_researcher,
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])
            state = DeepResearchAgentState(messages=[HumanMessage(content="Compare CUDA vs OpenCL")])

            agent._build_orchestrator_agent(state)

            assert create.call_count == 1
            assert create_researcher.call_count == 1
            researcher_kwargs = create_researcher.call_args.kwargs
            assert researcher_kwargs["response_format"] is ResearchNotes
            researcher_middleware = researcher_kwargs["middleware"]
            assert researcher_middleware is not agent.researcher_middleware
            assert not any(m.__class__.__name__ == "TodoListMiddleware" for m in researcher_middleware)
            assert not any(m.__class__.__name__ == "SkillsMiddleware" for m in researcher_middleware)
            assert any(m.__class__.__name__ == "FilesystemMiddleware" for m in researcher_middleware)
            assert any(m.__class__.__name__ == "PatchToolCallsMiddleware" for m in researcher_middleware)
            assert all(m in researcher_middleware for m in agent.researcher_middleware)
            assert create.call_args.kwargs["middleware"] is agent.orchestrator_middleware
            assert "skills" not in researcher_kwargs
            assert "skills" not in create.call_args.kwargs
            assert [tool.name for tool in create.call_args.kwargs["tools"]] == [
                "think",
                "get_verified_sources",
                "run_research_batch",
            ]
            assert real_tool.name not in {tool.name for tool in create.call_args.kwargs["tools"]}
            subagents = {subagent["name"]: subagent for subagent in create.call_args.kwargs["subagents"]}
            assert set(subagents) == {"source-router-agent", "planner-agent", "writer-agent"}
            assert "response_format" not in subagents["source-router-agent"]
            assert "skills" not in subagents["source-router-agent"]
            assert subagents["planner-agent"]["response_format"] is ResearchPlan
            assert real_tool.name in {tool.name for tool in subagents["planner-agent"]["tools"]}
            assert "response_format" not in subagents["writer-agent"]
            assert subagents["writer-agent"]["tools"] == agent.writer_tools
            assert real_tool.name not in {tool.name for tool in subagents["writer-agent"]["tools"]}
            assert subagents["writer-agent"]["middleware"] is agent.writer_middleware
            assert (
                "When available skills apply during planning, research, or synthesis"
                not in (create.call_args.kwargs["system_prompt"])
            )

    def test_build_orchestrator_can_disable_source_router(
        self,
        mock_llm_provider,
        real_tool,
        mock_create_deep_agent,
    ):
        """Source routing can be disabled without disabling planning, research, or writing."""
        with (
            patch(
                "aiq_agent.agents.deep_researcher.factory.create_deep_agent",
                return_value=mock_create_deep_agent,
            ) as create,
            patch(
                "aiq_agent.agents.deep_researcher.factory.create_agent",
                return_value=mock_create_deep_agent,
            ),
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
                enable_source_router=False,
                max_research_concurrency=2,
            )
            state = DeepResearchAgentState(messages=[HumanMessage(content="Compare CUDA vs OpenCL")])

            agent._build_orchestrator_agent(state)

            kwargs = create.call_args.kwargs
            prompt = kwargs["system_prompt"]
            subagents = {subagent["name"]: subagent for subagent in kwargs["subagents"]}
            requested_roles = [args[0] for args, _kwargs in mock_llm_provider.get.call_args_list]
            assert set(subagents) == {"planner-agent", "writer-agent"}
            assert "source-router-agent" not in prompt
            assert "/shared/source_routing.json" not in prompt
            assert "Start with `planner-agent`" in prompt
            assert "at most 2 full ResearchQuery objects per call" in prompt
            assert "all needed queries in one call when there are 2 or fewer" in prompt
            assert "fewest ordered batches" in prompt
            assert "Never repeat a covered query" in prompt
            assert subagents["planner-agent"]["response_format"] is ResearchPlan
            assert "/shared/source_routing.json" not in subagents["planner-agent"]["system_prompt"]
            assert real_tool.name in {tool.name for tool in subagents["planner-agent"]["tools"]}
            assert subagents["writer-agent"]["tools"] == agent.writer_tools
            assert LLMRole.ROUTER not in requested_roles
            assert LLMRole.EVIDENCE_JUDGE not in requested_roles

    @pytest.mark.asyncio
    async def test_run_research_batch_returns_structured_notes(
        self,
        mock_llm_provider,
        real_tool,
    ):
        """Batch research invokes the compiled researcher and returns ResearchNotes JSON."""
        from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

        class FakeResearcherRunnable:
            def __init__(self) -> None:
                self.calls = []

            async def ainvoke(self, state, config=None):
                self.calls.append((state, config))
                return {
                    "structured_response": {
                        "query_topic": "CUDA / OpenCL portability",
                        "target_components": ["programming_model"],
                        "summary": "CUDA is NVIDIA-specific while OpenCL targets portability.",
                        "findings": [
                            {
                                "claim": "OpenCL is designed for cross-vendor heterogeneous compute.",
                                "evidence": (
                                    "The source describes OpenCL as an open standard for heterogeneous platforms."
                                ),
                                "source_ids": [1],
                                "confidence": "high",
                                "caveats": [],
                            }
                        ],
                        "gaps": [],
                        "sources": [
                            {
                                "id": 1,
                                "title": "OpenCL Overview",
                                "source_type": "url",
                                "locator": "https://example.test/opencl",
                            }
                        ],
                        "narrative_notes": "OpenCL emphasizes portability; CUDA emphasizes NVIDIA ecosystem depth.",
                        "language": "English",
                    }
                }

        agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool], callbacks=[MagicMock()])
        fake_runnable = FakeResearcherRunnable()
        fake_backend = MagicMock()
        fake_backend.upload_files.side_effect = lambda files: [
            FileUploadResponse(path=path, error=None) for path, _content in files
        ]

        batch_tool = self._build_batch_tool(agent, fake_runnable, backend=fake_backend)
        agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.test/opencl", title="OpenCL"))
        agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.test/unused", title="Unused"))
        tool_properties = batch_tool.tool_call_schema.model_json_schema()["properties"]
        assert "runtime" not in tool_properties
        assert "max_concurrency" not in tool_properties
        result = await batch_tool.ainvoke(
            {
                "queries": [
                    {
                        "query": "CUDA OpenCL portability comparison",
                        "subqueries": ["CUDA OpenCL portability", "OpenCL cross vendor standard"],
                        "preferred_tools": ["web_search_tool"],
                        "fallback_tools": [],
                        "target_components": ["programming_model"],
                        "rationale": "Supports the comparison section.",
                    }
                ]
            }
        )

        payload = json.loads(result)
        assert len(payload) == 1
        assert payload[0]["query_topic"] == "CUDA / OpenCL portability"
        assert payload[0]["target_components"] == ["programming_model"]
        assert len(fake_runnable.calls) == 1
        call_state, call_config = fake_runnable.calls[0]
        assert "Batch research invocation" in call_state["messages"][0].content
        assert "return a structured ResearchNotes response" in call_state["messages"][0].content
        assert "Do not call write_file or edit_file" in call_state["messages"][0].content
        assert (
            "write the resulting ResearchNotes JSON under /shared/ exactly once"
            not in call_state["messages"][0].content
        )
        assert '"subqueries": [' in call_state["messages"][0].content
        assert "Execution order" not in call_state["messages"][0].content
        assert call_config == {"callbacks": agent.callbacks}
        fake_backend.upload_files.assert_called_once()
        persisted_files = fake_backend.upload_files.call_args.args[0]
        assert len(persisted_files) == 1
        persisted_path, persisted_content = persisted_files[0]
        assert persisted_path.startswith("/shared/research_note_01_cuda_opencl_portability_")
        assert persisted_path.endswith(".json")
        persisted_payload = json.loads(persisted_content.decode("utf-8"))
        assert persisted_payload["query_topic"] == "CUDA / OpenCL portability"
        assert persisted_payload["target_components"] == ["programming_model"]
        compact_sources = agent.source_registry_middleware.get_source_list_text()
        assert compact_sources is not None
        assert "https://example.test/opencl" in compact_sources
        assert "https://example.test/unused" not in compact_sources

    @pytest.mark.asyncio
    async def test_run_research_batch_rejects_unranked_oversized_batches(
        self,
        mock_llm_provider,
        real_tool,
    ):
        """Oversized batches must be curated by the caller instead of silently truncated."""
        from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

        fake_runnable = MagicMock()
        fake_runnable.ainvoke = AsyncMock()
        agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])
        batch_tool = self._build_batch_tool(agent, fake_runnable)

        with pytest.raises(ValueError, match="run_research_batch accepts at most 6 curated queries"):
            await batch_tool.ainvoke(
                {
                    "queries": [
                        {
                            "query": f"query {i}",
                            "preferred_tools": ["web_search_tool"],
                            "fallback_tools": [],
                            "target_components": [f"component_{i}"],
                            "rationale": "coverage",
                        }
                        for i in range(7)
                    ]
                }
            )
        fake_runnable.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_research_batch_delegates_tool_names_without_extra_validation(
        self,
        mock_llm_provider,
        real_tool,
    ):
        """The simplified batch tool delegates the planned query shape to the researcher."""
        from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

        fake_runnable = MagicMock()
        fake_runnable.ainvoke = AsyncMock(return_value=self._structured_notes_response("AI agents overview"))
        agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])
        batch_tool = self._build_batch_tool(agent, fake_runnable)

        result = await batch_tool.ainvoke(
            {
                "queries": [
                    {
                        "query": "AI agents overview",
                        "subqueries": ["AI agents definition 2025", "LLM agents architecture 2025"],
                        "preferred_tools": ["external"],
                        "fallback_tools": [],
                        "target_components": ["overview"],
                        "rationale": "External overview.",
                    }
                ]
            }
        )

        assert json.loads(result)[0]["query_topic"] == "AI agents overview"
        fake_runnable.ainvoke.assert_awaited_once()
        call_state = fake_runnable.ainvoke.call_args.args[0]
        assert '"preferred_tools": [' in call_state["messages"][0].content
        assert '"external"' in call_state["messages"][0].content

    @pytest.mark.asyncio
    async def test_run_research_batch_delegates_empty_subqueries(
        self,
        mock_llm_provider,
        real_tool,
    ):
        """The lightweight batch tool does not reintroduce planner-shape guards."""
        from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

        fake_runnable = MagicMock()
        fake_runnable.ainvoke = AsyncMock(return_value=self._structured_notes_response("AI agents survey"))
        agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])
        batch_tool = self._build_batch_tool(agent, fake_runnable)

        result = await batch_tool.ainvoke(
            {
                "queries": [
                    {
                        "query": "survey of AI agents 2023-2025",
                        "subqueries": [],
                        "preferred_tools": ["web_search_tool"],
                        "fallback_tools": [],
                        "target_components": ["definitions", "architecture", "taxonomy"],
                        "rationale": "Gather comprehensive survey coverage.",
                    }
                ]
            }
        )

        assert json.loads(result)[0]["query_topic"] == "AI agents survey"
        fake_runnable.ainvoke.assert_awaited_once()
        call_state = fake_runnable.ainvoke.call_args.args[0]
        assert '"subqueries": []' in call_state["messages"][0].content

    @pytest.mark.asyncio
    async def test_run_research_batch_waits_for_slow_workers_and_preserves_errors(
        self,
        mock_llm_provider,
        real_tool,
    ):
        """Failed researchers are surfaced as tool errors without timing out slow workers."""
        from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

        class FakeResearcherRunnable:
            async def ainvoke(self, state, config=None):
                content = state["messages"][0].content
                if "slow query" in content:
                    await asyncio.sleep(0.02)
                if "bad query" in content:
                    raise RuntimeError("search backend exploded")
                if "slow query" in content:
                    topic = "Slow Query"
                    title = "Slow"
                    locator = "https://example.test/slow"
                    component = "c"
                else:
                    topic = "Good Query"
                    title = "Good"
                    locator = "https://example.test/good"
                    component = "a"
                return {
                    "structured_response": {
                        "query_topic": topic,
                        "target_components": [component],
                        "summary": "A useful note.",
                        "findings": [
                            {
                                "claim": "A fact.",
                                "evidence": f"Evidence from {locator}.",
                                "source_ids": [1],
                                "confidence": "high",
                                "caveats": [],
                            }
                        ],
                        "gaps": [],
                        "sources": [
                            {
                                "id": 1,
                                "title": title,
                                "source_type": "url",
                                "locator": locator,
                            }
                        ],
                        "narrative_notes": "Useful narrative notes.",
                        "language": "English",
                    }
                }

        agent = DeepResearcherAgent(
            llm_provider=mock_llm_provider,
            tools=[real_tool],
            max_research_concurrency=3,
        )

        fake_backend = MagicMock()
        fake_backend.upload_files.side_effect = lambda files: [
            FileUploadResponse(path=path, error=None) for path, _content in files
        ]
        batch_tool = self._build_batch_tool(agent, FakeResearcherRunnable(), backend=fake_backend)
        agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.test/good", title="Good"))
        agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.test/slow", title="Slow"))
        agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.test/unused", title="Unused"))
        query_payloads = [
            {
                "query": "good query",
                "preferred_tools": ["web_search_tool"],
                "fallback_tools": [],
                "target_components": ["a"],
                "rationale": "success",
            },
            {
                "query": "bad query",
                "preferred_tools": ["web_search_tool"],
                "fallback_tools": [],
                "target_components": ["b"],
                "rationale": "failure",
            },
            {
                "query": "slow query",
                "preferred_tools": ["web_search_tool"],
                "fallback_tools": [],
                "target_components": ["c"],
                "rationale": "timeout",
            },
        ]
        with pytest.raises(RuntimeError) as exc_info:
            await batch_tool.ainvoke({"queries": query_payloads})

        assert "run_research_batch failed for 1 of 3 researcher worker" in str(exc_info.value)
        assert "search backend exploded" in str(exc_info.value)
        assert "timed out" not in str(exc_info.value)
        assert "2 successful researcher worker(s) were registered and persisted under /shared/" in str(exc_info.value)
        assert "resubmit only the failed queries" in str(exc_info.value)
        fake_backend.upload_files.assert_called_once()
        persisted_files = fake_backend.upload_files.call_args.args[0]
        assert len(persisted_files) == 2
        from aiq_agent.agents.deep_researcher.tools.research import _research_note_path

        persisted_notes = [
            ResearchNotes.model_validate(json.loads(content.decode("utf-8"))) for _path, content in persisted_files
        ]
        query_models = [ResearchQuery.model_validate(payload) for payload in query_payloads]
        assert [note.query_topic for note in persisted_notes] == ["Good Query", "Slow Query"]
        assert persisted_files[0][0] == _research_note_path(query_models[0], persisted_notes[0], 1)
        assert persisted_files[1][0] == _research_note_path(query_models[2], persisted_notes[1], 2)
        compact_sources = agent.source_registry_middleware.get_source_list_text()
        assert compact_sources is not None
        assert "https://example.test/good" in compact_sources
        assert "https://example.test/slow" in compact_sources
        assert "https://example.test/unused" not in compact_sources

    def test_researcher_invoke_state_carries_parent_files(self):
        """Nested researcher invocations inherit parent files for StateBackend-backed skills."""
        query = ResearchQuery(
            query="CUDA OpenCL portability comparison",
            preferred_tools=["web_search_tool"],
            fallback_tools=[],
            target_components=["programming_model"],
            rationale="Supports the comparison section.",
        )
        files = {"/skills/test/SKILL.md": {"content": "skill", "encoding": "utf-8"}}
        runtime = MagicMock(state={"messages": [], "files": files})

        invoke_state = researcher_invoke_state(query, runtime)

        assert invoke_state["files"] is files
        assert invoke_state["messages"][0].content.startswith("Batch research invocation")
        assert "Batch research invocation" in invoke_state["messages"][0].content

    def test_modal_backend_is_concrete_cached_and_routes_skills_locally(self, mock_llm_provider, real_tool):
        """Modal backend creation is lazy, cached, and skill reads do not hit Modal."""
        from deepagents.backends import StateBackend

        from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent
        from aiq_agent.agents.deep_researcher.deepagents_runtime import BUILTIN_SKILL_SOURCE
        from aiq_agent.agents.deep_researcher.deepagents_runtime import SandboxConfig
        from aiq_agent.agents.deep_researcher.deepagents_runtime import SkillsConfig

        sandbox = SandboxConfig()
        agent = DeepResearcherAgent(
            llm_provider=mock_llm_provider,
            tools=[real_tool],
            skills=SkillsConfig.enabled_builtin(),
            sandbox=sandbox,
            job_id="job-123",
        )
        fake_modal_backend = MagicMock()

        with (
            patch(
                "aiq_agent.agents.deep_researcher.deepagents_runtime._create_sandbox_backend",
                return_value=fake_modal_backend,
            ) as create_backend,
        ):
            backend_one = agent.deepagents_runtime.backend
            backend_two = agent.deepagents_runtime.backend

        assert backend_one is backend_two
        assert backend_one.default is fake_modal_backend
        create_backend.assert_called_once_with(
            sandbox,
            "job-123",
        )
        assert isinstance(backend_one.routes[BUILTIN_SKILL_SOURCE], StateBackend)
        fake_modal_backend.ls.assert_not_called()
        fake_modal_backend.read.assert_not_called()

    def test_modal_backend_creates_sandbox_lazily(self):
        """Modal sandbox lifetime starts on first sandbox operation, not agent construction."""
        from deepagents.backends.protocol import ExecuteResponse

        from aiq_agent.agents.deep_researcher.deepagents_runtime import SandboxConfig
        from aiq_agent.agents.deep_researcher.deepagents_runtime import _create_sandbox_backend

        fake_modal_backend = MagicMock()
        fake_modal_backend.execute.return_value = ExecuteResponse(output="ok", exit_code=0)

        with patch(
            "aiq_agent.agents.deep_researcher.deepagents_runtime._create_modal_backend_now",
            return_value=fake_modal_backend,
        ) as create_modal:
            backend = _create_sandbox_backend(SandboxConfig(), "job-123")

            create_modal.assert_not_called()
            result = backend.execute("echo ok", timeout=5)

        assert result.output == "ok"
        create_modal.assert_called_once()
        fake_modal_backend.execute.assert_called_once_with("echo ok", timeout=5)

    def test_modal_backend_recreates_and_retries_once_on_not_found(self):
        """A disappeared Modal container is recreated once for the same job-scoped name."""
        import modal
        from deepagents.backends.protocol import ExecuteResponse

        from aiq_agent.agents.deep_researcher.deepagents_runtime import SandboxConfig
        from aiq_agent.agents.deep_researcher.deepagents_runtime import _create_sandbox_backend

        first_modal_backend = MagicMock()
        first_modal_backend.execute.side_effect = modal.exception.NotFoundError("gone")
        second_modal_backend = MagicMock()
        second_modal_backend.execute.return_value = ExecuteResponse(output="ok", exit_code=0)
        config = SandboxConfig()

        with patch(
            "aiq_agent.agents.deep_researcher.deepagents_runtime._create_modal_backend_now",
            side_effect=[first_modal_backend, second_modal_backend],
        ) as create_modal:
            backend = _create_sandbox_backend(config, "job-123")
            result = backend.execute("echo ok", timeout=5)

        assert result.output == "ok"
        assert create_modal.call_args_list[0].args == (config, "job-123")
        assert create_modal.call_args_list[0].kwargs == {}
        assert create_modal.call_args_list[1].args == (config, "job-123")
        assert create_modal.call_args_list[1].kwargs == {"force_new": True}
        first_modal_backend.execute.assert_called_once_with("echo ok", timeout=5)
        second_modal_backend.execute.assert_called_once_with("echo ok", timeout=5)

    def test_load_prompts_raises_when_missing(self, mock_llm_provider, real_tool, mock_create_deep_agent):
        """Missing prompts fail fast instead of silently using inline defaults."""
        with patch("aiq_agent.agents.deep_researcher.factory.create_deep_agent", return_value=mock_create_deep_agent):
            with patch(
                "aiq_agent.agents.deep_researcher.agent.load_prompt",
                side_effect=FileNotFoundError(),
            ):
                from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

                with pytest.raises(FileNotFoundError):
                    DeepResearcherAgent(
                        llm_provider=mock_llm_provider,
                        tools=[real_tool],
                    )

    @pytest.mark.asyncio
    async def test_provider_roles_used_on_init(self, mock_llm_provider, real_tool, mock_create_deep_agent):
        """Test LLM roles (planner, researcher, orchestrator) are requested when run() is invoked."""
        with patch("aiq_agent.agents.deep_researcher.factory.create_deep_agent", return_value=mock_create_deep_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )
            state = DeepResearchAgentState(messages=[HumanMessage(content="Quick query")])
            agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.com"))
            await agent.run(state)

            mock_llm_provider.get.assert_any_call(LLMRole.PLANNER)
            mock_llm_provider.get.assert_any_call(LLMRole.ROUTER)
            mock_llm_provider.get.assert_any_call(LLMRole.RESEARCHER)
            mock_llm_provider.get.assert_any_call(LLMRole.REPORT_WRITER)
            mock_llm_provider.get.assert_any_call(LLMRole.ORCHESTRATOR)
            requested_roles = [args[0] for args, _kwargs in mock_llm_provider.get.call_args_list]
            assert LLMRole.EVIDENCE_JUDGE not in requested_roles

    @pytest.mark.asyncio
    async def test_run_basic_query(self, mock_llm_provider, real_tool, mock_create_deep_agent):
        """Test run() with a basic query."""
        with patch("aiq_agent.agents.deep_researcher.factory.create_deep_agent", return_value=mock_create_deep_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )

            state = DeepResearchAgentState(messages=[HumanMessage(content="Compare CUDA vs OpenCL in depth")])
            agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.com"))

            result = await agent.run(state)

            assert result is not None
            assert result.messages is not None
            assert len(result.messages) > 0

    @pytest.mark.asyncio
    async def test_run_empty_messages(self, mock_llm_provider, real_tool, mock_create_deep_agent):
        """Test run() with empty messages."""
        with patch("aiq_agent.agents.deep_researcher.factory.create_deep_agent", return_value=mock_create_deep_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )

            state = DeepResearchAgentState(messages=[])
            agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.com"))

            result = await agent.run(state)

            assert result is not None

    @pytest.mark.asyncio
    async def test_run_with_callbacks(self, mock_llm_provider, real_tool, mock_create_deep_agent):
        """Test run() uses callbacks."""
        with patch("aiq_agent.agents.deep_researcher.factory.create_deep_agent", return_value=mock_create_deep_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            mock_callback = MagicMock()
            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
                callbacks=[mock_callback],
            )

            state = DeepResearchAgentState(messages=[HumanMessage(content="Test query")])
            agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.com"))

            await agent.run(state)

            # Callbacks should have been passed to ainvoke
            call_kwargs = mock_create_deep_agent.ainvoke.call_args
            assert call_kwargs is not None

    @pytest.mark.asyncio
    async def test_run_handles_error(self, mock_llm_provider, real_tool):
        """Test run() handles errors gracefully."""
        mock_agent = MagicMock()
        mock_agent.with_config = MagicMock(return_value=mock_agent)
        mock_agent.ainvoke = AsyncMock(side_effect=Exception("Agent error"))

        with patch("aiq_agent.agents.deep_researcher.factory.create_deep_agent", return_value=mock_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )

            state = DeepResearchAgentState(messages=[HumanMessage(content="Test query")])

            with pytest.raises(Exception, match="Agent error"):
                await agent.run(state)
            assert mock_agent.ainvoke.await_count == 1

    @pytest.mark.asyncio
    async def test_run_empty_result_messages(self, mock_llm_provider, real_tool):
        """Test run() handles empty result messages."""
        mock_agent = MagicMock()
        mock_agent.with_config = MagicMock(return_value=mock_agent)
        mock_agent.ainvoke = AsyncMock(return_value={"messages": [], "files": output_markdown_file()})

        with patch("aiq_agent.agents.deep_researcher.factory.create_deep_agent", return_value=mock_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )

            state = DeepResearchAgentState(messages=[HumanMessage(content="Test")])
            agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.com"))

            result = await agent.run(state)

            # Should handle empty messages
            assert result is not None

    @pytest.mark.asyncio
    async def test_run_replaces_final_message_with_writer_markdown(self, mock_llm_provider, real_tool):
        """The final answer comes from /shared/output.md."""
        result_messages = [
            HumanMessage(content="Original query"),
            AIMessage(content="I'll help with that."),
            ToolMessage(content="Search results here", tool_call_id="123"),
            AIMessage(content="Raw orchestrator handoff."),
        ]

        mock_agent = MagicMock()
        mock_agent.with_config = MagicMock(return_value=mock_agent)
        mock_agent.ainvoke = AsyncMock(
            return_value={
                "messages": result_messages,
                "files": output_markdown_file("Writer markdown [1].\n\n## Sources\n[1] Example: https://example.com"),
            }
        )

        with patch("aiq_agent.agents.deep_researcher.factory.create_deep_agent", return_value=mock_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )

            state = DeepResearchAgentState(messages=[HumanMessage(content="Original query")])
            agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.com"))

            result = await agent.run(state)

            assert result.messages[0].content == "Original query"
            assert result.messages[1].content == "I'll help with that."
            assert result.messages[2].content == "Search results here"
            assert (
                result.messages[3].content == "Writer markdown [1].\n\n## Sources\n[1] Example: https://example.com\n"
            )


class TestFinalMarkdownExtraction:
    """Tests for extracting the writer's final Markdown."""

    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.ainvoke = AsyncMock()
        llm.bind_tools = MagicMock(return_value=llm)
        return llm

    @pytest.fixture
    def mock_llm_provider(self, mock_llm):
        provider = LLMProvider()
        provider.set_default(mock_llm)
        provider.configure(LLMRole.ORCHESTRATOR, mock_llm)
        provider.configure(LLMRole.PLANNER, mock_llm)
        provider.configure(LLMRole.RESEARCHER, mock_llm)
        provider.configure(LLMRole.REPORT_WRITER, mock_llm)
        return provider

    @pytest.fixture
    def real_tool(self):
        return web_search_tool

    def test_extract_final_markdown_does_not_download_from_backend(self, mock_llm_provider, real_tool):
        """Final Markdown extraction only reads files returned by graph state."""
        with patch(
            "aiq_agent.agents.deep_researcher.factory.create_deep_agent",
            return_value=MagicMock(),
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])
            fake_backend = MagicMock()
            agent.deepagents_runtime._backend = fake_backend

            output = agent._extract_final_markdown({"messages": [AIMessage(content="done")], "files": {}})

            assert output is None
            fake_backend.download_files.assert_not_called()

    def test_extract_final_markdown_from_shared_output_file(self, mock_llm_provider, real_tool):
        """Final Markdown can be loaded from /shared/output.md if the writer used the shared path."""
        with patch(
            "aiq_agent.agents.deep_researcher.factory.create_deep_agent",
            return_value=MagicMock(),
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])
            report = "Shared report [1].\n\n## Sources\n[1] Example: https://example.com"
            output = agent._extract_final_markdown(
                {
                    "messages": [AIMessage(content="done")],
                    "files": {"/shared/output.md": {"content": report}},
                }
            )

            assert output == report

    def test_extract_final_markdown_ignores_orchestrator_chatter(self, mock_llm_provider, real_tool):
        """Plain messages are not accepted as final Markdown."""
        with patch(
            "aiq_agent.agents.deep_researcher.factory.create_deep_agent",
            return_value=MagicMock(),
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])
            output = agent._extract_final_markdown(
                {
                    "messages": [
                        AIMessage(content="Next distributed constraints file."),
                        AIMessage(content="Let's call get_verified_sources now."),
                    ],
                    "files": {},
                }
            )

            assert output is None

    @pytest.mark.asyncio
    async def test_run_fails_on_missing_writer_output_before_citation_verification(
        self,
        mock_llm_provider,
        real_tool,
    ):
        """Missing /shared/output.md is a writer failure, not a citation failure."""
        mock_agent = MagicMock()
        mock_agent.with_config = MagicMock(return_value=mock_agent)
        mock_agent.ainvoke = AsyncMock(
            return_value={
                "messages": [AIMessage(content="Let's call get_verified_sources now.")],
                "files": {},
            }
        )

        with patch(
            "aiq_agent.agents.deep_researcher.factory.create_deep_agent",
            return_value=mock_agent,
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])
            agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.com"))

            state = DeepResearchAgentState(messages=[HumanMessage(content="Write a report")])
            with pytest.raises(ValueError, match="writer-agent did not produce a final Markdown answer"):
                await agent.run(state)


class TestDeepResearcherCitationVerification:
    """Tests for deep researcher citation post-processing."""

    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.ainvoke = AsyncMock()
        llm.bind_tools = MagicMock(return_value=llm)
        return llm

    @pytest.fixture
    def mock_llm_provider(self, mock_llm):
        provider = LLMProvider()
        provider.set_default(mock_llm)
        provider.configure(LLMRole.ORCHESTRATOR, mock_llm)
        provider.configure(LLMRole.PLANNER, mock_llm)
        provider.configure(LLMRole.RESEARCHER, mock_llm)
        provider.configure(LLMRole.REPORT_WRITER, mock_llm)
        return provider

    @pytest.fixture
    def real_tool(self):
        return web_search_tool

    @pytest.mark.asyncio
    async def test_run_returns_report_when_verify_finds_no_valid_citations(self, mock_llm_provider, real_tool, caplog):
        """Verifier false negatives degrade to a warning instead of discarding the report."""
        from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

        report = "CUDA findings here [1].\n\n## Sources\n[1] CUDA Docs: https://docs.nvidia.com/cuda/"
        sanitized_report = f"{report}\n"
        deep_result = {
            "messages": [AIMessage(content="done")],
            "files": output_markdown_file(report),
        }

        mock_agent = MagicMock()
        mock_agent.with_config = MagicMock(return_value=mock_agent)
        mock_agent.ainvoke = AsyncMock(return_value=deep_result)

        with patch(
            "aiq_agent.agents.deep_researcher.factory.create_deep_agent",
            return_value=mock_agent,
        ):
            agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])

            # Pre-populate registry with the matching URL plus an unrelated tool source.
            agent.source_registry_middleware.registry.add(
                SourceEntry(
                    citation_key="weather_observation_tool",
                    source_type="tool_result",
                    tool_name="weather_observation_tool",
                )
            )
            agent.source_registry_middleware.registry.add(
                SourceEntry(url="https://docs.nvidia.com/cuda/", title="CUDA Docs", tool_name="web_search")
            )

            # Force the verifier to report "no valid citations" while leaving the report unchanged,
            # so we can assert post-processing does not synthesize a citation.
            with (
                patch(
                    "aiq_agent.agents.deep_researcher.agent.verify_citations",
                    return_value=MagicMock(
                        verified_report=report,
                        removed_citations=[],
                        valid_citations=[],
                    ),
                ),
                patch(
                    "aiq_agent.agents.deep_researcher.agent.sanitize_report",
                    return_value=MagicMock(sanitized_report=sanitized_report),
                ),
                caplog.at_level("WARNING", logger="aiq_agent.agents.deep_researcher.agent"),
            ):
                state = DeepResearchAgentState(messages=[HumanMessage(content="What is CUDA?")])
                result = await agent.run(state)

        assert result.messages[-1].content == sanitized_report
        assert "Citation verification found no valid citations" in caplog.text

    @pytest.mark.asyncio
    async def test_run_verifies_and_sanitizes_writer_markdown(self, mock_llm_provider, real_tool):
        """Final writer Markdown still goes through citation verification and sanitization."""
        from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

        raw_answer = "CUDA docs are authoritative [1].\n\n## Sources\n[1] CUDA Docs: https://docs.nvidia.com/cuda/"
        verified_answer = raw_answer.replace("authoritative", "official")
        sanitized_answer = verified_answer + "\n"
        deep_result = {
            "messages": [AIMessage(content="done")],
            "files": output_markdown_file(raw_answer),
        }
        mock_agent = MagicMock()
        mock_agent.with_config = MagicMock(return_value=mock_agent)
        mock_agent.ainvoke = AsyncMock(return_value=deep_result)

        with patch(
            "aiq_agent.agents.deep_researcher.factory.create_deep_agent",
            return_value=mock_agent,
        ):
            agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])
            agent.source_registry_middleware.registry.add(
                SourceEntry(url="https://docs.nvidia.com/cuda/", title="CUDA Docs", tool_name="web_search")
            )

            with (
                patch(
                    "aiq_agent.agents.deep_researcher.agent.verify_citations",
                    return_value=MagicMock(
                        verified_report=verified_answer,
                        removed_citations=[],
                        valid_citations=[MagicMock()],
                    ),
                ) as verify,
                patch(
                    "aiq_agent.agents.deep_researcher.agent.sanitize_report",
                    return_value=MagicMock(sanitized_report=sanitized_answer),
                ) as sanitize,
            ):
                state = DeepResearchAgentState(messages=[HumanMessage(content="What is CUDA?")])
                result = await agent.run(state)

        verify.assert_called_once()
        sanitize.assert_called_once_with(verified_answer)
        assert result.messages[-1].content == sanitized_answer

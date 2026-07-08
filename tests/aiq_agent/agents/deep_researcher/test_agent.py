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
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from deepagents.backends.protocol import FileUploadResponse
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import tool

from aiq_agent.agents.deep_researcher.models import DeepResearchAgentState
from aiq_agent.agents.deep_researcher.models import ResearchNotes
from aiq_agent.agents.deep_researcher.models import ResearchPlan
from aiq_agent.agents.deep_researcher.models import ResearchQuery
from aiq_agent.agents.deep_researcher.tools import research as research_module
from aiq_agent.agents.deep_researcher.tools.research import build_research_batch_tool
from aiq_agent.agents.deep_researcher.tools.research import researcher_invoke_state
from aiq_agent.common import LLMProvider
from aiq_agent.common import LLMRole
from aiq_agent.common.citation_verification import SourceEntry
from aiq_api.jobs.callbacks import AgentEventCallback


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
        with (
            patch("aiq_agent.agents.deep_researcher.factory.create_deep_agent", return_value=mock_create_deep_agent),
            # Patch backend creation so the test does not require the optional OpenShell adapter
            # (the default sandbox provider) to be installed.
            patch(
                "aiq_agent.agents.deep_researcher.deepagents_runtime._create_sandbox_backend",
                return_value=MagicMock(),
            ),
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent
            from aiq_agent.agents.deep_researcher.deepagents_runtime import DeepResearchSandboxConfig
            from aiq_agent.agents.deep_researcher.deepagents_runtime import DeepResearchSkillsConfig

            callbacks = [MagicMock()]
            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
                verbose=False,
                callbacks=callbacks,
                enable_citation_verification=False,
                skills=DeepResearchSkillsConfig(agents={"researcher-agent": ("research",)}),
                sandbox=DeepResearchSandboxConfig(app_name="custom-aiq"),
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
            assert agent.enable_citation_verification is False
            assert agent.deepagents_runtime.skill_sources_for("orchestrator") is None
            assert agent.deepagents_runtime.skill_sources_for("researcher-agent") == ["/skills/research/"]

    def test_sandbox_config_rejects_unsupported_provider(self):
        """Unsupported sandbox providers fail validation at config load (registry-backed)."""
        from pydantic import ValidationError

        from aiq_agent.agents.deep_researcher.sandbox.config import SandboxConfig

        with pytest.raises(ValidationError, match="Unsupported sandbox provider"):
            SandboxConfig(provider="not-a-real-provider")

    def test_register_uses_runtime_config_models(self):
        """NAT config uses the same skills and sandbox models as runtime."""
        from aiq_agent.agents.deep_researcher.deepagents_runtime import DeepResearchSandboxConfig
        from aiq_agent.agents.deep_researcher.deepagents_runtime import DeepResearchSkillsConfig
        from aiq_agent.agents.deep_researcher.register import DeepResearchAgentConfig

        config = DeepResearchAgentConfig(
            orchestrator_llm="llm",
            source_router_llm="source-router-llm",
            writer_llm="writer-llm",
            enable_citation_verification=False,
            skills=DeepResearchSkillsConfig(agents={"writer-agent": ("synthesis",)}),
            sandbox=DeepResearchSandboxConfig(app_name="custom-aiq", packages=["matplotlib", "pillow"]),
            max_research_concurrency=2,
            max_concurrent_source_tool_calls=3,
            max_source_tool_batch_size=4,
            domain_catalog_path="configs/domain_catalogs/deep_research_domain_catalog.yml",
            enable_source_router=False,
        )

        assert config.skills is not None
        assert config.skills.agents == {"writer-agent": ("synthesis",)}
        assert config.source_router_llm == "source-router-llm"
        assert config.writer_llm == "writer-llm"
        assert config.enable_citation_verification is False
        assert config.domain_catalog_path == "configs/domain_catalogs/deep_research_domain_catalog.yml"
        assert config.max_research_concurrency == 2
        assert config.max_concurrent_source_tool_calls == 3
        assert config.max_source_tool_batch_size == 4
        assert config.enable_source_router is False
        assert config.sandbox is not None
        assert config.sandbox.provider == "openshell"
        assert config.sandbox.app_name == "custom-aiq"
        assert config.sandbox.packages == ("matplotlib", "pillow")

    def test_register_resolves_named_runtime_config_refs(self):
        """Deep research agent config can reference config-only skills and sandbox functions."""
        from aiq_agent.agents.deep_researcher.deepagents_runtime import DeepResearchSandboxConfig
        from aiq_agent.agents.deep_researcher.deepagents_runtime import DeepResearchSkillsConfig
        from aiq_agent.agents.deep_researcher.register import DeepResearchAgentConfig
        from aiq_agent.agents.deep_researcher.register import resolve_deep_research_runtime_config

        skills = DeepResearchSkillsConfig(agents={"writer-agent": ("synthesis",)})
        sandbox = DeepResearchSandboxConfig(app_name="custom-aiq")
        builder = MagicMock()
        builder.get_function_config.side_effect = {
            "deep_research_skills": skills,
            "deep_research_sandbox": sandbox,
        }.__getitem__
        config = DeepResearchAgentConfig(
            orchestrator_llm="llm",
            skills="deep_research_skills",
            sandbox="deep_research_sandbox",
        )

        resolved_skills, resolved_sandbox = resolve_deep_research_runtime_config(config, builder)

        assert resolved_skills is skills
        assert resolved_sandbox is sandbox

    def test_modal_sandbox_name_is_job_id(self):
        """Modal sandbox names use the resolved job ID directly."""
        from aiq_agent.agents.deep_researcher.sandbox.providers.modal import _validate_modal_sandbox_name

        assert _validate_modal_sandbox_name("job-123") == "job-123"

    def test_modal_sandbox_name_rejects_invalid_job_id(self):
        """Invalid custom job IDs fail before creating a Modal sandbox."""
        from aiq_agent.agents.deep_researcher.sandbox.providers.modal import _validate_modal_sandbox_name

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
            from aiq_agent.agents.deep_researcher.deepagents_runtime import DeepResearchSkillsConfig

            synthesis_skill_source = "/skills/synthesis/"
            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
                skills=DeepResearchSkillsConfig(agents={"writer-agent": ("synthesis",)}),
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
            assert all(m in kwargs["middleware"] for m in agent.orchestrator_middleware)
            assert any(m.__class__.__name__ == "ToolVisibilityMiddleware" for m in kwargs["middleware"])
            assert "skills" not in kwargs
            assert not callable(kwargs["backend"])
            assert [tool.name for tool in kwargs["tools"]] == [
                "think",
                "get_verified_sources",
                "run_research_batch",
            ]
            assert real_tool.name not in {tool.name for tool in kwargs["tools"]}
            subagents = {subagent["name"]: subagent for subagent in kwargs["subagents"]}
            assert set(subagents) == {"source-router-agent", "planner-agent", "writer-agent"}
            assert "response_format" not in subagents["source-router-agent"]
            assert "skills" not in subagents["source-router-agent"]
            assert {tool.name for tool in subagents["source-router-agent"]["tools"]} == {"lookup_source_catalog"}
            assert real_tool.name not in {tool.name for tool in subagents["source-router-agent"]["tools"]}
            assert subagents["planner-agent"]["response_format"] is ResearchPlan
            assert "skills" not in subagents["planner-agent"]
            assert real_tool.name in {tool.name for tool in subagents["planner-agent"]["tools"]}
            assert "response_format" not in subagents["writer-agent"]
            assert subagents["writer-agent"]["tools"] == agent.writer_tools
            assert real_tool.name not in {tool.name for tool in subagents["writer-agent"]["tools"]}
            assert all(m in subagents["writer-agent"]["middleware"] for m in agent.writer_middleware)
            assert any(
                m.__class__.__name__ == "ToolVisibilityMiddleware" for m in subagents["writer-agent"]["middleware"]
            )
            assert any(
                m.__class__.__name__ == "TodoSuppressionMiddleware" for m in subagents["writer-agent"]["middleware"]
            )
            assert subagents["writer-agent"]["skills"] == [synthesis_skill_source]

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
            assert all(m in create.call_args.kwargs["middleware"] for m in agent.orchestrator_middleware)
            assert any(
                m.__class__.__name__ == "ToolVisibilityMiddleware" for m in create.call_args.kwargs["middleware"]
            )
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
            assert all(m in subagents["writer-agent"]["middleware"] for m in agent.writer_middleware)
            assert any(
                m.__class__.__name__ == "ToolVisibilityMiddleware" for m in subagents["writer-agent"]["middleware"]
            )
            assert any(
                m.__class__.__name__ == "TodoSuppressionMiddleware" for m in subagents["writer-agent"]["middleware"]
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
            subagents = {subagent["name"]: subagent for subagent in kwargs["subagents"]}
            requested_roles = [args[0] for args, _kwargs in mock_llm_provider.get.call_args_list]
            assert set(subagents) == {"planner-agent", "writer-agent"}
            assert subagents["planner-agent"]["response_format"] is ResearchPlan
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
        assert call_config == {"callbacks": agent.callbacks, "run_name": "researcher-agent"}
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

    def test_researcher_invoke_config_preserves_runtime_callbacks_and_starts_a_child_run(self):
        """Nested researchers preserve callback lineage without reusing the parent run ID."""
        runtime_callbacks = MagicMock(name="runtime_callbacks")
        fallback_callbacks = [MagicMock(name="fallback_callback")]
        parent_run_id = uuid4()
        runtime = SimpleNamespace(
            config={
                "callbacks": runtime_callbacks,
                "run_id": parent_run_id,
                "tags": ["job"],
                "metadata": {"job_id": "job-1"},
                "configurable": {"thread_id": "parent-thread", "checkpoint_ns": "parent"},
            }
        )

        config = research_module.researcher_invoke_config(runtime, fallback_callbacks)

        assert config["callbacks"] is runtime_callbacks
        assert config["run_name"] == "researcher-agent"
        assert "run_id" not in config
        assert config["tags"] == ["job"]
        assert config["metadata"] == {"job_id": "job-1"}
        assert "configurable" not in config
        assert research_module.researcher_invoke_config(None, fallback_callbacks) == {
            "callbacks": fallback_callbacks,
            "run_name": "researcher-agent",
        }

    @pytest.mark.asyncio
    async def test_researcher_event_attribution_uses_named_workflow_and_nested_agent_id(
        self,
        mock_llm_provider,
        real_tool,
    ):
        """A batched researcher emits lifecycle events and owns its nested tools."""
        from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

        event_store = MagicMock()
        callback = AgentEventCallback(event_store=event_store)
        researcher_runnable = (
            RunnableLambda(lambda _state: {"query": "researcher observability"})
            | real_tool
            | RunnableLambda(lambda _output: self._structured_notes_response("Researcher Observability"))
        )
        agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool], callbacks=[callback])
        batch_tool = self._build_batch_tool(agent, researcher_runnable)

        await batch_tool.ainvoke(
            {
                "queries": [
                    {
                        "query": f"researcher observability {index}",
                        "preferred_tools": ["web_search_tool"],
                        "fallback_tools": [],
                        "target_components": ["observability"],
                        "rationale": "Verify researcher event attribution.",
                    }
                    for index in range(2)
                ]
            },
            config={"callbacks": [callback]},
        )

        events = [call.args[0] for call in event_store.store.call_args_list]
        workflow_starts = [event for event in events if event["type"] == "workflow.start"]
        workflow_ends = [event for event in events if event["type"] == "workflow.end"]
        search_starts = [
            event for event in events if event["type"] == "tool.start" and event["name"] == "web_search_tool"
        ]

        assert [event["name"] for event in workflow_starts] == ["researcher-agent", "researcher-agent"]
        assert [event["name"] for event in workflow_ends] == ["researcher-agent", "researcher-agent"]
        researcher_ids = {event["metadata"]["agent_id"] for event in workflow_starts}
        assert len(researcher_ids) == 2
        assert len(search_starts) == 2
        assert {event["metadata"]["agent_id"] for event in search_starts} == researcher_ids

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
        from deepagents.backends import FilesystemBackend
        from deepagents.backends import StateBackend

        from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent
        from aiq_agent.agents.deep_researcher.deepagents_runtime import BUILTIN_SKILL_SOURCE
        from aiq_agent.agents.deep_researcher.deepagents_runtime import SHARED_ROUTE
        from aiq_agent.agents.deep_researcher.deepagents_runtime import DeepResearchSandboxConfig
        from aiq_agent.agents.deep_researcher.deepagents_runtime import DeepResearchSkillsConfig

        sandbox = DeepResearchSandboxConfig()
        fake_modal_backend = MagicMock()

        # The runtime now builds the sandbox provider eagerly in __init__, so the patch
        # must wrap construction, not just the later .backend access.
        with patch(
            "aiq_agent.agents.deep_researcher.deepagents_runtime._create_sandbox_backend",
            return_value=fake_modal_backend,
        ) as create_backend:
            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
                skills=DeepResearchSkillsConfig(agents={"writer-agent": ("synthesis",)}),
                sandbox=sandbox,
                job_id="job-123",
            )
            backend_one = agent.deepagents_runtime.backend
            backend_two = agent.deepagents_runtime.backend

        assert backend_one is backend_two
        assert backend_one.default is fake_modal_backend
        create_backend.assert_called_once_with(sandbox, "job-123")
        assert isinstance(backend_one.routes[BUILTIN_SKILL_SOURCE], FilesystemBackend)
        assert isinstance(backend_one.routes[SHARED_ROUTE], StateBackend)
        fake_modal_backend.ls.assert_not_called()
        fake_modal_backend.read.assert_not_called()

    # NOTE: the former test_modal_backend_creates_sandbox_lazily and
    # test_modal_backend_recreates_and_retries_once_on_not_found tested 284's inline
    # _create_modal_backend_now / _LazyModalSandboxBackend internals, which are now
    # replaced by the provider-neutral sandbox package. Lazy session creation and
    # idempotency-gated retry are covered by tests/.../sandbox/test_sandbox_runtime.py
    # (note: our provider intentionally does NOT retry the non-idempotent execute()).

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

    def test_extract_final_markdown_salvages_substantive_inline_report(self, mock_llm_provider, real_tool):
        """A substantive report emitted inline (no output file) is salvaged, unlike plain chatter."""
        with patch(
            "aiq_agent.agents.deep_researcher.factory.create_deep_agent",
            return_value=MagicMock(),
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])
            report = (
                "# Quarterly CapEx Report\n\n"
                + "NVIDIA and Samsung capital expenditure analysis across quarters. " * 12
                + "\n\n## Sources\n[1] Example: https://example.com"
            )
            output = agent._extract_final_markdown({"messages": [AIMessage(content=report)], "files": {}})

            assert output == report.strip()

    def test_extract_final_markdown_rejects_writer_completion_marker(self, mock_llm_provider, real_tool):
        """The short writer completion marker is never salvaged as the report."""
        with patch(
            "aiq_agent.agents.deep_researcher.factory.create_deep_agent",
            return_value=MagicMock(),
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])
            output = agent._extract_final_markdown(
                {"messages": [AIMessage(content="Wrote /shared/output.md")], "files": {}}
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

    @pytest.mark.asyncio
    async def test_run_salvages_inline_report_when_writer_output_missing(self, mock_llm_provider, real_tool):
        """A substantive inline report is salvaged into the final message when no output file exists."""
        report = (
            "# CapEx Report\n\n"
            + "Detailed multi-quarter capital expenditure narrative for the comparison [1]. " * 12
            + "\n\n## Sources\n[1] Example: https://example.com"
        )
        result_messages = [
            HumanMessage(content="Original query"),
            AIMessage(content=report),
        ]

        mock_agent = MagicMock()
        mock_agent.with_config = MagicMock(return_value=mock_agent)
        mock_agent.ainvoke = AsyncMock(return_value={"messages": result_messages, "files": {}})

        with patch(
            "aiq_agent.agents.deep_researcher.factory.create_deep_agent",
            return_value=mock_agent,
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])
            agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.com"))

            state = DeepResearchAgentState(messages=[HumanMessage(content="Original query")])
            result = await agent.run(state)

            assert "# CapEx Report" in result.messages[-1].content

    @pytest.mark.asyncio
    async def test_run_seeds_parent_sources_for_delta_citation_verification(
        self,
        mock_llm_provider,
        real_tool,
    ):
        """Delta reports may preserve parent citations that must be valid in the child registry."""
        parent_url = "https://parent.example/source"
        report = f"Preserved parent claim [1].\n\n## Sources\n[1] Parent: {parent_url}"
        parent_context = {
            "parent_job_id": "parent-job-1",
            "source_summary_markdown": f"- [1] Parent: {parent_url}",
            "sources": [
                {
                    "url": parent_url,
                    "title": "Parent",
                    "source_type": "parent_report",
                    "tool_name": "parent_report",
                }
            ],
        }
        mock_agent = MagicMock()
        mock_agent.with_config = MagicMock(return_value=mock_agent)
        mock_agent.ainvoke = AsyncMock(
            return_value={
                "messages": [AIMessage(content="Wrote /shared/output.md")],
                "files": {
                    **output_markdown_file(report),
                    "/shared/parent_report_context.json": {"content": json.dumps(parent_context)},
                },
            }
        )

        with patch(
            "aiq_agent.agents.deep_researcher.factory.create_deep_agent",
            return_value=mock_agent,
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])
            state = DeepResearchAgentState(
                messages=[HumanMessage(content="Add OpenShell")],
                files={
                    "/shared/parent_report_context.json": json.dumps(parent_context),
                },
            )

            result = await agent.run(state)

            assert "[1] Parent: https://parent.example/source" in result.messages[-1].content
            assert agent.source_registry_middleware.active_registry().has_url(parent_url)
            assert agent.source_registry_middleware.get_source_entries(mode="compact")[0].url == parent_url


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

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

"""Tests for DeepAgents runtime config, skill collection resolution, and backend wiring."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from deepagents.backends import CompositeBackend
from deepagents.backends import FilesystemBackend
from deepagents.backends import StateBackend
from pydantic import ValidationError

from aiq_agent.agents.deep_researcher.deepagents_runtime import BUILTIN_SKILL_SOURCE
from aiq_agent.agents.deep_researcher.deepagents_runtime import SHARED_ROUTE
from aiq_agent.agents.deep_researcher.deepagents_runtime import DeepAgentsRuntime
from aiq_agent.agents.deep_researcher.deepagents_runtime import DeepResearchSandboxConfig
from aiq_agent.agents.deep_researcher.deepagents_runtime import DeepResearchSkillsConfig
from aiq_agent.agents.deep_researcher.deepagents_runtime import discover_skill_collections
from aiq_agent.agents.deep_researcher.deepagents_runtime import resolve_skill_collections

SYNTHESIS_SKILL_SOURCE = f"{BUILTIN_SKILL_SOURCE}synthesis/"


class TestSkillCollections:
    """Public skill config uses collection names, not DeepAgents virtual paths."""

    def test_builtin_skill_collections_are_discovered(self) -> None:
        collections = discover_skill_collections()

        assert collections["research"] == "/skills/research/"
        assert collections["synthesis"] == "/skills/synthesis/"

    def test_nested_skill_collections_are_discovered(self, tmp_path) -> None:
        skill_dir = tmp_path / "finance" / "earnings" / "quarterly-summary"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: quarterly-summary\n---\n", encoding="utf-8")

        assert discover_skill_collections(tmp_path) == {"finance/earnings": "/skills/finance/earnings/"}

    def test_resolve_skill_collections_maps_names_to_sources(self) -> None:
        assert resolve_skill_collections(("synthesis",)) == ("/skills/synthesis/",)

    def test_resolve_skill_collections_rejects_unknown_names(self) -> None:
        with pytest.raises(ValueError, match="Unknown deep research skill collection"):
            resolve_skill_collections(("typo",))

    def test_skills_config_forbids_old_fields(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            DeepResearchSkillsConfig(enabled=True)


class TestDeepAgentsRuntimeRouting:
    """Runtime uses stock DeepAgents backends with only the routes required."""

    def test_baseline_uses_plain_state_backend(self) -> None:
        runtime = DeepAgentsRuntime()

        assert isinstance(runtime.backend, StateBackend)
        assert runtime.execution_enabled is False
        assert runtime.skills_enabled is False

    def test_skills_only_adds_skills_route(self) -> None:
        runtime = DeepAgentsRuntime(
            skills=DeepResearchSkillsConfig(agents={"writer-agent": ("synthesis",)}),
        )
        backend = runtime.backend

        assert isinstance(backend, CompositeBackend)
        assert isinstance(backend.default, StateBackend)
        assert set(backend.routes) == {BUILTIN_SKILL_SOURCE}
        assert isinstance(backend.routes[BUILTIN_SKILL_SOURCE], FilesystemBackend)
        assert runtime.skill_sources_for("writer-agent") == [SYNTHESIS_SKILL_SOURCE]

    def test_sandbox_only_adds_shared_route(self) -> None:
        fake_sandbox = MagicMock()
        with patch(
            "aiq_agent.agents.deep_researcher.deepagents_runtime._create_sandbox_backend",
            return_value=fake_sandbox,
        ):
            runtime = DeepAgentsRuntime(sandbox=DeepResearchSandboxConfig())
            backend = runtime.backend

        assert isinstance(backend, CompositeBackend)
        assert backend.default is fake_sandbox
        assert set(backend.routes) == {SHARED_ROUTE}
        assert runtime.execution_enabled is True
        assert runtime.skills_enabled is False

    def test_prepare_state_files_preserves_shared_paths_without_route(self) -> None:
        runtime = DeepAgentsRuntime()

        files = runtime.prepare_state_files({"/shared/original_report.md": "# Parent"})

        assert "/shared/original_report.md" in files
        assert files["/shared/original_report.md"]["content"] == "# Parent"
        assert "modified_at" in files["/shared/original_report.md"]

    def test_prepare_state_files_normalizes_shared_paths_for_route_backend(self) -> None:
        with patch(
            "aiq_agent.agents.deep_researcher.deepagents_runtime._create_sandbox_backend",
            return_value=MagicMock(),
        ):
            runtime = DeepAgentsRuntime(sandbox=DeepResearchSandboxConfig())

        files = runtime.prepare_state_files(
            {
                "/shared/original_report.md": "# Parent",
                "/shared/source_summary.md": b"- src",
            }
        )

        assert "/original_report.md" in files
        assert "/source_summary.md" in files
        assert "/shared/original_report.md" not in files
        assert "/shared/source_summary.md" not in files
        assert files["/original_report.md"]["content"] == "# Parent"
        assert files["/source_summary.md"]["content"] == "- src"
        assert "modified_at" in files["/original_report.md"]

    def test_sandbox_and_skills_add_shared_and_skills_routes(self) -> None:
        fake_sandbox = MagicMock()
        skills = DeepResearchSkillsConfig(agents={"researcher-agent": ("research",)})
        with patch(
            "aiq_agent.agents.deep_researcher.deepagents_runtime._create_sandbox_backend",
            return_value=fake_sandbox,
        ):
            runtime = DeepAgentsRuntime(skills=skills, sandbox=DeepResearchSandboxConfig())
            backend = runtime.backend

        assert isinstance(backend, CompositeBackend)
        assert backend.default is fake_sandbox
        assert set(backend.routes) == {BUILTIN_SKILL_SOURCE, SHARED_ROUTE}
        assert isinstance(backend.routes[BUILTIN_SKILL_SOURCE], FilesystemBackend)
        assert isinstance(backend.routes[SHARED_ROUTE], StateBackend)
        assert runtime.skill_sources_for("researcher-agent") == ["/skills/research/"]

    def test_require_sandbox_collection_without_sandbox_raises(self) -> None:
        skills = DeepResearchSkillsConfig(
            agents={"researcher-agent": ("research",)},
            require_sandbox=("research",),
        )

        with pytest.raises(ValueError, match="require a sandbox"):
            DeepAgentsRuntime(skills=skills)

    def test_skills_config_rejects_unknown_agent_keys(self) -> None:
        with pytest.raises(ValidationError, match="Unknown deep research skill agent"):
            DeepResearchSkillsConfig(agents={"researcher": ("research",)})

    def test_require_sandbox_collection_with_sandbox_is_allowed(self) -> None:
        skills = DeepResearchSkillsConfig(
            agents={"researcher-agent": ("research",)},
            require_sandbox=("research",),
        )
        # Patch backend creation so the test does not require the optional OpenShell adapter
        # (the default provider) to be installed.
        with patch(
            "aiq_agent.agents.deep_researcher.deepagents_runtime._create_sandbox_backend",
            return_value=MagicMock(),
        ):
            runtime = DeepAgentsRuntime(skills=skills, sandbox=DeepResearchSandboxConfig())

        assert runtime.skill_sources_for("researcher-agent") == ["/skills/research/"]

    def test_require_sandbox_collection_with_sandbox_still_rejects_unknown_names(self) -> None:
        skills = DeepResearchSkillsConfig(
            agents={"researcher-agent": ("research",)},
            require_sandbox=("typo",),
        )

        with pytest.raises(ValueError, match="Unknown deep research skill collection"):
            DeepAgentsRuntime(skills=skills, sandbox=DeepResearchSandboxConfig())

    def test_deepagents_skill_scanner_finds_synthesis_skills_from_nested_source(self) -> None:
        from deepagents.middleware.skills import _list_skills

        runtime = DeepAgentsRuntime(skills=DeepResearchSkillsConfig(agents={"writer-agent": ("synthesis",)}))
        backend = runtime.backend

        top_level_skills = _list_skills(backend, BUILTIN_SKILL_SOURCE)
        synthesis_skills = _list_skills(backend, SYNTHESIS_SKILL_SOURCE)

        assert [skill["name"] for skill in top_level_skills] == []
        assert [skill["name"] for skill in synthesis_skills] == [
            "long-form-report-writer",
            "prediction-report-writer",
        ]
        assert [skill["path"] for skill in synthesis_skills] == [
            "/skills/synthesis/long-form-report-writer/SKILL.md",
            "/skills/synthesis/prediction-report-writer/SKILL.md",
        ]

    def test_deepagents_subagent_skills_key_adds_skills_middleware(self) -> None:
        from deepagents import create_deep_agent

        fake_graph = MagicMock()
        fake_graph.with_config.return_value = fake_graph
        create_agent_calls: list[dict[str, Any]] = []

        def fake_create_agent(*_args: Any, **kwargs: Any) -> MagicMock:
            create_agent_calls.append(kwargs)
            return fake_graph

        fake_model = MagicMock()
        profile = MagicMock()
        profile.tool_description_overrides = {}
        profile.excluded_tools = []
        profile.excluded_middleware = []
        profile.materialize_extra_middleware.return_value = []
        profile.general_purpose_subagent = MagicMock(enabled=False)
        profile.base_system_prompt = None
        profile.system_prompt_suffix = None

        with (
            patch("deepagents.graph.resolve_model", return_value=fake_model),
            patch("deepagents._models.resolve_model", return_value=fake_model),
            patch("deepagents.graph._harness_profile_for_model", return_value=profile),
            patch("deepagents.graph.create_summarization_middleware", return_value=MagicMock()),
            patch("deepagents.graph.create_agent", side_effect=fake_create_agent),
            patch("deepagents.middleware.subagents.create_agent", side_effect=fake_create_agent),
        ):
            create_deep_agent(
                model=fake_model,
                tools=[],
                subagents=[
                    {
                        "name": "writer-agent",
                        "description": "Writes the final answer.",
                        "system_prompt": "Write.",
                        "skills": [SYNTHESIS_SKILL_SOURCE],
                    }
                ],
                backend=StateBackend(),
                skills=[BUILTIN_SKILL_SOURCE],
            )

        writer_middleware = create_agent_calls[0]["middleware"]
        writer_skills = [m for m in writer_middleware if m.__class__.__name__ == "SkillsMiddleware"]
        assert len(writer_skills) == 1
        assert writer_skills[0].sources == [SYNTHESIS_SKILL_SOURCE]


class TestDeepAgentsRuntimeJobId:
    """job_id should drive the sandbox name; a missing one falls back to uuid."""

    def test_default_sandbox_provider_is_openshell(self) -> None:
        sandbox = DeepResearchSandboxConfig()

        assert sandbox.provider == "openshell"
        assert sandbox.workdir is None

    def test_explicit_job_id_is_kept(self) -> None:
        sandbox = DeepResearchSandboxConfig()
        with patch("aiq_agent.agents.deep_researcher.deepagents_runtime._create_sandbox_backend") as create_backend:
            runtime = DeepAgentsRuntime(sandbox=sandbox, job_id="job-abc-123")
            _ = runtime.backend

        create_backend.assert_called_once_with(sandbox, "job-abc-123")

    def test_missing_job_id_generates_uuid(self) -> None:
        sandbox_a = DeepResearchSandboxConfig()
        sandbox_b = DeepResearchSandboxConfig()
        with patch("aiq_agent.agents.deep_researcher.deepagents_runtime._create_sandbox_backend") as create_backend:
            runtime_a = DeepAgentsRuntime(sandbox=sandbox_a)
            runtime_b = DeepAgentsRuntime(sandbox=sandbox_b)
            _ = runtime_a.backend
            _ = runtime_b.backend

        job_id_a = create_backend.call_args_list[0].args[1]
        job_id_b = create_backend.call_args_list[1].args[1]
        assert len(job_id_a) == 36
        assert job_id_a != job_id_b

    def test_modal_sandbox_config_requires_provider_dependencies(self) -> None:
        def find_spec(module_name: str):
            if module_name == "langchain_modal":
                return None
            return object()

        with (
            patch(
                "aiq_agent.agents.deep_researcher.deepagents_runtime.importlib.util.find_spec", side_effect=find_spec
            ),
            pytest.raises(ImportError, match="langchain-modal"),
        ):
            _ = DeepAgentsRuntime(sandbox=DeepResearchSandboxConfig(provider="modal")).backend

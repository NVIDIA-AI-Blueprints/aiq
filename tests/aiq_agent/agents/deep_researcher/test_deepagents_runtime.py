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

"""Tests for DeepAgentsRuntime, especially the StateBackend error-path wrapper.

Background: deepagents' CompositeBackend strips the route prefix before
delegating to a routed StateBackend. The success path is restored via
``WriteResult.path``, but error messages embed the stripped key, which
caused the failing trajectory in PR #211: a nested research worker saw
``Cannot write to /0_weather_data.txt`` instead of ``/shared/0_weather_data.txt``
and chased the phantom path through the sandbox shell.

StateBackend itself reads/writes via LangGraph's RunnableConfig channel API
and cannot be exercised in isolation. We patch the two channel helpers
(``_read_files`` / ``_send_files_update``) with a plain dict so the wrapper's
path-rewriting behavior can be tested without spinning up a graph.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from deepagents.backends import CompositeBackend

from aiq_agent.agents.deep_researcher import deepagents_runtime as runtime_mod
from aiq_agent.agents.deep_researcher.deepagents_runtime import BUILTIN_SKILL_SOURCE
from aiq_agent.agents.deep_researcher.deepagents_runtime import SHARED_ROUTE
from aiq_agent.agents.deep_researcher.deepagents_runtime import DeepAgentsRuntime
from aiq_agent.agents.deep_researcher.deepagents_runtime import SandboxConfig
from aiq_agent.agents.deep_researcher.deepagents_runtime import SkillsConfig
from aiq_agent.agents.deep_researcher.deepagents_runtime import _builtin_skill_state_files
from aiq_agent.agents.deep_researcher.deepagents_runtime import _PrefixedStateBackend

SYNTHESIS_SKILL_SOURCE = f"{BUILTIN_SKILL_SOURCE}synthesis/"


def _attach_dict_state(backend: _PrefixedStateBackend, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Replace StateBackend's LangGraph channel I/O with a plain dict.

    Returns the state dict so tests can inspect or seed it directly.
    """
    files: dict[str, Any] = state if state is not None else {}

    def _read_files() -> dict[str, Any]:
        return files

    def _send_files_update(update: dict[str, Any]) -> None:
        files.update(update)

    backend._read_files = _read_files  # type: ignore[method-assign]
    backend._send_files_update = _send_files_update  # type: ignore[method-assign]
    return files


class TestPrefixedStateBackend:
    """The wrapper exists to keep error messages aligned with the user-visible path."""

    def test_write_then_overwrite_error_uses_full_path(self) -> None:
        backend = _PrefixedStateBackend(SHARED_ROUTE)
        _attach_dict_state(backend)

        first = backend.write("/notes.md", "hello")
        assert first.error is None
        assert first.path == "/notes.md"

        second = backend.write("/notes.md", "again")
        assert second.error is not None
        # The whole point of the wrapper: error must reference /shared/notes.md,
        # NOT the stripped /notes.md key that vanilla StateBackend reports.
        assert "/shared/notes.md" in second.error
        assert second.error.startswith("Cannot write to /shared/notes.md")

    def test_edit_error_uses_full_path_when_file_missing(self) -> None:
        backend = _PrefixedStateBackend(SHARED_ROUTE)
        _attach_dict_state(backend)
        # File does not exist; StateBackend.edit reports the (stripped) path it received.
        result = backend.edit("/missing.md", "old", "new")
        assert result.error is not None
        assert "/shared/missing.md" in result.error

    def test_read_missing_file_error_uses_full_path(self) -> None:
        # Same bug as write/edit: StateBackend.read embeds the stripped key in
        # its "File '/X' not found" error. The wrapper must restore /shared/X.
        backend = _PrefixedStateBackend(SHARED_ROUTE)
        _attach_dict_state(backend)
        result = backend.read("/missing.json")
        assert result.error is not None
        assert "/shared/missing.json" in result.error
        assert result.error.startswith("File '/shared/missing.json'")

    def test_read_existing_file_passes_through(self) -> None:
        backend = _PrefixedStateBackend(SHARED_ROUTE)
        _attach_dict_state(backend)
        backend.write("/notes.md", "hello")
        result = backend.read("/notes.md")
        assert result.error is None
        assert result.file_data is not None

    def test_edit_error_without_path_is_passed_through_unchanged(self) -> None:
        # StateBackend's "string not found" error does not embed the path, so
        # the wrapper should be a no-op for it (vs. spuriously injecting the
        # full path into an unrelated error string).
        backend = _PrefixedStateBackend(SHARED_ROUTE)
        _attach_dict_state(backend)
        backend.write("/notes.md", "hello world")
        result = backend.edit("/notes.md", "GOODBYE", "BYE")
        assert result.error is not None
        assert "GOODBYE" in result.error
        # The wrapper does not invent a path on errors that don't reference one.
        assert "/shared/" not in result.error

    def test_skill_route_prefix(self) -> None:
        # Same wrapper used for the skills route — confirm its prefix sticks.
        backend = _PrefixedStateBackend(BUILTIN_SKILL_SOURCE)
        _attach_dict_state(backend)
        backend.write("/foo/SKILL.md", "stub")
        result = backend.write("/foo/SKILL.md", "again")
        assert result.error is not None
        assert "/skills/foo/SKILL.md" in result.error

    def test_successful_write_path_unchanged(self) -> None:
        # Success case: the wrapper must not corrupt result.path
        # (CompositeBackend rewrites it back to the full path itself).
        backend = _PrefixedStateBackend(SHARED_ROUTE)
        _attach_dict_state(backend)
        result = backend.write("/notes.md", "hello")
        assert result.error is None
        # Wrapper passes the StateBackend-relative path through unchanged.
        # CompositeBackend is responsible for restoring the full path.
        assert result.path == "/notes.md"


class TestDeepAgentsRuntimeRouting:
    """Confirm DeepAgentsRuntime wires the wrapper into both routes dicts."""

    def test_no_sandbox_uses_prefixed_state_backend_for_routes(self) -> None:
        runtime = DeepAgentsRuntime(skills=SkillsConfig.enabled_builtin())
        backend = runtime.backend
        assert isinstance(backend, CompositeBackend)
        # CompositeBackend stores routes as a list of (prefix, backend) tuples.
        routes_by_prefix = dict(backend.sorted_routes)
        assert SHARED_ROUTE in routes_by_prefix
        assert BUILTIN_SKILL_SOURCE in routes_by_prefix
        assert isinstance(routes_by_prefix[SHARED_ROUTE], _PrefixedStateBackend)
        assert isinstance(routes_by_prefix[BUILTIN_SKILL_SOURCE], _PrefixedStateBackend)

    def test_shared_glob_routes_locally_without_touching_sandbox_default(self) -> None:
        fake_sandbox = MagicMock()
        fake_sandbox.glob.side_effect = AssertionError("sandbox glob should not be called for /shared patterns")

        with patch(
            "aiq_agent.agents.deep_researcher.deepagents_runtime._create_sandbox_backend",
            return_value=fake_sandbox,
        ):
            runtime = DeepAgentsRuntime(sandbox=SandboxConfig())
            backend = runtime.backend

        shared_backend = backend.routes[SHARED_ROUTE]
        _attach_dict_state(
            shared_backend,
            {
                "/plan.json": {"content": "{}", "modified_at": "2026-01-01T00:00:00"},
                "/00_research_notes.json": {"content": "{}", "modified_at": "2026-01-01T00:00:01"},
                "/notes.txt": {"content": "not json", "modified_at": "2026-01-01T00:00:02"},
            },
        )

        result = backend.glob("/shared/*.json")

        assert result.error is None
        assert sorted(match["path"] for match in result.matches) == [
            "/shared/00_research_notes.json",
            "/shared/plan.json",
        ]
        fake_sandbox.glob.assert_not_called()

    def test_builtin_skill_state_files_include_nested_synthesis_skills(self) -> None:
        files = _builtin_skill_state_files()
        assert "/research-sandbox/data-table-analysis/SKILL.md" in files
        assert "/research-sandbox/forecast-analysis/SKILL.md" in files
        assert "/research-sandbox/lightweight-calculation/SKILL.md" in files
        assert "/synthesis/long-form-report-writer/SKILL.md" in files
        assert "/synthesis/prediction-report-writer/SKILL.md" in files
        assert "Data Table Analysis Skill" in files["/research-sandbox/data-table-analysis/SKILL.md"]["content"]
        assert "Forecast Analysis Skill" in files["/research-sandbox/forecast-analysis/SKILL.md"]["content"]
        assert "Lightweight Calculation Skill" in files["/research-sandbox/lightweight-calculation/SKILL.md"]["content"]
        assert "Long-Form Report Writer Skill" in files["/synthesis/long-form-report-writer/SKILL.md"]["content"]
        assert (
            "Treat `required_components` as a coverage checklist"
            in (files["/synthesis/long-form-report-writer/SKILL.md"]["content"])
        )
        assert "target 3000-5000+ words" in files["/synthesis/long-form-report-writer/SKILL.md"]["content"]
        assert (
            "Do not produce a sequence of short, isolated bullet points"
            in (files["/synthesis/long-form-report-writer/SKILL.md"]["content"])
        )
        assert "Prediction Report Writer Skill" in files["/synthesis/prediction-report-writer/SKILL.md"]["content"]

    def test_builtin_skill_state_files_only_include_supported_text_files(self, tmp_path, monkeypatch) -> None:
        skill_dir = tmp_path / "demo-skill"
        scripts_dir = skill_dir / "scripts"
        references_dir = skill_dir / "references"
        hidden_dir = skill_dir / ".hidden"
        pycache_dir = skill_dir / "__pycache__"
        scripts_dir.mkdir(parents=True)
        references_dir.mkdir()
        hidden_dir.mkdir()
        pycache_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Demo Skill\n", encoding="utf-8")
        (scripts_dir / "helper.py").write_text("print('demo')\n", encoding="utf-8")
        (references_dir / "notes.md").write_text("reference notes\n", encoding="utf-8")
        (hidden_dir / "ignored.md").write_text("hidden notes\n", encoding="utf-8")
        (pycache_dir / "ignored.md").write_text("cached notes\n", encoding="utf-8")
        (skill_dir / "asset.bin").write_bytes(b"\xff\xfe\x00\x00")

        monkeypatch.setattr(runtime_mod, "BUILTIN_SKILLS_DIR", tmp_path)

        collected_paths = [path for path, _ in runtime_mod._collect_builtin_skill_files()]
        files = runtime_mod._builtin_skill_state_files()

        assert collected_paths == [
            "/skills/demo-skill/SKILL.md",
            "/skills/demo-skill/references/notes.md",
        ]
        assert "/demo-skill/SKILL.md" in files
        assert "/demo-skill/references/notes.md" in files
        assert "/demo-skill/scripts/helper.py" not in files
        assert "/demo-skill/.hidden/ignored.md" not in files
        assert "/demo-skill/__pycache__/ignored.md" not in files
        assert "/demo-skill/asset.bin" not in files
        assert files["/demo-skill/references/notes.md"]["content"] == "reference notes\n"

    def test_skill_sources_return_none_when_disabled(self) -> None:
        runtime = DeepAgentsRuntime()
        assert runtime.skill_sources_for("orchestrator") is None

    def test_skill_sources_are_explicit_per_agent(self) -> None:
        runtime = DeepAgentsRuntime(skills=SkillsConfig.enabled_builtin())
        assert runtime.skill_sources_for("researcher") == [BUILTIN_SKILL_SOURCE]
        assert runtime.skill_sources_for("writer-agent") == [BUILTIN_SKILL_SOURCE]
        assert runtime.skill_sources_for("orchestrator") is None
        assert runtime.skill_sources_for("future-agent") is None

    def test_deprecated_sources_alias_warns_and_is_ignored(self) -> None:
        with pytest.warns(DeprecationWarning, match="SkillsConfig.sources is deprecated and ignored"):
            config = SkillsConfig(enabled=True, sources=("/custom-skills/",))

        assert config.agent_sources == {}
        runtime = DeepAgentsRuntime(skills=config)
        assert runtime.skill_sources_for("researcher") is None

    def test_deprecated_default_sources_warns_and_is_ignored(self) -> None:
        with pytest.warns(DeprecationWarning, match="SkillsConfig.default_sources is deprecated and ignored"):
            config = SkillsConfig(enabled=True, default_sources=("/new-skills/",))

        assert config.agent_sources == {}
        runtime = DeepAgentsRuntime(skills=config)
        assert runtime.skill_sources_for("researcher") is None

    def test_agent_specific_sources_are_used_for_matching_agent_only(self) -> None:
        runtime = DeepAgentsRuntime(
            skills=SkillsConfig(
                enabled=True,
                agent_sources={"writer-agent": (SYNTHESIS_SKILL_SOURCE,)},
            )
        )

        assert runtime.skill_sources_for("writer-agent") == [SYNTHESIS_SKILL_SOURCE]
        assert runtime.skill_sources_for("planner-agent") is None

    def test_empty_agent_specific_sources_disable_that_agent(self) -> None:
        runtime = DeepAgentsRuntime(
            skills=SkillsConfig(
                enabled=True,
                agent_sources={"writer-agent": ()},
            )
        )

        assert runtime.skill_sources_for("writer-agent") is None
        assert runtime.skill_sources_for("planner-agent") is None

    def test_sandbox_required_source_without_sandbox_raises(self) -> None:
        runtime = DeepAgentsRuntime(
            skills=SkillsConfig(
                enabled=True,
                agent_sources={"writer-agent": (SYNTHESIS_SKILL_SOURCE,)},
                sandbox_required_sources=(BUILTIN_SKILL_SOURCE,),
            )
        )

        with pytest.raises(ValueError, match="writer-agent.*require a sandbox backend"):
            runtime.skill_sources_for("writer-agent")

    def test_sandbox_required_source_with_sandbox_is_allowed(self) -> None:
        runtime = DeepAgentsRuntime(
            skills=SkillsConfig(
                enabled=True,
                agent_sources={"writer-agent": (SYNTHESIS_SKILL_SOURCE,)},
                sandbox_required_sources=(BUILTIN_SKILL_SOURCE,),
            ),
            sandbox=SandboxConfig(),
        )

        assert runtime.skill_sources_for("writer-agent") == [SYNTHESIS_SKILL_SOURCE]

    def test_deepagents_skill_scanner_finds_synthesis_skills_from_nested_source(self) -> None:
        from deepagents.middleware.skills import _list_skills

        runtime = DeepAgentsRuntime(skills=SkillsConfig.enabled_builtin())
        backend = runtime.backend
        files = _builtin_skill_state_files()
        for _prefix, route_backend in backend.sorted_routes:
            if isinstance(route_backend, _PrefixedStateBackend):
                _attach_dict_state(route_backend, files)

        top_level_skills = _list_skills(backend, BUILTIN_SKILL_SOURCE)
        research_sandbox_skills = _list_skills(backend, f"{BUILTIN_SKILL_SOURCE}research-sandbox/")
        synthesis_skills = _list_skills(backend, SYNTHESIS_SKILL_SOURCE)

        assert [skill["name"] for skill in top_level_skills] == []
        assert [skill["name"] for skill in research_sandbox_skills] == [
            "data-table-analysis",
            "forecast-analysis",
            "lightweight-calculation",
        ]
        assert [skill["path"] for skill in research_sandbox_skills] == [
            "/skills/research-sandbox/data-table-analysis/SKILL.md",
            "/skills/research-sandbox/forecast-analysis/SKILL.md",
            "/skills/research-sandbox/lightweight-calculation/SKILL.md",
        ]
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
        from deepagents.backends import StateBackend

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

    def test_explicit_job_id_is_kept(self) -> None:
        sandbox = SandboxConfig()
        with patch("aiq_agent.agents.deep_researcher.deepagents_runtime._create_sandbox_backend") as create_backend:
            runtime = DeepAgentsRuntime(sandbox=sandbox, job_id="job-abc-123")
            _ = runtime.backend

        create_backend.assert_called_once_with(sandbox, "job-abc-123")

    def test_missing_job_id_generates_uuid(self) -> None:
        sandbox_a = SandboxConfig()
        sandbox_b = SandboxConfig()
        with patch("aiq_agent.agents.deep_researcher.deepagents_runtime._create_sandbox_backend") as create_backend:
            runtime_a = DeepAgentsRuntime(sandbox=sandbox_a)
            runtime_b = DeepAgentsRuntime(sandbox=sandbox_b)
            _ = runtime_a.backend
            _ = runtime_b.backend

        job_id_a = create_backend.call_args_list[0].args[1]
        job_id_b = create_backend.call_args_list[1].args[1]
        # uuid4 strings are 36 chars, distinct between instances.
        assert len(job_id_a) == 36
        assert job_id_a != job_id_b

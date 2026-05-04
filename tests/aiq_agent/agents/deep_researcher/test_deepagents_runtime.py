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
caused the failing trajectory in PR #211: a researcher subagent saw
``Cannot write to /0_weather_data.txt`` instead of ``/shared/0_weather_data.txt``
and chased the phantom path through the sandbox shell.

StateBackend itself reads/writes via LangGraph's RunnableConfig channel API
and cannot be exercised in isolation. We patch the two channel helpers
(``_read_files`` / ``_send_files_update``) with a plain dict so the wrapper's
path-rewriting behavior can be tested without spinning up a graph.
"""

from __future__ import annotations

from typing import Any

from deepagents.backends import CompositeBackend

from aiq_agent.agents.deep_researcher.deepagents_runtime import BUILTIN_SKILL_SOURCE
from aiq_agent.agents.deep_researcher.deepagents_runtime import SHARED_ROUTE
from aiq_agent.agents.deep_researcher.deepagents_runtime import DeepAgentsRuntime
from aiq_agent.agents.deep_researcher.deepagents_runtime import SkillsConfig
from aiq_agent.agents.deep_researcher.deepagents_runtime import _PrefixedStateBackend


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


class TestDeepAgentsRuntimeJobId:
    """job_id should drive the sandbox name; a missing one falls back to uuid."""

    def test_explicit_job_id_is_kept(self) -> None:
        runtime = DeepAgentsRuntime(job_id="job-abc-123")
        assert runtime.job_id == "job-abc-123"

    def test_missing_job_id_generates_uuid(self) -> None:
        runtime_a = DeepAgentsRuntime()
        runtime_b = DeepAgentsRuntime()
        # uuid4 strings are 36 chars, distinct between instances.
        assert len(runtime_a.job_id) == 36
        assert runtime_a.job_id != runtime_b.job_id

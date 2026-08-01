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

"""Tests for custom middleware."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from deepagents.backends import CompositeBackend
from deepagents.backends import StateBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.messages import ToolMessage

from aiq_agent.agents.deep_researcher.custom_middleware import ArtifactHarvestMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import ExecuteTimeoutClampMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import FilesystemToolCallGuardMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import FinalReportCommitMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import FinalReportCommitTracker
from aiq_agent.agents.deep_researcher.custom_middleware import FinalReportOwnershipGuardMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import PlanPersistenceMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import RequiredOutputFileMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import SourceRegistryMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import SourceRoutingGuardMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import SourceRoutingPersistenceMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import StateMutationGuardMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import TodoQuotaMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import TodoSuppressionMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import ToolNameSanitizationMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import ToolVisibilityMiddleware
from aiq_agent.agents.deep_researcher.resource_limits import DeepResearchResourceLimits
from aiq_agent.agents.deep_researcher.resource_limits import StateBudgetLedger
from aiq_agent.agents.deep_researcher.tools.source_registry import build_get_verified_sources_tool
from aiq_agent.common.citation_verification import SourceEntry
from aiq_agent.common.data_source_registry import populate_from_config
from aiq_agent.common.data_source_registry import reset_registry


class _ToolBindingFakeChatModel(FakeMessagesListChatModel):
    """Scripted chat model that accepts the tools bound by ``create_agent``."""

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self


class TestSourceRoutingGuardMiddleware:
    """Tests for the orchestrator's required source-routing transition."""

    @staticmethod
    def _request(tool_name: str, *, args: dict | None = None, files: dict | None = None) -> MagicMock:
        request = MagicMock()
        request.tool_call = {
            "name": tool_name,
            "args": args or {},
            "id": "tc1",
        }
        request.state = {"files": files or {}}
        return request

    @pytest.mark.asyncio
    async def test_blocks_other_tools_before_source_routing(self):
        """An orchestrator cannot infer source absence from filesystem inspection before routing."""
        middleware = SourceRoutingGuardMiddleware(enabled=True)
        handler = AsyncMock(return_value=ToolMessage(content="[]", tool_call_id="tc1"))

        result = await middleware.awrap_tool_call(self._request("ls", args={"path": "/shared"}), handler)

        handler.assert_not_awaited()
        assert result.status == "error"
        assert "source-router-agent" in str(result.content)

    @pytest.mark.asyncio
    async def test_allows_source_router_task_before_routing(self):
        """The required source-router task remains executable while the gate is closed."""
        middleware = SourceRoutingGuardMiddleware(enabled=True)
        expected = ToolMessage(content="Source routing complete.", tool_call_id="tc1")
        handler = AsyncMock(return_value=expected)
        request = self._request("task", args={"subagent_type": "source-router-agent"})

        result = await middleware.awrap_tool_call(request, handler)

        handler.assert_awaited_once_with(request)
        assert result is expected

    @pytest.mark.asyncio
    async def test_allows_normal_tools_after_routing_file_exists(self):
        """The gate opens once the source-router output is present in virtual state."""
        middleware = SourceRoutingGuardMiddleware(enabled=True)
        expected = ToolMessage(content="[]", tool_call_id="tc1")
        handler = AsyncMock(return_value=expected)
        request = self._request("ls", files={"/shared/source_routing.json": {"content": "{}"}})

        result = await middleware.awrap_tool_call(request, handler)

        handler.assert_awaited_once_with(request)
        assert result is expected

    @pytest.mark.asyncio
    async def test_allows_normal_tools_after_routing_file_exists_sandbox_key(self):
        """Under a sandbox provider the /shared/ route is stripped; the route-local key must also open the gate."""
        middleware = SourceRoutingGuardMiddleware(enabled=True)
        expected = ToolMessage(content="[]", tool_call_id="tc1")
        handler = AsyncMock(return_value=expected)
        request = self._request("ls", files={"/source_routing.json": {"content": "{}"}})

        result = await middleware.awrap_tool_call(request, handler)

        handler.assert_awaited_once_with(request)
        assert result is expected

    @pytest.mark.asyncio
    async def test_disabled_guard_is_noop(self):
        """Workflows with source routing disabled preserve their existing tool behavior."""
        middleware = SourceRoutingGuardMiddleware(enabled=False)
        expected = ToolMessage(content="[]", tool_call_id="tc1")
        handler = AsyncMock(return_value=expected)
        request = self._request("ls")

        result = await middleware.awrap_tool_call(request, handler)

        handler.assert_awaited_once_with(request)
        assert result is expected


class TestExecuteTimeoutClampMiddleware:
    """Tests for clamping the sandbox execute tool's per-call timeout."""

    @staticmethod
    def _request(tool_name: str, *, args: dict | None = None) -> MagicMock:
        request = MagicMock()
        request.tool_call = {"name": tool_name, "args": args if args is not None else {}, "id": "tc1"}

        def _override(*, tool_call):
            overridden = MagicMock()
            overridden.tool_call = tool_call
            return overridden

        request.override.side_effect = _override
        return request

    @pytest.mark.asyncio
    async def test_clamps_oversized_timeout(self):
        """An agent timeout above the ceiling is reduced to the configured maximum."""
        middleware = ExecuteTimeoutClampMiddleware(max_timeout_seconds=1200)
        handler = AsyncMock(return_value=ToolMessage(content="ok", tool_call_id="tc1"))
        request = self._request("execute", args={"command": "python x.py", "timeout": 120000})

        await middleware.awrap_tool_call(request, handler)

        request.override.assert_called_once()
        forwarded = handler.await_args.args[0]
        assert forwarded.tool_call["args"]["timeout"] == 1200
        assert forwarded.tool_call["args"]["command"] == "python x.py"

    @pytest.mark.asyncio
    async def test_timeout_within_ceiling_passthrough(self):
        """A reasonable timeout is left untouched (no override)."""
        middleware = ExecuteTimeoutClampMiddleware(max_timeout_seconds=1200)
        handler = AsyncMock(return_value=ToolMessage(content="ok", tool_call_id="tc1"))
        request = self._request("execute", args={"command": "python x.py", "timeout": 60})

        await middleware.awrap_tool_call(request, handler)

        request.override.assert_not_called()
        handler.assert_awaited_once_with(request)

    @pytest.mark.asyncio
    async def test_nonpositive_timeout_passthrough(self):
        """A non-positive timeout means 'no timeout' to the backend and is not clamped."""
        middleware = ExecuteTimeoutClampMiddleware(max_timeout_seconds=1200)
        handler = AsyncMock(return_value=ToolMessage(content="ok", tool_call_id="tc1"))
        request = self._request("execute", args={"command": "python x.py", "timeout": 0})

        await middleware.awrap_tool_call(request, handler)

        request.override.assert_not_called()
        handler.assert_awaited_once_with(request)

    @pytest.mark.asyncio
    async def test_missing_timeout_passthrough(self):
        """execute calls without a timeout arg are forwarded unchanged."""
        middleware = ExecuteTimeoutClampMiddleware(max_timeout_seconds=1200)
        handler = AsyncMock(return_value=ToolMessage(content="ok", tool_call_id="tc1"))
        request = self._request("execute", args={"command": "python x.py"})

        await middleware.awrap_tool_call(request, handler)

        request.override.assert_not_called()
        handler.assert_awaited_once_with(request)

    @pytest.mark.asyncio
    async def test_non_execute_tool_passthrough(self):
        """A large timeout on a non-execute tool is ignored by this middleware."""
        middleware = ExecuteTimeoutClampMiddleware(max_timeout_seconds=1200)
        handler = AsyncMock(return_value=ToolMessage(content="ok", tool_call_id="tc1"))
        request = self._request("ls", args={"path": "/shared", "timeout": 120000})

        await middleware.awrap_tool_call(request, handler)

        request.override.assert_not_called()
        handler.assert_awaited_once_with(request)


class TestFilesystemToolCallGuardMiddleware:
    """Filesystem calls are normalized and unresolved path templates fail before execution."""

    @staticmethod
    def _request(tool_name: str, args: dict) -> MagicMock:
        request = MagicMock()
        request.tool_call = {"name": tool_name, "args": args, "id": "tc1"}

        def _override(*, tool_call):
            overridden = MagicMock()
            overridden.tool_call = tool_call
            return overridden

        request.override.side_effect = _override
        return request

    @pytest.mark.asyncio
    async def test_normalizes_read_file_path_alias(self) -> None:
        middleware = FilesystemToolCallGuardMiddleware()
        request = self._request("read_file", {"path": "/shared/output.md", "offset": 1})
        handler = AsyncMock(return_value=ToolMessage(content="ok", tool_call_id="tc1"))

        await middleware.awrap_tool_call(request, handler)

        forwarded = handler.await_args.args[0]
        assert forwarded.tool_call["args"] == {"file_path": "/shared/output.md", "offset": 1}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "placeholder",
        [
            "<sandbox_artifact_dir>",
            "<  sandbox_workdir  >",
            "{{ sandbox_workdir }}",
            "{{sandbox_artifact_dir}}",
            "{{  sandbox_workdir  }}",
        ],
    )
    async def test_rejects_unresolved_execute_path_placeholder(self, placeholder: str) -> None:
        middleware = FilesystemToolCallGuardMiddleware()
        request = self._request("execute", {"command": f"python3 make_chart.py {placeholder}"})
        handler = AsyncMock(return_value=ToolMessage(content="ok", tool_call_id="tc1"))

        result = await middleware.awrap_tool_call(request, handler)

        handler.assert_not_awaited()
        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert placeholder in result.content

    @pytest.mark.asyncio
    async def test_allows_concrete_execute_paths(self) -> None:
        middleware = FilesystemToolCallGuardMiddleware()
        request = self._request(
            "execute",
            {"command": "python3 /sandbox/job/make_chart.py /sandbox/job/aiq-artifacts"},
        )
        expected = ToolMessage(content="ok", tool_call_id="tc1")
        handler = AsyncMock(return_value=expected)

        result = await middleware.awrap_tool_call(request, handler)

        assert result is expected
        handler.assert_awaited_once_with(request)


class TestFinalReportOwnershipGuardMiddleware:
    """Only the writer may mutate an accepted final-report path."""

    @staticmethod
    def _request(tool_name: str, path: str) -> MagicMock:
        request = MagicMock()
        request.tool_call = {"name": tool_name, "args": {"file_path": path}, "id": "tc1"}
        return request

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name", ["write_file", "edit_file"])
    @pytest.mark.parametrize("path", ["/shared/output.md", "/output.md", "/shared/./output.md"])
    async def test_rejects_final_report_mutation(self, tool_name: str, path: str) -> None:
        middleware = FinalReportOwnershipGuardMiddleware()
        handler = AsyncMock()

        result = await middleware.awrap_tool_call(self._request(tool_name, path), handler)

        handler.assert_not_awaited()
        assert result.status == "error"
        assert str(result.content).startswith("final_report_writer_only:")

    @pytest.mark.asyncio
    async def test_allows_unrelated_file_mutation(self) -> None:
        middleware = FinalReportOwnershipGuardMiddleware()
        request = self._request("write_file", "/shared/plan.md")
        expected = ToolMessage(content="ok", tool_call_id="tc1")
        handler = AsyncMock(return_value=expected)

        result = await middleware.awrap_tool_call(request, handler)

        assert result is expected
        handler.assert_awaited_once_with(request)


class TestStateMutationGuardMiddleware:
    """Model filesystem writes cannot mutate shared state outside writer ownership."""

    @staticmethod
    def _request(tool_name: str, path: str) -> MagicMock:
        request = MagicMock()
        request.tool_call = {"name": tool_name, "args": {"file_path": path}, "id": "tc1"}
        return request

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ["/shared/plan.json", "/shared/output.md", "/workspace/scratch.py"])
    async def test_non_writer_without_sandbox_cannot_mutate_any_state_path(self, path: str) -> None:
        middleware = StateMutationGuardMiddleware(writer=False, sandbox_enabled=False)
        handler = AsyncMock()

        result = await middleware.awrap_tool_call(self._request("write_file", path), handler)

        assert result.status == "error"
        assert str(result.content).startswith("state_mutation_role_denied:")
        handler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_writer_with_sandbox_can_write_workspace_but_not_shared_state(self) -> None:
        middleware = StateMutationGuardMiddleware(writer=False, sandbox_enabled=True)
        expected = ToolMessage(content="ok", tool_call_id="tc1")
        handler = AsyncMock(return_value=expected)

        workspace = await middleware.awrap_tool_call(self._request("write_file", "/workspace/scratch.py"), handler)
        shared = await middleware.awrap_tool_call(self._request("write_file", "/shared/plan.json"), handler)

        assert workspace is expected
        assert shared.status == "error"
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tool_name", "path", "reason"),
        [
            ("write_file", "/shared/plan.json", "writer_state_path_denied:"),
            ("edit_file", "/shared/output.md", "writer_output_edit_not_supported:"),
        ],
    )
    async def test_writer_is_limited_to_bounded_output_overwrite(
        self,
        tool_name: str,
        path: str,
        reason: str,
    ) -> None:
        middleware = StateMutationGuardMiddleware(writer=True, sandbox_enabled=True)
        handler = AsyncMock()

        result = await middleware.awrap_tool_call(self._request(tool_name, path), handler)

        assert result.status == "error"
        assert str(result.content).startswith(reason)
        handler.assert_not_awaited()

    @pytest.mark.parametrize(
        ("writer", "tool_name", "path", "reason"),
        [
            (False, "write_file", "/shared/plan.json", "state_mutation_role_denied:"),
            (True, "write_file", "/shared/plan.json", "writer_state_path_denied:"),
            (True, "edit_file", "/shared/output.md", "writer_output_edit_not_supported:"),
        ],
    )
    def test_sync_hook_enforces_same_state_mutation_policy(
        self,
        writer: bool,
        tool_name: str,
        path: str,
        reason: str,
    ) -> None:
        middleware = StateMutationGuardMiddleware(writer=writer, sandbox_enabled=True)
        handler = MagicMock()

        result = middleware.wrap_tool_call(self._request(tool_name, path), handler)

        assert result.status == "error"
        assert str(result.content).startswith(reason)
        handler.assert_not_called()

    @pytest.mark.parametrize(
        ("writer", "tool_name", "path"),
        [
            (False, "write_file", "/workspace/scratch.py"),
            (False, "read_file", "/shared/plan.json"),
            (True, "write_file", "/shared/output.md"),
        ],
    )
    def test_sync_hook_delegates_allowed_calls(self, writer: bool, tool_name: str, path: str) -> None:
        middleware = StateMutationGuardMiddleware(writer=writer, sandbox_enabled=True)
        expected = ToolMessage(content="ok", tool_call_id="tc1")
        handler = MagicMock(return_value=expected)

        result = middleware.wrap_tool_call(self._request(tool_name, path), handler)

        assert result is expected
        handler.assert_called_once()


class TestFinalReportCommitMiddleware:
    """Writer mutations are overwrite-capable and recorded only after success."""

    @staticmethod
    def _request(tool_name: str, *, path: str = "/shared/output.md", **args: object) -> MagicMock:
        request = MagicMock()
        request.tool_call = {
            "name": tool_name,
            "args": {"file_path": path, **args},
            "id": "tc1",
        }
        return request

    @pytest.mark.asyncio
    async def test_successful_write_records_exact_digest(self) -> None:
        tracker = FinalReportCommitTracker()
        backend = MagicMock()
        backend.aupload_files = AsyncMock(return_value=[SimpleNamespace(error=None)])
        middleware = FinalReportCommitMiddleware(backend=backend, tracker=tracker)
        handler = AsyncMock()
        report = "# Final\r\n\r\nExact bytes.\r\n"

        result = await middleware.awrap_tool_call(
            self._request("write_file", content=report),
            handler,
        )

        handler.assert_not_awaited()
        backend.aupload_files.assert_awaited_once_with([("/shared/output.md", report.encode("utf-8"))])
        assert result.status == "success"
        assert tracker.committed_text({"/shared/output.md": {"content": report}}) == report
        assert tracker.committed_text({"/shared/output.md": {"content": report.replace("\r\n", "\n")}}) is None

    @pytest.mark.asyncio
    async def test_failed_write_is_not_recorded(self) -> None:
        tracker = FinalReportCommitTracker()
        backend = MagicMock()
        backend.aupload_files = AsyncMock(return_value=[SimpleNamespace(error="internal detail")])
        middleware = FinalReportCommitMiddleware(backend=backend, tracker=tracker)

        result = await middleware.awrap_tool_call(
            self._request("write_file", content="# Final"),
            AsyncMock(),
        )

        assert result.status == "error"
        assert str(result.content).startswith("writer_output_commit_failed:")
        assert "internal detail" not in str(result.content)
        assert tracker.digest is None

    @pytest.mark.asyncio
    async def test_write_exception_is_sanitized_and_not_recorded(self) -> None:
        tracker = FinalReportCommitTracker()
        backend = MagicMock()
        backend.aupload_files = AsyncMock(side_effect=RuntimeError("sensitive backend detail"))
        middleware = FinalReportCommitMiddleware(backend=backend, tracker=tracker)

        result = await middleware.awrap_tool_call(
            self._request("write_file", content="# Final"),
            AsyncMock(),
        )

        assert result.status == "error"
        assert str(result.content).startswith("writer_output_commit_failed:")
        assert "sensitive backend detail" not in str(result.content)
        assert tracker.digest is None

    @pytest.mark.asyncio
    async def test_route_local_alias_is_not_a_writer_destination(self) -> None:
        middleware = FinalReportCommitMiddleware(backend=MagicMock(), tracker=FinalReportCommitTracker())

        result = await middleware.awrap_tool_call(
            self._request("write_file", path="/output.md", content="# Final"),
            AsyncMock(),
        )

        assert result.status == "error"
        assert str(result.content).startswith("writer_output_path_invalid:")

    @pytest.mark.asyncio
    async def test_edit_is_rejected_before_backend_mutation(self) -> None:
        tracker = FinalReportCommitTracker()
        tracker.record("# Baseline")
        backend = MagicMock()
        backend.adownload_files = AsyncMock()
        middleware = FinalReportCommitMiddleware(backend=backend, tracker=tracker)
        handler = AsyncMock()

        result = await middleware.awrap_tool_call(
            self._request("edit_file", old_string="# Baseline", new_string="# Baseline"),
            handler,
        )

        assert result.status == "error"
        assert str(result.content).startswith("writer_output_edit_not_supported:")
        assert "use write_file" in str(result.content)
        handler.assert_not_awaited()
        backend.adownload_files.assert_not_awaited()
        assert tracker.committed_text({"/shared/output.md": {"content": "# Baseline"}}) == "# Baseline"

    @pytest.mark.asyncio
    async def test_edit_rejection_keeps_previous_digest(self) -> None:
        tracker = FinalReportCommitTracker()
        tracker.record("# Baseline")
        backend = MagicMock()
        backend.adownload_files = AsyncMock()
        middleware = FinalReportCommitMiddleware(backend=backend, tracker=tracker)
        handler = AsyncMock()

        result = await middleware.awrap_tool_call(
            self._request("edit_file", old_string="missing", new_string="new"),
            handler,
        )

        assert result.status == "error"
        assert str(result.content).startswith("writer_output_edit_not_supported:")
        handler.assert_not_awaited()
        backend.adownload_files.assert_not_awaited()
        assert tracker.committed_text({"/shared/output.md": {"content": "# Baseline"}}) == "# Baseline"

    @pytest.mark.asyncio
    async def test_edit_handler_is_never_called(self) -> None:
        tracker = FinalReportCommitTracker()
        tracker.record("# Baseline")
        backend = MagicMock()
        backend.adownload_files = AsyncMock()
        middleware = FinalReportCommitMiddleware(backend=backend, tracker=tracker)

        result = await middleware.awrap_tool_call(
            self._request("edit_file", old_string="# Baseline", new_string="# Revised"),
            AsyncMock(side_effect=RuntimeError("sensitive backend detail")),
        )

        assert result.status == "error"
        assert str(result.content).startswith("writer_output_edit_not_supported:")
        backend.adownload_files.assert_not_awaited()
        assert tracker.committed_text({"/shared/output.md": {"content": "# Baseline"}}) == "# Baseline"

    @pytest.mark.asyncio
    async def test_oversized_write_is_rejected_before_backend_mutation(self) -> None:
        limits = DeepResearchResourceLimits(max_final_report_bytes=4)
        backend = MagicMock()
        backend.aupload_files = AsyncMock()
        middleware = FinalReportCommitMiddleware(
            backend=backend,
            tracker=FinalReportCommitTracker(),
            resource_limits=limits,
        )

        result = await middleware.awrap_tool_call(
            self._request("write_file", content="ééé"),
            AsyncMock(),
        )

        assert result.status == "error"
        assert str(result.content).startswith("writer_output_limit_exceeded:")
        backend.aupload_files.assert_not_awaited()

    def test_trackers_do_not_share_commit_state_between_runs(self) -> None:
        first = FinalReportCommitTracker()
        second = FinalReportCommitTracker()
        first.record("# First run")

        assert first.committed_text({"/shared/output.md": {"content": "# First run"}}) == "# First run"
        assert second.committed_text({"/shared/output.md": {"content": "# First run"}}) is None


class TestRequiredOutputFileMiddleware:
    """The writer may only claim completion after committing the current bytes."""

    marker = "Wrote /shared/output.md"

    @staticmethod
    def _state(*, files: dict | None = None, messages: list | None = None) -> dict:
        return {
            "files": files or {},
            "messages": messages or [AIMessage(content="Wrote /shared/output.md")],
        }

    @pytest.mark.parametrize("path", ["/shared/output.md", "/output.md"])
    @pytest.mark.parametrize("content", ["# Final report\n", "# Final report\r\n"])
    def test_accepts_committed_output_in_both_backend_path_forms(self, path: str, content: str) -> None:
        tracker = FinalReportCommitTracker()
        tracker.record(content)
        middleware = RequiredOutputFileMiddleware(tracker=tracker)
        state = self._state(files={path: {"content": content}})

        assert middleware.after_model(state, None) is None

    def test_rejects_non_empty_stale_output_without_writer_mutation(self) -> None:
        middleware = RequiredOutputFileMiddleware(tracker=FinalReportCommitTracker())
        state = self._state(files={"/output.md": {"content": "# Planner prose"}})

        update = middleware.after_model(state, None)

        assert update is not None
        assert update["jump_to"] == "model"

    @pytest.mark.parametrize("content", ["", "   ", b"\n", []])
    def test_empty_output_requests_one_local_corrective_turn(self, content: object) -> None:
        middleware = RequiredOutputFileMiddleware(tracker=FinalReportCommitTracker())
        state = self._state(files={"/output.md": {"content": content}})

        update = middleware.after_model(state, None)

        assert update is not None
        assert update["jump_to"] == "model"
        correction = update["messages"][0]
        assert isinstance(correction, HumanMessage)
        assert "Call write_file" in str(correction.content)
        assert "Do not repeat research" in str(correction.content)

    def test_committed_whitespace_only_output_is_still_rejected(self) -> None:
        content = " \r\n"
        tracker = FinalReportCommitTracker()
        tracker.record(content)
        middleware = RequiredOutputFileMiddleware(tracker=tracker)

        update = middleware.after_model(self._state(files={"/shared/output.md": {"content": content}}), None)

        assert update is not None
        assert update["jump_to"] == "model"

    def test_rejects_post_commit_tampering(self) -> None:
        tracker = FinalReportCommitTracker()
        tracker.record("# Writer report")
        middleware = RequiredOutputFileMiddleware(tracker=tracker)

        update = middleware.after_model(
            self._state(files={"/shared/output.md": {"content": "# Modified report"}}),
            None,
        )

        assert update is not None
        assert update["jump_to"] == "model"

    def test_does_not_interrupt_intermediate_tool_call(self) -> None:
        middleware = RequiredOutputFileMiddleware(tracker=FinalReportCommitTracker())
        state = self._state(
            messages=[
                AIMessage(
                    content=self.marker,
                    tool_calls=[{"name": "write_file", "args": {}, "id": "tc1"}],
                )
            ]
        )

        assert middleware.after_model(state, None) is None

    @pytest.mark.asyncio
    async def test_async_retry_accepts_repaired_route_local_output(self) -> None:
        tracker = FinalReportCommitTracker()
        middleware = RequiredOutputFileMiddleware(tracker=tracker)
        first = middleware.after_model(self._state(), None)
        correction = first["messages"][0]
        tracker.record("# Final report")
        repaired = self._state(
            files={"/output.md": {"content": "# Final report"}},
            messages=[AIMessage(content=self.marker), correction, AIMessage(content=self.marker)],
        )

        assert await middleware.aafter_model(repaired, None) is None

    def test_repeated_false_completion_fails_with_stable_reason_code(self) -> None:
        middleware = RequiredOutputFileMiddleware(tracker=FinalReportCommitTracker())
        first = middleware.after_model(self._state(), None)
        correction = first["messages"][0]
        still_missing = self._state(
            messages=[AIMessage(content=self.marker), correction, AIMessage(content=self.marker)]
        )

        with pytest.raises(RuntimeError, match="^writer_output_not_committed$"):
            middleware.after_model(still_missing, None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("shared_route", [False, True])
    async def test_graph_overwrites_stale_planner_output_and_commits_writer_report(self, shared_route: bool) -> None:
        """A create-only collision cannot leave planner prose as the final report."""
        model = _ToolBindingFakeChatModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "write_file",
                            "args": {"file_path": "/shared/output.md", "content": "# Writer report"},
                            "id": "tc1",
                        }
                    ],
                ),
                AIMessage(content=self.marker),
            ]
        )
        backend = (
            CompositeBackend(default=StateBackend(), routes={"/shared/": StateBackend()})
            if shared_route
            else StateBackend()
        )
        tracker = FinalReportCommitTracker()
        graph = create_agent(
            model,
            tools=[],
            middleware=[
                FilesystemMiddleware(backend=backend),
                FinalReportCommitMiddleware(backend=backend, tracker=tracker),
                RequiredOutputFileMiddleware(tracker=tracker),
            ],
        )
        stale_path = "/output.md" if shared_route else "/shared/output.md"

        result = await graph.ainvoke(
            {
                "messages": [HumanMessage(content="Write the report")],
                "files": {stale_path: {"content": "# Planner prose"}},
            }
        )

        assert result["files"][stale_path]["content"] == "# Writer report"
        assert tracker.committed_text(result["files"]) == "# Writer report"

    @pytest.mark.asyncio
    async def test_graph_stops_after_bounded_false_completion_retry(self) -> None:
        model = _ToolBindingFakeChatModel(
            responses=[
                AIMessage(content=self.marker),
                AIMessage(content=self.marker),
            ]
        )
        tracker = FinalReportCommitTracker()
        graph = create_agent(
            model,
            tools=[],
            middleware=[FilesystemMiddleware(), RequiredOutputFileMiddleware(tracker=tracker)],
        )

        with pytest.raises(RuntimeError, match="^writer_output_not_committed"):
            await graph.ainvoke(
                {
                    "messages": [HumanMessage(content="Write the report")],
                    "files": {"/shared/output.md": {"content": "# Planner prose"}},
                }
            )


class TestToolNameSanitizationMiddleware:
    """Tests for ToolNameSanitizationMiddleware."""

    @pytest.fixture
    def valid_tool_names(self):
        return ["advanced_web_search_tool", "paper_search_tool", "read_file", "write_file", "grep", "glob", "think"]

    @pytest.fixture
    def middleware(self, valid_tool_names):
        return ToolNameSanitizationMiddleware(valid_tool_names=valid_tool_names)

    def test_sanitize_channel_suffix(self, middleware):
        """Strip <|channel|> and everything after it."""
        assert (
            middleware._sanitize_tool_name("advanced_web_search_tool<|channel|>commentary")
            == "advanced_web_search_tool"
        )

    def test_sanitize_channel_json_suffix(self, middleware):
        """Strip <|channel|>json suffix."""
        assert middleware._sanitize_tool_name("advanced_web_search_tool<|channel|>json") == "advanced_web_search_tool"

    def test_sanitize_dot_suffix(self, middleware):
        """Strip .commentary suffix when base name is valid."""
        assert middleware._sanitize_tool_name("advanced_web_search_tool.commentary") == "advanced_web_search_tool"

    def test_sanitize_dot_exec_suffix(self, middleware):
        """Strip .exec suffix when base name is valid."""
        assert middleware._sanitize_tool_name("advanced_web_search_tool.exec") == "advanced_web_search_tool"

    def test_sanitize_paper_search_channel(self, middleware):
        """Strip channel suffix from paper_search_tool too."""
        assert middleware._sanitize_tool_name("paper_search_tool<|channel|>commentary") == "paper_search_tool"

    def test_map_open_file_to_read_file(self, middleware):
        """Map hallucinated open_file to read_file."""
        assert middleware._sanitize_tool_name("open_file") == "read_file"

    def test_map_find_to_grep(self, middleware):
        """Map hallucinated find to grep."""
        assert middleware._sanitize_tool_name("find") == "grep"

    def test_map_find_file_to_glob(self, middleware):
        """Map hallucinated find_file to glob."""
        assert middleware._sanitize_tool_name("find_file") == "glob"

    def test_passthrough_valid_name(self, middleware):
        """Valid tool names pass through unchanged."""
        assert middleware._sanitize_tool_name("advanced_web_search_tool") == "advanced_web_search_tool"

    def test_passthrough_unknown_invalid_name(self, middleware):
        """Unknown invalid names pass through unchanged (let framework report the error)."""
        assert middleware._sanitize_tool_name("totally_fake_tool") == "totally_fake_tool"

    def test_dot_suffix_with_invalid_base_passes_through(self, middleware):
        """Dot suffix stripping only applies when base name is valid."""
        assert middleware._sanitize_tool_name("fake_tool.commentary") == "fake_tool.commentary"

    @pytest.mark.asyncio
    async def test_awrap_model_call_sanitizes_tool_calls(self, middleware):
        """Integration: middleware sanitizes tool_calls in AIMessage."""
        from langchain.agents.middleware.types import ModelResponse

        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {"name": "advanced_web_search_tool<|channel|>commentary", "args": {"question": "test"}, "id": "tc1"},
            ],
        )
        mock_response = ModelResponse(result=[ai_msg])
        mock_handler = AsyncMock(return_value=mock_response)
        mock_request = MagicMock()

        result = await middleware.awrap_model_call(mock_request, mock_handler)

        assert result.result[0].tool_calls[0]["name"] == "advanced_web_search_tool"

    @pytest.mark.asyncio
    async def test_awrap_model_call_no_tool_calls_passthrough(self, middleware):
        """Messages without tool_calls pass through unchanged."""
        from langchain.agents.middleware.types import ModelResponse

        ai_msg = AIMessage(content="Just text, no tools")
        mock_response = ModelResponse(result=[ai_msg])
        mock_handler = AsyncMock(return_value=mock_response)
        mock_request = MagicMock()

        result = await middleware.awrap_model_call(mock_request, mock_handler)

        assert result.result[0].content == "Just text, no tools"
        assert not result.result[0].tool_calls


class TestToolVisibilityMiddleware:
    """Tests for hiding tools from model requests."""

    def test_wrap_model_call_filters_hidden_tools(self):
        middleware = ToolVisibilityMiddleware(hidden_tool_names={"execute"})
        execute_tool = SimpleNamespace(name="execute")
        read_file_tool = SimpleNamespace(name="read_file")
        mock_request = MagicMock()
        mock_request.tools = [execute_tool, read_file_tool, {"function": {"name": "execute"}}]
        filtered_request = MagicMock()
        mock_request.override.return_value = filtered_request
        mock_handler = MagicMock(return_value="ok")

        result = middleware.wrap_model_call(mock_request, mock_handler)

        assert result == "ok"
        mock_request.override.assert_called_once_with(tools=[read_file_tool])
        mock_handler.assert_called_once_with(filtered_request)

    @pytest.mark.asyncio
    async def test_awrap_model_call_filters_hidden_tools(self):
        middleware = ToolVisibilityMiddleware(hidden_tool_names={"execute"})
        execute_tool = SimpleNamespace(name="execute")
        read_file_tool = SimpleNamespace(name="read_file")
        mock_request = MagicMock()
        mock_request.tools = [execute_tool, read_file_tool, {"function": {"name": "execute"}}]
        filtered_request = MagicMock()
        mock_request.override.return_value = filtered_request
        mock_handler = AsyncMock(return_value="ok")

        result = await middleware.awrap_model_call(mock_request, mock_handler)

        assert result == "ok"
        mock_request.override.assert_called_once_with(tools=[read_file_tool])
        mock_handler.assert_awaited_once_with(filtered_request)


class TestTodoSuppressionMiddleware:
    """Tests for stripping the framework's write_todos tool and its injected prompt."""

    @staticmethod
    def _request_with_todos():
        todo_block = {"type": "text", "text": "\n\n## `write_todos`\nYou have access to the write_todos tool."}
        base_block = {"type": "text", "text": "You are the planner."}
        request = MagicMock()
        request.tools = [SimpleNamespace(name="write_todos"), SimpleNamespace(name="think")]
        request.system_message = SimpleNamespace(content_blocks=[base_block, todo_block])
        request.override.return_value = "overridden"
        return request

    def test_strips_write_todos_tool_and_prompt_block(self):
        request = self._request_with_todos()
        handler = MagicMock(return_value="ok")

        result = TodoSuppressionMiddleware().wrap_model_call(request, handler)

        assert result == "ok"
        kwargs = request.override.call_args.kwargs
        assert [tool.name for tool in kwargs["tools"]] == ["think"]
        new_system = kwargs["system_message"]
        assert isinstance(new_system, SystemMessage)
        assert "## `write_todos`" not in str(new_system.content)
        assert "You are the planner." in str(new_system.content)
        handler.assert_called_once_with("overridden")

    @pytest.mark.asyncio
    async def test_awrap_strips_write_todos(self):
        request = self._request_with_todos()
        handler = AsyncMock(return_value="ok")

        result = await TodoSuppressionMiddleware().awrap_model_call(request, handler)

        assert result == "ok"
        assert [tool.name for tool in request.override.call_args.kwargs["tools"]] == ["think"]
        handler.assert_awaited_once_with("overridden")

    def test_noop_when_no_todos_present(self):
        """Only tools are overridden (unchanged) when no write_todos tool or prompt exists."""
        request = MagicMock()
        request.tools = [SimpleNamespace(name="think")]
        request.system_message = SimpleNamespace(content_blocks=[{"type": "text", "text": "You are the planner."}])
        request.override.return_value = "overridden"

        TodoSuppressionMiddleware().wrap_model_call(request, MagicMock(return_value="ok"))

        kwargs = request.override.call_args.kwargs
        assert [tool.name for tool in kwargs["tools"]] == ["think"]
        assert "system_message" not in kwargs

    def test_suppresses_real_langchain_todo_injection(self):
        """Guard against drift: strip the ACTUAL langchain write_todos tool + prompt.

        Builds the request the way TodoListMiddleware does - the real ``write_todos``
        tool and the real ``WRITE_TODOS_SYSTEM_PROMPT`` block. If a langchain upgrade
        renames the tool or changes the prompt header so our matcher misses it, this
        test fails loudly instead of silently leaking todos back into the planner.
        """
        from langchain.agents.middleware import TodoListMiddleware
        from langchain.agents.middleware.todo import WRITE_TODOS_SYSTEM_PROMPT

        base_block = {"type": "text", "text": "You are the planner."}
        todo_block = {"type": "text", "text": f"\n\n{WRITE_TODOS_SYSTEM_PROMPT}"}
        request = MagicMock()
        request.tools = [*TodoListMiddleware().tools, SimpleNamespace(name="think")]
        request.system_message = SimpleNamespace(content_blocks=[base_block, todo_block])
        request.override.return_value = "overridden"

        TodoSuppressionMiddleware().wrap_model_call(request, MagicMock(return_value="ok"))

        kwargs = request.override.call_args.kwargs
        assert all(getattr(tool, "name", None) != "write_todos" for tool in kwargs["tools"])
        assert "write_todos" not in str(kwargs["system_message"].content)


class TestTodoQuotaMiddleware:
    """Tests for bounded orchestrator write_todos state replacement."""

    @staticmethod
    def _request(todos):
        request = MagicMock()
        request.tool_call = {
            "name": "write_todos",
            "args": {"todos": todos},
            "id": "todo-call",
        }
        return request

    def test_exact_todo_count_item_and_aggregate_boundaries_pass(self):
        """Equality at every configured todo boundary still reaches the state tool."""
        middleware = TodoQuotaMiddleware(
            resource_limits=DeepResearchResourceLimits(
                max_todo_items=2,
                max_todo_item_chars=3,
                max_total_todo_chars=6,
            )
        )
        request = self._request(
            [
                {"content": "one", "status": "in_progress"},
                {"content": "two", "status": "pending"},
            ]
        )
        handler = MagicMock(return_value="updated")

        assert middleware.wrap_tool_call(request, handler) == "updated"
        handler.assert_called_once_with(request)

    @pytest.mark.parametrize(
        ("todos", "message"),
        [
            (
                [
                    {"content": "a", "status": "pending"},
                    {"content": "b", "status": "pending"},
                    {"content": "c", "status": "pending"},
                ],
                "2-item limit",
            ),
            ([{"content": "four", "status": "pending"}], "3-character limit"),
            (
                [
                    {"content": "aaa", "status": "pending"},
                    {"content": "bbb", "status": "pending"},
                ],
                "5-character aggregate",
            ),
        ],
    )
    def test_oversized_todos_return_tool_error_before_state_mutation(self, todos, message):
        """Count, per-item, and aggregate overages remain recoverable by the model."""
        middleware = TodoQuotaMiddleware(
            resource_limits=DeepResearchResourceLimits(
                max_todo_items=2,
                max_todo_item_chars=3,
                max_total_todo_chars=5,
            )
        )
        handler = MagicMock()

        result = middleware.wrap_tool_call(self._request(todos), handler)

        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert result.tool_call_id == "todo-call"
        assert message in str(result.content)
        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_oversized_todos_return_tool_error_before_state_mutation(self):
        """The asynchronous guard has the same recoverable rejection contract."""
        middleware = TodoQuotaMiddleware(
            resource_limits=DeepResearchResourceLimits(
                max_todo_items=1,
                max_todo_item_chars=3,
                max_total_todo_chars=3,
            )
        )
        handler = AsyncMock()

        result = await middleware.awrap_tool_call(
            self._request([{"content": "one"}, {"content": "two"}]),
            handler,
        )

        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert "1-item limit" in str(result.content)
        handler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_todo_tool_is_unchanged(self):
        """The quota middleware remains narrow to the single state-replacement tool."""
        middleware = TodoQuotaMiddleware(resource_limits=DeepResearchResourceLimits(max_todo_items=1))
        request = MagicMock()
        request.tool_call = {"name": "think", "args": {"thought": "x"}, "id": "think-call"}
        handler = AsyncMock(return_value="ok")

        assert await middleware.awrap_tool_call(request, handler) == "ok"
        handler.assert_awaited_once_with(request)


class TestSourceRegistryMiddleware:
    """Tests for SourceRegistryMiddleware allowlist + source extraction."""

    @pytest.fixture
    def source_tools(self):
        return {"advanced_web_search_tool", "knowledge_search", "paper_search_tool"}

    @pytest.fixture(autouse=True)
    def _reset_data_source_registry(self):
        """Keep the global data_source_registry clean across tests.

        Tests that need a populated registry either depend on
        ``_default_data_sources`` (via the ``middleware`` fixture) or
        populate their own registry explicitly in the test body.
        """
        reset_registry()
        yield
        reset_registry()

    @pytest.fixture
    def _default_data_sources(self):
        """Populate the three default data sources used by the shared tests."""
        populate_from_config(
            [
                {
                    "id": "web_search",
                    "name": "Web Search",
                    "description": "Search the web for real-time information.",
                    "tools": ["advanced_web_search_tool"],
                },
                {
                    "id": "knowledge_layer",
                    "name": "Knowledge Base",
                    "description": "Search uploaded documents and files.",
                    "tools": ["knowledge_search"],
                },
                {
                    "id": "paper_search",
                    "name": "Academic Papers",
                    "description": "Search academic papers.",
                    "tools": ["paper_search_tool"],
                },
            ]
        )

    @pytest.fixture
    def middleware(self, source_tools, _default_data_sources):
        return SourceRegistryMiddleware(source_tool_names=source_tools)

    def _make_request(self, tool_name: str):
        req = MagicMock()
        req.tool_call = {"name": tool_name}
        return req

    def _make_tool_result(self, content: str):
        return ToolMessage(content=content, tool_call_id="tc1")

    # -- URL extraction --

    @pytest.mark.asyncio
    async def test_url_source_captured(self, middleware):
        """URLs in tool output are extracted and registered."""
        content = "Found result at https://arxiv.org/abs/2401.00001"
        handler = AsyncMock(return_value=self._make_tool_result(content))
        request = self._make_request("advanced_web_search_tool")

        await middleware.awrap_tool_call(request, handler)

        sources = middleware.registry.all_sources()
        assert len(sources) == 1
        assert sources[0].url == "https://arxiv.org/abs/2401.00001"

    @pytest.mark.asyncio
    async def test_multiple_urls_captured(self, middleware):
        """Multiple URLs from a single tool call are all captured."""
        content = "Result from https://a.com/page and also https://b.com/page"
        handler = AsyncMock(return_value=self._make_tool_result(content))
        request = self._make_request("advanced_web_search_tool")

        await middleware.awrap_tool_call(request, handler)

        urls = {s.url for s in middleware.registry.all_sources()}
        assert urls == {"https://a.com/page", "https://b.com/page"}

    @pytest.mark.asyncio
    async def test_knowledge_layer_citation_key_captured(self, middleware):
        """Knowledge layer citation keys are captured via regex."""
        content = (
            "--- Result 1 ---\n"
            "Source: report.pdf\n"
            "Page: 5\n"
            "Citation: report.pdf, p.5\n"
            "Content Type: pdf\n"
            "\nSome content here."
        )
        handler = AsyncMock(return_value=self._make_tool_result(content))
        request = self._make_request("knowledge_search")

        await middleware.awrap_tool_call(request, handler)

        sources = middleware.registry.all_sources()
        assert len(sources) == 1
        assert sources[0].citation_key == "report.pdf, p.5"

    # -- Allowlist filtering --

    @pytest.mark.asyncio
    async def test_think_tool_ignored(self, middleware):
        """Internal tools not in the allowlist are ignored."""
        content = "Thinking about https://hallucinated.com"
        handler = AsyncMock(return_value=self._make_tool_result(content))
        request = self._make_request("think")

        await middleware.awrap_tool_call(request, handler)

        assert len(middleware.registry.all_sources()) == 0

    @pytest.mark.asyncio
    async def test_unknown_tool_ignored(self, middleware):
        """Tools not in the allowlist are ignored."""
        content = "https://unknown.com/data"
        handler = AsyncMock(return_value=self._make_tool_result(content))
        request = self._make_request("some_random_tool")

        await middleware.awrap_tool_call(request, handler)

        assert len(middleware.registry.all_sources()) == 0

    @pytest.mark.asyncio
    async def test_allowlisted_tool_not_in_data_source_registry_is_still_captured(self):
        """Agent-loaded tools are captured even when not declared under data_sources.

        Tools may be passed directly to the agent (programmatically or via
        `tools:` in YAML) without being declared under `data_sources:`. Their
        outputs are still real, citable evidence and must contribute to the
        citation registry.
        """
        # Autouse fixture already reset the registry; leave it empty.
        mw = SourceRegistryMiddleware(source_tool_names={"mcp_time__get_current_time"})
        content = "2026-05-11T14:30:00+09:00"
        handler = AsyncMock(return_value=self._make_tool_result(content))
        request = self._make_request("mcp_time__get_current_time")

        await mw.awrap_tool_call(request, handler)

        sources = mw.registry.all_sources()
        assert len(sources) == 1
        assert sources[0].citation_key == "mcp_time__get_current_time"
        assert sources[0].source_type == "tool_result"

    @pytest.mark.asyncio
    async def test_registered_group_tool_without_urls_captured(self):
        """Registered group child tools without URLs can be non-URL citation sources."""
        populate_from_config(
            [
                {
                    "id": "mcp_time",
                    "name": "MCP Time",
                    "description": "Get current time and timezone information through MCP.",
                    "tools": ["mcp_time"],
                }
            ],
            group_names={"mcp_time"},
        )
        mw = SourceRegistryMiddleware(source_tool_names={"mcp_time__get_current_time"})
        content = "2026-05-11T14:30:00+09:00"
        handler = AsyncMock(return_value=self._make_tool_result(content))
        request = self._make_request("mcp_time__get_current_time")

        await mw.awrap_tool_call(request, handler)

        sources = mw.registry.all_sources()
        assert len(sources) == 1
        assert sources[0].citation_key == "mcp_time__get_current_time"
        assert sources[0].source_type == "tool_result"

    @pytest.mark.asyncio
    async def test_registered_exact_data_source_tool_without_urls_captured(self):
        """Any exact tool declared under data_sources can be a non-URL citation source."""
        populate_from_config(
            [
                {
                    "id": "weather_observations",
                    "name": "Weather Observations",
                    "description": "Current observed weather conditions.",
                    "tools": ["weather_observation_tool"],
                }
            ]
        )
        mw = SourceRegistryMiddleware(source_tool_names={"weather_observation_tool"})
        content = "Current conditions for San Francisco: clear, 68F"
        handler = AsyncMock(return_value=self._make_tool_result(content))
        request = self._make_request("weather_observation_tool")

        await mw.awrap_tool_call(request, handler)

        sources = mw.registry.all_sources()
        assert len(sources) == 1
        assert sources[0].citation_key == "weather_observation_tool"
        assert sources[0].source_type == "tool_result"

    @pytest.mark.asyncio
    async def test_mixed_source_tools(self, middleware):
        """Multiple tool calls — only allowlisted tools contribute sources."""
        h1 = AsyncMock(return_value=self._make_tool_result("See https://a.com"))
        h2 = AsyncMock(return_value=self._make_tool_result("See https://b.com"))

        await middleware.awrap_tool_call(self._make_request("advanced_web_search_tool"), h1)
        await middleware.awrap_tool_call(self._make_request("paper_search_tool"), h2)

        urls = {s.url for s in middleware.registry.all_sources()}
        assert "https://a.com" in urls
        assert "https://b.com" in urls

    def test_get_verified_sources_defaults_to_research_note_compact_subset(self, middleware):
        """The writer-facing source list prefers sources carried forward by ResearchNotes."""
        middleware.registry.add(SourceEntry(url="https://used.example/report", title="Used Report"))
        middleware.registry.add(SourceEntry(url="https://unused.example/report", title="Unused Report"))
        middleware.register_research_note_sources(
            [SimpleNamespace(sources=[SimpleNamespace(locator="https://used.example/report")])]
        )
        tool = build_get_verified_sources_tool(middleware)

        compact = tool.invoke({})
        full = tool.invoke({"mode": "full"})
        compact_entries = middleware.get_source_entries()
        full_entries = middleware.get_source_entries(mode="full")

        assert "https://used.example/report" in compact
        assert "https://unused.example/report" not in compact
        assert [entry.url for entry in compact_entries] == ["https://used.example/report"]
        assert "https://used.example/report" in full
        assert "https://unused.example/report" in full
        assert {entry.url for entry in full_entries} == {
            "https://used.example/report",
            "https://unused.example/report",
        }

    def test_get_verified_sources_compact_matches_internal_citation_keys(self, middleware):
        """Compact source filtering also works for URL-less internal citation keys."""
        middleware.registry.add(SourceEntry(citation_key="report.pdf, p.5", title="report.pdf"))
        middleware.registry.add(SourceEntry(citation_key="other.pdf, p.9", title="other.pdf"))
        middleware.register_research_note_sources(
            [SimpleNamespace(sources=[SimpleNamespace(locator="report.pdf, p.5")])]
        )
        tool = build_get_verified_sources_tool(middleware)

        compact = tool.invoke({})
        full = tool.invoke({"mode": "full"})

        assert "report.pdf, p.5" in compact
        assert "other.pdf, p.9" not in compact
        assert "report.pdf, p.5" in full
        assert "other.pdf, p.9" in full

    # -- Edge cases --

    @pytest.mark.asyncio
    async def test_empty_content_skipped(self, middleware):
        """Empty content is ignored gracefully."""
        handler = AsyncMock(return_value=self._make_tool_result(""))
        request = self._make_request("advanced_web_search_tool")

        await middleware.awrap_tool_call(request, handler)

        assert len(middleware.registry.all_sources()) == 0

    @pytest.mark.asyncio
    async def test_non_tool_message_passthrough(self, middleware):
        """Non-ToolMessage results pass through without error."""
        handler = AsyncMock(return_value=AIMessage(content="just an AI reply"))
        request = self._make_request("advanced_web_search_tool")

        result = await middleware.awrap_tool_call(request, handler)

        assert isinstance(result, AIMessage)
        assert len(middleware.registry.all_sources()) == 0

    @pytest.mark.asyncio
    async def test_default_empty_allowlist_captures_nothing(self):
        """Middleware with no source_tool_names captures nothing."""
        mw = SourceRegistryMiddleware()
        content = "See https://should-not-be-captured.com"
        handler = AsyncMock(return_value=ToolMessage(content=content, tool_call_id="tc1"))
        request = MagicMock()
        request.tool_call = {"name": "advanced_web_search_tool"}

        await mw.awrap_tool_call(request, handler)

        assert len(mw.registry.all_sources()) == 0

    @pytest.mark.asyncio
    async def test_content_returned_unchanged(self, middleware):
        """Tool result content is not modified by the middleware."""
        content = "Results from https://example.com/page"
        handler = AsyncMock(return_value=self._make_tool_result(content))
        request = self._make_request("advanced_web_search_tool")

        result = await middleware.awrap_tool_call(request, handler)

        assert result.content == content


class TestArtifactHarvestMiddleware:
    """Checkpoint harvesting runs only after successful execute tool calls."""

    @pytest.mark.asyncio
    async def test_execute_checkpoints_after_handler(self) -> None:
        manager = MagicMock()
        middleware = ArtifactHarvestMiddleware(manager)
        request = MagicMock()
        request.tool_call = {"name": "execute"}
        handler = AsyncMock(return_value="ok")

        result = await middleware.awrap_tool_call(request, handler)

        assert result == "ok"
        manager.harvest_after_execute.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_non_execute_tool_does_not_harvest(self) -> None:
        manager = MagicMock()
        middleware = ArtifactHarvestMiddleware(manager)
        request = MagicMock()
        request.tool_call = {"name": "read_file"}

        await middleware.awrap_tool_call(request, AsyncMock(return_value="ok"))

        manager.harvest_after_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_handler_failure_does_not_harvest(self) -> None:
        manager = MagicMock()
        middleware = ArtifactHarvestMiddleware(manager)
        request = MagicMock()
        request.tool_call = {"name": "execute"}

        with pytest.raises(RuntimeError, match="tool failed"):
            await middleware.awrap_tool_call(request, AsyncMock(side_effect=RuntimeError("tool failed")))

        manager.harvest_after_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_error_result_does_not_harvest(self) -> None:
        manager = MagicMock()
        middleware = ArtifactHarvestMiddleware(manager)
        request = MagicMock()
        request.tool_call = {"name": "execute"}

        await middleware.awrap_tool_call(
            request,
            AsyncMock(return_value=ToolMessage(content="failed", tool_call_id="tc1", status="error")),
        )

        manager.harvest_after_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_checkpoint_failure_logs_only_exception_type(self, caplog: pytest.LogCaptureFixture) -> None:
        manager = MagicMock()
        manager.harvest_after_execute.side_effect = RuntimeError("credential=do-not-log")
        middleware = ArtifactHarvestMiddleware(manager)
        request = MagicMock()
        request.tool_call = {"name": "execute"}

        with caplog.at_level(logging.WARNING):
            result = await middleware.awrap_tool_call(request, AsyncMock(return_value="ok"))

        assert result == "ok"
        assert "RuntimeError" in caplog.text
        assert "credential=do-not-log" not in caplog.text

    @pytest.mark.asyncio
    async def test_checkpoint_returns_exact_inline_filename_to_model(self) -> None:
        manager = MagicMock()
        manager.harvest_after_execute.return_value = [
            SimpleNamespace(filename="capex_by_quarter.png", inline=True),
            SimpleNamespace(filename="capex_by_quarter.csv", inline=False),
        ]
        middleware = ArtifactHarvestMiddleware(manager)
        request = MagicMock()
        request.tool_call = {"name": "execute"}
        handler = AsyncMock(return_value=ToolMessage(content="command succeeded", tool_call_id="tc1"))

        result = await middleware.awrap_tool_call(request, handler)

        assert "artifact://capex_by_quarter.png" in result.content
        assert "capex_by_quarter.csv (downloadable; not marked inline)" in result.content


class _RecordingBackend:
    """Minimal backend stub capturing upload_files calls (overwrite-safe)."""

    def __init__(self):
        self.uploads: list[tuple[str, bytes]] = []

    def upload_files(self, files):
        self.uploads.extend(files)
        return [SimpleNamespace(path=path, error=None) for path, _ in files]


class TestSourceRoutingPersistenceMiddleware:
    """Source-routing state is written by middleware, not model filesystem tools."""

    @staticmethod
    def _routing() -> dict[str, object]:
        return {
            "domain_id": "general",
            "domain_name": "General",
            "routing_reason": "Best fit",
            "recommendations": [],
            "fallback_sources": [],
            "planner_guidance": "Use web search.",
        }

    def test_persists_structured_response_to_shared_state(self) -> None:
        backend = MagicMock()
        backend.upload_files.return_value = [SimpleNamespace(path="/shared/source_routing.json", error=None)]
        middleware = SourceRoutingPersistenceMiddleware(backend=backend)

        middleware.after_agent({"structured_response": self._routing()}, None)

        path, content = backend.upload_files.call_args.args[0][0]
        assert path == "/shared/source_routing.json"
        assert json.loads(content) == self._routing()

    def test_rolls_back_budget_when_backend_rejects_route(self) -> None:
        limits = DeepResearchResourceLimits(max_state_file_count=1)
        ledger = StateBudgetLedger(limits=limits, files={}, sandbox_enabled=True)
        backend = MagicMock()
        backend.upload_files.return_value = [SimpleNamespace(path="/shared/source_routing.json", error="private")]
        middleware = SourceRoutingPersistenceMiddleware(
            backend=backend,
            state_budget=ledger,
            resource_limits=limits,
        )

        with pytest.raises(RuntimeError, match="Failed to persist source routing"):
            middleware.after_agent({"structured_response": self._routing()}, None)

        ledger.reserve([("/shared/plan.json", b"ok")])

    def test_serialized_byte_boundary_uses_dedicated_source_routing_limit(self) -> None:
        routing = self._routing()
        serialized_size = len(json.dumps(routing, indent=2, ensure_ascii=False).encode("utf-8"))
        accepted_backend = MagicMock()
        accepted_backend.upload_files.return_value = [SimpleNamespace(path="/shared/source_routing.json", error=None)]
        accepted = SourceRoutingPersistenceMiddleware(
            backend=accepted_backend,
            resource_limits=DeepResearchResourceLimits(max_source_routing_bytes=serialized_size),
        )

        accepted.after_agent({"structured_response": routing}, None)

        accepted_backend.upload_files.assert_called_once()
        rejected_backend = MagicMock()
        rejected = SourceRoutingPersistenceMiddleware(
            backend=rejected_backend,
            resource_limits=DeepResearchResourceLimits(max_source_routing_bytes=serialized_size - 1),
        )
        with pytest.raises(ValueError, match=f"{serialized_size - 1}-byte serialized size limit"):
            rejected.after_agent({"structured_response": routing}, None)
        rejected_backend.upload_files.assert_not_called()


class TestPlanPersistenceMiddleware:
    """Tests for PlanPersistenceMiddleware."""

    @pytest.mark.asyncio
    async def test_persists_structured_plan(self):
        """A structured ResearchPlan in state is serialized and uploaded once."""
        import json

        backend = _RecordingBackend()
        mw = PlanPersistenceMiddleware(backend=backend)
        plan = SimpleNamespace(model_dump=lambda **_: {"answer_strategy": {"answer_type": "table"}})

        result = await mw.aafter_agent({"structured_response": plan}, runtime=None)

        assert result is None
        assert len(backend.uploads) == 1
        path, content = backend.uploads[0]
        assert path == "/shared/plan.json"
        assert json.loads(content.decode("utf-8")) == {"answer_strategy": {"answer_type": "table"}}

    @pytest.mark.asyncio
    async def test_no_structured_response_is_noop(self):
        """Missing structured_response writes nothing rather than erroring."""
        backend = _RecordingBackend()
        mw = PlanPersistenceMiddleware(backend=backend)

        await mw.aafter_agent({"structured_response": None}, runtime=None)
        await mw.aafter_agent({}, runtime=None)

        assert backend.uploads == []

    @pytest.mark.asyncio
    async def test_plan_accepts_exact_query_character_boundary(self):
        """Main-query plus subquery characters are counted exactly before upload."""
        backend = _RecordingBackend()
        middleware = PlanPersistenceMiddleware(
            backend=backend,
            resource_limits=DeepResearchResourceLimits(max_total_query_chars=5),
        )
        plan = {"queries": [{"query": "abc", "subqueries": ["de"]}]}

        await middleware.aafter_agent({"structured_response": plan}, runtime=None)

        assert len(backend.uploads) == 1

    @pytest.mark.asyncio
    async def test_plan_rejects_query_character_overage_before_upload(self):
        """One aggregate query character over the quota cannot mutate shared state."""
        backend = _RecordingBackend()
        middleware = PlanPersistenceMiddleware(
            backend=backend,
            resource_limits=DeepResearchResourceLimits(max_total_query_chars=4),
        )
        plan = {"queries": [{"query": "abc", "subqueries": ["de"]}]}

        with pytest.raises(ValueError, match="4-character aggregate query limit"):
            await middleware.aafter_agent({"structured_response": plan}, runtime=None)

        assert backend.uploads == []

    @pytest.mark.asyncio
    async def test_plan_serialized_byte_boundary_accepts_exact_and_rejects_one_less(self):
        """Plan size is measured on the exact UTF-8 payload that would be uploaded."""
        import json

        plan = {"queries": [{"query": "abc", "subqueries": []}]}
        serialized_size = len(json.dumps(plan, indent=2, ensure_ascii=False).encode("utf-8"))
        accepted_backend = _RecordingBackend()
        accepted = PlanPersistenceMiddleware(
            backend=accepted_backend,
            resource_limits=DeepResearchResourceLimits(max_plan_bytes=serialized_size),
        )

        await accepted.aafter_agent({"structured_response": plan}, runtime=None)

        assert len(accepted_backend.uploads) == 1
        rejected_backend = _RecordingBackend()
        rejected = PlanPersistenceMiddleware(
            backend=rejected_backend,
            resource_limits=DeepResearchResourceLimits(max_plan_bytes=serialized_size - 1),
        )
        with pytest.raises(ValueError, match="serialized size limit"):
            await rejected.aafter_agent({"structured_response": plan}, runtime=None)
        assert rejected_backend.uploads == []

    @pytest.mark.asyncio
    async def test_plan_query_count_boundary_rejects_before_upload(self):
        """The middleware independently enforces the job query-count ceiling."""
        accepted_backend = _RecordingBackend()
        accepted = PlanPersistenceMiddleware(
            backend=accepted_backend,
            resource_limits=DeepResearchResourceLimits(max_research_queries=2),
        )
        queries = [
            {"query": "one", "subqueries": []},
            {"query": "two", "subqueries": []},
        ]

        await accepted.aafter_agent({"structured_response": {"queries": queries}}, runtime=None)

        assert len(accepted_backend.uploads) == 1
        rejected_backend = _RecordingBackend()
        rejected = PlanPersistenceMiddleware(
            backend=rejected_backend,
            resource_limits=DeepResearchResourceLimits(max_research_queries=1),
        )
        with pytest.raises(ValueError, match="1-query job limit"):
            await rejected.aafter_agent({"structured_response": {"queries": queries}}, runtime=None)
        assert rejected_backend.uploads == []

    def test_sync_after_agent_persists(self):
        """The synchronous hook persists via the same path (dict payloads supported)."""
        import json

        backend = _RecordingBackend()
        mw = PlanPersistenceMiddleware(backend=backend)

        mw.after_agent({"structured_response": {"title": "Plan"}}, runtime=None)

        assert len(backend.uploads) == 1
        assert json.loads(backend.uploads[0][1].decode("utf-8")) == {"title": "Plan"}

    @pytest.mark.asyncio
    async def test_backend_failure_propagates(self):
        """Upload failures abort the planner task with the backend error."""

        class _BoomBackend:
            def upload_files(self, files):
                raise RuntimeError("boom")

        mw = PlanPersistenceMiddleware(backend=_BoomBackend())

        with pytest.raises(RuntimeError, match="boom"):
            await mw.aafter_agent({"structured_response": {"title": "Plan"}}, runtime=None)

    @pytest.mark.asyncio
    async def test_upload_error_response_propagates(self, caplog):
        """Non-empty upload errors abort the task; backend detail stays in logs only."""

        class _ErrorBackend:
            def upload_files(self, files):
                return [SimpleNamespace(path="/shared/plan.json", error="disk full")]

        mw = PlanPersistenceMiddleware(backend=_ErrorBackend())

        with caplog.at_level(logging.ERROR):
            with pytest.raises(RuntimeError, match="Failed to persist the research plan") as exc:
                await mw.aafter_agent({"structured_response": {"title": "Plan"}}, runtime=None)

        assert "disk full" not in str(exc.value)  # sanitized out of the raised error
        assert "disk full" in caplog.text  # but preserved in logs

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

"""OpenShell provider tests: the env-free upload/download shim.

OpenShell 0.0.57's exec does not propagate ``env`` to the child process, which
breaks the official adapter's env-var file-transfer bootstraps. Our provider
overrides ``upload_files``/``download_files`` to pass the path via argv (and data
via stdin). These tests assert that contract with a fake sandbox, so they require
only the optional SDK + adapter to be importable.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("openshell")
pytest.importorskip("langchain_nvidia_openshell")

from aiq_agent.agents.deep_researcher.sandbox.config import SandboxConfig  # noqa: E402
from aiq_agent.agents.deep_researcher.sandbox.providers.openshell import OpenShellSandboxProvider  # noqa: E402


@dataclass
class _ExecResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""


class _FakeOpenShellSandbox:
    """Records exec calls and returns scripted results."""

    id = "fake-os-id"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = _ExecResult(exit_code=0)
        self.exit_calls = 0

    def exec(self, command, **kwargs):  # noqa: ANN001 - mirrors openshell.Sandbox.exec
        self.calls.append({"command": list(command), **kwargs})
        return self.result

    def __exit__(self, *_args: object) -> None:
        self.exit_calls += 1


def _provider() -> OpenShellSandboxProvider:
    cfg = SandboxConfig(
        provider="openshell",
        network={"mode": "blocked"},
        providers={"openshell": {"sandbox_name": "demo", "delete_on_exit": False}},
    )
    provider = OpenShellSandboxProvider(cfg, "job-1")
    # Avoid real session creation: a non-None _session short-circuits _session_or_create.
    provider._session = MagicMock()  # type: ignore[assignment]
    return provider


def test_upload_passes_path_via_argv_and_data_via_stdin_no_env() -> None:
    provider = _provider()
    fake = _FakeOpenShellSandbox()
    provider._os_context = fake

    result = provider.upload_files([("/sandbox/x.py", b"print('hi')")])

    assert result[0].error is None
    call = fake.calls[0]
    assert call["command"][0] == "python3" and call["command"][-1] == "/sandbox/x.py"
    assert call["stdin"] == base64.b64encode(b"print('hi')")
    assert "env" not in call  # the whole point: never rely on exec env propagation


def test_upload_classifies_failure() -> None:
    provider = _provider()
    fake = _FakeOpenShellSandbox()
    fake.result = _ExecResult(exit_code=1, stderr="No such file or directory")
    provider._os_context = fake

    result = provider.upload_files([("/sandbox/x.py", b"data")])
    assert result[0].error == "file_not_found"


def test_upload_rejects_relative_path() -> None:
    provider = _provider()
    provider._os_context = _FakeOpenShellSandbox()
    result = provider.upload_files([("relative.py", b"data")])
    assert result[0].error == "invalid_path"


def test_download_passes_path_via_argv_and_decodes_base64() -> None:
    provider = _provider()
    fake = _FakeOpenShellSandbox()
    fake.result = _ExecResult(exit_code=0, stdout=base64.b64encode(b"chart-bytes").decode())
    provider._os_context = fake

    artifact_path = f"{provider.artifact_dir}/chart.png"
    result = provider.download_files([artifact_path])

    assert result[0].error is None
    assert result[0].content == b"chart-bytes"
    call = fake.calls[0]
    # Path is passed positionally via argv (with the size cap appended); never via env.
    assert artifact_path in call["command"]
    assert call["command"][-1] == provider.artifact_dir
    assert "env" not in call


def test_download_uses_confined_shim_when_adapter_transfer_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider()
    fake = _FakeOpenShellSandbox()
    fake.result = _ExecResult(exit_code=0, stdout=base64.b64encode(b"chart-bytes").decode())
    provider._os_context = fake
    provider._session.download_files.side_effect = AssertionError("adapter download bypassed confinement")  # type: ignore[union-attr]
    monkeypatch.setenv("AIQ_OPENSHELL_ADAPTER_FILE_TRANSFER", "1")

    result = provider.download_files([f"{provider.artifact_dir}/chart.png"])

    assert result[0].content == b"chart-bytes"
    assert fake.calls[0]["command"][-1] == provider.artifact_dir


def test_download_is_directory_exit_code() -> None:
    provider = _provider()
    fake = _FakeOpenShellSandbox()
    fake.result = _ExecResult(exit_code=3, stderr="")
    provider._os_context = fake

    result = provider.download_files(["/sandbox"])
    assert result[0].content is None
    assert result[0].error == "is_directory"  # _DOWNLOAD_CODE exits 3 specifically for a directory


def test_download_passes_size_cap_via_argv() -> None:
    provider = _provider()
    fake = _FakeOpenShellSandbox()
    fake.result = _ExecResult(exit_code=0, stdout=base64.b64encode(b"x").decode())
    provider._os_context = fake

    provider.download_files(["/sandbox/aiq-artifacts/chart.png"])

    # The artifact size cap is passed to the bootstrap so it can refuse oversized files
    # before reading them into host memory.
    assert str(provider.config.artifact_capture.max_file_bytes) in fake.calls[0]["command"]


def test_download_rejects_oversized_and_symlink() -> None:
    provider = _provider()
    fake = _FakeOpenShellSandbox()
    provider._os_context = fake

    fake.result = _ExecResult(exit_code=4, stderr="")
    assert provider.download_files(["/sandbox/aiq-artifacts/huge.bin"])[0].error == "too_large"

    fake.result = _ExecResult(exit_code=5, stderr="")
    assert provider.download_files(["/sandbox/aiq-artifacts/evil.png"])[0].error == "symlink_rejected"


def test_download_rejects_non_base64_stdout() -> None:
    provider = _provider()
    fake = _FakeOpenShellSandbox()
    fake.result = _ExecResult(exit_code=0, stdout="not valid base64 !!!")
    provider._os_context = fake

    result = provider.download_files(["/sandbox/aiq-artifacts/chart.png"])
    assert result[0].content is None
    assert result[0].error == "invalid_content"


def test_terminate_exits_openshell_context_once() -> None:
    provider = _provider()
    fake = _FakeOpenShellSandbox()
    provider._os_context = fake

    provider.terminate()
    provider.terminate()

    assert fake.exit_calls == 1
    assert provider._os_context is None

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the OpenShell persistent-kernel transport and evidence bridge."""

import ast
import json
import sys
from pathlib import Path

import pytest
from deepagents.backends.protocol import ExecuteResponse
from deepagents.backends.protocol import FileUploadResponse
from stateful_python import kernel_launcher
from stateful_python import kernel_worker
from stateful_python.session import OpenShellPythonSession
from stateful_python.session import PythonSessionLimits


class _FakeBackend:
    def __init__(self, responses: list[ExecuteResponse] | None = None) -> None:
        self.id = "sandbox-physical-1"
        self.responses = list(responses or [])
        self.uploads: list[dict[str, bytes]] = []
        self.commands: list[tuple[str, int | None]] = []

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        self.uploads.append(dict(files))
        return [FileUploadResponse(path=path, error=None) for path, _content in files]

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        self.commands.append((command, timeout))
        if self.responses:
            return self.responses.pop(0)
        return ExecuteResponse(output="", exit_code=0)


class _FakeRuntime:
    def __init__(self, backend: _FakeBackend) -> None:
        self.sandbox_backend = backend
        self.workdir = "/sandbox/data-science-job"
        self.closed = False
        self.terminated = False

    def close(self) -> None:
        self.closed = True

    def terminate(self) -> None:
        self.terminated = True


def _write_evidence(root: Path) -> Path:
    result_path = root / "gsf_1.json"
    result_path.write_text(
        json.dumps({"sql": "SELECT value", "rows": [{"value": 2}, {"value": 5}]}),
        encoding="utf-8",
    )
    manifest_path = root / "gsf-results.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "results": [
                    {
                        "ref": "gsf_1",
                        "question": "Values",
                        "database_name": "example",
                        "request_id": "r1",
                        "row_count": 2,
                        "columns": ["value"],
                        "truncated": False,
                        "path": str(result_path),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_worker_namespace_persists_dataframes_across_cells() -> None:
    namespace = kernel_worker._new_namespace()
    first, _ = kernel_worker._handle_request(
        namespace,
        json.dumps({"operation": "execute", "code": "frame = pd.DataFrame({'value': [1, 2, 3]})\nframe"}),
        50_000,
    )
    second, _ = kernel_worker._handle_request(
        namespace,
        json.dumps({"operation": "execute", "code": "int(frame['value'].sum())"}),
        50_000,
    )

    assert first["status"] == "ok"
    assert "frame" in first["variables"]
    assert second["status"] == "ok"
    assert second["result"] == "6"


def test_worker_helpers_reload_the_sandbox_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _write_evidence(tmp_path)
    monkeypatch.setattr(sys, "argv", ["kernel_worker.py", str(manifest_path), "50000"])
    response, _ = kernel_worker._handle_request(
        kernel_worker._new_namespace(),
        json.dumps(
            {
                "operation": "execute",
                "code": "df = gsf_rows('gsf_1')\n(int(df['value'].sum()), gsf_sql('gsf_1'))",
            }
        ),
        50_000,
    )

    assert response["status"] == "ok"
    assert ast.literal_eval(response["result"]) == (7, "SELECT value")


def test_worker_serializes_system_exit_and_keeps_namespace_usable() -> None:
    namespace = kernel_worker._new_namespace()
    failed, _ = kernel_worker._handle_request(
        namespace,
        json.dumps({"operation": "execute", "code": "value = 7\nexit()"}),
        50_000,
    )
    recovered, _ = kernel_worker._handle_request(
        namespace,
        json.dumps({"operation": "execute", "code": "value + 1"}),
        50_000,
    )

    assert failed["status"] == "error"
    assert failed["error"] == "SystemExit"
    assert "value" in failed["variables"]
    assert recovered["status"] == "ok"
    assert recovered["result"] == "8"


def test_worker_main_rejects_incomplete_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["kernel_worker.py"])

    with pytest.raises(ValueError, match="kernel worker requires --socket <path>"):
        kernel_worker.main()


def test_worker_output_is_capped_while_written() -> None:
    response, _ = kernel_worker._handle_request(
        kernel_worker._new_namespace(),
        json.dumps({"operation": "execute", "code": "print('x' * 100_000)"}),
        64,
    )

    assert response["status"] == "ok"
    assert response["output"] == ("x" * 64) + "\n... output truncated ..."


def test_launcher_applies_hard_worker_resource_limits() -> None:
    command = kernel_launcher._limited_worker_command(
        worker_path="/sandbox/kernel_worker.py",
        manifest_path="/sandbox/evidence/manifest.json",
        max_output_chars="50000",
        socket_path="/sandbox/kernel.sock",
        max_memory_mb=2_048,
        max_cpu_seconds=120,
        max_processes=64,
        max_open_files=128,
        max_file_bytes=25_000_000,
    )

    assert command == [
        "/usr/bin/prlimit",
        "--as=2147483648:2147483648",
        "--cpu=120:120",
        "--nproc=64:64",
        "--nofile=128:128",
        "--fsize=25000000:25000000",
        "--",
        sys.executable,
        "-I",
        "-u",
        "/sandbox/kernel_worker.py",
        "/sandbox/evidence/manifest.json",
        "50000",
        "--socket",
        "/sandbox/kernel.sock",
    ]


@pytest.mark.asyncio
async def test_session_uploads_only_runtime_files_and_request_evidence(tmp_path: Path) -> None:
    manifest_path = _write_evidence(tmp_path)
    response = json.dumps({"status": "ok", "result": "7", "output": "", "variables": ["df"]})
    backend = _FakeBackend(
        responses=[
            ExecuteResponse(output="", exit_code=0),
            ExecuteResponse(output=response, exit_code=0),
        ]
    )
    runtime = _FakeRuntime(backend)
    session = OpenShellPythonSession(
        runtime=runtime,
        host_manifest_path=manifest_path,
        host_evidence_root=tmp_path,
    )
    try:
        result = json.loads(await session.execute("gsf_rows('gsf_1')['value'].sum()"))
    finally:
        await session.aclose()

    assert result["status"] == "ok"
    assert result["result"] == "7"
    uploaded = backend.uploads[0]
    assert set(uploaded) == {
        "/sandbox/data-science-job/evidence/gsf-results.json",
        "/sandbox/data-science-job/evidence/gsf_1.json",
        "/sandbox/data-science-job/kernel_client.py",
        "/sandbox/data-science-job/kernel_launcher.py",
        "/sandbox/data-science-job/kernel_worker.py",
        "/sandbox/data-science-job/requests/cell-1.json",
    }
    remote_manifest = json.loads(uploaded["/sandbox/data-science-job/evidence/gsf-results.json"])
    assert remote_manifest["results"][0]["path"] == "/sandbox/data-science-job/evidence/gsf_1.json"
    assert str(tmp_path) not in uploaded["/sandbox/data-science-job/evidence/gsf-results.json"].decode()
    assert backend.commands[0][0].endswith("8192 600 256 256 100000000")
    assert runtime.closed is True
    assert runtime.terminated is False


@pytest.mark.asyncio
async def test_session_terminates_sandbox_after_cell_timeout(tmp_path: Path) -> None:
    manifest_path = _write_evidence(tmp_path)
    backend = _FakeBackend(
        responses=[
            ExecuteResponse(output="", exit_code=0),
            ExecuteResponse(output="", exit_code=124),
        ]
    )
    runtime = _FakeRuntime(backend)
    session = OpenShellPythonSession(
        runtime=runtime,
        host_manifest_path=manifest_path,
        host_evidence_root=tmp_path,
        limits=PythonSessionLimits(wall_timeout_seconds=1),
    )

    response = json.loads(await session.execute("while True: pass"))

    assert response == {"status": "error", "error": "execution_timed_out"}
    assert runtime.terminated is True


@pytest.mark.asyncio
async def test_session_rejects_evidence_outside_request_root(tmp_path: Path) -> None:
    root = tmp_path / "request"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text('{"rows":[]}', encoding="utf-8")
    manifest = root / "gsf-results.json"
    manifest.write_text(
        json.dumps({"version": 1, "results": [{"ref": "gsf_1", "path": str(outside)}]}),
        encoding="utf-8",
    )
    runtime = _FakeRuntime(_FakeBackend())
    session = OpenShellPythonSession(
        runtime=runtime,
        host_manifest_path=manifest,
        host_evidence_root=root,
    )

    response = json.loads(await session.execute("1 + 1"))

    assert response == {"status": "error", "error": "sandbox_execution_failed"}
    assert runtime.terminated is True

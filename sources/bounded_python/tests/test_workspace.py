# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for bounded, stateful Python workspaces."""

import json

import pytest
from bounded_python.workspace import BoundedPythonWorkspace
from bounded_python.workspace import WorkspaceLimits


async def _start(manager: BoundedPythonWorkspace) -> str:
    result = json.loads(await manager.run(operation="start"))
    assert result["status"] == "ok"
    return result["workspace_id"]


@pytest.mark.asyncio
async def test_state_persists_and_workspaces_are_isolated() -> None:
    manager = BoundedPythonWorkspace()
    first = await _start(manager)
    second = await _start(manager)

    result = json.loads(
        await manager.run(
            operation="execute",
            workspace_id=first,
            code="values = inputs['values']\ntotal = sum(values)\nresult = total",
            inputs={"values": [2, 3, 5]},
        )
    )
    follow_up = json.loads(
        await manager.run(operation="execute", workspace_id=first, code="result = total / len(values)")
    )
    other = json.loads(await manager.run(operation="inspect", workspace_id=second))

    assert result["result"] == 10
    assert follow_up["result"] == 10 / 3
    assert other["state"] == {}


@pytest.mark.asyncio
async def test_last_expression_becomes_result_and_safe_statistics_work() -> None:
    manager = BoundedPythonWorkspace()
    workspace_id = await _start(manager)

    result = json.loads(
        await manager.run(
            operation="execute",
            workspace_id=workspace_id,
            code="ordered = sorted(inputs['values'])\nmedian(ordered)",
            inputs={"values": [10, 1, 4]},
        )
    )

    assert result["status"] == "ok"
    assert result["result"] == 4
    assert result["state_variables"] == ["ordered"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    [
        "import os\nresult = 1",
        "result = inputs.get('secret')",
        "result = open('/etc/passwd')",
        "result = (1).__class__",
    ],
)
async def test_unsafe_syntax_is_rejected(code: str) -> None:
    manager = BoundedPythonWorkspace()
    workspace_id = await _start(manager)

    result = json.loads(await manager.run(operation="execute", workspace_id=workspace_id, code=code))

    assert result["status"] == "error"
    assert result["error"] == "invalid_or_failed_code"


@pytest.mark.asyncio
async def test_execution_timeout_does_not_corrupt_state() -> None:
    manager = BoundedPythonWorkspace(WorkspaceLimits(wall_timeout_seconds=0.5, cpu_time_seconds=1))
    workspace_id = await _start(manager)
    await manager.run(operation="execute", workspace_id=workspace_id, code="safe = 7\nresult = safe")

    result = json.loads(
        await manager.run(
            operation="execute",
            workspace_id=workspace_id,
            code="result = sum(x for x in range(1000000000))",
        )
    )
    state = json.loads(await manager.run(operation="inspect", workspace_id=workspace_id))

    assert result["status"] == "error"
    assert result["error"] == "execution_timed_out"
    assert state["state"] == {"safe": 7}


@pytest.mark.asyncio
async def test_reset_close_and_payload_validation() -> None:
    manager = BoundedPythonWorkspace(WorkspaceLimits(max_code_chars=1_000, max_input_bytes=1_024))
    workspace_id = await _start(manager)
    await manager.run(operation="execute", workspace_id=workspace_id, code="value = 9\nresult = value")

    reset = json.loads(await manager.run(operation="reset", workspace_id=workspace_id))
    state = json.loads(await manager.run(operation="inspect", workspace_id=workspace_id))
    invalid = json.loads(
        await manager.run(
            operation="execute",
            workspace_id=workspace_id,
            code="result = 1",
            inputs={"bad": float("nan")},
        )
    )
    closed = json.loads(await manager.run(operation="close", workspace_id=workspace_id))
    missing = json.loads(await manager.run(operation="inspect", workspace_id=workspace_id))

    assert reset["status"] == "ok"
    assert state["state"] == {}
    assert invalid["error"] == "inputs_must_be_finite_json"
    assert closed["status"] == "ok"
    assert missing["error"] == "workspace_not_found_or_expired"

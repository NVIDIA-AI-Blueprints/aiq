# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Register the bounded Python analysis workspace as a NAT function."""

from typing import Any
from typing import Literal

from pydantic import ConfigDict
from pydantic import Field

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

from .workspace import BoundedPythonWorkspace
from .workspace import WorkspaceLimits


class BoundedPythonConfig(FunctionBaseConfig, name="bounded_python"):
    """Configuration for bounded, stateful JSON analysis."""

    model_config = ConfigDict(extra="forbid")

    wall_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    cpu_time_seconds: int = Field(default=3, ge=1, le=30)
    memory_mb: int = Field(default=256, ge=64, le=2_048)
    max_code_chars: int = Field(default=20_000, ge=1_000, le=100_000)
    max_input_bytes: int = Field(default=1_000_000, ge=1_024, le=10_000_000)
    max_state_bytes: int = Field(default=2_000_000, ge=1_024, le=20_000_000)
    max_output_chars: int = Field(default=50_000, ge=1_000, le=500_000)
    workspace_ttl_seconds: int = Field(default=3_600, ge=60, le=86_400)
    max_workspaces: int = Field(default=128, ge=1, le=10_000)


@register_function(config_type=BoundedPythonConfig)
async def bounded_python(tool_config: BoundedPythonConfig, _builder: Builder):
    """Build one process-local manager for isolated analytical workspaces."""

    manager = BoundedPythonWorkspace(
        WorkspaceLimits(
            wall_timeout_seconds=tool_config.wall_timeout_seconds,
            cpu_time_seconds=tool_config.cpu_time_seconds,
            memory_mb=tool_config.memory_mb,
            max_code_chars=tool_config.max_code_chars,
            max_input_bytes=tool_config.max_input_bytes,
            max_state_bytes=tool_config.max_state_bytes,
            max_output_chars=tool_config.max_output_chars,
            workspace_ttl_seconds=tool_config.workspace_ttl_seconds,
            max_workspaces=tool_config.max_workspaces,
        )
    )

    async def _run(
        operation: Literal["start", "execute", "inspect", "reset", "close"],
        workspace_id: str | None = None,
        code: str | None = None,
        inputs: dict[str, Any] | None = None,
    ) -> str:
        """Run deterministic calculations in a bounded, stateful Python workspace.

        Call `start` once for each user task and retain the returned workspace_id.
        Use `execute` with that ID, Python code, and optional JSON-compatible
        inputs. Assigned JSON-compatible variables persist for later calls.
        Imports, attributes, filesystem/network access, and unbounded execution
        are unavailable. Set a `result` variable or make the last statement an
        expression. Use `inspect`, `reset`, and `close` to manage the workspace.
        """

        return await manager.run(
            operation=operation,
            workspace_id=workspace_id,
            code=code,
            inputs=inputs,
        )

    yield FunctionInfo.from_fn(_run, description=_run.__doc__)

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Register a request-scoped persistent Python kernel as a NAT function."""

from pydantic import ConfigDict
from pydantic import Field

from aiq_agent.agents.data_science.utils.analysis_runtime import get_analysis_run
from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

from .session import PersistentPythonSession
from .session import PythonSessionLimits


class StatefulPythonConfig(FunctionBaseConfig, name="stateful_python"):
    """Configuration for one persistent Python kernel per DS request."""

    model_config = ConfigDict(extra="forbid")

    wall_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_code_chars: int = Field(default=50_000, ge=1_000, le=500_000)
    max_output_chars: int = Field(default=50_000, ge=1_000, le=500_000)


@register_function(config_type=StatefulPythonConfig)
async def stateful_python(tool_config: StatefulPythonConfig, _builder: Builder):
    """Build one model-facing Python tool backed by request-owned kernels."""

    limits = PythonSessionLimits(
        wall_timeout_seconds=tool_config.wall_timeout_seconds,
        max_code_chars=tool_config.max_code_chars,
        max_output_chars=tool_config.max_output_chars,
    )

    async def _run(code: str) -> str:
        """Execute Python in the persistent analysis kernel for this request.

        Variables, imports, DataFrames, and fitted objects persist across calls.
        NumPy (`np`), pandas (`pd`), SciPy (`scipy`, `stats`), scikit-learn
        (`sklearn`), and statsmodels (`sm`) are preloaded. Successful agent-level
        GSF results are available through `list_gsf_results()`, `gsf_result(ref)`,
        `gsf_rows(ref)`, `gsf_sql(ref)`, and `gsf_latest()`.

        This is an analysis tool, not a data-access tool. It has no configured GSF
        client, source SQL connection, or benchmark database. Call GSF with the
        agent-level tools first, then analyze its registered rows here.
        """

        run_state = get_analysis_run()
        if run_state is None:
            return '{"status":"error","error":"analysis_runtime_unavailable"}'
        session = run_state.resources.get("stateful_python")
        if session is None:
            session = PersistentPythonSession(
                manifest_path=run_state.manifest_path,
                working_directory=run_state.root,
                limits=limits,
            )
            run_state.resources["stateful_python"] = session
        return await session.execute(code)

    yield FunctionInfo.from_fn(_run, description=_run.__doc__)

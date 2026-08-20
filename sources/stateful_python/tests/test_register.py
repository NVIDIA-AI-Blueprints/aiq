# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""NAT registration tests for request-scoped persistent Python."""

import json
from unittest.mock import MagicMock

import pytest
from stateful_python import register as register_module

from aiq_agent.agents.data_science.utils.analysis_runtime import begin_analysis_run
from aiq_agent.agents.data_science.utils.analysis_runtime import end_analysis_run
from aiq_agent.agents.data_science.utils.analysis_runtime import register_gsf_result


@pytest.mark.asyncio
async def test_registration_loads_exact_gsf_rows_without_copying() -> None:
    config = register_module.StatefulPythonConfig(wall_timeout_seconds=60)
    registration = register_module.stateful_python.__wrapped__(config, MagicMock())
    function_info = await anext(registration)
    token = begin_analysis_run()
    try:
        reference = register_gsf_result(
            question="Values",
            database_name="example",
            payload={"sql": "SELECT value", "rows": [{"value": 4}, {"value": 9}]},
        )
        response = json.loads(await function_info.single_fn(f"frame = gsf_rows('{reference}')\nframe['value'].mean()"))
    finally:
        await end_analysis_run(token)
        await registration.aclose()

    assert reference == "gsf_1"
    assert response["status"] == "ok"
    assert response["result"] == "np.float64(6.5)"

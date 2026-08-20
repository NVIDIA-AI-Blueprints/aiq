# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""NAT registration tests for bounded Python."""

import json
from unittest.mock import MagicMock

import pytest
from bounded_python import register as register_module


@pytest.mark.asyncio
async def test_registration_exposes_workspace_protocol() -> None:
    config = register_module.BoundedPythonConfig()
    registration = register_module.bounded_python.__wrapped__(config, MagicMock())
    function_info = await anext(registration)
    try:
        started = json.loads(await function_info.single_fn(function_info.input_schema(operation="start")))
        result = json.loads(
            await function_info.single_fn(
                function_info.input_schema(
                    operation="execute",
                    workspace_id=started["workspace_id"],
                    code="result = sum(inputs['values'])",
                    inputs={"values": [1, 2, 3]},
                )
            )
        )
    finally:
        await registration.aclose()

    assert result["result"] == 6

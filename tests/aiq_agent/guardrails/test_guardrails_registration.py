# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

"""Tests for Guardrails middleware registration behavior."""

from types import ModuleType
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aiq_agent.guardrails.deep_agent import register as deep_register
from aiq_agent.guardrails.shallow_agent import register as shallow_register
from aiq_agent.guardrails.workflow import register as workflow_register


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("register_module", "middleware_class_name", "factory_name"),
    [
        (workflow_register, "_WorkflowGuardrails", "workflow_guardrails_middleware"),
        (shallow_register, "_ShallowAgentGuardrails", "shallow_agent_guardrails_middleware"),
        (deep_register, "_DeepAgentGuardrails", "deep_agent_guardrails_middleware"),
    ],
)
async def test_registration_fails_fast_when_rail_binding_fails(
    register_module: ModuleType,
    middleware_class_name: str,
    factory_name: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """A configured Guardrails middleware must not load if rail LLM binding fails."""
    bind_llms_to_rail = AsyncMock(side_effect=RuntimeError("missing guardrails backend"))

    class FakeGuardrails:
        def __init__(self, config: object, builder: object):
            self.config = config
            self.builder = builder
            self.bind_llms_to_rail = bind_llms_to_rail

    monkeypatch.setattr(register_module, middleware_class_name, FakeGuardrails)
    factory = getattr(register_module, factory_name)

    with pytest.raises(RuntimeError, match="missing guardrails backend"):
        async with factory(config=SimpleNamespace(), builder=SimpleNamespace()):
            raise AssertionError("middleware should not be yielded when binding fails")

    bind_llms_to_rail.assert_awaited_once()

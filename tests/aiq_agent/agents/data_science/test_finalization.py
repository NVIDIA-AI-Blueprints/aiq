# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the reserved no-tool finalization turn."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import SystemMessage

from aiq_agent.agents.data_science.utils.analysis_runtime import begin_analysis_run
from aiq_agent.agents.data_science.utils.analysis_runtime import end_analysis_run
from aiq_agent.agents.data_science.utils.finalization import FinalizationReserveMiddleware


class _Request(SimpleNamespace):
    def override(self, **updates):
        values = vars(self) | updates
        return _Request(**values)


@pytest.mark.asyncio
async def test_finalization_removes_tools_at_configured_model_call() -> None:
    middleware = FinalizationReserveMiddleware(max_model_calls=2)
    request = _Request(
        system_message=SystemMessage(content="Base prompt"),
        tools=[{"name": "gsf__text_to_sql"}],
        tool_choice="auto",
    )
    handler = AsyncMock(side_effect=lambda value: value)
    token = begin_analysis_run()
    try:
        first = await middleware.awrap_model_call(request, handler)
        second = await middleware.awrap_model_call(request, handler)
    finally:
        await end_analysis_run(token)

    assert first.tools == request.tools
    assert second.tools == []
    assert second.tool_choice is None
    assert "FINALIZATION TURN" in second.system_message.text

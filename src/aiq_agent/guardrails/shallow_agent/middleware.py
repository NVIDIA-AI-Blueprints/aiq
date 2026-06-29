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

"""Shallow-agent Guardrails middleware."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from aiq_agent.agents.shallow_researcher.models import ShallowResearchAgentState
from aiq_agent.guardrails.interface.middleware import GuardrailsMixin
from aiq_agent.guardrails.shallow_agent.config import ShallowAgentGuardrailsConfig
from nat.builder.builder import Builder
from nat.middleware.middleware import InvocationContext


class _ShallowAgentGuardrails(GuardrailsMixin):
    """Provide Guardrails enforcement for shallow-agent boundaries.

    This middleware evaluates configured policies around shallow-agent
    invocation: selected input and output fields are checked, and blocked
    responses are returned in the shallow-agent state schema when possible.
    """

    def __init__(self, config: ShallowAgentGuardrailsConfig, builder: Builder):
        """Initialize shallow-agent Guardrails with its registered config."""
        super().__init__(config=config, builder=builder)

    def _on_pre_invoke_blocked(self, context: InvocationContext, block_message: str) -> ShallowResearchAgentState | str:
        """Return a shallow-agent state when input rails block."""
        return self._blocked_agent_state(context, block_message)

    def _on_post_invoke_blocked(
        self,
        context: InvocationContext,
        block_message: str,
        original_output: object,
    ) -> ShallowResearchAgentState | str:
        """Return a shallow-agent state when output rails block."""
        return self._blocked_agent_state(context, block_message, original_output)

    def _blocked_agent_state(
        self,
        context: InvocationContext,
        block_message: str,
        original_output: object | None = None,
    ) -> ShallowResearchAgentState | str:
        state = self._agent_state_from_context(context, original_output)
        if state is None:
            return block_message
        return state.model_copy(update={"messages": [*state.messages, AIMessage(content=block_message)]})

    def _agent_state_from_context(
        self,
        context: InvocationContext,
        original_output: object | None = None,
    ) -> ShallowResearchAgentState | None:
        modified_args = getattr(context, "modified_args", ())
        original_args = getattr(context, "original_args", ())
        for value in (
            original_output,
            context.output,
            modified_args[0] if modified_args else None,
            original_args[0] if original_args else None,
        ):
            if isinstance(value, ShallowResearchAgentState):
                return value
        return None

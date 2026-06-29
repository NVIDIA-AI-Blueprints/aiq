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

"""Shared Guardrails middleware behavior."""

from __future__ import annotations

from aiq_agent.guardrails.dynamic_field_selection import DynamicFieldSelectionMixin
from nat.middleware.middleware import InvocationContext
from nat.plugins.security.middleware.guardrails.nemo_guardrails_middleware import GuardrailsMiddleware


class GuardrailsMixin(DynamicFieldSelectionMixin, GuardrailsMiddleware):
    """Provide shared Guardrails behavior for boundary-specific middleware.

    This mixin adds dynamic field-selection traversal and block-response
    adaptation hooks so concrete middleware can guard selected boundary fields
    while preserving the intercepted function's expected return schema.
    """

    async def pre_invoke(self, context: InvocationContext) -> InvocationContext | None:
        """Run input rails and adapt blocked outputs for the intercepted boundary."""
        result = await super().pre_invoke(context)
        current_context = result or context
        # NAT returns a context for both input rewrites and blocks; only blocks populate output with a refusal.
        blocked = result is not None and current_context.output is not None
        if blocked and isinstance(current_context.output, str):
            current_context.output = self._on_pre_invoke_blocked(current_context, current_context.output)
        return result

    def _on_pre_invoke_blocked(self, context: InvocationContext, block_message: str) -> object:
        """Adapt input-rail block output for the intercepted boundary."""
        return block_message

    async def post_invoke(self, context: InvocationContext) -> InvocationContext | None:
        """Run output rails and adapt blocked outputs for the intercepted boundary."""
        return await super().post_invoke(context)

    def on_post_invoke_blocked(self, context: InvocationContext, block_message: str) -> object:
        """Adapt blocked output before the intercepted result is returned."""
        return self._on_post_invoke_blocked(context, block_message, context.output)

    def _on_post_invoke_blocked(
        self,
        context: InvocationContext,
        block_message: str,
        original_output: object,
    ) -> object:
        """Adapt output-rail block output for the intercepted boundary."""
        return block_message

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

"""Workflow-input Guardrails middleware."""

from __future__ import annotations

import logging
from typing import Any

from nemoguardrails.rails.llm.options import GenerationLogOptions
from nemoguardrails.rails.llm.options import GenerationOptions
from nemoguardrails.rails.llm.options import GenerationResponse

from aiq_agent.agents.chat_researcher.utils import _extract_query_and_sources
from aiq_agent.guardrails.interface.middleware import GuardrailsMixin
from aiq_agent.guardrails.workflow.config import WorkflowGuardrailsConfig
from nat.builder.builder import Builder
from nat.middleware.middleware import InvocationContext
from nat.plugins.security.middleware.guardrails.nemo_guardrails_middleware import GuardrailsMiddleware

logger = logging.getLogger(__name__)


class _WorkflowGuardrails(GuardrailsMixin):
    """Provide Guardrails enforcement for workflow boundaries.

    This middleware evaluates configured policies around workflow invocation:
    incoming workflow input is reduced to the user-facing text that should be
    checked, and outgoing workflow results are checked through the configured
    field selections.
    """

    def __init__(self, config: WorkflowGuardrailsConfig, builder: Builder):
        """Initialize workflow Guardrails with its registered config."""
        super().__init__(config=config, builder=builder)

    async def pre_invoke(self, context: InvocationContext) -> InvocationContext | None:
        """Run input rails over the normalized workflow query.

        Args:
            context: Invocation context for the workflow boundary.

        Returns:
            Updated context when input is blocked or rewritten; otherwise ``None``.
        """
        if not context.modified_args or context.modified_args[0] is None:
            return None

        input: Any = context.modified_args[0]

        query_text = self._extract_guardrail_target(input)
        if query_text is None:
            return None

        try:
            await self.bind_llms_to_rail()

            response: GenerationResponse = await self._llm_rails.generate_async(
                prompt=query_text,
                options=GenerationOptions(
                    rails=["input"],
                    log=GenerationLogOptions(activated_rails=True),
                    output_vars=["user_message", "bot_message"],
                ),
            )

            if self._rail_blocked(response):
                context.output = self._handle_blocked_rail_response(response)
                return context

            modified_query_text = self._handle_modified_rail_response(response, fallback=query_text)
            if modified_query_text != query_text:
                args = list(context.modified_args)
                args[0] = modified_query_text
                context.modified_args = tuple(args)
                return context

            return None
        except Exception:
            logger.exception("Workflow input Guardrails failed while evaluating query text; continuing without rails")
            return None

    async def post_invoke(self, context: InvocationContext) -> InvocationContext | None:
        """Run output rails for the configured workflow result fields."""
        return await GuardrailsMiddleware.post_invoke(self, context)

    def _extract_guardrail_target(self, raw_input: object) -> str | None:
        """Extract the normalized user query text from a raw workflow input."""
        try:
            query_text, _data_sources = _extract_query_and_sources(raw_input)
        except Exception:
            logger.exception(
                "Workflow input Guardrails could not extract query text from input type %s; continuing without rails",
                type(raw_input).__name__,
            )
            return None

        if not query_text:
            logger.warning(
                "Workflow input Guardrails could not extract query text from input type %s; continuing without rails",
                type(raw_input).__name__,
            )
            return None

        return query_text

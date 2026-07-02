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

import json
import logging
from collections.abc import Callable
from typing import Any

from nemoguardrails.rails.llm.options import GenerationLogOptions
from nemoguardrails.rails.llm.options import GenerationOptions
from nemoguardrails.rails.llm.options import GenerationResponse

from aiq_agent.agents.chat_researcher.utils import _extract_context_from_text
from aiq_agent.agents.chat_researcher.utils import _is_user_role
from aiq_agent.guardrails.interface.middleware import _GUARDRAILS_FAILURE_REFUSAL
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

        targets = self._extract_guardrail_targets_for_rewrite(input)
        if not targets:
            return None

        try:
            await self.bind_llms_to_rail()

            modified = False
            args = list(context.modified_args)
            for query_text, replace_query in targets:
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
                if modified_query_text == query_text:
                    continue

                args = list(context.modified_args)
                args[0] = replace_query(modified_query_text)
                context.modified_args = tuple(args)
                modified = True

            return context if modified else None
        except Exception:
            logger.exception("Workflow input Guardrails failed while evaluating query text; refusing request")
            context.output = self._on_pre_invoke_blocked(context, _GUARDRAILS_FAILURE_REFUSAL)
            return context

    async def post_invoke(self, context: InvocationContext) -> InvocationContext | None:
        """Run output rails for the configured workflow result fields."""
        return await GuardrailsMiddleware.post_invoke(self, context)

    def _extract_guardrail_target(self, raw_input: object) -> str | None:
        """Extract the normalized user query text from a raw workflow input."""
        targets = self._extract_guardrail_targets_for_rewrite(raw_input)
        if not targets:
            return None
        return targets[0][0]

    def _extract_guardrail_targets_for_rewrite(
        self,
        raw_input: object,
    ) -> list[tuple[str, Callable[[str], object]]]:
        """Extract guardrail targets that each map to one writable string leaf."""
        try:
            targets = self._extract_guardrail_targets_for_rewrite_unchecked(raw_input)
        except Exception:
            logger.exception(
                "Workflow input Guardrails could not extract query text from input type %s; continuing without rails",
                type(raw_input).__name__,
            )
            return []

        targets = [(text, replace_text) for text, replace_text in targets if text]
        if not targets:
            logger.warning(
                "Workflow input Guardrails could not extract query text from input type %s; continuing without rails",
                type(raw_input).__name__,
            )
            return []

        return targets

    def _extract_guardrail_targets_for_rewrite_unchecked(
        self,
        raw_input: object,
    ) -> list[tuple[str, Callable[[str], object]]]:
        """Extract query text targets and preserve their source locations."""
        # Each target is one concrete string leaf. Input rails are applied to
        # leaves independently, and modified text is written back to that same
        # leaf without aggregating or redistributing text.
        if isinstance(raw_input, str):
            return [self._target_from_text(raw_input, lambda new_text: new_text)]

        if isinstance(raw_input, dict):
            content = raw_input.get("content", {}) if isinstance(raw_input.get("content"), dict) else {}
            targets = self._extract_messages_targets(raw_input, content.get("messages"))
            if targets:
                return targets

            for field in ("query", "message", "text"):
                item = raw_input.get(field)
                if isinstance(item, str) and item.strip():
                    return [
                        self._target_from_text(
                            item,
                            lambda new_text, field=field: self._set_dict_value(raw_input, raw_input, field, new_text),
                        )
                    ]

            return []

        messages = getattr(raw_input, "messages", None)
        targets = self._extract_messages_targets(raw_input, messages)
        if targets:
            return targets
        return []

    def _extract_messages_targets(
        self,
        raw_input: object,
        messages: object,
    ) -> list[tuple[str, Callable[[str], object]]]:
        """Extract guardrail targets from the selected message in a list."""
        if not isinstance(messages, list) or not messages:
            return []

        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if self._message_has_user_role(message):
                targets = self._extract_message_targets(
                    raw_input,
                    message,
                    lambda new_text, index=index: self._set_list_value(raw_input, messages, index, new_text),
                )
                if targets:
                    return targets

        return self._extract_message_targets(
            raw_input,
            messages[-1],
            lambda new_text: self._set_list_value(raw_input, messages, len(messages) - 1, new_text),
        )

    def _message_has_user_role(self, message: object) -> bool:
        """Return whether a message object or dictionary has the user role."""
        role = message.get("role") if isinstance(message, dict) else getattr(message, "role", None)
        return _is_user_role(role)

    def _extract_message_targets(
        self,
        raw_input: object,
        message: object,
        write_message: Callable[[str], object],
    ) -> list[tuple[str, Callable[[str], object]]]:
        """Extract guardrail targets from a message without aggregating text."""
        if isinstance(message, str):
            return [self._target_from_text(message, write_message)]

        if isinstance(message, dict):
            targets = self._extract_content_targets(
                raw_input,
                message.get("content"),
                lambda new_text: self._set_dict_value(raw_input, message, "content", new_text),
            )
            if targets:
                return targets
            text_value = message.get("text")
            if isinstance(text_value, str) and text_value.strip():
                return [
                    self._target_from_text(
                        text_value,
                        lambda new_text: self._set_dict_value(raw_input, message, "text", new_text),
                    )
                ]
            return targets

        content = getattr(message, "content", None)
        targets = self._extract_content_targets(
            raw_input,
            content,
            lambda new_text: self._set_attr_value(raw_input, message, "content", new_text),
        )
        if targets:
            return targets

        text_value = getattr(message, "text", None)
        if isinstance(text_value, str) and text_value.strip():
            return [
                self._target_from_text(
                    text_value,
                    lambda new_text: self._set_attr_value(raw_input, message, "text", new_text),
                )
            ]
        return []

    def _extract_content_targets(
        self,
        raw_input: object,
        content: object,
        write_content: Callable[[str], object],
    ) -> list[tuple[str, Callable[[str], object]]]:
        """Extract guardrail targets from one message content value."""
        if isinstance(content, str) and content.strip():
            return [self._target_from_text(content, write_content)]

        if not isinstance(content, list):
            return []

        targets: list[tuple[str, Callable[[str], object]]] = []
        for index, item in enumerate(content):
            targets.extend(
                self._extract_content_item_targets(
                    raw_input,
                    item,
                    lambda new_text, index=index: self._set_list_value(raw_input, content, index, new_text),
                )
            )
        return targets

    def _extract_content_item_targets(
        self,
        raw_input: object,
        item: object,
        write_item: Callable[[str], object],
    ) -> list[tuple[str, Callable[[str], object]]]:
        """Extract guardrail targets from one message content list item."""
        if isinstance(item, str) and item.strip():
            return [self._target_from_text(item, write_item)]

        if isinstance(item, dict):
            text_value = item.get("text")
            if isinstance(text_value, str) and text_value.strip():
                return [
                    self._target_from_text(
                        text_value,
                        lambda new_text: self._set_dict_value(raw_input, item, "text", new_text),
                    )
                ]
            return []

        text_value = getattr(item, "text", None)
        if isinstance(text_value, str) and text_value.strip():
            return [
                self._target_from_text(
                    text_value,
                    lambda new_text: self._set_attr_value(raw_input, item, "text", new_text),
                )
            ]
        return []

    def _target_from_text(
        self,
        text: str,
        write_text: Callable[[str], object],
    ) -> tuple[str, Callable[[str], object]]:
        """Normalize inline JSON query text and keep a matching writer."""
        query_text = _extract_context_from_text(text).query_text

        def replace_query(new_query_text: str) -> object:
            return write_text(self._replace_inline_query_text(text, new_query_text))

        return query_text, replace_query

    def _replace_inline_query_text(self, original_text: str, new_query_text: str) -> str:
        """Replace query/text inside inline JSON while preserving other fields."""
        trimmed = original_text.strip()
        if trimmed.startswith("{") and trimmed.endswith("}"):
            try:
                payload = json.loads(trimmed)
            except json.JSONDecodeError:
                return new_query_text
            if isinstance(payload, dict):
                for field in ("query", "text"):
                    if isinstance(payload.get(field), str) and payload[field].strip():
                        payload[field] = new_query_text
                        return json.dumps(payload)
        return new_query_text

    def _set_dict_value(self, raw_input: object, payload: dict[str, Any], field: str, value: str) -> object:
        """Update the dictionary field that provided guardrail text."""
        payload[field] = value
        return raw_input

    def _set_attr_value(self, raw_input: object, payload: object, field: str, value: str) -> object:
        """Update the object attribute that provided guardrail text."""
        setattr(payload, field, value)
        return raw_input

    def _set_list_value(self, raw_input: object, payload: list[Any], index: int, value: str) -> object:
        """Update the list item that provided guardrail text."""
        payload[index] = value
        return raw_input

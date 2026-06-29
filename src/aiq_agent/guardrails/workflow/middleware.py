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

from aiq_agent.agents.chat_researcher.utils import _extract_query_and_sources
from aiq_agent.agents.chat_researcher.utils import _extract_query_from_text
from aiq_agent.agents.chat_researcher.utils import _extract_text_from_message
from aiq_agent.agents.chat_researcher.utils import _is_text_type
from aiq_agent.agents.chat_researcher.utils import _is_user_role
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

        target = self._extract_guardrail_target_for_rewrite(input)
        if target is None:
            return None
        query_text, replace_query = target

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
                args[0] = replace_query(modified_query_text)
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
        target = self._extract_guardrail_target_for_rewrite(raw_input)
        if target is None:
            return None
        return target[0]

    def _extract_guardrail_target_for_rewrite(
        self,
        raw_input: object,
    ) -> tuple[str, Callable[[str], object]] | None:
        """Extract query text with a writer for the same input location."""
        try:
            target = self._extract_guardrail_target_for_rewrite_unchecked(raw_input)
        except Exception:
            logger.exception(
                "Workflow input Guardrails could not extract query text from input type %s; continuing without rails",
                type(raw_input).__name__,
            )
            return None

        if target is None:
            query_text = ""
        else:
            query_text = target[0]
        if not query_text:
            logger.warning(
                "Workflow input Guardrails could not extract query text from input type %s; continuing without rails",
                type(raw_input).__name__,
            )
            return None

        return target

    def _extract_guardrail_target_for_rewrite_unchecked(
        self,
        raw_input: object,
    ) -> tuple[str, Callable[[str], object]] | None:
        """Extract query text and preserve the source location for rewrites."""
        if isinstance(raw_input, dict):
            content = raw_input.get("content", {}) if isinstance(raw_input.get("content"), dict) else {}
            target = self._extract_messages_target(raw_input, content.get("messages"))
            if target is not None:
                return target

            query_text, _data_sources = _extract_query_and_sources(raw_input)
            if query_text:
                return self._find_matching_text_target(raw_input, raw_input, query_text)

            return None

        messages = getattr(raw_input, "messages", None)
        target = self._extract_messages_target(raw_input, messages)
        if target is not None:
            return target
        if isinstance(messages, list):
            return None

        text = str(raw_input)
        return self._target_from_text(text, lambda new_text: new_text)

    def _extract_messages_target(
        self,
        raw_input: object,
        messages: object,
    ) -> tuple[str, Callable[[str], object]] | None:
        """Extract a guardrail target from a message list."""
        if not isinstance(messages, list) or not messages:
            return None

        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if self._message_has_user_role(message):
                target = self._extract_message_target(
                    raw_input,
                    message,
                    lambda new_text, index=index: self._set_list_value(raw_input, messages, index, new_text),
                )
                if target is not None:
                    return target

        return self._extract_message_target(
            raw_input,
            messages[-1],
            lambda new_text: self._set_list_value(raw_input, messages, len(messages) - 1, new_text),
        )

    def _message_has_user_role(self, message: object) -> bool:
        """Return whether a message object or dictionary has the user role."""
        role = message.get("role") if isinstance(message, dict) else getattr(message, "role", None)
        return _is_user_role(role)

    def _extract_message_target(
        self,
        raw_input: object,
        message: object,
        write_message: Callable[[str], object],
    ) -> tuple[str, Callable[[str], object]] | None:
        """Extract guardrail text from a message with a writer for that source."""
        expected_text = _extract_text_from_message(message)
        if not expected_text:
            return None
        return self._find_matching_text_target(raw_input, message, expected_text, fallback_writer=write_message)

    def _find_matching_text_target(
        self,
        raw_input: object,
        value: object,
        expected_text: str,
        *,
        fallback_writer: Callable[[str], object] | None = None,
    ) -> tuple[str, Callable[[str], object]] | None:
        """Find the writable text value matching the extracted guardrail text."""
        for text, write_text in self._iter_text_targets(raw_input, value, fallback_writer):
            query_text, _data_sources = _extract_query_from_text(text)
            if expected_text in (query_text, text):
                return self._target_from_text(text, write_text)

        return None

    def _iter_text_targets(
        self,
        raw_input: object,
        value: object,
        write_value: Callable[[str], object] | None,
    ) -> list[tuple[str, Callable[[str], object]]]:
        """Return writable text targets contained in a value."""
        if isinstance(value, str):
            return [(value, write_value)] if write_value is not None else []

        if isinstance(value, list):
            targets: list[tuple[str, Callable[[str], object]]] = []
            text_parts = self._list_text_parts(value)
            if text_parts and write_value is not None:
                targets.append(("\n".join(text_parts).strip(), write_value))

            for index, item in enumerate(value):
                targets.extend(
                    self._iter_text_targets(
                        raw_input,
                        item,
                        lambda new_text, index=index: self._set_list_value(raw_input, value, index, new_text),
                    )
                )
            return targets

        if isinstance(value, dict):
            targets = []
            for field, item in value.items():
                targets.extend(
                    self._iter_text_targets(
                        raw_input,
                        item,
                        lambda new_text, field=field: self._set_dict_value(raw_input, value, field, new_text),
                    )
                )
            return targets

        try:
            fields = vars(value)
        except TypeError:
            return []

        targets = []
        for field in fields:
            item = getattr(value, field)
            targets.extend(
                self._iter_text_targets(
                    raw_input,
                    item,
                    lambda new_text, field=field: self._set_attr_value(raw_input, value, field, new_text),
                )
            )
        return targets

    def _list_text_parts(self, value: list[Any]) -> list[str]:
        """Extract text parts from a multimodal content list."""
        parts: list[str] = []
        for item in value:
            if hasattr(item, "type") and _is_text_type(getattr(item, "type")):
                text_value = getattr(item, "text", None)
            elif isinstance(item, dict) and _is_text_type(item.get("type")):
                text_value = item.get("text")
            else:
                text_value = None

            if text_value:
                parts.append(str(text_value))
        return parts

    def _target_from_text(
        self,
        text: str,
        write_text: Callable[[str], object],
    ) -> tuple[str, Callable[[str], object]]:
        """Normalize inline JSON query text and keep a matching writer."""
        query_text, _inline_sources = _extract_query_from_text(text)

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

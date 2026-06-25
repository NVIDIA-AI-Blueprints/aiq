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

"""Tests for workflow-input Guardrails target selection and response handling.

These tests mock the NeMo Guardrails response shapes observed from the built-in
sensitive-data input rails. They verify that the workflow input class can find
the normalized user input text and apply pass/block/modify results returned by
the Guardrails runtime.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aiq_agent.guardrails.workflow_input_guardrails import _WorkflowInputGuardrails
from nat.middleware.middleware import FunctionMiddlewareContext


@pytest.fixture
def guardrails() -> _WorkflowInputGuardrails:
    """Create the middleware without constructing the NeMo Guardrails runtime."""
    return _WorkflowInputGuardrails.__new__(_WorkflowInputGuardrails)


def _rail_response(
    response: str,
    *,
    rail_name: str,
    stopped: bool = False,
    bot_message: str | None = None,
) -> SimpleNamespace:
    """Build the small response shape used by the NAT Guardrails helpers."""
    output_data = {"user_message": response}
    if bot_message is not None:
        output_data["bot_message"] = bot_message

    return SimpleNamespace(
        response=response,
        output_data=output_data,
        log=SimpleNamespace(activated_rails=[SimpleNamespace(name=rail_name, stop=stopped)]),
    )


@pytest.mark.parametrize(
    ("raw_input", "expected_query_text"),
    [
        pytest.param(  # Plain string input.
            "Research NAT guardrails",
            "Research NAT guardrails",
        ),
        pytest.param(  # Stringified JSON payload with query and data sources.
            '{"query": "Research NAT guardrails", "data_sources": ["docs"]}',
            "Research NAT guardrails",
        ),
        pytest.param(  # Stringified JSON payload with text and a single data source.
            '{"text": "Research NAT guardrails", "data_sources": "docs"}',
            "Research NAT guardrails",
        ),
        pytest.param(  # Dict with top-level message.
            {"message": "Research NAT guardrails"},
            "Research NAT guardrails",
        ),
        pytest.param(  # Dict with top-level text.
            {"text": "Research NAT guardrails"},
            "Research NAT guardrails",
        ),
        pytest.param(  # Dict with API-style message history.
            {
                "content": {
                    "messages": [
                        {"role": "system", "content": "system text"},
                        {"role": "user", "content": "Research NAT guardrails"},
                    ]
                }
            },
            "Research NAT guardrails",
        ),
        pytest.param(  # Dict message history prefers the latest user message.
            {
                "content": {
                    "messages": [
                        {"role": "user", "content": "First question"},
                        {"role": "assistant", "content": "First answer"},
                        {"role": "user", "content": "Research NAT guardrails"},
                    ]
                }
            },
            "Research NAT guardrails",
        ),
        pytest.param(  # Dict message history falls back to the last message when no user role exists.
            {
                "content": {
                    "messages": [
                        {"role": "assistant", "content": "Assistant response"},
                        {"role": "system", "content": "Research NAT guardrails"},
                    ]
                }
            },
            "Research NAT guardrails",
        ),
        pytest.param(  # Dict message history can carry data sources at the content level.
            {
                "content": {
                    "messages": [{"role": "user", "content": "Research NAT guardrails"}],
                    "data_sources": ["docs"],
                }
            },
            "Research NAT guardrails",
        ),
        pytest.param(  # Dict message content can be multipart text.
            {
                "content": {
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Research NAT"},
                                {"type": "image", "url": "https://example.com/image.png"},
                                {"type": "text", "text": "guardrails"},
                            ],
                        }
                    ]
                }
            },
            "Research NAT\nguardrails",
        ),
        pytest.param(  # Dict message content can contain inline JSON with data sources.
            {
                "content": {
                    "messages": [
                        {
                            "role": "user",
                            "content": '{"query": "Research NAT guardrails", "data_sources": ["docs"]}',
                        }
                    ]
                }
            },
            "Research NAT guardrails",
        ),
        pytest.param(  # Object with message attributes and data sources.
            SimpleNamespace(
                messages=[
                    SimpleNamespace(role="system", content="system text"),
                    SimpleNamespace(role="user", content="Research NAT guardrails"),
                ],
                data_sources=["docs"],
            ),
            "Research NAT guardrails",
        ),
        pytest.param(  # Object message content can be multipart text.
            SimpleNamespace(
                messages=[
                    SimpleNamespace(
                        role="user",
                        content=[
                            SimpleNamespace(type="text", text="Research NAT"),
                            SimpleNamespace(type="image", url="https://example.com/image.png"),
                            SimpleNamespace(type="text", text="guardrails"),
                        ],
                    )
                ],
                data_sources=None,
            ),
            "Research NAT\nguardrails",
        ),
    ],
)
def test_input_text_can_be_extracted_to_apply_rail(
    guardrails: _WorkflowInputGuardrails,
    raw_input: object,
    expected_query_text: str,
):
    """Supported raw inputs resolve to guardable query text."""
    query_text = guardrails._extract_guardrail_target(raw_input)

    assert query_text == expected_query_text


@pytest.mark.parametrize(
    "raw_input",
    [
        pytest.param(  # Empty dict has no query-bearing field.
            {},
        ),
        pytest.param(  # Dict with empty message history has no query-bearing message.
            {"content": {"messages": []}},
        ),
        pytest.param(  # Dict with data sources but no query text.
            {"data_sources": ["docs"]},
        ),
        pytest.param(  # Dict with content in an unsupported shape.
            {"content": ["not a supported content payload"]},
        ),
        pytest.param(  # Dict message whose user content is not extractable text.
            {"content": {"messages": [{"role": "user", "content": {"nested": "not supported"}}]}},
        ),
        pytest.param(  # Object with empty message history.
            SimpleNamespace(messages=[], data_sources=["docs"]),
        ),
        pytest.param(  # Object message whose user content is not extractable text.
            SimpleNamespace(
                messages=[SimpleNamespace(role="user", content=SimpleNamespace(nested="not supported"))],
                data_sources=None,
            ),
        ),
    ],
)
@pytest.mark.asyncio
async def test_pre_invoke_does_nothing_when_input_text_cannot_be_extracted(
    guardrails: _WorkflowInputGuardrails,
    raw_input: object,
):
    """Unsupported structured inputs do not run rails or change workflow input."""
    guardrails.bind_llms_to_rail = AsyncMock()
    context = SimpleNamespace(modified_args=(raw_input,), output=None)

    result = await guardrails.pre_invoke(context)

    assert result is None
    assert context.modified_args == (raw_input,)
    assert context.output is None


@pytest.mark.asyncio
async def test_pre_invoke_passes_when_rail_passes(guardrails: _WorkflowInputGuardrails):
    """A passing `detect sensitive data on input` response leaves the input unchanged."""
    raw_input = "Please follow up about this issue."

    guardrails.bind_llms_to_rail = AsyncMock()
    guardrails._llm_rails = SimpleNamespace(
        generate_async=AsyncMock(return_value=_rail_response(raw_input, rail_name="detect sensitive data on input"))
    )
    context = SimpleNamespace(modified_args=(raw_input,), output=None)

    result = await guardrails.pre_invoke(context)

    assert result is None
    assert context.modified_args == (raw_input,)
    assert context.output is None


@pytest.mark.asyncio
async def test_pre_invoke_modifies_when_rail_modifies(
    guardrails: _WorkflowInputGuardrails,
):
    """A modified `mask sensitive data on input` response rewrites the workflow input."""
    raw_input = "Please follow up with customer@example.com about this issue."
    modified_input = "Please follow up with <EMAIL_ADDRESS> about this issue."

    guardrails.bind_llms_to_rail = AsyncMock()
    guardrails._llm_rails = SimpleNamespace(
        generate_async=AsyncMock(return_value=_rail_response(modified_input, rail_name="mask sensitive data on input"))
    )
    context = SimpleNamespace(modified_args=(raw_input,), output=None)

    result = await guardrails.pre_invoke(context)

    assert result is context
    assert context.modified_args == (modified_input,)
    assert context.output is None


@pytest.mark.asyncio
async def test_pre_invoke_block_skips_function_invocation(
    guardrails: _WorkflowInputGuardrails,
):
    """A blocked `detect sensitive data on input` response skips the wrapped function."""
    raw_input = "Please follow up with customer@example.com about this issue."
    blocked_output = "I don't know the answer to that."

    guardrails.bind_llms_to_rail = AsyncMock()
    guardrails._llm_rails = SimpleNamespace(
        generate_async=AsyncMock(
            return_value=_rail_response(
                blocked_output,
                rail_name="detect sensitive data on input",
                stopped=True,
                bot_message=blocked_output,
            )
        )
    )
    call_next = AsyncMock(return_value="workflow result")

    result = await guardrails.function_middleware_invoke(
        raw_input,
        call_next=call_next,
        context=FunctionMiddlewareContext(
            name="chat_deepresearcher_agent",
            config=None,
            description=None,
            input_schema=None,
            single_output_schema=type(None),
            stream_output_schema=type(None),
        ),
    )

    assert result == blocked_output
    call_next.assert_not_awaited()

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

"""Tests for workflow Guardrails input and output boundary handling.

These tests mock the NeMo Guardrails response shapes observed from the built-in
sensitive-data rails. They verify that the workflow middleware can find the
normalized workflow input text and apply pass/block/modify results returned by
the Guardrails runtime on both pre-invoke and post-invoke boundaries.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aiq_agent.common import _create_chat_response
from aiq_agent.guardrails.workflow.middleware import _WorkflowGuardrails
from nat.middleware.middleware import FunctionMiddlewareContext
from nat.plugins.security.middleware.guardrails.nemo_guardrails_middleware import _DEFAULT_REFUSAL
from nat.plugins.security.middleware.guardrails.nemo_guardrails_middleware_config import GuardrailFunctionFields

_TEST_WORKFLOW_FUNCTION = "test_workflow_function"


@pytest.fixture
def guardrails() -> _WorkflowGuardrails:
    """Create the middleware without constructing the NeMo Guardrails runtime."""
    guardrails = _WorkflowGuardrails.__new__(_WorkflowGuardrails)
    guardrails._guardrails_config = SimpleNamespace(
        workflow_functions={
            _TEST_WORKFLOW_FUNCTION: GuardrailFunctionFields.model_validate({"choices": ["message.content"]})
        }
    )
    return guardrails


def _workflow_context(output: object, *, original_input: str = "Please summarize this issue.") -> SimpleNamespace:
    return SimpleNamespace(
        function_context=FunctionMiddlewareContext(
            name=_TEST_WORKFLOW_FUNCTION,
            config=None,
            description=None,
            input_schema=None,
            single_output_schema=type(None),
            stream_output_schema=type(None),
        ),
        original_args=(original_input,),
        output=output,
    )


def _workflow_response(content: str):
    return _create_chat_response(content, response_id="research_response", model=_TEST_WORKFLOW_FUNCTION)


def _rail_response(
    response: object,
    *,
    rail_name: str,
    stopped: bool = False,
    bot_message: str | None = None,
) -> SimpleNamespace:
    """Build the small response shape used by the NAT Guardrails helpers."""
    output_data = {"user_message": response} if isinstance(response, str) else {}
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
    guardrails: _WorkflowGuardrails,
    raw_input: object,
    expected_query_text: str,
):
    """Supported raw workflow inputs resolve to guardable query text."""
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
    guardrails: _WorkflowGuardrails,
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
async def test_pre_invoke_passes_when_rail_passes(guardrails: _WorkflowGuardrails):
    """A passing `detect sensitive data on input` response leaves the input unchanged."""
    raw_input = "Please follow up about this issue."

    # Rail returns the same text, so pre_invoke should not change the workflow input.
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
    guardrails: _WorkflowGuardrails,
):
    """A modified `mask sensitive data on input` response rewrites the workflow input."""
    raw_input = "Please follow up with customer@example.com about this issue."
    modified_input = "Please follow up with <EMAIL_ADDRESS> about this issue."

    # Rail returns rewritten text, so pre_invoke should replace the workflow argument.
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
    guardrails: _WorkflowGuardrails,
):
    """A blocked `detect sensitive data on input` response skips the wrapped function."""
    raw_input = "Please follow up with customer@example.com about this issue."
    blocked_output = _DEFAULT_REFUSAL

    # Blocking input rails set context.output, so the wrapped workflow must not run.
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
            name=_TEST_WORKFLOW_FUNCTION,
            config=None,
            description=None,
            input_schema=None,
            single_output_schema=type(None),
            stream_output_schema=type(None),
        ),
    )

    assert result == blocked_output
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_invoke_passes_when_rail_passes(guardrails: _WorkflowGuardrails):
    """A passing output rail leaves configured ChatResponse message content unchanged."""
    output_text = "The requested follow up is complete."
    output = _workflow_response(output_text)

    # Output rail returns the same assistant content, so the ChatResponse stays unchanged.
    guardrails.bind_llms_to_rail = AsyncMock()
    guardrails._llm_rails = SimpleNamespace(
        generate_async=AsyncMock(
            return_value=_rail_response(
                [{"role": "assistant", "content": output_text}],
                rail_name="detect sensitive data on output",
            )
        )
    )
    context = _workflow_context(output)

    result = await guardrails.post_invoke(context)

    assert result is None
    assert context.output.choices[0].message.content == output_text
    guardrails._llm_rails.generate_async.assert_awaited_once()
    assert guardrails._llm_rails.generate_async.await_args.kwargs["messages"][-1]["content"] == output_text


@pytest.mark.asyncio
async def test_post_invoke_modifies_when_rail_modifies(guardrails: _WorkflowGuardrails):
    """A modified output rail rewrites configured ChatResponse message content."""
    output_text = "Please follow up with customer@example.com about this issue."
    modified_output = "Please follow up with <EMAIL_ADDRESS> about this issue."
    output = _workflow_response(output_text)

    # Output rail returns rewritten assistant content, so the configured field is updated.
    guardrails.bind_llms_to_rail = AsyncMock()
    guardrails._llm_rails = SimpleNamespace(
        generate_async=AsyncMock(
            return_value=_rail_response(
                [{"role": "assistant", "content": modified_output}],
                rail_name="mask sensitive data on output",
            )
        )
    )
    context = _workflow_context(output)

    result = await guardrails.post_invoke(context)

    assert result is context
    assert context.output.choices[0].message.content == modified_output
    guardrails._llm_rails.generate_async.assert_awaited_once()
    assert guardrails._llm_rails.generate_async.await_args.kwargs["messages"][-1]["content"] == output_text


@pytest.mark.asyncio
async def test_post_invoke_blocks_when_rail_blocks(guardrails: _WorkflowGuardrails):
    """A blocked output rail replaces context output with the inherited refusal string."""
    output_text = "Please follow up with customer@example.com about this issue."
    blocked_output = _DEFAULT_REFUSAL
    output = _workflow_response(output_text)

    # Blocking output rails replace context.output with the inherited refusal string.
    guardrails.bind_llms_to_rail = AsyncMock()
    guardrails._llm_rails = SimpleNamespace(
        generate_async=AsyncMock(
            return_value=_rail_response(
                [{"role": "assistant", "content": blocked_output}],
                rail_name="detect sensitive data on output",
                stopped=True,
                bot_message=blocked_output,
            )
        )
    )
    context = _workflow_context(output)

    result = await guardrails.post_invoke(context)

    assert result is context
    assert context.output == blocked_output
    assert output.choices[0].message.content == output_text
    guardrails._llm_rails.generate_async.assert_awaited_once()
    assert guardrails._llm_rails.generate_async.await_args.kwargs["messages"][-1]["content"] == output_text

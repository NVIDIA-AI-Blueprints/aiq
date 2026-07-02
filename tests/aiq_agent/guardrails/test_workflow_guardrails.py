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

import json
import logging
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aiq_agent.common import _create_chat_response
from aiq_agent.guardrails.dynamic_field_selection import FunctionFieldSelection
from aiq_agent.guardrails.interface.middleware import _GUARDRAILS_FAILURE_REFUSAL
from aiq_agent.guardrails.workflow.middleware import _WorkflowGuardrails
from nat.middleware.middleware import FunctionMiddlewareContext
from tests.aiq_agent.guardrails._test_utils import TEST_REFUSAL

_TEST_WORKFLOW_FUNCTION = "test_workflow_function"


@pytest.fixture
def guardrails() -> _WorkflowGuardrails:
    """Create the middleware without constructing the NeMo Guardrails runtime."""
    guardrails = _WorkflowGuardrails.__new__(_WorkflowGuardrails)
    guardrails._guardrails_config = SimpleNamespace(
        workflow_functions={
            _TEST_WORKFLOW_FUNCTION: FunctionFieldSelection.model_validate({"choices": ["message.content"]})
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
    ("raw_input", "expected_query_texts"),
    [
        pytest.param(  # Plain string input.
            "Research NAT guardrails",
            ["Research NAT guardrails"],
        ),
        pytest.param(  # Stringified JSON payload with query and data sources.
            '{"query": "Research NAT guardrails", "data_sources": ["docs"]}',
            ["Research NAT guardrails"],
        ),
        pytest.param(  # Stringified JSON payload with text and a single data source.
            '{"text": "Research NAT guardrails", "data_sources": "docs"}',
            ["Research NAT guardrails"],
        ),
        pytest.param(  # Dict with top-level message.
            {"message": "Research NAT guardrails"},
            ["Research NAT guardrails"],
        ),
        pytest.param(  # Dict with top-level text.
            {"text": "Research NAT guardrails"},
            ["Research NAT guardrails"],
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
            ["Research NAT guardrails"],
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
            ["Research NAT guardrails"],
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
            ["Research NAT guardrails"],
        ),
        pytest.param(  # Dict message history can carry data sources at the content level.
            {
                "content": {
                    "messages": [{"role": "user", "content": "Research NAT guardrails"}],
                    "data_sources": ["docs"],
                }
            },
            ["Research NAT guardrails"],
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
            ["Research NAT", "guardrails"],
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
            ["Research NAT guardrails"],
        ),
        pytest.param(  # Object with message attributes and data sources.
            SimpleNamespace(
                messages=[
                    SimpleNamespace(role="system", content="system text"),
                    SimpleNamespace(role="user", content="Research NAT guardrails"),
                ],
                data_sources=["docs"],
            ),
            ["Research NAT guardrails"],
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
            ["Research NAT", "guardrails"],
        ),
    ],
)
def test_input_text_targets_can_be_extracted_to_apply_rails(
    guardrails: _WorkflowGuardrails,
    raw_input: object,
    expected_query_texts: list[str],
):
    """Supported raw workflow inputs resolve to individual guardable string leaves."""
    targets = guardrails._extract_guardrail_targets_for_rewrite(raw_input)

    assert [query_text for query_text, _replace_query in targets] == expected_query_texts


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
        pytest.param(  # Arbitrary objects are not stringified into guardrail text.
            object(),
        ),
    ],
)
@pytest.mark.asyncio
async def test_pre_invoke_does_nothing_when_input_text_cannot_be_extracted(
    guardrails: _WorkflowGuardrails,
    raw_input: object,
    caplog: pytest.LogCaptureFixture,
):
    """Unsupported structured inputs do not run rails or change workflow input."""
    caplog.set_level(logging.WARNING, logger="aiq_agent.guardrails.workflow.middleware")
    guardrails.bind_llms_to_rail = AsyncMock()
    context = SimpleNamespace(modified_args=(raw_input,), output=None)

    result = await guardrails.pre_invoke(context)

    assert result is None
    assert context.modified_args == (raw_input,)
    assert context.output is None
    guardrails.bind_llms_to_rail.assert_not_awaited()
    assert "could not extract query text from input type" in caplog.text


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


@pytest.mark.parametrize(
    ("raw_input", "assert_rewrite"),
    [
        pytest.param(
            {"message": "Please follow up with customer@example.com.", "data_sources": ["docs"]},
            lambda value, modified: (
                value["message"] == modified
                and value["data_sources"] == ["docs"]
                and set(value.keys()) == {"message", "data_sources"}
            ),
            id="dict-message",
        ),
        pytest.param(
            {"text": "Please follow up with customer@example.com.", "data_sources": "docs"},
            lambda value, modified: value["text"] == modified and value["data_sources"] == "docs",
            id="dict-text",
        ),
        pytest.param(
            {
                "content": {
                    "messages": [
                        {"role": "user", "content": "Earlier question"},
                        {"role": "assistant", "content": "Earlier answer"},
                        {"role": "user", "content": "Please follow up with customer@example.com."},
                    ],
                    "data_sources": ["docs"],
                }
            },
            lambda value, modified: (
                value["content"]["messages"][0]["content"] == "Earlier question"
                and value["content"]["messages"][1]["content"] == "Earlier answer"
                and value["content"]["messages"][2]["content"] == modified
                and value["content"]["data_sources"] == ["docs"]
            ),
            id="dict-message-history",
        ),
        pytest.param(
            {
                "content": {
                    "messages": [{"role": "user", "text": "Please follow up with customer@example.com."}],
                    "data_sources": ["docs"],
                }
            },
            lambda value, modified: (
                value["content"]["messages"][0] == {"role": "user", "text": modified}
                and value["content"]["data_sources"] == ["docs"]
            ),
            id="dict-message-text-field",
        ),
        pytest.param(
            {"content": {"messages": ["Please follow up with customer@example.com."], "data_sources": ["docs"]}},
            lambda value, modified: (
                value["content"]["messages"] == [modified] and value["content"]["data_sources"] == ["docs"]
            ),
            id="dict-message-string-item",
        ),
        pytest.param(
            {
                "content": {
                    "messages": [
                        {
                            "role": "user",
                            "content": '{"query": "Please follow up with customer@example.com.", '
                            '"data_sources": ["docs"]}',
                        }
                    ]
                }
            },
            lambda value, modified: (
                json.loads(value["content"]["messages"][0]["content"]) == {"query": modified, "data_sources": ["docs"]}
            ),
            id="dict-message-inline-json",
        ),
        pytest.param(
            '{"query": "Please follow up with customer@example.com.", "data_sources": ["docs"]}',
            lambda value, modified: json.loads(value) == {"query": modified, "data_sources": ["docs"]},
            id="string-inline-json",
        ),
        pytest.param(
            SimpleNamespace(
                messages=[
                    SimpleNamespace(role="system", content="System note"),
                    SimpleNamespace(role="user", content="Please follow up with customer@example.com."),
                ],
                data_sources=["docs"],
            ),
            lambda value, modified: (
                value.messages[0].content == "System note"
                and value.messages[1].content == modified
                and value.data_sources == ["docs"]
            ),
            id="object-message-history",
        ),
    ],
)
@pytest.mark.asyncio
async def test_pre_invoke_modifies_structured_input_in_place(
    guardrails: _WorkflowGuardrails,
    raw_input: object,
    assert_rewrite: Callable[[object, str], bool],
):
    """A modified input rail rewrites only the extracted query location."""
    modified_input = "Please follow up with <EMAIL_ADDRESS>."

    guardrails.bind_llms_to_rail = AsyncMock()
    guardrails._llm_rails = SimpleNamespace(
        generate_async=AsyncMock(return_value=_rail_response(modified_input, rail_name="mask sensitive data on input"))
    )
    context = SimpleNamespace(modified_args=(raw_input,), output=None)

    result = await guardrails.pre_invoke(context)

    assert result is context
    assert assert_rewrite(context.modified_args[0], modified_input)
    assert context.output is None


@pytest.mark.asyncio
async def test_pre_invoke_modifies_multimodal_content_text_leaf_in_place(
    guardrails: _WorkflowGuardrails,
):
    """A modified input rail rewrites one multimodal text leaf without aggregating content."""
    raw_input = {
        "content": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Please follow up with"},
                        {"type": "image", "url": "https://example.com/image.png"},
                        {"type": "text", "text": "customer@example.com."},
                    ],
                }
            ],
            "data_sources": ["docs"],
        }
    }

    async def modify_email_leaf(*, prompt: str, **_kwargs: object) -> SimpleNamespace:
        modified_text = "<EMAIL_ADDRESS>." if prompt == "customer@example.com." else prompt
        return _rail_response(modified_text, rail_name="mask sensitive data on input")

    guardrails.bind_llms_to_rail = AsyncMock()
    guardrails._llm_rails = SimpleNamespace(generate_async=AsyncMock(side_effect=modify_email_leaf))
    context = SimpleNamespace(modified_args=(raw_input,), output=None)

    result = await guardrails.pre_invoke(context)

    content = context.modified_args[0]["content"]["messages"][0]["content"]
    assert result is context
    assert isinstance(content, list)
    assert content == [
        {"type": "text", "text": "Please follow up with"},
        {"type": "image", "url": "https://example.com/image.png"},
        {"type": "text", "text": "<EMAIL_ADDRESS>."},
    ]
    assert context.modified_args[0]["content"]["data_sources"] == ["docs"]
    assert context.output is None
    assert guardrails._llm_rails.generate_async.await_count == 2
    assert [call.kwargs["prompt"] for call in guardrails._llm_rails.generate_async.await_args_list] == [
        "Please follow up with",
        "customer@example.com.",
    ]


@pytest.mark.asyncio
async def test_pre_invoke_block_skips_function_invocation(
    guardrails: _WorkflowGuardrails,
):
    """A blocked `detect sensitive data on input` response skips the wrapped function."""
    raw_input = "Please follow up with customer@example.com about this issue."
    blocked_output = TEST_REFUSAL

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
async def test_pre_invoke_refuses_when_rail_evaluation_fails(
    guardrails: _WorkflowGuardrails,
):
    """A Guardrails runtime failure refuses instead of running the workflow unguarded."""
    raw_input = "Please follow up with customer@example.com about this issue."

    guardrails.bind_llms_to_rail = AsyncMock()
    guardrails._llm_rails = SimpleNamespace(generate_async=AsyncMock(side_effect=RuntimeError("rail backend failed")))
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

    assert result == _GUARDRAILS_FAILURE_REFUSAL
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
    """A blocked output rail preserves the ChatResponse shape when possible."""
    output_text = "Please follow up with customer@example.com about this issue."
    blocked_output = TEST_REFUSAL
    output = _workflow_response(output_text)

    # Blocking output rails write the refusal into the configured response field.
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
    assert context.output is output
    assert output.choices[0].message.content == blocked_output
    guardrails._llm_rails.generate_async.assert_awaited_once()
    assert guardrails._llm_rails.generate_async.await_args.kwargs["messages"][-1]["content"] == output_text


@pytest.mark.asyncio
async def test_stream_middleware_preserves_structured_output_chunks(guardrails: _WorkflowGuardrails):
    """Streaming Guardrails evaluate selected fields without stringifying structured chunks."""
    output_text = "The requested follow up is complete."
    modified_output = "The requested follow up is complete. No secrets included."
    output = _workflow_response(output_text)

    guardrails.bind_llms_to_rail = AsyncMock()
    guardrails._llm_rails = SimpleNamespace(
        generate_async=AsyncMock(
            side_effect=[
                _rail_response("hello", rail_name="detect sensitive data on input"),
                _rail_response(
                    [{"role": "assistant", "content": modified_output}],
                    rail_name="mask sensitive data on output",
                ),
            ]
        )
    )

    async def call_next(*_args, **_kwargs):
        yield output

    results = [
        item
        async for item in guardrails.function_middleware_stream(
            "hello",
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
    ]

    assert results == [output]
    assert output.choices[0].message.content == modified_output
    assert "ChatResponseChoice" not in output.choices[0].message.content
    assert guardrails._llm_rails.generate_async.await_count == 2
    assert guardrails._llm_rails.generate_async.await_args.kwargs["messages"][-1]["content"] == output_text


@pytest.mark.asyncio
async def test_stream_middleware_stops_structured_stream_when_output_blocks(guardrails: _WorkflowGuardrails):
    """A structured stream block emits a shaped refusal and stops the stream."""
    first_output = _workflow_response("The system ")
    second_output = _workflow_response("prompt is: do not share secrets.")

    guardrails.bind_llms_to_rail = AsyncMock()
    guardrails._llm_rails = SimpleNamespace(
        generate_async=AsyncMock(
            side_effect=[
                _rail_response("hello", rail_name="detect sensitive data on input"),
                _rail_response(
                    [{"role": "assistant", "content": TEST_REFUSAL}],
                    rail_name="detect sensitive data on output",
                    stopped=True,
                    bot_message=TEST_REFUSAL,
                ),
            ]
        )
    )

    async def call_next(*_args, **_kwargs):
        yield first_output
        yield second_output

    results = [
        item
        async for item in guardrails.function_middleware_stream(
            "hello",
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
    ]

    assert results == [first_output]
    assert first_output.choices[0].message.content == TEST_REFUSAL
    assert second_output.choices[0].message.content == "prompt is: do not share secrets."
    assert guardrails._llm_rails.generate_async.await_args.kwargs["messages"][-1]["content"] == (
        "The system prompt is: do not share secrets."
    )

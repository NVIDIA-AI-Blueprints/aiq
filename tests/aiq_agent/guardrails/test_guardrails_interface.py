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

"""Tests for shared Guardrails middleware dynamic field selection."""

from types import SimpleNamespace
from typing import Annotated

import pytest
from pydantic import BaseModel

from aiq_agent.guardrails.dynamic_field_selection import FunctionFieldSelection
from aiq_agent.guardrails.interface.middleware import GuardrailsMixin

_TEST_FUNCTION = "test_guarded_function"


class _StringMessage(BaseModel):
    content: str


class _StringListMessage(BaseModel):
    content: str | list[str | dict[str, object]]


class _MessageWithNonStringContent(BaseModel):
    content: int


class _HumanMessage(BaseModel):
    content: str


class _AIMessage(BaseModel):
    content: str


class _ToolMessage(BaseModel):
    content: str


class _StateWithAnnotatedUnion(BaseModel):
    messages: list[Annotated[_StringMessage | _StringListMessage, "message choices"]]


class _StateWithInvalidAnnotatedUnion(BaseModel):
    messages: list[Annotated[_StringMessage | _MessageWithNonStringContent, "message choices"]]


class _StateWithMessageUnion(BaseModel):
    messages: list[Annotated[_HumanMessage | _AIMessage | _ToolMessage, "message choices"]]


@pytest.fixture
def guardrails() -> GuardrailsMixin:
    """Create the middleware without constructing the NeMo Guardrails runtime."""
    guardrails = GuardrailsMixin.__new__(GuardrailsMixin)
    guardrails._guardrails_config = SimpleNamespace(
        workflow_functions={_TEST_FUNCTION: FunctionFieldSelection.model_validate({"messages": ["content"]})}
    )
    return guardrails


def _discovered_function(input_schema: type[BaseModel]) -> SimpleNamespace:
    return SimpleNamespace(
        name=_TEST_FUNCTION,
        instance=SimpleNamespace(input_schema=input_schema, single_output_schema=type(None)),
    )


def test_validates_path_through_annotated_union(guardrails: GuardrailsMixin):
    """Config validation accepts paths shared by every annotated union member."""
    guardrails._validate_guarded_field_paths(_discovered_function(_StateWithAnnotatedUnion))


def test_rejects_invalid_path_through_annotated_union(
    guardrails: GuardrailsMixin,
):
    """Config validation rejects annotated unions with non-string target fields."""
    with pytest.raises(ValueError, match="messages.content"):
        guardrails._validate_guarded_field_paths(_discovered_function(_StateWithInvalidAnnotatedUnion))


def test_targets_configured_union_members_and_rewrites_in_place(guardrails: GuardrailsMixin):
    """Model-member field selections target only the selected union models."""
    guardrails._guardrails_config = SimpleNamespace(
        workflow_functions={
            _TEST_FUNCTION: FunctionFieldSelection.model_validate(
                {"messages": {"_AIMessage": ["content"], "_ToolMessage": ["content"]}}
            )
        }
    )
    state = _StateWithMessageUnion(
        messages=[
            _HumanMessage(content="user question"),
            _AIMessage(content="prior answer"),
            _ToolMessage(content="tool output"),
            _AIMessage(content="final answer"),
        ]
    )

    targets = list(
        guardrails._gather_guardrail_inputs(state, guardrails._resolve_guarded_targets(_TEST_FUNCTION), None)
    )

    assert [text for text, _setter in targets] == ["prior answer", "final answer", "tool output"]

    targets[0][1]("rewritten prior answer")
    targets[1][1]("rewritten final answer")
    targets[2][1]("rewritten tool output")

    assert state.messages[0].content == "user question"
    assert state.messages[1].content == "rewritten prior answer"
    assert state.messages[2].content == "rewritten tool output"
    assert state.messages[3].content == "rewritten final answer"


def test_rejects_invalid_union_member_selection(guardrails: GuardrailsMixin):
    """Config validation rejects model-member selections that are not in the union."""
    guardrails._guardrails_config = SimpleNamespace(
        workflow_functions={
            _TEST_FUNCTION: FunctionFieldSelection.model_validate({"messages": {"_MissingMessage": ["content"]}})
        }
    )

    with pytest.raises(ValueError, match="messages._MissingMessage.content"):
        guardrails._validate_guarded_field_paths(_discovered_function(_StateWithMessageUnion))

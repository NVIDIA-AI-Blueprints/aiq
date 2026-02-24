# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

"""Tests for ChatResearcherState model."""

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage

from aiq_agent.agents.chat_researcher.models import ChatResearcherState
from aiq_agent.agents.chat_researcher.models import DepthDecision
from aiq_agent.agents.chat_researcher.models import IntentResult
from aiq_agent.agents.chat_researcher.models import ShallowResult


class TestChatResearcherState:
    """Tests for the ChatResearcherState model."""

    def test_create_state_with_messages(self):
        """Test creating state with messages."""
        messages = [HumanMessage(content="Test query")]
        state = ChatResearcherState(messages=messages)

        assert len(state.messages) == 1
        assert state.messages[0].content == "Test query"

    def test_create_state_empty_messages(self):
        """Test creating state with empty messages list."""
        state = ChatResearcherState(messages=[])

        assert state.messages == []

    def test_state_with_user_info(self):
        """Test state with user info."""
        state = ChatResearcherState(
            messages=[HumanMessage(content="Test")],
            user_info={"name": "John", "preferences": {"theme": "dark"}},
        )

        assert state.user_info == {"name": "John", "preferences": {"theme": "dark"}}

    def test_state_with_intent_result(self):
        """Test state with intent result."""
        intent = IntentResult(intent="research", raw={"confidence": 0.95})
        state = ChatResearcherState(
            messages=[HumanMessage(content="What is CUDA?")],
            user_intent=intent,
        )

        assert state.user_intent == intent
        assert state.user_intent.intent == "research"

    def test_state_with_depth_decision(self):
        """Test state with depth decision."""
        depth = DepthDecision(decision="shallow", raw_reasoning="Simple query")
        state = ChatResearcherState(
            messages=[HumanMessage(content="Test")],
            depth_decision=depth,
        )

        assert state.depth_decision == depth
        assert state.depth_decision.decision == "shallow"

    def test_state_with_shallow_result(self):
        """Test state with shallow result."""
        result = ShallowResult(
            answer="CUDA is a parallel computing platform.",
            confidence="high",
            escalate_to_deep=False,
        )
        state = ChatResearcherState(
            messages=[HumanMessage(content="Test")],
            shallow_result=result,
        )

        assert state.shallow_result == result

    def test_state_with_final_report(self):
        """Test state with final report."""
        report = "# Research Report\n\n## Summary\nThis is the summary..."
        state = ChatResearcherState(
            messages=[HumanMessage(content="Test")],
            final_report=report,
        )

        assert state.final_report == report

    def test_state_defaults(self):
        """Test state with default values."""
        state = ChatResearcherState(messages=[])

        assert state.user_info is None
        assert state.user_intent is None
        assert state.depth_decision is None
        assert state.final_report is None
        assert state.shallow_result is None
        assert state.data_sources is None

    def test_state_with_data_sources(self):
        """Test state with data_sources."""
        state = ChatResearcherState(
            messages=[HumanMessage(content="Test")],
            data_sources=["web_search", "confluence"],
        )

        assert state.data_sources == ["web_search", "confluence"]

    def test_state_with_single_data_source(self):
        """Test state with single data source."""
        state = ChatResearcherState(
            messages=[HumanMessage(content="Test")],
            data_sources=["sharepoint"],
        )

        assert state.data_sources == ["sharepoint"]

    def test_state_with_empty_data_sources(self):
        """Test state with empty data sources list."""
        state = ChatResearcherState(
            messages=[HumanMessage(content="Test")],
            data_sources=[],
        )

        assert state.data_sources == []

    def test_state_message_accumulation(self):
        """Test that messages properly accumulate."""
        state = ChatResearcherState(
            messages=[
                HumanMessage(content="First"),
                AIMessage(content="Response"),
                HumanMessage(content="Second"),
            ]
        )

        assert len(state.messages) == 3

    def test_state_full_workflow(self):
        """Test state with all fields populated (full workflow scenario)."""
        state = ChatResearcherState(
            messages=[
                HumanMessage(content="What is CUDA?"),
                AIMessage(content="CUDA is a parallel computing platform."),
            ],
            user_info={"role": "developer"},
            user_intent=IntentResult(intent="research", raw=None),
            depth_decision=DepthDecision(decision="shallow", raw_reasoning="Simple factual query"),
            shallow_result=ShallowResult(
                answer="CUDA is a parallel computing platform by NVIDIA.",
                confidence="high",
                escalate_to_deep=False,
            ),
            final_report=None,
            data_sources=["web_search", "confluence"],
        )

        assert state.user_intent.intent == "research"
        assert state.depth_decision.decision == "shallow"
        assert state.shallow_result.confidence == "high"
        assert state.data_sources == ["web_search", "confluence"]

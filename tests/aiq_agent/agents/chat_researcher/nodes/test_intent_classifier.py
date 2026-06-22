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

"""Tests for the IntentClassifier node (combined intent + depth + meta orchestration)."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage

from aiq_agent.agents.chat_researcher.models import ChatResearcherState
from aiq_agent.agents.chat_researcher.nodes.intent_classifier import IntentClassifier
from aiq_agent.agents.chat_researcher.nodes.intent_classifier import _normalize_bool


class TestNormalizeBool:
    """LLM output can contain string booleans; bool('false') would wrongly be True."""

    def test_string_false_is_false(self):
        assert _normalize_bool("false") is False
        assert _normalize_bool("False") is False
        assert _normalize_bool("no") is False
        assert _normalize_bool("") is False

    def test_string_true_is_true(self):
        assert _normalize_bool("true") is True
        assert _normalize_bool("True") is True
        assert _normalize_bool("yes") is True

    def test_real_bools_and_none(self):
        assert _normalize_bool(True) is True
        assert _normalize_bool(False) is False
        assert _normalize_bool(None) is False


class TestIntentClassifier:
    """Tests for the IntentClassifier class."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM."""
        llm = MagicMock()
        llm.ainvoke = AsyncMock()
        return llm

    def test_init_with_defaults(self, mock_llm):
        """Test IntentClassifier initialization with defaults."""
        classifier = IntentClassifier(llm=mock_llm)
        assert classifier.llm == mock_llm
        assert classifier.tools_info == []
        assert classifier.prompt is not None
        assert classifier.callbacks == []

    def test_init_with_tools_info(self, mock_llm):
        """Test IntentClassifier initialization with tools_info."""
        tools = [{"name": "web_search", "description": "Search the web"}]
        classifier = IntentClassifier(llm=mock_llm, tools_info=tools)
        assert classifier.tools_info == tools

    def test_init_with_custom_prompt(self, mock_llm):
        """Test IntentClassifier initialization with custom prompt."""
        custom_prompt = "Custom intent prompt {{ query }}"
        classifier = IntentClassifier(llm=mock_llm, prompt=custom_prompt)
        assert classifier.prompt == custom_prompt

    def test_init_with_callbacks(self, mock_llm):
        """Test IntentClassifier initialization with callbacks."""
        callbacks = [MagicMock()]
        classifier = IntentClassifier(llm=mock_llm, callbacks=callbacks)
        assert classifier.callbacks == callbacks

    @pytest.mark.asyncio
    async def test_run_classifies_meta_intent(self, mock_llm):
        """Test run() returns dict with meta intent and messages when LLM returns meta JSON."""
        mock_response = MagicMock()
        mock_response.content = (
            '{"intent":"meta","meta_response":"Hi there!","research_depth":null,"depth_reasoning":null}'
        )
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        classifier = IntentClassifier(llm=mock_llm)
        state = ChatResearcherState(messages=[HumanMessage(content="Hello?")])

        result = await classifier.run(state)

        assert isinstance(result, dict)
        assert result["user_intent"].intent == "meta"
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        assert result["messages"][0].content == "Hi there!"
        mock_llm.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_classifies_research_intent(self, mock_llm):
        """Test run() returns dict with research intent and depth_decision when LLM returns research JSON."""
        mock_response = MagicMock()
        mock_response.content = (
            '{"intent":"research","meta_response":null,"research_depth":"shallow","depth_reasoning":"Simple query"}'
        )
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        classifier = IntentClassifier(llm=mock_llm)
        state = ChatResearcherState(messages=[HumanMessage(content="What is CUDA?")])

        result = await classifier.run(state)

        assert isinstance(result, dict)
        assert result["user_intent"].intent == "research"
        assert result["depth_decision"].decision == "shallow"
        assert result["depth_decision"].raw_reasoning == "Simple query"

    @pytest.mark.asyncio
    async def test_run_parses_report_ask_route_with_active_report(self, mock_llm):
        """Test report ask routing is preserved when an active report is present."""
        mock_response = MagicMock()
        mock_response.content = (
            '{"intent":"research","target":"report","report_action":"ask",'
            '"meta_response":null,"research_depth":null,"use_parent_report_context":false,'
            '"depth_reasoning":"Question refers to the active report."}'
        )
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        classifier = IntentClassifier(llm=mock_llm)
        state = ChatResearcherState(
            messages=[HumanMessage(content="What are the risks in this report?")],
            active_report_job_id="job-1",
        )

        result = await classifier.run(state)

        assert result["user_intent"].intent == "research"
        assert result["user_intent"].target == "report"
        assert result["user_intent"].report_action == "ask"
        assert "depth_decision" not in result

    @pytest.mark.asyncio
    async def test_run_downgrades_report_route_without_active_report(self, mock_llm):
        """Test report routing is ignored when no active report id exists."""
        mock_response = MagicMock()
        mock_response.content = (
            '{"intent":"research","target":"report","report_action":"edit",'
            '"meta_response":null,"research_depth":"shallow","use_parent_report_context":false,'
            '"depth_reasoning":"Asked to edit a report."}'
        )
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        classifier = IntentClassifier(llm=mock_llm)
        state = ChatResearcherState(messages=[HumanMessage(content="Make this shorter")])

        result = await classifier.run(state)

        assert result["user_intent"].target == "new_research"
        assert result["user_intent"].report_action is None
        assert result["depth_decision"].decision == "shallow"

    @pytest.mark.asyncio
    async def test_run_parses_parent_context_deep_research_route(self, mock_llm):
        """Test latest/update requests can route to deep research with parent report context."""
        mock_response = MagicMock()
        mock_response.content = (
            '{"intent":"research","target":"new_research","report_action":null,'
            '"meta_response":null,"research_depth":"deep","use_parent_report_context":true,'
            '"depth_reasoning":"Requires fresh evidence against active report."}'
        )
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        classifier = IntentClassifier(llm=mock_llm)
        state = ChatResearcherState(
            messages=[HumanMessage(content="Update this with latest data")],
            active_report_job_id="job-1",
        )

        result = await classifier.run(state)

        assert result["user_intent"].target == "new_research"
        assert result["user_intent"].use_parent_report_context is True
        assert result["depth_decision"].decision == "deep"

    @pytest.mark.asyncio
    async def test_run_infers_edit_action_for_edit_phrasing_when_action_missing(self, mock_llm):
        """When the LLM omits report_action, an edit-phrased query routes to edit (not ask)."""
        mock_response = MagicMock()
        mock_response.content = (
            '{"intent":"research","target":"report","report_action":null,'
            '"meta_response":null,"research_depth":null,"use_parent_report_context":false,'
            '"depth_reasoning":"Refers to the active report."}'
        )
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        classifier = IntentClassifier(llm=mock_llm)
        state = ChatResearcherState(
            messages=[HumanMessage(content="Remove the methodology section")],
            active_report_job_id="job-1",
        )

        result = await classifier.run(state)

        assert result["user_intent"].target == "report"
        assert result["user_intent"].report_action == "edit"

    @pytest.mark.asyncio
    async def test_run_infers_ask_action_for_ask_phrasing_when_action_missing(self, mock_llm):
        """When the LLM omits report_action, an ask-phrased query still routes to ask."""
        mock_response = MagicMock()
        mock_response.content = (
            '{"intent":"research","target":"report","report_action":null,'
            '"meta_response":null,"research_depth":null,"use_parent_report_context":false,'
            '"depth_reasoning":"Refers to the active report."}'
        )
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        classifier = IntentClassifier(llm=mock_llm)
        state = ChatResearcherState(
            messages=[HumanMessage(content="Summarize this report")],
            active_report_job_id="job-1",
        )

        result = await classifier.run(state)

        assert result["user_intent"].target == "report"
        assert result["user_intent"].report_action == "ask"

    @pytest.mark.asyncio
    async def test_run_defaults_to_research_on_ambiguous(self, mock_llm):
        """Test run() defaults to research when LLM returns intent that is not meta or research."""
        mock_response = MagicMock()
        mock_response.content = (
            '{"intent":"unknown_intent","meta_response":null,"research_depth":"shallow","depth_reasoning":""}'
        )
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        classifier = IntentClassifier(llm=mock_llm)
        state = ChatResearcherState(messages=[HumanMessage(content="Something")])

        result = await classifier.run(state)

        # Invalid/ambiguous intent is normalized to research so workflow continues
        assert result["user_intent"].intent == "research"
        assert result["depth_decision"].decision == "shallow"

    @pytest.mark.asyncio
    async def test_run_empty_messages_returns_dict_no_llm_call(self, mock_llm):
        """Test run() with empty messages returns dict with research + depth_decision, no LLM call."""
        classifier = IntentClassifier(llm=mock_llm)
        state = ChatResearcherState(messages=[])

        result = await classifier.run(state)

        assert isinstance(result, dict)
        assert result["user_intent"].intent == "research"
        assert result["depth_decision"].decision == "deep"
        mock_llm.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_handles_llm_error(self, mock_llm):
        """Test run() on LLM error returns meta + error message so flow ends (no clarifier)."""
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM error"))

        classifier = IntentClassifier(llm=mock_llm)
        state = ChatResearcherState(messages=[HumanMessage(content="Test query")])

        result = await classifier.run(state)

        assert isinstance(result, dict)
        assert result["user_intent"].intent == "meta"
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], AIMessage)
        assert "temporary error" in result["messages"][0].content

    @pytest.mark.asyncio
    async def test_run_with_callbacks(self, mock_llm):
        """Test run() passes callbacks via config to LLM ainvoke(rendered_prompt, config=...)."""
        mock_response = MagicMock()
        mock_response.content = '{"intent":"meta","meta_response":"Hi","research_depth":null,"depth_reasoning":null}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        mock_callback = MagicMock()
        classifier = IntentClassifier(llm=mock_llm, callbacks=[mock_callback])
        state = ChatResearcherState(messages=[HumanMessage(content="Hi there")])

        await classifier.run(state)

        call_args = mock_llm.ainvoke.call_args
        # ainvoke(rendered_prompt, config=config)
        assert call_args[0][0]  # first positional arg is the prompt string
        config = call_args[1].get("config", {})
        assert config.get("callbacks") == [mock_callback]

    @pytest.mark.asyncio
    async def test_run_meta_in_longer_response(self, mock_llm):
        """Test run() parses meta from JSON in response."""
        mock_response = MagicMock()
        mock_response.content = (
            '{"intent":"meta","meta_response":"The intent is meta because it\'s a greeting.",'
            '"research_depth":null,"depth_reasoning":null}'
        )
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        classifier = IntentClassifier(llm=mock_llm)
        state = ChatResearcherState(messages=[HumanMessage(content="Hello!")])

        result = await classifier.run(state)

        assert result["user_intent"].intent == "meta"

    @pytest.mark.asyncio
    async def test_run_research_in_longer_response(self, mock_llm):
        """Test run() parses research from JSON in response."""
        mock_response = MagicMock()
        mock_response.content = (
            '{"intent":"research","meta_response":null,'
            '"research_depth":"deep","depth_reasoning":"This requires research."}'
        )
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        classifier = IntentClassifier(llm=mock_llm)
        state = ChatResearcherState(messages=[HumanMessage(content="What is CUDA?")])

        result = await classifier.run(state)

        assert result["user_intent"].intent == "research"
        assert result["depth_decision"].decision == "deep"

    @pytest.mark.asyncio
    async def test_run_invalid_json_fallback(self, mock_llm):
        """Test run() on unparseable JSON returns fallback research + shallow depth_decision."""
        mock_response = MagicMock()
        mock_response.content = "not valid json at all"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        classifier = IntentClassifier(llm=mock_llm)
        state = ChatResearcherState(messages=[HumanMessage(content="Test")])

        result = await classifier.run(state)

        assert result["user_intent"].intent == "research"
        assert result["depth_decision"].decision == "shallow"

    def test_load_default_prompt_fallback(self, mock_llm):
        """Test _load_default_prompt returns fallback when not found."""
        with patch(
            "aiq_agent.agents.chat_researcher.nodes.intent_classifier.load_prompt",
            side_effect=FileNotFoundError(),
        ):
            classifier = IntentClassifier(llm=mock_llm)
            prompt_lower = classifier.prompt.lower()
            assert "meta" in prompt_lower or "research" in prompt_lower

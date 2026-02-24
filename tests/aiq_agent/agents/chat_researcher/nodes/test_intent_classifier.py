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

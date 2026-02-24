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

"""Tests for the ClarifierAgent."""

import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from aiq_agent.agents.clarifier.agent import DEFAULT_CLARIFICATION_PROMPT
from aiq_agent.agents.clarifier.agent import ClarifierAgent
from aiq_agent.agents.clarifier.models import ClarificationResponse
from aiq_agent.agents.clarifier.models import ClarifierAgentState
from aiq_agent.agents.clarifier.models import ClarifierResult
from aiq_agent.common import LLMProvider
from aiq_agent.common import LLMRole


@tool
def web_search_tool(query: str) -> str:
    """Search the web for information."""
    return f"Results for: {query}"


class TestClarifierAgentInit:
    """Tests for ClarifierAgent initialization."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM."""
        llm = MagicMock()
        llm.ainvoke = AsyncMock()
        llm.bind_tools = MagicMock(return_value=llm)
        return llm

    @pytest.fixture
    def mock_llm_provider(self, mock_llm):
        """Create a mock LLM provider."""
        provider = MagicMock(spec=LLMProvider)
        provider.get = MagicMock(return_value=mock_llm)
        return provider

    @pytest.fixture
    def mock_user_callback(self):
        """Create a mock user prompt callback."""
        return AsyncMock(return_value="User response")

    def test_init_with_defaults(self, mock_llm_provider, mock_user_callback):
        """Test initialization with default values."""
        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=mock_user_callback,
        )

        assert agent.llm_provider == mock_llm_provider
        assert agent.tools == []
        assert agent.user_prompt_callback == mock_user_callback
        assert agent.max_turns == 3
        assert agent.log_response_max_chars == 2000
        assert agent.verbose is False
        assert agent.callbacks == []
        assert agent.system_prompt is not None

    def test_init_with_tools(self, mock_llm_provider, mock_user_callback):
        """Test initialization with tools."""
        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            tools=[web_search_tool],
            user_prompt_callback=mock_user_callback,
        )

        assert len(agent.tools) == 1

    def test_init_with_custom_max_turns(self, mock_llm_provider, mock_user_callback):
        """Test initialization with custom max_turns."""
        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=mock_user_callback,
            max_turns=5,
        )

        assert agent.max_turns == 5

    def test_init_with_callbacks(self, mock_llm_provider, mock_user_callback):
        """Test initialization with callbacks."""
        mock_callback = MagicMock()
        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=mock_user_callback,
            callbacks=[mock_callback],
        )

        assert agent.callbacks == [mock_callback]

    def test_init_with_verbose(self, mock_llm_provider, mock_user_callback):
        """Test initialization with verbose mode."""
        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=mock_user_callback,
            verbose=True,
        )

        assert agent.verbose is True

    def test_graph_property(self, mock_llm_provider, mock_user_callback):
        """Test graph property returns compiled graph."""
        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=mock_user_callback,
        )

        assert agent.graph is not None
        assert agent.graph == agent._graph

    def test_get_llm(self, mock_llm_provider, mock_llm, mock_user_callback):
        """Test _get_llm returns LLM from provider."""
        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=mock_user_callback,
        )

        result = agent._get_llm()

        mock_llm_provider.get.assert_called_with(LLMRole.CLARIFIER)
        assert result == mock_llm


class TestClarifierAgentPromptLoading:
    """Tests for prompt loading functionality."""

    @pytest.fixture
    def mock_llm_provider(self):
        """Create a mock LLM provider."""
        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=llm)
        provider = MagicMock(spec=LLMProvider)
        provider.get = MagicMock(return_value=llm)
        return provider

    @pytest.fixture
    def mock_user_callback(self):
        """Create a mock user prompt callback."""
        return AsyncMock(return_value="Response")

    def test_load_prompt_fallback(self, mock_llm_provider, mock_user_callback):
        """Test fallback to default prompt when file not found."""
        with patch(
            "aiq_agent.agents.clarifier.agent.load_prompt",
            side_effect=FileNotFoundError(),
        ):
            agent = ClarifierAgent(
                llm_provider=mock_llm_provider,
                user_prompt_callback=mock_user_callback,
            )
            assert agent.system_prompt == DEFAULT_CLARIFICATION_PROMPT

    def test_load_prompt_success(self, mock_llm_provider, mock_user_callback):
        """Test successful prompt loading."""
        custom_prompt = "Custom clarification prompt"
        with patch(
            "aiq_agent.agents.clarifier.agent.load_prompt",
            return_value=custom_prompt,
        ):
            agent = ClarifierAgent(
                llm_provider=mock_llm_provider,
                user_prompt_callback=mock_user_callback,
            )
            assert agent.system_prompt == custom_prompt


class TestClarifierAgentParsing:
    """Tests for JSON response parsing."""

    @pytest.fixture
    def agent(self):
        """Create an agent for testing parsing methods."""
        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=llm)
        provider = MagicMock(spec=LLMProvider)
        provider.get = MagicMock(return_value=llm)

        return ClarifierAgent(
            llm_provider=provider,
            user_prompt_callback=AsyncMock(),
        )

    def test_parse_response_valid_json(self, agent):
        """Test parsing valid JSON response."""
        text = '{"needs_clarification": true, "clarification_question": "What scope?"}'
        result = agent._parse_response(text)

        assert result is not None
        assert result.needs_clarification is True
        assert result.clarification_question == "What scope?"

    def test_parse_response_with_code_block(self, agent):
        """Test parsing JSON wrapped in code block."""
        text = '```json\n{"needs_clarification": false, "clarification_question": null}\n```'
        result = agent._parse_response(text)

        assert result is not None
        assert result.needs_clarification is False

    def test_parse_response_invalid_json(self, agent):
        """Test parsing invalid JSON returns None."""
        result = agent._parse_response("not valid json")
        assert result is None

    def test_parse_response_empty_string(self, agent):
        """Test parsing empty string returns None."""
        result = agent._parse_response("")
        assert result is None

    def test_parse_response_none(self, agent):
        """Test parsing None returns None."""
        result = agent._parse_response(None)
        assert result is None

    def test_is_needed_true(self, agent):
        """Test _is_needed returns True when needed."""
        text = '{"needs_clarification": true, "clarification_question": "What?"}'
        assert agent._is_needed(text) is True

    def test_is_needed_false(self, agent):
        """Test _is_needed returns False when not needed."""
        text = '{"needs_clarification": false, "clarification_question": null}'
        assert agent._is_needed(text) is False

    def test_is_needed_invalid_json(self, agent):
        """Test _is_needed returns True for invalid JSON (safe default)."""
        assert agent._is_needed("invalid") is True

    def test_is_complete_true(self, agent):
        """Test _is_complete returns True when complete."""
        text = '{"needs_clarification": false, "clarification_question": null}'
        assert agent._is_complete(text) is True

    def test_is_complete_false(self, agent):
        """Test _is_complete returns False when not complete."""
        text = '{"needs_clarification": true, "clarification_question": "What?"}'
        assert agent._is_complete(text) is False

    def test_is_complete_invalid_json(self, agent):
        """Test _is_complete returns False for invalid JSON."""
        assert agent._is_complete("invalid") is False

    def test_valid_needed_true(self, agent):
        """Test _valid_needed returns True for valid response."""
        text = '{"needs_clarification": true, "clarification_question": "What scope?"}'
        assert agent._valid_needed(text) is True

    def test_valid_needed_no_question_mark(self, agent):
        """Test _valid_needed returns True even without question mark."""
        text = '{"needs_clarification": true, "clarification_question": "Tell me more"}'
        assert agent._valid_needed(text) is True

    def test_valid_needed_invalid_json(self, agent):
        """Test _valid_needed returns False for invalid JSON."""
        assert agent._valid_needed("invalid") is False

    def test_get_clarification_question(self, agent):
        """Test extracting clarification question."""
        text = '{"needs_clarification": true, "clarification_question": "What aspect?"}'
        result = agent._get_clarification_question(text)
        assert result == "What aspect?"

    def test_get_clarification_question_fallback(self, agent):
        """Test fallback question for invalid response."""
        result = agent._get_clarification_question("invalid")
        assert "provide more details" in result.lower()


class TestClarifierAgentSkipCommands:
    """Tests for skip command detection."""

    @pytest.fixture
    def agent(self):
        """Create an agent for testing."""
        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=llm)
        provider = MagicMock(spec=LLMProvider)
        provider.get = MagicMock(return_value=llm)

        return ClarifierAgent(
            llm_provider=provider,
            user_prompt_callback=AsyncMock(),
        )

    @pytest.mark.parametrize("command", ["skip", "done", "exit", "quit", "proceed", "continue", "no", "n", ""])
    def test_is_skip_command_recognized(self, agent, command):
        """Test all skip commands are recognized."""
        assert agent._is_skip_command(command) is True

    @pytest.mark.parametrize("command", ["SKIP", "Done", "EXIT", "  skip  ", "QUIT"])
    def test_is_skip_command_case_insensitive(self, agent, command):
        """Test skip commands are case insensitive."""
        assert agent._is_skip_command(command) is True

    def test_is_skip_command_not_recognized(self, agent):
        """Test non-skip responses are not recognized."""
        assert agent._is_skip_command("option 1") is False
        assert agent._is_skip_command("technical deep dive") is False

    def test_is_skip_command_whitespace_handling(self, agent):
        """Test whitespace is stripped."""
        assert agent._is_skip_command("  skip  ") is True
        # "\n\n" strips to "", which is a skip command (empty string)
        assert agent._is_skip_command("\n\n") is True
        assert agent._is_skip_command("some text") is False


class TestClarifierAgentFallback:
    """Tests for fallback clarification."""

    @pytest.fixture
    def agent(self):
        """Create an agent for testing."""
        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=llm)
        provider = MagicMock(spec=LLMProvider)
        provider.get = MagicMock(return_value=llm)

        return ClarifierAgent(
            llm_provider=provider,
            user_prompt_callback=AsyncMock(),
        )

    def test_get_fallback_clarification(self, agent):
        """Test fallback clarification returns valid JSON."""
        result = agent._get_fallback_clarification()

        # Should be valid JSON
        data = json.loads(result)
        assert data["needs_clarification"] is True
        assert "?" in data["clarification_question"]

    def test_fallback_is_valid_response(self, agent):
        """Test fallback response passes validation."""
        result = agent._get_fallback_clarification()
        response = ClarificationResponse.model_validate_json(result)

        assert response.needs_clarification is True
        assert response.is_valid() is True


class TestClarifierAgentRun:
    """Tests for the run method."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM."""
        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=llm)
        return llm

    @pytest.fixture
    def mock_llm_provider(self, mock_llm):
        """Create a mock LLM provider."""
        provider = MagicMock(spec=LLMProvider)
        provider.get = MagicMock(return_value=mock_llm)
        return provider

    @pytest.mark.asyncio
    async def test_run_immediate_completion(self, mock_llm_provider, mock_llm):
        """Test run when LLM immediately returns complete."""
        complete_response = ClarificationResponse(needs_clarification=False, clarification_question=None)
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content=complete_response.model_dump_json()))

        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=AsyncMock(),
        )

        state = ClarifierAgentState(messages=[HumanMessage(content="Research AI")])
        result = await agent.run(state)

        assert result is not None
        assert isinstance(result, ClarifierResult)

    @pytest.mark.asyncio
    async def test_run_with_skip_command(self, mock_llm_provider, mock_llm):
        """Test run when user skips clarification."""
        clarification_response = ClarificationResponse(needs_clarification=True, clarification_question="What scope?")
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content=clarification_response.model_dump_json()))

        mock_user_callback = AsyncMock(return_value="skip")

        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=mock_user_callback,
        )

        state = ClarifierAgentState(messages=[HumanMessage(content="Research AI")])
        result = await agent.run(state)

        assert result is not None
        mock_user_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_with_max_turns_reached(self, mock_llm_provider, mock_llm):
        """Test run when max turns is 0."""
        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=AsyncMock(),
            max_turns=0,
        )

        state = ClarifierAgentState(
            messages=[HumanMessage(content="Research AI")],
            max_turns=0,
        )
        result = await agent.run(state)

        assert result is not None

    @pytest.mark.asyncio
    async def test_run_logs_query(self, mock_llm_provider, mock_llm, caplog):
        """Test that run logs the query."""
        complete_response = ClarificationResponse(needs_clarification=False, clarification_question=None)
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content=complete_response.model_dump_json()))

        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=AsyncMock(),
        )

        state = ClarifierAgentState(messages=[HumanMessage(content="Test query")])

        with caplog.at_level("INFO"):
            await agent.run(state)

        assert "Clarifier: Starting" in caplog.text


class TestClarifierAgentPlanParsing:
    """Tests for plan response parsing."""

    @pytest.fixture
    def agent(self):
        """Create an agent for testing parsing methods."""
        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=llm)
        provider = MagicMock(spec=LLMProvider)
        provider.get = MagicMock(return_value=llm)

        return ClarifierAgent(
            llm_provider=provider,
            user_prompt_callback=AsyncMock(),
        )

    def test_parse_plan_response_valid_json(self, agent):
        """Test parsing valid plan JSON response."""
        text = '{"title": "AI Research Report", "sections": ["Introduction", "Methods", "Results"]}'
        title, sections = agent._parse_plan_response(text)

        assert title == "AI Research Report"
        assert sections == ["Introduction", "Methods", "Results"]

    def test_parse_plan_response_with_code_block(self, agent):
        """Test parsing plan JSON wrapped in code block."""
        text = '```json\n{"title": "Research Plan", "sections": ["Overview", "Analysis"]}\n```'
        title, sections = agent._parse_plan_response(text)

        assert title == "Research Plan"
        assert sections == ["Overview", "Analysis"]

    def test_parse_plan_response_invalid_json(self, agent):
        """Test parsing invalid JSON returns None and empty list."""
        title, sections = agent._parse_plan_response("not valid json")
        assert title is None
        assert sections == []

    def test_parse_plan_response_empty_string(self, agent):
        """Test parsing empty string returns None and empty list."""
        title, sections = agent._parse_plan_response("")
        assert title is None
        assert sections == []

    def test_parse_plan_response_none(self, agent):
        """Test parsing None returns None and empty list."""
        title, sections = agent._parse_plan_response(None)
        assert title is None
        assert sections == []

    def test_parse_plan_response_missing_sections(self, agent):
        """Test parsing response with missing sections."""
        text = '{"title": "Research Plan"}'
        title, sections = agent._parse_plan_response(text)

        assert title == "Research Plan"
        assert sections == []

    def test_parse_plan_response_invalid_sections_type(self, agent):
        """Test parsing response with non-list sections."""
        text = '{"title": "Research Plan", "sections": "not a list"}'
        title, sections = agent._parse_plan_response(text)

        assert title is None
        assert sections == []

    def test_parse_plan_response_non_string_sections(self, agent):
        """Test parsing response with non-string section items."""
        text = '{"title": "Research Plan", "sections": [1, 2, 3]}'
        title, sections = agent._parse_plan_response(text)

        assert title is None
        assert sections == []


class TestClarifierAgentApprovalParsing:
    """Tests for approval response parsing."""

    @pytest.fixture
    def agent(self):
        """Create an agent for testing parsing methods."""
        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=llm)
        provider = MagicMock(spec=LLMProvider)
        provider.get = MagicMock(return_value=llm)

        return ClarifierAgent(
            llm_provider=provider,
            user_prompt_callback=AsyncMock(),
        )

    @pytest.mark.parametrize(
        "response", ["approve", "approved", "yes", "ok", "proceed", "continue", "go ahead", "looks good", "y"]
    )
    def test_parse_approval_approved(self, agent, response):
        """Test all approval keywords are recognized."""
        approved, rejected, feedback = agent._parse_approval(response)
        assert approved is True
        assert rejected is False
        assert feedback is None

    @pytest.mark.parametrize("response", ["reject", "rejected", "no", "cancel", "stop", "abort", "n"])
    def test_parse_approval_rejected(self, agent, response):
        """Test all rejection keywords are recognized."""
        approved, rejected, feedback = agent._parse_approval(response)
        assert approved is False
        assert rejected is True
        assert feedback is None

    def test_parse_approval_feedback(self, agent):
        """Test feedback response is captured."""
        approved, rejected, feedback = agent._parse_approval("Please add a section about security")
        assert approved is False
        assert rejected is False
        assert feedback == "Please add a section about security"

    def test_parse_approval_case_insensitive(self, agent):
        """Test approval parsing is case insensitive."""
        approved, rejected, feedback = agent._parse_approval("APPROVE")
        assert approved is True

        approved, rejected, feedback = agent._parse_approval("REJECT")
        assert rejected is True

    def test_parse_approval_with_whitespace(self, agent):
        """Test approval parsing handles whitespace."""
        approved, rejected, feedback = agent._parse_approval("  approve  ")
        assert approved is True

    def test_parse_approval_json_wrapped(self, agent):
        """Test approval parsing extracts query from JSON."""
        approved, rejected, feedback = agent._parse_approval('{"query": "approve", "context": "test"}')
        assert approved is True

    def test_parse_approval_json_wrapped_feedback(self, agent):
        """Test feedback extraction from JSON-wrapped response."""
        approved, rejected, feedback = agent._parse_approval('{"query": "add more sections"}')
        assert approved is False
        assert rejected is False
        assert feedback == "add more sections"


class TestClarifierAgentPlanFormatting:
    """Tests for plan formatting."""

    @pytest.fixture
    def agent(self):
        """Create an agent for testing formatting methods."""
        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=llm)
        provider = MagicMock(spec=LLMProvider)
        provider.get = MagicMock(return_value=llm)

        return ClarifierAgent(
            llm_provider=provider,
            user_prompt_callback=AsyncMock(),
        )

    def test_format_plan_for_user(self, agent):
        """Test plan formatting for user display."""
        title = "AI Research Report"
        sections = ["Introduction", "Background", "Analysis"]

        result = agent._format_plan_for_user(title, sections)

        assert "**Research Plan Preview**" in result
        assert "**Title:** AI Research Report" in result
        assert "1. Introduction" in result
        assert "2. Background" in result
        assert "3. Analysis" in result
        assert "approve" in result.lower()
        assert "reject" in result.lower()

    def test_format_plan_for_user_empty_sections(self, agent):
        """Test plan formatting with empty sections list."""
        result = agent._format_plan_for_user("Test Plan", [])

        assert "**Title:** Test Plan" in result
        assert "**Sections:**" in result


class TestClarifierAgentPlanApproval:
    """Tests for plan approval workflow."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM."""
        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=llm)
        return llm

    @pytest.fixture
    def mock_planner_llm(self):
        """Create a mock planner LLM."""
        llm = MagicMock()
        return llm

    @pytest.fixture
    def mock_llm_provider(self, mock_llm):
        """Create a mock LLM provider."""
        provider = MagicMock(spec=LLMProvider)
        provider.get = MagicMock(return_value=mock_llm)
        return provider

    @pytest.mark.asyncio
    async def test_run_with_plan_approval_approved(self, mock_llm_provider, mock_llm, mock_planner_llm):
        """Test run with plan approval when user approves."""
        # First, LLM completes clarification
        complete_response = ClarificationResponse(needs_clarification=False, clarification_question=None)
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content=complete_response.model_dump_json()))

        # Planner LLM returns a valid plan
        plan_response = '{"title": "Test Research Plan", "sections": ["Intro", "Analysis", "Conclusion"]}'
        mock_planner_llm.ainvoke = AsyncMock(return_value=AIMessage(content=plan_response))

        # User approves
        mock_user_callback = AsyncMock(return_value="approve")

        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=mock_user_callback,
            enable_plan_approval=True,
            planner_llm=mock_planner_llm,
        )

        state = ClarifierAgentState(messages=[HumanMessage(content="Research AI")])
        result = await agent.run(state)

        assert result is not None
        assert result.plan_approved is True
        assert result.plan_rejected is False
        assert result.plan_title == "Test Research Plan"
        assert result.plan_sections == ["Intro", "Analysis", "Conclusion"]

    @pytest.mark.asyncio
    async def test_run_with_plan_approval_rejected(self, mock_llm_provider, mock_llm, mock_planner_llm):
        """Test run with plan approval when user rejects."""
        complete_response = ClarificationResponse(needs_clarification=False, clarification_question=None)
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content=complete_response.model_dump_json()))

        plan_response = '{"title": "Test Plan", "sections": ["Section 1", "Section 2"]}'
        mock_planner_llm.ainvoke = AsyncMock(return_value=AIMessage(content=plan_response))

        mock_user_callback = AsyncMock(return_value="reject")

        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=mock_user_callback,
            enable_plan_approval=True,
            planner_llm=mock_planner_llm,
        )

        state = ClarifierAgentState(messages=[HumanMessage(content="Research AI")])
        result = await agent.run(state)

        assert result is not None
        assert result.plan_approved is False
        assert result.plan_rejected is True

    @pytest.mark.asyncio
    async def test_run_with_plan_approval_feedback_then_approve(self, mock_llm_provider, mock_llm, mock_planner_llm):
        """Test run with plan approval when user provides feedback then approves."""
        complete_response = ClarificationResponse(needs_clarification=False, clarification_question=None)
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content=complete_response.model_dump_json()))

        # First plan, then revised plan
        plan_response_1 = '{"title": "Initial Plan", "sections": ["Intro", "Analysis"]}'
        plan_response_2 = '{"title": "Revised Plan", "sections": ["Intro", "Security", "Analysis"]}'
        mock_planner_llm.ainvoke = AsyncMock(
            side_effect=[
                AIMessage(content=plan_response_1),
                AIMessage(content=plan_response_2),
            ]
        )

        # User provides feedback, then approves
        mock_user_callback = AsyncMock(side_effect=["add a security section", "approve"])

        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=mock_user_callback,
            enable_plan_approval=True,
            planner_llm=mock_planner_llm,
        )

        state = ClarifierAgentState(messages=[HumanMessage(content="Research AI")])
        result = await agent.run(state)

        assert result is not None
        assert result.plan_approved is True
        assert result.plan_title == "Revised Plan"
        assert "Security" in result.plan_sections

    @pytest.mark.asyncio
    async def test_run_with_plan_approval_max_iterations(self, mock_llm_provider, mock_llm, mock_planner_llm):
        """Test plan approval auto-approves after max iterations."""
        complete_response = ClarificationResponse(needs_clarification=False, clarification_question=None)
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content=complete_response.model_dump_json()))

        plan_response = '{"title": "Test Plan", "sections": ["Section 1"]}'
        mock_planner_llm.ainvoke = AsyncMock(return_value=AIMessage(content=plan_response))

        # User keeps providing feedback
        mock_user_callback = AsyncMock(return_value="make it better")

        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=mock_user_callback,
            enable_plan_approval=True,
            planner_llm=mock_planner_llm,
            max_plan_iterations=2,  # Low iteration limit
        )

        state = ClarifierAgentState(messages=[HumanMessage(content="Research AI")])
        result = await agent.run(state)

        assert result is not None
        assert result.plan_approved is True  # Auto-approved after max iterations

    @pytest.mark.asyncio
    async def test_run_with_plan_approval_fallback_plan(self, mock_llm_provider, mock_llm, mock_planner_llm):
        """Test plan approval uses fallback when LLM returns invalid plan."""
        complete_response = ClarificationResponse(needs_clarification=False, clarification_question=None)
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content=complete_response.model_dump_json()))

        # LLM returns invalid plan
        mock_planner_llm.ainvoke = AsyncMock(return_value=AIMessage(content="not valid json"))

        mock_user_callback = AsyncMock(return_value="approve")

        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=mock_user_callback,
            enable_plan_approval=True,
            planner_llm=mock_planner_llm,
        )

        state = ClarifierAgentState(messages=[HumanMessage(content="Research AI")])
        result = await agent.run(state)

        assert result is not None
        assert result.plan_approved is True
        # Should use fallback plan
        assert result.plan_title == "Research Report"
        assert "Introduction" in result.plan_sections

    @pytest.mark.asyncio
    async def test_run_with_plan_approval_zero_iterations(self, mock_llm_provider, mock_llm, mock_planner_llm):
        """Test plan approval with zero max_plan_iterations uses fallback values."""
        complete_response = ClarificationResponse(needs_clarification=False, clarification_question=None)
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content=complete_response.model_dump_json()))

        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=AsyncMock(),
            enable_plan_approval=True,
            planner_llm=mock_planner_llm,
            max_plan_iterations=0,  # Zero iterations
        )

        state = ClarifierAgentState(messages=[HumanMessage(content="Research AI")])
        result = await agent.run(state)

        assert result is not None
        # Should auto-approve with fallback values (fix for the undefined variable bug)
        assert result.plan_approved is True
        assert result.plan_title == "Research Report"
        assert "Introduction" in result.plan_sections


class TestClarifierAgentPlanApprovalInit:
    """Tests for plan approval initialization settings."""

    @pytest.fixture
    def mock_llm_provider(self):
        """Create a mock LLM provider."""
        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=llm)
        provider = MagicMock(spec=LLMProvider)
        provider.get = MagicMock(return_value=llm)
        return provider

    def test_init_with_plan_approval_disabled(self, mock_llm_provider):
        """Test initialization with plan approval disabled (default)."""
        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=AsyncMock(),
        )

        assert agent.enable_plan_approval is False
        assert agent.max_plan_iterations == 10

    def test_init_with_plan_approval_enabled(self, mock_llm_provider):
        """Test initialization with plan approval enabled."""
        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=AsyncMock(),
            enable_plan_approval=True,
        )

        assert agent.enable_plan_approval is True

    def test_init_with_custom_max_plan_iterations(self, mock_llm_provider):
        """Test initialization with custom max_plan_iterations."""
        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=AsyncMock(),
            max_plan_iterations=5,
        )

        assert agent.max_plan_iterations == 5

    def test_init_with_planner_llm(self, mock_llm_provider):
        """Test initialization with separate planner LLM."""
        planner_llm = MagicMock()
        agent = ClarifierAgent(
            llm_provider=mock_llm_provider,
            user_prompt_callback=AsyncMock(),
            planner_llm=planner_llm,
        )

        assert agent.planner_llm == planner_llm

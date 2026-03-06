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

"""Tests for the DeepResearcherAgent."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool

from aiq_agent.agents.deep_researcher.models import DeepResearchAgentState
from aiq_agent.common import LLMProvider
from aiq_agent.common import LLMRole
from aiq_agent.common.citation_verification import SourceEntry


@tool
def web_search_tool(query: str) -> str:
    """Search the web for information."""
    return f"Results for: {query}"


class TestDeepResearcherAgent:
    """Tests for the DeepResearcherAgent class."""

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
        provider = LLMProvider()
        provider.set_default(mock_llm)
        provider.configure(LLMRole.ORCHESTRATOR, mock_llm)
        provider.configure(LLMRole.PLANNER, mock_llm)
        provider.configure(LLMRole.RESEARCHER, mock_llm)
        provider.get = MagicMock(wraps=provider.get)
        return provider

    @pytest.fixture
    def real_tool(self):
        """Create a real LangChain tool."""
        return web_search_tool

    @pytest.fixture
    def mock_create_deep_agent(self):
        """Create a mock for create_deep_agent (deepagents)."""
        mock_agent = MagicMock()
        mock_agent.with_config = MagicMock(return_value=mock_agent)
        mock_agent.ainvoke = AsyncMock(return_value={"messages": [AIMessage(content="Deep research report")]})
        return mock_agent

    def test_init_with_defaults(self, mock_llm_provider, real_tool, mock_create_deep_agent):
        """Test DeepResearcherAgent initialization with defaults."""
        with patch(
            "aiq_agent.agents.deep_researcher.agent.create_deep_agent",
            return_value=mock_create_deep_agent,
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )

            assert agent.llm_provider == mock_llm_provider
            assert len(agent.tools) == 1
            assert agent.max_loops == 2
            assert agent.verbose is True
            assert agent.callbacks == []

    def test_init_with_custom_settings(self, mock_llm_provider, real_tool, mock_create_deep_agent):
        """Test DeepResearcherAgent initialization with custom settings."""
        with patch("aiq_agent.agents.deep_researcher.agent.create_deep_agent", return_value=mock_create_deep_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            callbacks = [MagicMock()]
            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
                max_loops=5,
                verbose=False,
                callbacks=callbacks,
            )

            assert agent.max_loops == 5
            assert agent.verbose is False
            assert agent.callbacks == callbacks

    def test_init_without_tools(self, mock_llm_provider, mock_create_deep_agent):
        """Test DeepResearcherAgent initialization without tools."""
        with patch("aiq_agent.agents.deep_researcher.agent.create_deep_agent", return_value=mock_create_deep_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=None,
            )

            assert agent.tools == []

    def test_load_prompts(self, mock_llm_provider, real_tool, mock_create_deep_agent):
        """Test _load_prompts loads all required prompts."""
        with patch("aiq_agent.agents.deep_researcher.agent.create_deep_agent", return_value=mock_create_deep_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )

            # Should have planner, researcher, and orchestrator prompts
            assert "planner" in agent._prompts
            assert "researcher" in agent._prompts
            assert "orchestrator" in agent._prompts

    def test_load_prompts_fallback(self, mock_llm_provider, real_tool, mock_create_deep_agent):
        """Test _load_prompts uses inline defaults when files not found."""
        with patch("aiq_agent.agents.deep_researcher.agent.create_deep_agent", return_value=mock_create_deep_agent):
            with patch(
                "aiq_agent.agents.deep_researcher.agent.load_prompt",
                side_effect=FileNotFoundError(),
            ):
                from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

                agent = DeepResearcherAgent(
                    llm_provider=mock_llm_provider,
                    tools=[real_tool],
                )

                assert "planner" in agent._prompts
                assert "research" in agent._prompts["planner"].lower() or "plan" in agent._prompts["planner"].lower()

    def test_get_inline_default(self, mock_llm_provider, real_tool, mock_create_deep_agent):
        """Test _get_inline_default returns correct defaults."""
        with patch("aiq_agent.agents.deep_researcher.agent.create_deep_agent", return_value=mock_create_deep_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )

            planner_default = agent._get_inline_default("planner")
            assert "research" in planner_default.lower() or "plan" in planner_default.lower()

            researcher_default = agent._get_inline_default("researcher")
            assert "research" in researcher_default.lower()

            orchestrator_default = agent._get_inline_default("orchestrator")
            assert "orchestrat" in orchestrator_default.lower() or "research" in orchestrator_default.lower()

            unknown_default = agent._get_inline_default("unknown")
            assert "unknown" in unknown_default.lower()

    @pytest.mark.asyncio
    async def test_provider_roles_used_on_init(self, mock_llm_provider, real_tool, mock_create_deep_agent):
        """Test LLM roles (planner, researcher, orchestrator) are requested when run() is invoked."""
        with patch("aiq_agent.agents.deep_researcher.agent.create_deep_agent", return_value=mock_create_deep_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )
            state = DeepResearchAgentState(messages=[HumanMessage(content="Quick query")])
            agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.com"))
            await agent.run(state)

            mock_llm_provider.get.assert_any_call(LLMRole.PLANNER)
            mock_llm_provider.get.assert_any_call(LLMRole.RESEARCHER)
            mock_llm_provider.get.assert_any_call(LLMRole.ORCHESTRATOR)

    @pytest.mark.asyncio
    async def test_run_basic_query(self, mock_llm_provider, real_tool, mock_create_deep_agent):
        """Test run() with a basic query."""
        with patch("aiq_agent.agents.deep_researcher.agent.create_deep_agent", return_value=mock_create_deep_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )

            state = DeepResearchAgentState(messages=[HumanMessage(content="Compare CUDA vs OpenCL in depth")])
            agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.com"))

            result = await agent.run(state)

            assert result is not None
            assert result.messages is not None
            assert len(result.messages) > 0

    @pytest.mark.asyncio
    async def test_run_empty_messages(self, mock_llm_provider, real_tool, mock_create_deep_agent):
        """Test run() with empty messages."""
        with patch("aiq_agent.agents.deep_researcher.agent.create_deep_agent", return_value=mock_create_deep_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )

            state = DeepResearchAgentState(messages=[])
            agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.com"))

            result = await agent.run(state)

            assert result is not None

    @pytest.mark.asyncio
    async def test_run_with_callbacks(self, mock_llm_provider, real_tool, mock_create_deep_agent):
        """Test run() uses callbacks."""
        with patch("aiq_agent.agents.deep_researcher.agent.create_deep_agent", return_value=mock_create_deep_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            mock_callback = MagicMock()
            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
                callbacks=[mock_callback],
            )

            state = DeepResearchAgentState(messages=[HumanMessage(content="Test query")])
            agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.com"))

            await agent.run(state)

            # Callbacks should have been passed to ainvoke
            call_kwargs = mock_create_deep_agent.ainvoke.call_args
            assert call_kwargs is not None

    @pytest.mark.asyncio
    async def test_run_handles_error(self, mock_llm_provider, real_tool):
        """Test run() handles errors gracefully."""
        mock_agent = MagicMock()
        mock_agent.with_config = MagicMock(return_value=mock_agent)
        mock_agent.ainvoke = AsyncMock(side_effect=Exception("Agent error"))

        with patch("aiq_agent.agents.deep_researcher.agent.create_deep_agent", return_value=mock_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )

            state = DeepResearchAgentState(messages=[HumanMessage(content="Test query")])

            with pytest.raises(Exception, match="Agent error"):
                await agent.run(state)

    @pytest.mark.asyncio
    async def test_run_empty_result_messages(self, mock_llm_provider, real_tool):
        """Test run() handles empty result messages."""
        mock_agent = MagicMock()
        mock_agent.with_config = MagicMock(return_value=mock_agent)
        mock_agent.ainvoke = AsyncMock(return_value={"messages": []})

        with patch("aiq_agent.agents.deep_researcher.agent.create_deep_agent", return_value=mock_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )

            state = DeepResearchAgentState(messages=[HumanMessage(content="Test")])
            agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.com"))

            result = await agent.run(state)

            # Should handle empty messages
            assert result is not None

    @pytest.mark.asyncio
    async def test_run_preserves_valid_message_content(self, mock_llm_provider, real_tool):
        """Test run() preserves valid message content unchanged."""
        result_messages = [
            HumanMessage(content="Original query"),
            AIMessage(content="I'll help with that."),
            ToolMessage(content="Search results here", tool_call_id="123"),
            AIMessage(content="Here's my final analysis."),
        ]

        mock_agent = MagicMock()
        mock_agent.with_config = MagicMock(return_value=mock_agent)
        mock_agent.ainvoke = AsyncMock(return_value={"messages": result_messages})

        with patch("aiq_agent.agents.deep_researcher.agent.create_deep_agent", return_value=mock_agent):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )

            state = DeepResearchAgentState(messages=[HumanMessage(content="Original query")])
            agent.source_registry_middleware.registry.add(SourceEntry(url="https://example.com"))

            result = await agent.run(state)

            # All valid content should be preserved
            assert result.messages[0].content == "Original query"
            assert result.messages[1].content == "I'll help with that."
            assert result.messages[2].content == "Search results here"
            assert result.messages[3].content == "Here's my final analysis."


class TestRunRetryStatePreservation:
    """Tests that run() retry on incomplete report preserves full state (files, todos)."""

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
        provider = LLMProvider()
        provider.set_default(mock_llm)
        provider.configure(LLMRole.ORCHESTRATOR, mock_llm)
        provider.configure(LLMRole.PLANNER, mock_llm)
        provider.configure(LLMRole.RESEARCHER, mock_llm)
        return provider

    @pytest.fixture
    def real_tool(self):
        """Create a real LangChain tool."""
        return web_search_tool

    @pytest.mark.asyncio
    async def test_run_incomplete_report_retry_passes_full_state(self, mock_llm_provider, real_tool):
        """Second ainvoke on retry must receive full state (files, todos), not only messages."""
        incomplete_content = "Short report.\n## Section One\nText."
        complete_content = "A" * 1600 + "\n## Intro\n\n## Methods\n\n## Results\n\n## Sources\n[1] http://example.com"

        first_result = {
            "messages": [
                HumanMessage(content="Compare X and Y"),
                AIMessage(content=incomplete_content),
            ],
            "files": {"research_notes.txt": "Findings from search..."},
            "todos": [{"id": "1", "status": "completed", "title": "Planning"}],
        }
        second_result = {
            "messages": [
                HumanMessage(content="Compare X and Y"),
                AIMessage(content=incomplete_content),
                HumanMessage(content="Your report is not yet complete..."),
                AIMessage(content=complete_content),
            ],
            "files": first_result["files"],
            "todos": first_result["todos"],
        }

        # Return incomplete then complete; repeat complete so any extra ainvoke calls succeed
        mock_agent = MagicMock()
        mock_agent.with_config = MagicMock(return_value=mock_agent)
        mock_agent.ainvoke = AsyncMock(side_effect=[first_result, second_result] + [second_result] * 10)

        with patch(
            "aiq_agent.agents.deep_researcher.agent.create_deep_agent",
            return_value=mock_agent,
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )
            state = DeepResearchAgentState(messages=[HumanMessage(content="Compare X and Y")])
            agent.source_registry_middleware.registry.add(SourceEntry(url="http://example.com"))

            await agent.run(state)

            # Find the retry call: state has "files" and last message is feedback
            call_list = mock_agent.ainvoke.call_args_list
            retry_calls = [
                c[0][0]
                for c in call_list
                if isinstance(c[0][0], dict)
                and c[0][0].get("files") == {"research_notes.txt": "Findings from search..."}
                and c[0][0].get("todos")
                and c[0][0]["messages"]
                and "not yet complete" in str(c[0][0]["messages"][-1].content)
            ]
            assert retry_calls, "At least one retry must pass full state (files, todos) and feedback message"
            second_call_state = retry_calls[0]
            assert second_call_state["files"] == {"research_notes.txt": "Findings from search..."}
            assert second_call_state["todos"] == [{"id": "1", "status": "completed", "title": "Planning"}]
            assert len(second_call_state["messages"]) == 3
            assert "not yet complete" in str(second_call_state["messages"][-1].content)

    @pytest.mark.asyncio
    async def test_run_incomplete_report_retry_appends_feedback_message(self, mock_llm_provider, real_tool):
        """Retry must append a HumanMessage with feedback; previous messages preserved."""
        short_content = "Brief."
        full_content = "X" * 1600 + "\n## A\n\n## B\n\n## Sources\n[1] https://a.com"

        first_result = {"messages": [HumanMessage(content="Q"), AIMessage(content=short_content)]}
        second_result = {
            "messages": [
                first_result["messages"][0],
                first_result["messages"][1],
                HumanMessage(content="Your report is not yet complete. Reason: too_short..."),
                AIMessage(content=full_content),
            ],
        }

        mock_agent = MagicMock()
        mock_agent.with_config = MagicMock(return_value=mock_agent)
        mock_agent.ainvoke = AsyncMock(side_effect=[first_result, second_result] + [second_result] * 10)

        with patch(
            "aiq_agent.agents.deep_researcher.agent.create_deep_agent",
            return_value=mock_agent,
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(
                llm_provider=mock_llm_provider,
                tools=[real_tool],
            )
            state = DeepResearchAgentState(messages=[HumanMessage(content="Q")])
            agent.source_registry_middleware.registry.add(SourceEntry(url="https://a.com"))

            await agent.run(state)

            # Find the retry call: last message is feedback about too_short
            call_list = mock_agent.ainvoke.call_args_list
            retry_calls = [
                c[0][0]
                for c in call_list
                if isinstance(c[0][0], dict)
                and c[0][0].get("messages")
                and len(c[0][0]["messages"]) == 3
                and "too_short" in str(c[0][0]["messages"][-1].content)
            ]
            assert retry_calls, "Retry must append feedback message to messages"
            second_call_state = retry_calls[0]
            assert second_call_state["messages"][0].content == "Q"
            assert second_call_state["messages"][1].content == short_content
            assert "too_short" in str(second_call_state["messages"][2].content)
            assert "Expand" in str(second_call_state["messages"][2].content)


class TestIsReportComplete:
    """Tests for _is_report_complete heuristic."""

    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.ainvoke = AsyncMock()
        llm.bind_tools = MagicMock(return_value=llm)
        return llm

    @pytest.fixture
    def mock_llm_provider(self, mock_llm):
        provider = LLMProvider()
        provider.set_default(mock_llm)
        provider.configure(LLMRole.ORCHESTRATOR, mock_llm)
        provider.configure(LLMRole.PLANNER, mock_llm)
        provider.configure(LLMRole.RESEARCHER, mock_llm)
        return provider

    @pytest.fixture
    def real_tool(self):
        return web_search_tool

    def test_complete_report_returns_true(self, mock_llm_provider, real_tool):
        """Report with length, headers, and Sources section is complete."""
        with patch(
            "aiq_agent.agents.deep_researcher.agent.create_deep_agent",
            return_value=MagicMock(),
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])
            content = "A" * 1600 + "\n## Introduction\n\n## Methods\n\n## Sources\n[1] http://x.com"
            result = {"messages": [AIMessage(content=content)]}
            is_complete, reason = agent._is_report_complete(result)
            assert is_complete is True
            assert "complete" in reason.lower()

    def test_too_short_returns_false(self, mock_llm_provider, real_tool):
        """Report under length threshold is incomplete."""
        with patch(
            "aiq_agent.agents.deep_researcher.agent.create_deep_agent",
            return_value=MagicMock(),
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])
            result = {"messages": [AIMessage(content="Short.")]}
            is_complete, reason = agent._is_report_complete(result)
            assert is_complete is False
            assert "too_short" in reason

    def test_missing_sources_returns_false(self, mock_llm_provider, real_tool):
        """Report without Sources section is incomplete."""
        with patch(
            "aiq_agent.agents.deep_researcher.agent.create_deep_agent",
            return_value=MagicMock(),
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])
            content = "A" * 1600 + "\n## Intro\n\n## Body\n\nNo sources here."
            result = {"messages": [AIMessage(content=content)]}
            is_complete, reason = agent._is_report_complete(result)
            assert is_complete is False
            assert "missing_sources" in reason or "sources" in reason.lower()

    def test_empty_messages_returns_false(self, mock_llm_provider, real_tool):
        """Empty messages is incomplete."""
        with patch(
            "aiq_agent.agents.deep_researcher.agent.create_deep_agent",
            return_value=MagicMock(),
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])
            result = {"messages": []}
            is_complete, reason = agent._is_report_complete(result)
            assert is_complete is False
            assert "no_messages" in reason or "message" in reason.lower()

    def test_write_file_tool_call_extracts_content(self, mock_llm_provider, real_tool):
        """Report written via write_file tool call should be detected as complete."""
        with patch(
            "aiq_agent.agents.deep_researcher.agent.create_deep_agent",
            return_value=MagicMock(),
        ):
            from aiq_agent.agents.deep_researcher.agent import DeepResearcherAgent

            agent = DeepResearcherAgent(llm_provider=mock_llm_provider, tools=[real_tool])
            report_content = "A" * 1600 + "\n## Introduction\n\n## Methods\n\n## Sources\n[1] http://x.com"
            # AIMessage with empty text but report in write_file tool call
            msg = AIMessage(
                content="",
                tool_calls=[
                    {"name": "write_file", "args": {"file_path": "/report.md", "content": report_content}, "id": "tc1"}
                ],
            )
            result = {"messages": [msg]}
            is_complete, reason = agent._is_report_complete(result)
            assert is_complete is True
            assert "complete" in reason.lower()

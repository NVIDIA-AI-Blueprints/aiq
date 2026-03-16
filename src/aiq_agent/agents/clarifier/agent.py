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

"""
Clarifier agent for interactive clarification dialog.

This module provides the ClarifierAgent class which handles multi-turn
clarification dialogs with users before deep research begins. The agent
uses LangGraph for workflow orchestration and supports tool calling
for context gathering.

Example:
    >>> from aiq_agent.agents.clarifier_agent import ClarifierAgent
    >>> from aiq_agent.common import LLMProvider
    >>>
    >>> async def prompt_user(question: str) -> str:
    ...     return input(question)
    >>>
    >>> provider = LLMProvider()
    >>> provider.set_default(my_llm)
    >>> agent = ClarifierAgent(
    ...     llm_provider=provider,
    ...     user_prompt_callback=prompt_user,
    ... )
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable
from collections.abc import Callable
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from aiq_agent.common import LLMProvider
from aiq_agent.common import LLMRole
from aiq_agent.common import get_latest_user_query
from aiq_agent.common import load_prompt
from aiq_agent.common import render_prompt_template

from .models import ClarificationResponse
from .models import ClarifierAgentState
from .models import ClarifierResult

logger = logging.getLogger(__name__)

AGENT_DIR = Path(__file__).parent
"""Path to the clarifier agent's directory, used for loading prompts."""

DEFAULT_CLARIFICATION_PROMPT = (
    "/no_think\n\n"
    "You are a helpful research clarification assistant. "
    "Ask focused questions to understand the user's needs. "
    'Respond with JSON: {"needs_clarification": true/false, "clarification_question": "your question?" or null}'
)
"""Fallback prompt used when the prompt file cannot be loaded."""

DEFAULT_PLAN_GENERATION_PROMPT = (
    "/no_think\n\n"
    "Generate a research plan with a title and 5-8 sections. "
    'Respond with JSON: {"title": "...", "sections": ["...", "..."]}'
)
"""Fallback prompt for plan generation."""

APPROVAL_KEYWORDS = {"approve", "approved", "yes", "ok", "proceed", "continue", "go ahead", "looks good", "y", "accept"}
"""Keywords that indicate the user approves the plan."""

REJECTION_KEYWORDS = {"reject", "rejected", "no", "cancel", "stop", "abort", "n"}
"""Keywords that indicate the user rejects the plan."""

JSON_REMINDER_AFTER_TOOLS = (
    "Based on the search results above, now make your clarification decision. "
    "IMPORTANT: You must respond with ONLY a valid JSON object, nothing else. "
    "Do NOT write a report, summary, or analysis. "
    "Output exactly: "
    '{"needs_clarification": true, "clarification_question": "your question"} '
    "OR "
    '{"needs_clarification": false, "clarification_question": null}'
)
"""Reminder prompt added after tool results to reinforce JSON-only output."""


class ClarifierAgent:
    """
    Clarifier agent for interactive clarification dialog.

    This agent handles interactive clarification dialogs for deep research queries.
    It asks follow-up questions to refine the research scope, constraints, and
    requirements before the actual research begins.

    The agent uses LangGraph for workflow orchestration with three main nodes:
    - agent: Generates clarification questions using the LLM
    - tools: Executes tool calls for context gathering (e.g., web search)
    - ask_for_clarification: Prompts the user and processes their response

    Attributes:
        llm_provider: Provider for obtaining LLM instances.
        tools: List of tools available for context gathering.
        user_prompt_callback: Async callback for prompting user input.
        max_turns: Maximum number of Q&A turns before auto-completing.
        system_prompt: The loaded system prompt for the LLM.
        callbacks: LangChain callbacks for tracing/logging.

    Example:
        >>> async def user_prompt_fn(question: str) -> str:
        ...     return input(question)
        >>>
        >>> provider = LLMProvider()
        >>> provider.set_default(my_llm)
        >>> agent = ClarifierAgent(
        ...     llm_provider=provider,
        ...     tools=[search_tool],
        ...     user_prompt_callback=user_prompt_fn,
        ...     max_turns=3,
        ... )
        >>> state = ClarifierAgentState(messages=[HumanMessage(content="Research AI")])
        >>> result = await agent.run(state)
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        tools: Sequence[BaseTool] | None = None,
        *,
        user_prompt_callback: Callable[[str], Awaitable[str]],
        max_turns: int = 3,
        enable_plan_approval: bool = False,
        max_plan_iterations: int = 10,
        planner_llm: BaseChatModel | None = None,
        log_response_max_chars: int = 2000,
        verbose: bool = False,
        callbacks: list[Any] | None = None,
    ) -> None:
        """
        Initialize the clarifier agent.

        Args:
            llm_provider: Provider for obtaining LLM instances by role.
            tools: Optional sequence of LangChain tools for context gathering
                (e.g., web search). Tools help the agent ask more informed questions.
            user_prompt_callback: Async callback function to prompt the user for input.
                Takes a question string and returns the user's response string.
            max_turns: Maximum number of clarification Q&A turns before
                automatically completing clarification. Defaults to 3.
            enable_plan_approval: Whether to enable plan preview and approval
                after clarification completes. Defaults to False.
            max_plan_iterations: Maximum number of plan feedback iterations
                before auto-approving. Defaults to 10.
            planner_llm: Optional LLM to use for plan generation. If not provided,
                uses the default clarifier LLM.
            log_response_max_chars: Maximum characters to log from LLM responses.
                Used for debugging. Defaults to 2000.
            verbose: Whether to enable detailed logging. Defaults to False.
            callbacks: Optional list of LangChain callback handlers for
                tracing and logging.
        """
        self.llm_provider: LLMProvider = llm_provider
        self.tools = list(tools) if tools else []
        self.user_prompt_callback = user_prompt_callback
        self.max_turns = max_turns
        self.enable_plan_approval = enable_plan_approval
        self.max_plan_iterations = max_plan_iterations
        self.planner_llm = planner_llm
        self.log_response_max_chars = log_response_max_chars
        self.verbose = verbose
        self.callbacks = callbacks or []

        self.system_prompt = self._load_default_prompt()
        self.plan_generation_prompt = self._load_plan_generation_prompt()

        self._graph = self._build_graph()

    def _load_default_prompt(self) -> str:
        """
        Load the research clarification prompt from file.

        Attempts to load the prompt from the prompts/research_clarification.j2
        file. Falls back to DEFAULT_CLARIFICATION_PROMPT if the file is not found.

        Returns:
            The loaded prompt string, or the default fallback prompt.
        """
        try:
            return load_prompt(AGENT_DIR / "prompts", "research_clarification")
        except Exception:
            logger.warning("Clarifier prompt not found, using inline default")
            return DEFAULT_CLARIFICATION_PROMPT

    def _load_plan_generation_prompt(self) -> str:
        """
        Load the plan generation prompt from file.

        Returns:
            The loaded prompt string, or the default fallback prompt.
        """
        try:
            return load_prompt(AGENT_DIR / "prompts", "plan_generation")
        except Exception:
            logger.warning("Plan generation prompt not found, using inline default")
            return DEFAULT_PLAN_GENERATION_PROMPT

    def _parse_plan_response(self, text: str) -> tuple[str | None, list[str]]:
        """
        Parse plan generation response from LLM.

        Args:
            text: Raw JSON text response from the LLM.

        Returns:
            Tuple of (title, sections) or (None, []) if parsing fails.
        """
        if not text:
            return None, []

        text = text.strip()
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if json_match:
            text = json_match.group(1).strip()

        try:
            data = json.loads(text)
            title = data.get("title")
            sections = data.get("sections", [])
            if isinstance(sections, list) and all(isinstance(s, str) for s in sections):
                return title, sections
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Failed to parse plan response as JSON: %s", e)

        return None, []

    def _parse_approval(self, response: str) -> tuple[bool, bool, str | None]:
        """
        Parse user's approval response.

        Args:
            response: User's response text (may be JSON wrapped).

        Returns:
            Tuple of (approved, rejected, feedback).
            - If approved: (True, False, None)
            - If rejected: (False, True, None)
            - If feedback: (False, False, feedback_text)
        """
        # Extract query from JSON if wrapped (e.g., {"query": "approve", ...})
        text = response.strip()
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "query" in data:
                text = data["query"]
        except (json.JSONDecodeError, TypeError):
            pass  # Not JSON, use original text

        normalized = text.strip().lower()

        if normalized in APPROVAL_KEYWORDS:
            return True, False, None

        if normalized in REJECTION_KEYWORDS:
            return False, True, None

        # Treat as feedback for plan revision
        return False, False, text.strip()

    def _format_plan_for_user(self, title: str, sections: list[str]) -> str:
        """
        Format the plan for user display.

        Args:
            title: Plan title.
            sections: List of section titles.

        Returns:
            Formatted string for user display.
        """
        sections_text = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(sections))
        return (
            f"**Research Plan Preview**\n\n"
            f"**Title:** {title}\n\n"
            f"**Sections:**\n{sections_text}\n\n"
            f"---\n"
            f"Reply **approve** to proceed, **reject** to cancel, or provide feedback to revise the plan."
        )

    def _parse_response(self, text: str) -> ClarificationResponse | None:
        """
        Parse JSON response from LLM into ClarificationResponse.

        Attempts multiple strategies to extract JSON:
        1. Parse the entire text as JSON
        2. Extract from markdown code blocks
        3. Find JSON object pattern anywhere in text

        Args:
            text: Raw text response from LLM.

        Returns:
            ClarificationResponse if parsing succeeds, None otherwise.
        """
        if not text:
            return None

        text = text.strip()

        # Strategy 1: Try parsing the entire text as JSON
        try:
            data = json.loads(text)
            return ClarificationResponse.model_validate(data)
        except (json.JSONDecodeError, Exception):
            pass

        # Strategy 2: Extract from markdown code blocks
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if json_match:
            try:
                data = json.loads(json_match.group(1).strip())
                return ClarificationResponse.model_validate(data)
            except (json.JSONDecodeError, Exception):
                pass

        # Strategy 3: Find JSON object pattern anywhere in text
        # Look for {"needs_clarification": ...} pattern
        json_pattern = re.search(r'\{[^{}]*"needs_clarification"[^{}]*\}', text)
        if json_pattern:
            try:
                data = json.loads(json_pattern.group(0))
                return ClarificationResponse.model_validate(data)
            except (json.JSONDecodeError, Exception):
                pass

        # Strategy 4: Find any JSON object (more permissive)
        brace_match = re.search(r"\{[\s\S]*?\}", text)
        if brace_match:
            try:
                data = json.loads(brace_match.group(0))
                return ClarificationResponse.model_validate(data)
            except (json.JSONDecodeError, Exception):
                pass

        logger.warning("Failed to parse clarification response as JSON: %s...", text[:200])
        return None

    def _is_needed(self, text: str) -> bool:
        """
        Check if clarification is needed based on JSON response.

        Args:
            text: Raw JSON text response from the LLM.

        Returns:
            True if clarification is needed or parsing failed, False otherwise.
        """
        response = self._parse_response(text)
        if response is None:
            logger.warning("Failed to parse response, assuming clarification needed")
            return True
        return response.needs_clarification

    def _is_complete(self, text: str) -> bool:
        """
        Check if clarification is complete based on JSON response.

        Args:
            text: Raw JSON text response from the LLM.

        Returns:
            True if clarification is complete (needs_clarification=false),
            False otherwise or if parsing failed.
        """
        response = self._parse_response(text)
        if response is None:
            return False
        return response.is_complete()

    def _valid_needed(self, text: str) -> bool:
        """
        Check if the clarification response is valid.

        A response is valid if:
        - It parses successfully as JSON
        - When needs_clarification is true, it contains a clarification question

        Args:
            text: Raw JSON text response from the LLM.

        Returns:
            True if the response is valid, False otherwise.
        """
        response = self._parse_response(text)
        if response is None:
            return False
        return response.is_valid()

    def _get_clarification_question(self, text: str) -> str:
        """
        Extract the clarification question from the response.

        Args:
            text: Raw text response from LLM.

        Returns:
            The clarification question text.
        """
        response = self._parse_response(text)
        if response is not None and response.clarification_question:
            return response.clarification_question
        logger.warning("No clarification question found in response")
        return "Could you provide more details about your research needs?"

    def _get_llm(self) -> BaseChatModel:
        """
        Get the LLM instance for the clarifier agent.

        Uses LLMRole.CLARIFIER to obtain the appropriate LLM from the provider.

        Returns:
            The LangChain LLM instance for generating clarification questions.
        """
        return self.llm_provider.get(LLMRole.CLARIFIER)

    def _get_fallback_clarification(self, query: str | None = None) -> str:
        """
        Get fallback clarification text when the LLM response is invalid.

        Returns a topic-aware clarification question when query is provided,
        otherwise falls back to a generic question.

        Args:
            query: Optional user query to make the fallback more relevant.

        Returns:
            JSON string representing a ClarificationResponse with a fallback question.
        """
        if query:
            # Create topic-aware fallback
            topic_snippet = query[:80].strip()
            if len(query) > 80:
                topic_snippet += "..."
            question = (
                f'To help with your research on: "{topic_snippet}"\n\n'
                "Could you specify:\n"
                "1. Which specific aspects are most important to you?\n"
                "2. What level of detail do you need?\n"
                "3. Or type 'skip' to proceed with a general approach."
            )
        else:
            question = (
                "I'd like to help with your research. Could you provide more details about:\n\n"
                "1. What specific aspects interest you most?\n"
                "2. Who is this report for?\n"
                "3. How detailed should it be?"
            )

        fallback = ClarificationResponse(
            needs_clarification=True,
            clarification_question=question,
        )
        return fallback.model_dump_json()

    SKIP_COMMANDS = {"skip", "done", "exit", "quit", "proceed", "continue", "no", "n", ""}
    """Set of commands that indicate the user wants to skip clarification."""

    def _is_skip_command(self, user_reply: str) -> bool:
        """
        Check if the user's reply indicates they want to skip clarification.

        Recognized skip commands: skip, done, exit, quit, proceed, continue, no, n,
        or empty string.

        Args:
            user_reply: The user's response text.

        Returns:
            True if the reply is a skip command, False otherwise.
        """
        return user_reply.strip().lower() in self.SKIP_COMMANDS

    def _build_graph(self) -> CompiledStateGraph:
        """
        Build the LangGraph StateGraph for the clarification workflow.

        Creates a graph with three nodes:
        - agent: Generates clarification questions using the LLM
        - tools: Executes tool calls (e.g., web search) for context
        - ask_for_clarification: Prompts user and processes response

        The graph flow:
        1. agent generates a response (question, tool call, or completion)
        2. If tool call → tools node → back to agent
        3. If question → ask_for_clarification → back to agent
        4. If complete → end

        Returns:
            Compiled LangGraph StateGraph ready for execution.
        """
        llm = self._get_llm()
        bound_llm = llm.bind_tools(self.tools, parallel_tool_calls=True) if self.tools else llm
        # Use planner_llm for plan generation if provided, otherwise use default llm
        planner_llm = self.planner_llm if self.planner_llm is not None else llm

        graph = StateGraph(ClarifierAgentState)

        async def agent_node(state: ClarifierAgentState):
            if state.remaining_questions <= 0:
                complete_response = ClarificationResponse(needs_clarification=False, clarification_question=None)
                return {"messages": [AIMessage(content=complete_response.model_dump_json())]}
            tools_info = [
                {"name": getattr(t, "name", ""), "description": getattr(t, "description", "")} for t in self.tools
            ]
            rendered_system_prompt = render_prompt_template(
                self.system_prompt,
                clarifier_result=state.clarifier_log,
                available_documents=state.available_documents or [],
                tools=tools_info,
                tool_names=[t["name"] for t in tools_info],
            )

            # Build message list
            messages = [SystemMessage(content=rendered_system_prompt)] + state.messages

            # If last message is a tool result, add JSON reminder to prevent report generation
            if state.messages and isinstance(state.messages[-1], ToolMessage):
                logger.info("Adding JSON reminder after tool results")
                messages.append(HumanMessage(content=JSON_REMINDER_AFTER_TOOLS))

            response = await bound_llm.ainvoke(messages)
            return {"messages": [response]}

        async def ask_clarification(state: ClarifierAgentState):
            iteration = state.iteration
            max_turns = state.max_turns
            clarifier_log = state.clarifier_log
            if iteration >= max_turns:
                return {
                    "clarifier_log": f"Clarification complete: Met the maximum number of turns\n{clarifier_log}",
                }
            text = state.messages[-1].content if state.messages else ""
            if not self._is_needed(text):
                return {}

            if not self._valid_needed(text):
                logger.warning("Invalid clarification format, forcing fallback")
                # Extract latest query for topic-aware fallback
                original_query = get_latest_user_query(state.messages)
                text = self._get_fallback_clarification(query=original_query if original_query else None)

            question_text = self._get_clarification_question(text)
            clarifier_log = f"{clarifier_log}\n**Turn {iteration + 1} - Assistant:**\n{question_text}"
            user_reply = await self.user_prompt_callback(question_text)

            if self._is_skip_command(user_reply):
                logger.info("Clarifier: User requested to skip clarification")
                complete_response = ClarificationResponse(needs_clarification=False, clarification_question=None)
                clarifier_log = f"{clarifier_log}\n**Turn {iteration + 1} - User:** [Skipped clarification]"
                return {
                    "messages": [AIMessage(content=complete_response.model_dump_json())],
                    "iteration": max_turns,  # Force end of clarification
                    "clarifier_log": clarifier_log,
                }

            clarifier_log = f"{clarifier_log}\n**Turn {iteration + 1} - User:**\n{user_reply}"
            return {
                "messages": [HumanMessage(content=user_reply)],
                "iteration": iteration + 1,
                "clarifier_log": clarifier_log,
            }

        def decide_route(state: ClarifierAgentState | dict):
            if isinstance(state, dict):
                messages = state.get("messages", [])
            elif hasattr(state, "messages"):
                messages = state.messages
            else:
                msg = f"No messages found in input state to tool_edge: {state}"
                raise ValueError(msg)

            if not messages:
                msg = f"Empty messages list in state: {state}"
                raise ValueError(msg)

            ai_message = messages[-1]
            if hasattr(ai_message, "tool_calls") and len(ai_message.tool_calls) > 0:
                return "tools"

            if self._is_complete(ai_message.content):
                if self.enable_plan_approval:
                    return "plan_preview"
                return "__end__"
            return "ask_for_clarification"

        async def plan_preview_node(state: ClarifierAgentState):
            """Generate plan preview and handle approval/feedback loop."""
            clarifier_log = state.clarifier_log
            feedback_history: list[str] = list(state.plan_feedback_history)

            # Initialize with fallback values in case loop doesn't execute (max_plan_iterations <= 0)
            title: str = "Research Report"
            sections: list[str] = ["Introduction", "Background", "Analysis", "Findings", "Conclusion"]

            for iteration in range(self.max_plan_iterations):
                rendered_prompt = render_prompt_template(
                    self.plan_generation_prompt,
                    clarifier_context=clarifier_log,
                    feedback_history=feedback_history if feedback_history else None,
                )

                # Generate plan using planner LLM
                messages_for_plan = state.messages + [HumanMessage(content="Generate a research plan.")]
                response = await planner_llm.ainvoke([SystemMessage(content=rendered_prompt)] + messages_for_plan)
                title, sections = self._parse_plan_response(response.content)

                if not title or not sections:
                    logger.warning("Failed to generate valid plan, using fallback")
                    title = "Research Report"
                    sections = ["Introduction", "Background", "Analysis", "Findings", "Conclusion"]

                # Present plan to user
                plan_display = self._format_plan_for_user(title, sections)
                user_response = await self.user_prompt_callback(plan_display)

                approved, rejected, feedback = self._parse_approval(user_response)

                if approved:
                    logger.info("Clarifier: Plan approved by user")
                    return {
                        "plan_title": title,
                        "plan_sections": sections,
                        "plan_approved": True,
                        "plan_rejected": False,
                        "plan_feedback_history": feedback_history,
                    }

                if rejected:
                    logger.info("Clarifier: Plan rejected by user")
                    return {
                        "plan_title": title,
                        "plan_sections": sections,
                        "plan_approved": False,
                        "plan_rejected": True,
                        "plan_feedback_history": feedback_history,
                    }

                # User provided feedback, add to history and continue loop
                logger.info("Clarifier: User provided feedback, regenerating plan")
                feedback_history.append(feedback)

            # Max iterations reached, auto-approve
            logger.warning("Clarifier: Max plan iterations reached, auto-approving")
            return {
                "plan_title": title,
                "plan_sections": sections,
                "plan_approved": True,
                "plan_rejected": False,
                "plan_feedback_history": feedback_history,
            }

        graph.add_node("agent", agent_node)
        graph.add_node("tools", ToolNode(self.tools))
        graph.add_node("ask_for_clarification", ask_clarification)
        graph.add_node("plan_preview", plan_preview_node)

        graph.set_entry_point("agent")

        graph.add_conditional_edges(
            "agent",
            decide_route,
            {
                "tools": "tools",
                "ask_for_clarification": "ask_for_clarification",
                "plan_preview": "plan_preview",
                "__end__": "__end__",
            },
        )

        graph.add_edge("tools", "agent")
        graph.add_edge("ask_for_clarification", "agent")
        graph.add_edge("plan_preview", "__end__")

        return graph.compile()

    async def run(self, state: ClarifierAgentState) -> ClarifierResult:
        """
        Execute the clarification dialog.

        Args:
            state: Initial state of the clarifier agent.

        Returns:
            ClarifierResult with clarification log and plan approval details.
        """
        logger.info("Clarifier: Starting (max %d turns)", self.max_turns)
        query = get_latest_user_query(state.messages)
        logger.info("User's query: %s...", str(query)[:100] if query else "")
        result = await self._graph.ainvoke(state, config={"callbacks": self.callbacks})
        final_state = ClarifierAgentState.model_validate(result)
        return ClarifierResult(
            clarifier_log=final_state.clarifier_log,
            plan_title=final_state.plan_title,
            plan_sections=final_state.plan_sections,
            plan_approved=final_state.plan_approved,
            plan_rejected=final_state.plan_rejected,
        )

    @property
    def graph(self) -> CompiledStateGraph:
        """Get the compiled LangGraph for direct access."""
        return self._graph

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
Chat Researcher Agent - Orchestrates intent classification, depth routing, and research.

This is the main orchestrator agent that coordinates the full research workflow:
1. Intent classification (meta vs research)
2. Depth routing (shallow vs deep)
3. Research execution
4. Optional escalation from shallow to deep
"""

import logging
from collections.abc import Awaitable
from collections.abc import Callable
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.messages import BaseMessage
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from aiq_agent.agents.clarifier.models import ClarifierAgentState
from aiq_agent.agents.clarifier.models import ClarifierResult
from aiq_agent.agents.deep_researcher.models import DeepResearchAgentState
from aiq_agent.agents.shallow_researcher.models import ShallowResearchAgentState
from aiq_agent.common import get_latest_user_query

from .models import ChatResearcherState
from .models import ShallowResult
from .utils import trim_message_history

logger = logging.getLogger(__name__)


class ChatResearcherAgent:
    """
    Orchestrates the full chat research workflow.

    Coordinates intent classification, depth routing, and research agents
    to produce research results based on user queries.

    The workflow:
    1. Classify intent (meta vs research)
    2. If meta → respond with meta chatter
    3. If research → route to shallow or deep based on complexity
    4. Optionally escalate from shallow to deep if results insufficient
    """

    def __init__(
        self,
        intent_classifier_fn: Callable[[str], Awaitable[str]],
        shallow_research_fn: Callable[[str], Awaitable[str]],
        deep_research_fn: Callable[[str], Awaitable[str]],
        clarifier_fn: Callable[
            [ClarifierAgentState | list[BaseMessage]],
            Awaitable[ClarifierResult],
        ]
        | None,
        *,
        enable_clarifier: bool = True,
        enable_escalation: bool = True,
        callbacks: list[BaseCallbackHandler] | None = None,
        max_history: int = 5,
        deep_research_job_submitter: Callable[[Any], Awaitable[str]] | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        validate_deep_research_tools_fn: Callable[[list[str] | None], Awaitable[tuple[bool, str]]] | None = None,
    ) -> None:
        """
        Initialize the chat researcher agent.

        Args:
            intent_classifier_fn: Combined orchestration (intent + meta response + depth in one node)
            shallow_research_fn: Function for shallow research
            deep_research_fn: Function for deep research
            clarifier_fn: Function for clarification
            enable_clarifier: Whether to enable clarification
            enable_escalation: Whether to escalate shallow to deep on low confidence
            callbacks: Optional list of callback handlers
            max_history: Maximum number of messages to keep in history
            deep_research_job_submitter: Optional function to submit deep research as async job
            checkpointer: Optional checkpointer for persistent state (defaults to MemorySaver)
        """
        self.intent_classifier_fn = intent_classifier_fn
        self.shallow_research_fn = shallow_research_fn
        self.deep_research_fn = deep_research_fn
        self.clarifier_fn = clarifier_fn
        self.enable_clarifier = enable_clarifier
        self.enable_escalation = enable_escalation
        self.callbacks = callbacks or []
        self.max_history = max_history
        self.deep_research_job_submitter = deep_research_job_submitter
        self.checkpointer = checkpointer
        self.validate_deep_research_tools_fn = validate_deep_research_tools_fn

        self._graph = self._build_graph()

    def _build_graph(self) -> CompiledStateGraph:
        """Build the LangGraph workflow."""

        async def intent_classifier_node(state: ChatResearcherState) -> dict[str, Any]:
            return await self.intent_classifier_fn(state)

        async def clarifier_node(state: ChatResearcherState) -> dict[str, Any]:
            original_query = get_latest_user_query(state.messages)

            # Validate deep research tools before proceeding to clarifier
            if self.validate_deep_research_tools_fn:
                is_valid, error_msg = await self.validate_deep_research_tools_fn(state.data_sources)
                if not is_valid:
                    logger.error("Deep research tools validation failed: %s", error_msg)
                    return Command(
                        goto=END,
                        update={
                            "messages": [AIMessage(content=error_msg)],
                            "original_query": original_query,
                        },
                    )

            if self.enable_clarifier:
                if self.clarifier_fn is None:
                    raise ValueError(
                        "enable_clarifier is True but clarifier_agent is not defined in config. "
                        "Either add clarifier_agent to functions or set enable_clarifier: false."
                    )
                trimmed_messages: list[BaseMessage] = trim_message_history(state.messages, self.max_history)
                available_docs = [doc.model_dump() for doc in (state.available_documents or [])]
                clarifier_state = ClarifierAgentState(
                    messages=trimmed_messages,
                    data_sources=state.data_sources,
                    available_documents=available_docs if available_docs else None,
                )
                result = await self.clarifier_fn(clarifier_state)

                # Check if plan was rejected
                if result.plan_rejected:
                    logger.info("ChatResearcher: Plan rejected by user, ending workflow")
                    return Command(
                        goto=END,
                        update={
                            "messages": [
                                AIMessage(
                                    content="Research plan was rejected. Please start a new research query when ready."
                                )
                            ],
                            "original_query": original_query,
                        },
                    )

                # Build clarifier result with optional approved plan context
                clarifier_result = result.clarifier_log
                approved_plan_context = result.get_approved_plan_context()
                if approved_plan_context:
                    clarifier_result = f"{clarifier_result}\n\n{approved_plan_context}"

                return Command(
                    goto="deep_research",
                    update={
                        "clarifier_result": clarifier_result,
                        "original_query": original_query,
                    },
                )
            return Command(goto="deep_research", update={"original_query": original_query})

        async def shallow_research_node(state: ChatResearcherState) -> dict[str, Any]:
            trimmed_messages: list[BaseMessage] = trim_message_history(state.messages, self.max_history)

            logger.debug(
                "shallow_research_node: ChatResearcherState.available_documents = %s",
                state.available_documents,
            )

            try:
                shallow_state = ShallowResearchAgentState(
                    messages=trimmed_messages,
                    data_sources=state.data_sources,
                    available_documents=state.available_documents,
                )
                result = await self.shallow_research_fn(shallow_state)
            except Exception as e:
                logger.exception("Error in shallow research: %s", e)
                err_msg = "An error occurred while researching your question. Please try again."
                return {"messages": [AIMessage(content=err_msg)]}

            if not result.messages:
                logger.error("Shallow research agent returned no messages")
                return {
                    "shallow_result": ShallowResult(
                        answer="An error occurred during shallow research.",
                        confidence="low",
                        escalate_to_deep=True,
                        escalation_reason="Shallow research encountered an error",
                    )
                }
            new_messages = result.messages[len(trimmed_messages) :]
            final_ai_message = next(
                (m for m in reversed(new_messages) if isinstance(m, AIMessage) and not m.tool_calls),
                None,
            )
            if final_ai_message:
                return {"messages": [final_ai_message]}
            if new_messages:
                return {"messages": [new_messages[-1]]}
            return {"messages": []}

        async def deep_research_node(state: ChatResearcherState) -> dict[str, Any]:
            trimmed_messages: list[BaseMessage] = trim_message_history(state.messages, self.max_history)
            if self.deep_research_job_submitter is not None:
                job_id = await self.deep_research_job_submitter(state)
                response = f"Deep research job submitted. Job ID: {job_id}"
                return {"messages": [AIMessage(content=response)]}

            research_query = state.original_query or get_latest_user_query(state.messages)
            deep_state = DeepResearchAgentState(
                messages=trimmed_messages + [HumanMessage(content=research_query)],
                data_sources=state.data_sources,
                clarifier_result=state.clarifier_result,
                available_documents=state.available_documents,
            )
            result = await self.deep_research_fn(deep_state)
            if not result.messages:
                error_message = "An error occurred during deep research."
                logger.error(error_message)
                final_message = AIMessage(content=error_message)
                return {"messages": [final_message]}
            else:
                return {"messages": [result.messages[-1]]}

        def route_after_orchestration(state: ChatResearcherState) -> str:
            """From combined orchestration: meta -> END (response already in messages), else by depth."""
            if state.user_intent and state.user_intent.intent == "meta":
                return "END"
            if state.depth_decision and state.depth_decision.decision == "deep":
                return "clarifier"
            return "shallow_research"

        def should_escalate(state: ChatResearcherState) -> str:
            if not self.enable_escalation:
                return END

            messages = state.messages
            if not messages:
                return END

            last_ai_content = None
            for m in reversed(messages):
                if isinstance(m, AIMessage):
                    last_ai_content = m.content if hasattr(m, "content") else str(m)
                    break
            if not last_ai_content:
                return END

            last_content = last_ai_content if isinstance(last_ai_content, str) else str(last_ai_content)
            if not last_content.strip():
                return "deep_research"

            tail = last_content[-800:].lower() if len(last_content) > 800 else last_content.lower()
            escalation_keywords = ["i don't have enough information", "unable to find", "need more research"]
            if any(kw in tail for kw in escalation_keywords):
                return "deep_research"

            return END

        graph = StateGraph(ChatResearcherState)

        graph.add_node("intent_classifier", intent_classifier_node)
        graph.add_node("shallow_research", shallow_research_node)
        graph.add_node("clarifier", clarifier_node)
        graph.add_node("deep_research", deep_research_node)

        graph.set_entry_point("intent_classifier")

        graph.add_conditional_edges(
            "intent_classifier",
            route_after_orchestration,
            {
                "END": END,
                "clarifier": "clarifier",
                "shallow_research": "shallow_research",
            },
        )

        graph.add_conditional_edges(
            "shallow_research",
            should_escalate,
            {
                "deep_research": "clarifier",
                END: END,
            },
        )

        graph.add_edge("deep_research", END)

        return graph.compile(checkpointer=self.checkpointer)

    async def run(
        self, state: ChatResearcherState | dict[str, Any], thread_id: str | None = None
    ) -> ChatResearcherState:
        """
        Execute the chat researcher workflow.

        Args:
            state: ChatResearcherState or dict with new messages to add.
            thread_id: Thread ID for the conversation (used for checkpointing).
        Returns:
            Updated state with response in messages.
        """
        graph_config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        logger.info("ChatResearcherAgent: Starting workflow")

        if isinstance(state, dict):
            input_state = state
            messages = state.get("messages", [])
        else:
            input_state = {
                "messages": state.messages,
                "user_info": state.user_info,
                "data_sources": state.data_sources,
                "available_documents": state.available_documents,
            }
            messages = state.messages

        if messages:
            query = messages[-1].content
            logger.info("Query: %s...", str(query)[:100] if query else "")
        result = await self._graph.ainvoke(input_state, config=graph_config)

        logger.info("ChatResearcherAgent: Workflow complete")

        return result

    @property
    def graph(self) -> CompiledStateGraph:
        """Get the compiled LangGraph for direct access."""
        return self._graph

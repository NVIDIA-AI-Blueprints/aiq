# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""One autonomous data-science agent."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain.agents import create_agent
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from aiq_agent.common import SourceRegistry
from aiq_agent.common import get_session_registry
from aiq_agent.common import load_prompt
from aiq_agent.common import reset_session_registry
from aiq_agent.common import set_session_registry

from .messages import is_clarification_request
from .messages import message_text
from .models import DataScienceAgentContext
from .models import DataScienceAgentState
from .models import InteractionMode
from .utils.prompt import build_prompt_middleware
from .utils.reporting import capture_data_sources
from .utils.reporting import finalize_data_science_messages

AGENT_DIR = Path(__file__).parent
_HEADLESS_RETRY_MESSAGE_NAME = "aiq_headless_synthesis_retry"
_HEADLESS_RETRY_INSTRUCTION = (
    "No user interaction is available. Return the best supported answer to the original request now. "
    "Use the semantic and query evidence already gathered; make and disclose only defensible assumptions. "
    "If the request still cannot be completed safely, give a terminal explanation without asking a question."
)
_HEADLESS_TERMINAL_RESPONSE = (
    "I could not complete the request non-interactively because a material ambiguity remained after semantic "
    "discovery and one bounded synthesis retry. The available evidence did not support a safe assumption."
)


class DataScienceAgent:
    """Run discovery, adaptive tool calls, analysis, and writing in one history."""

    def __init__(
        self,
        *,
        llm: BaseChatModel,
        tools: Sequence[BaseTool],
        recursion_limit: int = 64,
        callbacks: Sequence[Any] = (),
        middleware: Sequence[AgentMiddleware] = (),
        interaction_mode: InteractionMode = "interactive",
    ) -> None:
        if recursion_limit < 4:
            raise ValueError("recursion_limit must be at least four")

        tool_name_counts = Counter(tool.name for tool in tools)
        duplicates = sorted(name for name, count in tool_name_counts.items() if count > 1)
        if duplicates:
            raise ValueError(f"data-science agent received duplicate tool names: {', '.join(duplicates)}")
        if not tool_name_counts:
            raise ValueError("data-science agent has no available data tools")
        if interaction_mode not in {"interactive", "headless"}:
            raise ValueError(f"unsupported data-science interaction mode: {interaction_mode}")

        agent_tools = list(tools)
        prompt_middleware = build_prompt_middleware(
            load_prompt(AGENT_DIR / "prompts", "agent"),
            agent_tools,
            interaction_mode=interaction_mode,
        )
        self.graph: CompiledStateGraph = create_agent(
            model=llm,
            tools=agent_tools,
            middleware=[prompt_middleware, *middleware],
            context_schema=DataScienceAgentContext,
            name="data_science_agent",
        )
        self.recursion_limit = recursion_limit
        self.source_tool_names = frozenset(tool_name_counts)
        self.callbacks = tuple(callbacks)
        self.interaction_mode = interaction_mode

    @staticmethod
    def _validate_question(state: DataScienceAgentState) -> None:
        if not state.messages:
            raise ValueError("data-science agent requires at least one message")
        latest = next((message for message in reversed(state.messages) if isinstance(message, HumanMessage)), None)
        if latest is None or not message_text(latest).strip():
            raise ValueError("data-science agent received an empty question")

    async def run(self, state: DataScienceAgentState) -> DataScienceAgentState:
        """Execute one request while preserving any caller-owned source registry."""
        self._validate_question(state)
        registry_token = None
        registry = get_session_registry()
        if registry is None:
            registry = SourceRegistry()
            registry_token = set_session_registry(registry)
        try:
            invoke_config: dict[str, Any] = {"recursion_limit": self.recursion_limit}
            if self.callbacks:
                invoke_config["callbacks"] = list(self.callbacks)
            result = await self.graph.ainvoke(
                {"messages": state.messages},
                config=invoke_config,
                context=DataScienceAgentContext(user_info=state.user_info),
            )
            result_messages = list(result["messages"])
            if (
                self.interaction_mode == "headless"
                and result_messages
                and is_clarification_request(result_messages[-1])
            ):
                retry_id = str(uuid4())
                retry_input = [
                    *result_messages[:-1],
                    HumanMessage(
                        content=_HEADLESS_RETRY_INSTRUCTION,
                        id=retry_id,
                        name=_HEADLESS_RETRY_MESSAGE_NAME,
                    ),
                ]
                retry_result = await self.graph.ainvoke(
                    {"messages": retry_input},
                    config=invoke_config,
                    context=DataScienceAgentContext(user_info=state.user_info),
                )
                result_messages = [
                    message
                    for message in retry_result["messages"]
                    if getattr(message, "id", None) != retry_id
                    and getattr(message, "name", None) != _HEADLESS_RETRY_MESSAGE_NAME
                ]
                if result_messages and is_clarification_request(result_messages[-1]):
                    result_messages[-1] = result_messages[-1].model_copy(
                        update={"content": _HEADLESS_TERMINAL_RESPONSE}
                    )
            capture_data_sources(
                result_messages,
                registry=registry,
                eligible_tool_names=self.source_tool_names,
            )
            messages = finalize_data_science_messages(
                result_messages,
                registry=registry,
                callbacks=self.callbacks,
                data_sources=state.data_sources,
                available_tools=list(self.source_tool_names),
            )
        finally:
            if registry_token is not None:
                reset_session_registry(registry_token)

        return state.model_copy(update={"messages": messages})

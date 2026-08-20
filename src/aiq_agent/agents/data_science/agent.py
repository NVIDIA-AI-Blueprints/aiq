# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""One autonomous data-science agent."""

from __future__ import annotations

import logging
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from aiq_agent.common import SourceRegistry
from aiq_agent.common import get_session_registry
from aiq_agent.common import load_prompt
from aiq_agent.common import reset_session_registry
from aiq_agent.common import sanitize_report
from aiq_agent.common import set_session_registry

from .messages import is_clarification_request
from .messages import message_text
from .models import DataScienceAgentContext
from .models import DataScienceAgentState
from .models import InteractionMode
from .models import ResponseMode
from .utils.analysis_runtime import begin_analysis_run
from .utils.analysis_runtime import end_analysis_run
from .utils.analysis_runtime import get_analysis_run
from .utils.finalization import FinalizationReserveMiddleware
from .utils.gsf_guardrails import GSFCallBudget
from .utils.gsf_guardrails import GSFCallGuardMiddleware
from .utils.gsf_guardrails import begin_gsf_run
from .utils.gsf_guardrails import end_gsf_run
from .utils.gsf_guardrails import summarize_gsf_run
from .utils.prompt import build_prompt_middleware
from .utils.reporting import capture_data_sources
from .utils.reporting import finalize_data_science_messages

AGENT_DIR = Path(__file__).parent
logger = logging.getLogger(__name__)
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
_CHOICE_REPAIR_MESSAGE_NAME = "aiq_choice_format_repair"
_EMPTY_RESPONSE_RETRY_MESSAGE_NAME = "aiq_empty_response_synthesis_retry"
_EMPTY_RESPONSE_RETRY_INSTRUCTION = (
    "Your previous final response contained no visible answer. Return the best supported final answer to the "
    "original request now, using only evidence already present in the conversation. Do not call tools, ask a "
    "question, or return an empty response. Follow the required answer-first and citation contracts."
)
_EMPTY_RESPONSE_TERMINAL = (
    "I could not produce a supported answer because the final synthesis model returned no visible content after "
    "one bounded retry."
)


def _choice_contract(messages: Sequence[Any]) -> tuple[list[str], bool] | None:
    latest = next((message_text(message) for message in reversed(messages) if isinstance(message, HumanMessage)), "")
    labels = list(dict.fromkeys(match.upper() for match in re.findall(r"(?im)^\s*([A-Z])\s*(?:[.)]|:)\s+\S", latest)))
    lowered = latest.lower()
    choice_markers = ("single-choice", "multiple-choice", "select exactly", "select all")
    if len(labels) < 2 or not any(token in lowered for token in choice_markers):
        return None
    return labels, "multiple-choice" in lowered or "select all correct" in lowered


def _has_valid_choice_line(content: str, labels: Sequence[str], *, multiple: bool) -> bool:
    first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
    match = re.fullmatch(r"Answer\s*[:：]\s*([^\r\n]+)", first_line, flags=re.IGNORECASE)
    if match is None:
        return False
    values = [value.strip().upper() for value in match.group(1).split(",")]
    return bool(values) and all(value in labels for value in values) and (multiple or len(values) == 1)


def _visible_report_text(message: Any) -> str:
    """Return displayable report text after the public sanitizer runs."""
    content = message_text(message).strip()
    if not content:
        return ""
    return sanitize_report(content).sanitized_report.strip()


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
        response_mode: ResponseMode = "standard",
        gsf_catalog_call_limit: int | None = None,
        gsf_text_to_sql_call_limit: int | None = None,
        gsf_cache_repeated_calls: bool = True,
        python_call_limit: int | None = None,
        finalization_model_call_limit: int | None = None,
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
        if response_mode not in {"standard", "fdabench_choice"}:
            raise ValueError(f"unsupported data-science response mode: {response_mode}")

        gsf_budget = GSFCallBudget(
            catalog_calls=gsf_catalog_call_limit,
            text_to_sql_calls=gsf_text_to_sql_call_limit,
            cache_repeated_calls=gsf_cache_repeated_calls,
        )

        agent_tools = list(tools)
        prompt_middleware = build_prompt_middleware(
            load_prompt(AGENT_DIR / "prompts", "agent"),
            agent_tools,
            interaction_mode=interaction_mode,
            response_mode=response_mode,
            gsf_catalog_call_limit=gsf_catalog_call_limit,
            gsf_text_to_sql_call_limit=gsf_text_to_sql_call_limit,
            python_call_limit=python_call_limit,
        )
        agent_middleware = [prompt_middleware]
        if gsf_catalog_call_limit is not None or gsf_text_to_sql_call_limit is not None or gsf_cache_repeated_calls:
            agent_middleware.append(GSFCallGuardMiddleware(gsf_budget))
        if python_call_limit is not None and "python" in tool_name_counts:
            agent_middleware.append(
                ToolCallLimitMiddleware(
                    tool_name="python",
                    run_limit=python_call_limit,
                    exit_behavior="continue",
                )
            )
        effective_finalization_limit = finalization_model_call_limit or max(2, (recursion_limit - 8) // 2)
        agent_middleware.append(FinalizationReserveMiddleware(effective_finalization_limit))
        agent_middleware.extend(middleware)
        self.graph: CompiledStateGraph = create_agent(
            model=llm,
            tools=agent_tools,
            middleware=agent_middleware,
            context_schema=DataScienceAgentContext,
            name="data_science_agent",
        )
        self.recursion_limit = recursion_limit
        self.source_tool_names = frozenset(tool_name_counts)
        self.callbacks = tuple(callbacks)
        self.interaction_mode = interaction_mode
        self.response_mode = response_mode
        self.gsf_budget = gsf_budget
        self.python_call_limit = python_call_limit
        self.finalization_model_call_limit = effective_finalization_limit

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
        analysis_run_token = begin_analysis_run()
        gsf_run_token = begin_gsf_run(self.gsf_budget)
        registry = get_session_registry()
        if registry is None:
            registry = SourceRegistry()
            registry_token = set_session_registry(registry)
        try:
            invoke_config: dict[str, Any] = {"recursion_limit": self.recursion_limit}
            if self.callbacks:
                invoke_config["callbacks"] = list(self.callbacks)
            runtime_context = DataScienceAgentContext(
                user_info=state.user_info,
                database_name=state.database_name,
                catalog_context=state.catalog_context,
                catalog_request_id=state.catalog_request_id,
            )
            result = await self.graph.ainvoke(
                {"messages": state.messages},
                config=invoke_config,
                context=runtime_context,
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
                    context=runtime_context,
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
            if not result_messages or not _visible_report_text(result_messages[-1]):
                run_state = get_analysis_run()
                if run_state is not None:
                    run_state.force_finalization = True
                    run_state.finalization_instruction = _EMPTY_RESPONSE_RETRY_INSTRUCTION
                retry_id = str(uuid4())
                retry_history = result_messages
                if retry_history and isinstance(retry_history[-1], AIMessage):
                    # Drop blank output and leaked tool-call markup. Keeping a max-token
                    # malformed answer in context can cause the repair call to repeat it.
                    retry_history = retry_history[:-1]
                retry_input = [
                    *retry_history,
                    HumanMessage(
                        content=_EMPTY_RESPONSE_RETRY_INSTRUCTION,
                        id=retry_id,
                        name=_EMPTY_RESPONSE_RETRY_MESSAGE_NAME,
                    ),
                ]
                retry_result = await self.graph.ainvoke(
                    {"messages": retry_input},
                    config=invoke_config,
                    context=runtime_context,
                )
                result_messages = [
                    message
                    for message in retry_result["messages"]
                    if getattr(message, "id", None) != retry_id
                    and getattr(message, "name", None) != _EMPTY_RESPONSE_RETRY_MESSAGE_NAME
                ]
                if not result_messages:
                    result_messages = [AIMessage(content=_EMPTY_RESPONSE_TERMINAL)]
                elif not _visible_report_text(result_messages[-1]):
                    result_messages[-1] = result_messages[-1].model_copy(update={"content": _EMPTY_RESPONSE_TERMINAL})
            choice_contract = _choice_contract(state.messages) if self.response_mode == "fdabench_choice" else None
            if choice_contract and result_messages:
                labels, multiple = choice_contract
                if not _has_valid_choice_line(message_text(result_messages[-1]), labels, multiple=multiple):
                    run_state = get_analysis_run()
                    if run_state is not None:
                        run_state.force_finalization = True
                        run_state.finalization_instruction = (
                            "FORMAT REPAIR ONLY: Return exactly one plain-text `Answer:` line containing "
                            "the conclusion already reached. Do not use tools, redo the analysis, add "
                            "rationale, citations, Markdown, or a Sources section."
                        )
                    retry_id = str(uuid4())
                    selection_rule = (
                        "Select every supported label, comma-separated with no spaces."
                        if multiple
                        else "Select exactly one label."
                    )
                    retry_input = [
                        *result_messages,
                        HumanMessage(
                            content=(
                                "Format repair only. Using the conclusion already reached, return exactly one line and "
                                "nothing else: `Answer: <labels>`. Valid labels are "
                                f"{', '.join(labels)}. {selection_rule}"
                            ),
                            id=retry_id,
                            name=_CHOICE_REPAIR_MESSAGE_NAME,
                        ),
                    ]
                    retry_result = await self.graph.ainvoke(
                        {"messages": retry_input},
                        config=invoke_config,
                        context=runtime_context,
                    )
                    result_messages = [
                        message
                        for message in retry_result["messages"]
                        if getattr(message, "id", None) != retry_id
                        and getattr(message, "name", None) != _CHOICE_REPAIR_MESSAGE_NAME
                    ]
            capture_data_sources(
                result_messages,
                registry=registry,
                eligible_tool_names=self.source_tool_names,
            )
            if choice_contract:
                # Preserve the exact leading Answer line required by the benchmark.
                # The model still supplies rationale and sources after the blank line.
                messages = result_messages
            else:
                messages = finalize_data_science_messages(
                    result_messages,
                    registry=registry,
                    callbacks=self.callbacks,
                    data_sources=state.data_sources,
                    available_tools=list(self.source_tool_names),
                )
        finally:
            summary = summarize_gsf_run()
            if summary and (summary["catalog_calls"] or summary["text_to_sql_calls"] or summary["cache_hits"]):
                logger.info("Data-science GSF call summary: %s", summary)
            end_gsf_run(gsf_run_token)
            await end_analysis_run(analysis_run_token)
            if registry_token is not None:
                reset_session_registry(registry_token)

        return state.model_copy(update={"messages": messages})

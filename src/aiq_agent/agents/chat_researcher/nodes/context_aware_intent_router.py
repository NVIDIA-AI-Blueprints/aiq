# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Context-aware entry routing with catalog discovery."""

import asyncio
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any
from typing import Literal
from typing import TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest
from langchain.agents.middleware import ModelResponse
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain.agents.middleware import wrap_model_call
from langchain.agents.structured_output import ToolStrategy
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages import BaseMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import ValidationError
from pydantic import model_validator

from aiq_agent.common import get_latest_user_query
from aiq_agent.common import render_prompt_template

from ..models import CatalogRoutingResponse
from ..models import ChatResearcherState
from ..models import DepthDecision
from ..models import IntentResult
from ..preclassification import get_preclassified_depth
from .intent_classifier import _route_to_fields

_RESEARCH_ROUTES = frozenset({"standalone_research", "hybrid_research"})


class RoutingProtocolError(RuntimeError):
    """The routing agent violated its catalog-call contract."""


class EntryDecision(BaseModel):
    """Model-owned interaction route and classic research depth."""

    model_config = ConfigDict(extra="forbid")

    route: Literal[
        "meta",
        "report_ask",
        "report_cosmetic_edit",
        "report_delta_research",
        "standalone_research",
        "hybrid_research",
    ]
    catalog_action: Literal["skip", "search"] | None
    meta_response: str | None
    research_depth: Literal["shallow", "deep"] | None
    route_reasoning: str | None

    @model_validator(mode="after")
    def validate_route_fields(self) -> "EntryDecision":
        if self.route == "meta" and not (self.meta_response and self.meta_response.strip()):
            raise ValueError("Meta routes require a response")
        if self.route == "standalone_research" and self.research_depth is None:
            raise ValueError("Standalone research requires a depth")
        if self.route != "meta" and self.meta_response is not None:
            raise ValueError("Research and report routes cannot return a meta response")
        if self.route == "hybrid_research" and self.research_depth is not None:
            raise ValueError("Hybrid research does not use classic research depth")
        if self.route in ("report_ask", "report_cosmetic_edit") and self.research_depth is not None:
            raise ValueError("Report ask and edit routes do not use research depth")
        if self.route == "report_delta_research" and self.research_depth != "deep":
            raise ValueError("Report delta research requires deep depth")
        if self.route in _RESEARCH_ROUTES and self.catalog_action is None:
            raise ValueError("New research routes require a catalog action")
        if self.route not in _RESEARCH_ROUTES and self.catalog_action is not None:
            raise ValueError("Meta and report routes do not use a catalog action")
        if self.route == "hybrid_research" and self.catalog_action != "search":
            raise ValueError("Hybrid research requires catalog search")
        return self


class RouterRunContext(TypedDict):
    active_report_available: bool
    catalog_confidence_threshold: float
    catalog_enabled: bool
    catalog_max_distance: float
    current_datetime: str
    max_catalog_results: int
    protocol_retry: Literal["none", "catalog_call_required", "catalog_disabled"]
    query: str
    user_info: dict[str, str]


def _prompt_middleware(prompt: str):
    @wrap_model_call
    async def render_router_prompt(
        request: ModelRequest[RouterRunContext],
        handler: Callable[[ModelRequest[RouterRunContext]], Any],
    ) -> ModelResponse:
        context = request.runtime.context
        system_prompt = render_prompt_template(prompt, **context)
        if context["protocol_retry"] == "catalog_call_required":
            system_prompt += (
                "\n\nThe previous attempt declared catalog_action=search without calling the catalog tool. "
                "Call it exactly once now. Do not reclassify the request as meta or report to avoid the call. "
                "Keep catalog_action=search and select the final standalone or hybrid route from the catalog result."
            )
        elif context["protocol_retry"] == "catalog_disabled":
            system_prompt += (
                "\n\nThe previous attempt selected catalog_action=search even though the catalog source is disabled. "
                "Correct the protocol now: return route=standalone_research and catalog_action=skip, preserve the "
                "classic research depth selected from the user request, and do not reclassify the request as meta or "
                "report. The catalog tool is unavailable for this request."
            )
        return await handler(request.override(system_message=SystemMessage(content=system_prompt)))

    return render_router_prompt


class ContextAwareIntentRouter:
    """Run entry classification and enforce the model's catalog applicability decision."""

    def __init__(
        self,
        llm: BaseChatModel,
        catalog_tool: BaseTool,
        prompt: str,
        *,
        catalog_source_id: str = "gsf",
        max_catalog_results: int = 10,
        catalog_confidence_threshold: float = 0.6,
        catalog_max_distance: float = 0.75,
        callbacks: list[BaseCallbackHandler] | None = None,
        llm_timeout: float = 90,
    ) -> None:
        self.catalog_tool_name = catalog_tool.name
        self.catalog_input_schema = catalog_tool.get_input_schema()
        self.catalog_source_id = catalog_source_id
        self.max_catalog_results = max_catalog_results
        self.catalog_confidence_threshold = catalog_confidence_threshold
        self.catalog_max_distance = catalog_max_distance
        self.callbacks = callbacks or []
        self.llm_timeout = llm_timeout
        self.agent = create_agent(
            model=llm,
            tools=[catalog_tool],
            response_format=ToolStrategy(EntryDecision),
            context_schema=RouterRunContext,
            middleware=[
                _prompt_middleware(prompt),
                ToolCallLimitMiddleware(tool_name=catalog_tool.name, run_limit=1, exit_behavior="error"),
            ],
        )
        self.no_catalog_agent = create_agent(
            model=llm,
            tools=[],
            response_format=ToolStrategy(EntryDecision),
            context_schema=RouterRunContext,
            middleware=[_prompt_middleware(prompt)],
        )

    async def run(self, state: ChatResearcherState) -> dict[str, Any]:
        if not state.messages:
            raise RoutingProtocolError("Routing requires a user message")

        query = get_latest_user_query(state.messages)
        catalog_enabled = state.data_sources is None or self.catalog_source_id in state.data_sources
        agent = self.agent if catalog_enabled else self.no_catalog_agent
        route_on_first_attempt: str | None = None
        catalog_action_on_first_attempt: str | None = None
        disabled_catalog_depth: str | None = None
        retry_reason: Literal["none", "catalog_call_required", "catalog_disabled"] = "none"
        async with asyncio.timeout(self.llm_timeout):
            for attempt in range(2):
                result = await agent.ainvoke(
                    {"messages": [HumanMessage(content=query)]},
                    config={"callbacks": self.callbacks} if self.callbacks else None,
                    context={
                        "active_report_available": bool(state.active_report_job_id or state.last_report_markdown),
                        "catalog_confidence_threshold": self.catalog_confidence_threshold,
                        "catalog_enabled": catalog_enabled,
                        "catalog_max_distance": self.catalog_max_distance,
                        "current_datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "max_catalog_results": self.max_catalog_results,
                        "protocol_retry": retry_reason,
                        "query": query,
                        "user_info": _router_user_info(state.user_info),
                    },
                )
                decision = EntryDecision.model_validate(result.get("structured_response"))
                decision = _normalize_report_route(decision, state)

                if not catalog_enabled:
                    catalog_required = decision.route in _RESEARCH_ROUTES and decision.catalog_action == "search"
                    if retry_reason == "catalog_disabled":
                        decision = _disabled_catalog_fallback(decision, disabled_catalog_depth)
                    elif catalog_required:
                        disabled_catalog_depth = get_preclassified_depth() or decision.research_depth
                        retry_reason = "catalog_disabled"
                        continue
                    return _build_state_update(
                        decision,
                        [],
                        state,
                        catalog_confidence_threshold=self.catalog_confidence_threshold,
                        max_catalog_results=self.max_catalog_results,
                    )

                if attempt == 0:
                    route_on_first_attempt = decision.route
                    catalog_action_on_first_attempt = decision.catalog_action
                elif route_on_first_attempt in _RESEARCH_ROUTES and decision.route not in _RESEARCH_ROUTES:
                    raise RoutingProtocolError("Protocol retry changed the request interaction route")
                elif catalog_action_on_first_attempt == "search" and decision.catalog_action != "search":
                    raise RoutingProtocolError("Protocol retry changed the required catalog action")

                exchanges = _catalog_exchanges(result.get("messages", []), self.catalog_tool_name)
                research_route = decision.route in _RESEARCH_ROUTES
                catalog_required = research_route and decision.catalog_action == "search"
                if catalog_required and not exchanges:
                    if attempt == 0:
                        retry_reason = "catalog_call_required"
                        continue
                    raise RoutingProtocolError("Required catalog search completed without catalog lookup")
                if catalog_required and exchanges:
                    _validate_catalog_call(
                        exchanges[0][0],
                        query=query,
                        input_schema=self.catalog_input_schema,
                        max_results=self.max_catalog_results,
                        max_distance=self.catalog_max_distance,
                    )
                return _build_state_update(
                    decision,
                    exchanges,
                    state,
                    catalog_confidence_threshold=self.catalog_confidence_threshold,
                    max_catalog_results=self.max_catalog_results,
                )

        raise AssertionError("Protocol retry loop exhausted")


def _router_user_info(user_info: dict[str, Any] | None) -> dict[str, str]:
    if not user_info or not isinstance(user_info.get("name"), str):
        return {}
    return {"name": user_info["name"]}


def _disabled_catalog_fallback(decision: EntryDecision, preserved_depth: str | None) -> EntryDecision:
    depth = get_preclassified_depth() or preserved_depth or decision.research_depth or "shallow"
    return decision.model_copy(
        update={
            "route": "standalone_research",
            "catalog_action": "skip",
            "meta_response": None,
            "research_depth": depth,
        }
    )


def _normalize_report_route(decision: EntryDecision, state: ChatResearcherState) -> EntryDecision:
    if state.active_report_job_id or state.last_report_markdown or not decision.route.startswith("report_"):
        return decision
    depth = "deep" if decision.route == "report_delta_research" else decision.research_depth or "shallow"
    return decision.model_copy(
        update={"route": "standalone_research", "catalog_action": "skip", "research_depth": depth}
    )


def _catalog_exchanges(messages: list[BaseMessage], tool_name: str) -> list[tuple[dict[str, Any], ToolMessage]]:
    calls: list[dict[str, Any]] = []
    results: dict[str, ToolMessage] = {}
    for message in messages:
        if isinstance(message, AIMessage):
            calls.extend(call for call in message.tool_calls if call.get("name") == tool_name)
        elif isinstance(message, ToolMessage) and message.name == tool_name:
            results[message.tool_call_id] = message

    if len(calls) > 1:
        raise RoutingProtocolError("Catalog tool was called more than once")
    if not calls:
        if results:
            raise RoutingProtocolError("Catalog result has no matching call")
        return []

    call = calls[0]
    result = results.get(call["id"])
    if result is None:
        raise RoutingProtocolError("Catalog call has no matching result")
    return [(call, result)]


def _catalog_response(message: ToolMessage) -> CatalogRoutingResponse:
    if message.status == "error":
        raise RoutingProtocolError("Catalog tool failed")
    payload = message.artifact if message.artifact is not None else message.content
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as error:
            raise RoutingProtocolError("Catalog tool returned invalid JSON") from error
    if isinstance(payload, dict) and payload.get("status") == "error":
        raise RoutingProtocolError("Catalog tool failed")
    try:
        return CatalogRoutingResponse.model_validate(payload)
    except ValidationError as error:
        raise RoutingProtocolError("Catalog tool returned an invalid response") from error


def _validate_catalog_call(
    call: dict[str, Any],
    *,
    query: str,
    input_schema: type[BaseModel],
    max_results: int,
    max_distance: float,
) -> None:
    args = call.get("args")
    if not isinstance(args, dict):
        raise RoutingProtocolError("Catalog call arguments are invalid")
    try:
        validated_args = input_schema.model_validate(args).model_dump()
    except ValidationError as error:
        raise RoutingProtocolError("Catalog call arguments are invalid") from error
    question = validated_args.get("question")
    if not isinstance(question, str) or not question.strip() or question not in query:
        raise RoutingProtocolError("Catalog question must be a non-empty verbatim span of the user query")
    if validated_args.get("max_results") != max_results or validated_args.get("max_distance") != max_distance:
        raise RoutingProtocolError("Catalog call changed the configured bounds")
    if validated_args.get("database_name") is not None:
        raise RoutingProtocolError("Catalog call supplied an unconfigured database scope")


def _build_state_update(
    decision: EntryDecision,
    exchanges: list[tuple[dict[str, Any], ToolMessage]],
    state: ChatResearcherState,
    *,
    catalog_confidence_threshold: float,
    max_catalog_results: int,
) -> dict[str, Any]:
    if decision.route not in _RESEARCH_ROUTES:
        if exchanges:
            raise RoutingProtocolError("Catalog tool is only allowed for research with catalog_action=search")
        if decision.route == "meta":
            return {
                "user_intent": IntentResult(intent="meta", target="meta"),
                "messages": [AIMessage(content=decision.meta_response or "I'm here to help.")],
            }
        target, report_action, use_parent, depth, reasoning = _route_to_fields(
            route=decision.route,
            active_report=bool(state.active_report_job_id or state.last_report_markdown),
            research_depth=decision.research_depth or "shallow",
            depth_reasoning=decision.route_reasoning or "",
        )
        update: dict[str, Any] = {
            "user_intent": IntentResult(
                intent="research",
                target=target,
                report_action=report_action,
                use_parent_report_context=use_parent,
            )
        }
        if target != "report":
            update["depth_decision"] = DepthDecision(decision=depth, raw_reasoning=reasoning)
        return update

    if decision.catalog_action == "skip":
        if exchanges:
            raise RoutingProtocolError("Catalog tool is not allowed when catalog_action=skip")
        depth = get_preclassified_depth() or decision.research_depth or "shallow"
        return {
            "user_intent": IntentResult(intent="research", target="new_research"),
            "depth_decision": DepthDecision(decision=depth, raw_reasoning=decision.route_reasoning),
        }
    if not exchanges:
        raise RoutingProtocolError("Required catalog search has no result")

    catalog = _catalog_response(exchanges[0][1])
    if len(catalog.candidates) > max_catalog_results:
        raise RoutingProtocolError("Catalog tool exceeded the configured result limit")
    supports_hybrid = catalog.coverage >= catalog_confidence_threshold
    if supports_hybrid and not catalog.candidates:
        raise RoutingProtocolError("Catalog confidence met the hybrid threshold without candidates")
    if decision.route == "standalone_research" and not supports_hybrid:
        depth = get_preclassified_depth() or decision.research_depth or "shallow"
        return {
            "user_intent": IntentResult(intent="research", target="new_research"),
            "depth_decision": DepthDecision(decision=depth, raw_reasoning=decision.route_reasoning),
        }
    if decision.route == "hybrid_research" and supports_hybrid:
        return {
            "user_intent": IntentResult(intent="research", target="hybrid_research"),
            "catalog_context": catalog,
            "catalog_request_id": catalog.request_id,
        }
    raise RoutingProtocolError("EntryDecision route does not match catalog coverage")

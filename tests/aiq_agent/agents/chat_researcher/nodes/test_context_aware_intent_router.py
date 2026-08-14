# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for catalog-aware entry routing."""

import json

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import ToolMessage
from langchain_core.outputs import ChatGeneration
from langchain_core.outputs import ChatResult
from langchain_core.tools import tool
from pydantic import BaseModel
from pydantic import ValidationError

from aiq_agent.agents.chat_researcher.models import ChatResearcherState
from aiq_agent.agents.chat_researcher.nodes.context_aware_intent_router import ContextAwareIntentRouter
from aiq_agent.agents.chat_researcher.nodes.context_aware_intent_router import EntryDecision
from aiq_agent.agents.chat_researcher.nodes.context_aware_intent_router import RoutingProtocolError
from aiq_agent.agents.chat_researcher.preclassification import preclassified_depth

CATALOG_TOOL = "gsf__catalog_search"
CATALOG_CANDIDATE = {
    "label": "ColumnAttribute",
    "attribute": "recognized_revenue",
    "term": "Revenue",
    "id": "attr:revenue",
}


class CatalogToolInput(BaseModel):
    question: str
    database_name: str | None = None
    max_results: int = 10
    max_distance: float = 0.75


def _decision(
    route,
    *,
    catalog_action=None,
    meta_response=None,
    research_depth=None,
    route_reasoning=None,
):
    if route in ("standalone_research", "hybrid_research") and catalog_action is None:
        catalog_action = "search"
    return EntryDecision(
        route=route,
        catalog_action=catalog_action,
        meta_response=meta_response,
        research_depth=research_depth,
        route_reasoning=route_reasoning,
    )


class FakeAgent:
    def __init__(self, results):
        self.results = iter(results)
        self.contexts = []

    async def ainvoke(self, inputs, *, config, context):
        self.contexts.append(context)
        return next(self.results)


class ScriptedModel(BaseChatModel):
    responses: list[AIMessage]
    calls: int = 0

    @property
    def _llm_type(self):
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        response = self.responses[self.calls]
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=response)])


def _catalog_messages(payload, question="query"):
    call = {
        "name": CATALOG_TOOL,
        "args": {"question": question, "max_results": 10, "max_distance": 0.75},
        "id": "catalog-1",
        "type": "tool_call",
    }
    return [
        AIMessage(content="", tool_calls=[call]),
        ToolMessage(content=json.dumps(payload), name=CATALOG_TOOL, tool_call_id="catalog-1"),
    ]


def _router(*results):
    router = ContextAwareIntentRouter.__new__(ContextAwareIntentRouter)
    router.agent = FakeAgent(results)
    router.catalog_tool_name = CATALOG_TOOL
    router.catalog_input_schema = CatalogToolInput
    router.catalog_source_id = "gsf"
    router.max_catalog_results = 10
    router.catalog_confidence_threshold = 0.6
    router.catalog_max_distance = 0.75
    router.callbacks = []
    router.llm_timeout = 5
    return router


def _state(query="query", **kwargs):
    return ChatResearcherState(messages=[HumanMessage(content=query)], **kwargs)


def test_entry_decision_tool_schema_requires_every_field():
    schema = EntryDecision.model_json_schema()

    assert set(schema["required"]) == {
        "route",
        "catalog_action",
        "meta_response",
        "research_depth",
        "route_reasoning",
    }
    with pytest.raises(ValidationError):
        EntryDecision.model_validate({"route": "meta"})


def test_entry_decision_enforces_catalog_action_by_route():
    with pytest.raises(ValidationError, match="require a catalog action"):
        EntryDecision(
            route="standalone_research",
            catalog_action=None,
            meta_response=None,
            research_depth="shallow",
            route_reasoning=None,
        )
    with pytest.raises(ValidationError, match="Hybrid research requires catalog search"):
        EntryDecision(
            route="hybrid_research",
            catalog_action="skip",
            meta_response=None,
            research_depth=None,
            route_reasoning=None,
        )
    with pytest.raises(ValidationError, match="do not use a catalog action"):
        EntryDecision(
            route="meta",
            catalog_action="skip",
            meta_response="Hello.",
            research_depth=None,
            route_reasoning=None,
        )


def test_router_builds_one_create_agent_with_catalog_tool(monkeypatch):
    captured = {}

    @tool
    def catalog_search(question: str) -> str:
        """Search the semantic catalog."""
        return question

    def fake_create_agent(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        "aiq_agent.agents.chat_researcher.nodes.context_aware_intent_router.create_agent",
        fake_create_agent,
    )

    router = ContextAwareIntentRouter(object(), catalog_search, "User query: {{ query }}")

    assert router.agent is not None
    assert captured["tools"] == [catalog_search]
    assert captured["context_schema"] is not None
    assert len(captured["middleware"]) == 2


@pytest.mark.asyncio
async def test_compiled_agent_executes_catalog_and_structured_output():
    @tool
    async def catalog(question: str, max_results: int, max_distance: float) -> str:
        """Search the semantic catalog."""
        return json.dumps(
            {
                "request_id": "request-compiled",
                "coverage": 0.5,
                "candidates": [],
            }
        )

    model = ScriptedModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "catalog",
                        "args": {"question": "Show revenue by region", "max_results": 10, "max_distance": 0.75},
                        "id": "catalog-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "EntryDecision",
                        "args": {
                            "route": "standalone_research",
                            "catalog_action": "search",
                            "meta_response": None,
                            "research_depth": "shallow",
                            "route_reasoning": None,
                        },
                        "id": "decision-1",
                        "type": "tool_call",
                    }
                ],
            ),
        ]
    )
    router = ContextAwareIntentRouter(model, catalog, "User query: {{ query }}")

    result = await router.run(_state("Show revenue by region"))

    assert result["user_intent"].target == "new_research"
    assert result["depth_decision"].decision == "shallow"


@pytest.mark.asyncio
async def test_compiled_agent_can_return_public_skip_without_catalog_call():
    @tool
    async def catalog(question: str, max_results: int, max_distance: float) -> str:
        """Search the semantic catalog."""
        raise AssertionError("Catalog must not execute for the public-web skip path")

    model = ScriptedModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "EntryDecision",
                        "args": {
                            "route": "standalone_research",
                            "catalog_action": "skip",
                            "meta_response": None,
                            "research_depth": "shallow",
                            "route_reasoning": "The request is a public-web fact.",
                        },
                        "id": "decision-1",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    )
    router = ContextAwareIntentRouter(model, catalog, "User query: {{ query }}")

    result = await router.run(_state("Who is the president of the USA?"))

    assert result["user_intent"].target == "new_research"
    assert result["depth_decision"].decision == "shallow"
    assert model.calls == 1


@pytest.mark.asyncio
async def test_meta_returns_directly_without_catalog():
    router = _router(
        {
            "structured_response": _decision(route="meta", meta_response="Hello."),
            "messages": [],
        }
    )

    result = await router.run(_state("Hello", user_info={"name": "Ada"}))

    assert result["user_intent"].target == "meta"
    assert result["messages"][0].content == "Hello."
    assert len(router.agent.contexts) == 1
    assert router.agent.contexts[0]["query"] == "Hello"
    assert router.agent.contexts[0]["user_info"] == {"name": "Ada"}
    assert router.agent.contexts[0]["current_datetime"]
    assert router.agent.contexts[0]["catalog_confidence_threshold"] == 0.6
    assert router.agent.contexts[0]["catalog_enabled"] is True
    assert router.agent.contexts[0]["catalog_max_distance"] == 0.75


@pytest.mark.asyncio
async def test_public_research_can_skip_catalog():
    router = _router(
        {
            "structured_response": _decision(
                route="standalone_research",
                catalog_action="skip",
                research_depth="shallow",
                route_reasoning="This is a public-web fact with no enterprise-data dimension.",
            ),
            "messages": [],
        }
    )

    result = await router.run(_state("Who is the president of the USA?", data_sources=["web_search", "gsf"]))

    assert result["user_intent"].target == "new_research"
    assert result["depth_decision"].decision == "shallow"
    assert len(router.agent.contexts) == 1
    assert router.agent.contexts[0]["catalog_enabled"] is True


@pytest.mark.asyncio
async def test_catalog_skip_rejects_an_unexpected_catalog_call():
    router = _router(
        {
            "structured_response": _decision(
                route="standalone_research",
                catalog_action="skip",
                research_depth="shallow",
            ),
            "messages": _catalog_messages({"coverage": 0.5, "candidates": []}),
        }
    )

    with pytest.raises(RoutingProtocolError, match="catalog_action=skip"):
        await router.run(_state())


@pytest.mark.asyncio
async def test_disabled_catalog_source_uses_skip_path_without_a_call():
    router = _router(
        {
            "structured_response": _decision(
                route="standalone_research",
                catalog_action="skip",
                research_depth="shallow",
            ),
            "messages": [],
        }
    )

    result = await router.run(_state(data_sources=["web_search"]))

    assert result["user_intent"].target == "new_research"
    assert router.agent.contexts[0]["catalog_enabled"] is False


@pytest.mark.asyncio
async def test_search_is_rejected_when_catalog_source_is_disabled():
    router = _router(
        {
            "structured_response": _decision(route="standalone_research", research_depth="shallow"),
            "messages": [],
        }
    )

    with pytest.raises(RoutingProtocolError, match="catalog source is disabled"):
        await router.run(_state(data_sources=["web_search"]))


@pytest.mark.parametrize("depth", ["shallow", "deep"])
@pytest.mark.asyncio
async def test_below_threshold_preserves_classic_depth(depth):
    router = _router(
        {
            "structured_response": _decision(route="standalone_research", research_depth=depth),
            "messages": _catalog_messages(
                {
                    "request_id": "request-1",
                    "coverage": 0.5,
                    "candidates": [],
                }
            ),
        }
    )

    result = await router.run(_state())

    assert result["user_intent"].target == "new_research"
    assert result["depth_decision"].decision == depth
    assert "catalog_context" not in result


@pytest.mark.asyncio
async def test_threshold_coverage_routes_to_hybrid_with_typed_context():
    router = _router(
        {
            "structured_response": _decision(route="hybrid_research"),
            "messages": _catalog_messages(
                {
                    "request_id": "request-2",
                    "coverage": 0.6,
                    "candidates": [CATALOG_CANDIDATE],
                },
                question="Show revenue by region",
            ),
        }
    )

    result = await router.run(_state("Show revenue by region"))

    assert result["user_intent"].target == "hybrid_research"
    assert result["catalog_request_id"] == "request-2"
    assert result["catalog_context"].candidates[0].id == "attr:revenue"


@pytest.mark.asyncio
async def test_missing_request_id_does_not_block_hybrid_routing():
    router = _router(
        {
            "structured_response": _decision(route="hybrid_research"),
            "messages": _catalog_messages(
                {
                    "coverage": 0.6,
                    "candidates": [CATALOG_CANDIDATE],
                    "uncovered_entities": None,
                    "truncated": False,
                }
            ),
        }
    )

    result = await router.run(_state())

    assert result["user_intent"].target == "hybrid_research"
    assert result["catalog_request_id"] is None


@pytest.mark.asyncio
async def test_at_threshold_rejects_standalone_route():
    router = _router(
        {
            "structured_response": _decision(route="standalone_research", research_depth="shallow"),
            "messages": _catalog_messages(
                {
                    "request_id": "request-full-mismatch",
                    "coverage": 0.6,
                    "candidates": [CATALOG_CANDIDATE],
                }
            ),
        }
    )

    with pytest.raises(RoutingProtocolError, match="does not match catalog coverage"):
        await router.run(_state())


@pytest.mark.asyncio
async def test_below_threshold_rejects_hybrid_route():
    router = _router(
        {
            "structured_response": _decision(route="hybrid_research"),
            "messages": _catalog_messages(
                {
                    "request_id": "request-none-mismatch",
                    "coverage": 0.59,
                    "candidates": [CATALOG_CANDIDATE],
                }
            ),
        }
    )

    with pytest.raises(RoutingProtocolError, match="does not match catalog coverage"):
        await router.run(_state())


@pytest.mark.asyncio
async def test_preclassified_depth_does_not_bypass_catalog():
    router = _router(
        {
            "structured_response": _decision(route="standalone_research", research_depth="shallow"),
            "messages": _catalog_messages(
                {
                    "request_id": "request-preclassified",
                    "coverage": 0.5,
                    "candidates": [],
                }
            ),
        }
    )

    with preclassified_depth("deep"):
        result = await router.run(_state())

    assert result["depth_decision"].decision == "deep"
    assert len(router.agent.contexts) == 1


@pytest.mark.asyncio
async def test_below_threshold_with_candidates_routes_to_classic():
    router = _router(
        {
            "structured_response": _decision(route="standalone_research", research_depth="shallow"),
            "messages": _catalog_messages(
                {
                    "request_id": "request-partial",
                    "coverage": 0.5,
                    "candidates": [CATALOG_CANDIDATE],
                }
            ),
        }
    )

    result = await router.run(_state())

    assert result["user_intent"].target == "new_research"


@pytest.mark.asyncio
async def test_at_threshold_without_candidates_is_rejected():
    router = _router(
        {
            "structured_response": _decision(route="hybrid_research"),
            "messages": _catalog_messages(
                {
                    "request_id": "request-no-candidates",
                    "coverage": 0.6,
                    "candidates": [],
                }
            ),
        }
    )

    with pytest.raises(RoutingProtocolError, match="without candidates"):
        await router.run(_state())


@pytest.mark.asyncio
async def test_serialized_catalog_error_is_rejected():
    router = _router(
        {
            "structured_response": _decision(route="standalone_research", research_depth="shallow"),
            "messages": _catalog_messages(
                {
                    "status": "error",
                    "code": "authentication_required",
                    "retryable": False,
                    "message": "GSF authentication is required.",
                }
            ),
        }
    )

    with pytest.raises(RoutingProtocolError, match="authentication_required"):
        await router.run(_state())


@pytest.mark.asyncio
async def test_malformed_catalog_response_is_rejected():
    messages = _catalog_messages({})
    messages[1] = ToolMessage(content="not-json", name=CATALOG_TOOL, tool_call_id="catalog-1")
    router = _router(
        {
            "structured_response": _decision(route="standalone_research", research_depth="shallow"),
            "messages": messages,
        }
    )

    with pytest.raises(RoutingProtocolError, match="invalid JSON"):
        await router.run(_state())


@pytest.mark.asyncio
async def test_missing_catalog_call_retries_same_agent_once():
    decision = _decision(route="standalone_research", research_depth="shallow")
    router = _router(
        {"structured_response": decision, "messages": []},
        {
            "structured_response": decision,
            "messages": _catalog_messages(
                {
                    "request_id": "request-3",
                    "coverage": 0.5,
                    "candidates": [],
                }
            ),
        },
    )

    await router.run(_state())

    assert [context["protocol_retry"] for context in router.agent.contexts] == [False, True]


@pytest.mark.asyncio
async def test_retry_can_select_hybrid_after_catalog_lookup():
    router = _router(
        {
            "structured_response": _decision(route="standalone_research", research_depth="shallow"),
            "messages": [],
        },
        {
            "structured_response": _decision(route="hybrid_research"),
            "messages": _catalog_messages(
                {
                    "request_id": "request-retry-hybrid",
                    "coverage": 0.9,
                    "candidates": [CATALOG_CANDIDATE],
                }
            ),
        },
    )

    result = await router.run(_state())

    assert result["user_intent"].target == "hybrid_research"


@pytest.mark.asyncio
async def test_second_missing_catalog_call_is_rejected():
    decision = _decision(route="standalone_research", research_depth="shallow")
    router = _router(
        {"structured_response": decision, "messages": []},
        {"structured_response": decision, "messages": []},
    )

    with pytest.raises(RoutingProtocolError, match="without catalog lookup"):
        await router.run(_state())


@pytest.mark.asyncio
async def test_retry_cannot_change_route():
    router = _router(
        {
            "structured_response": _decision(route="standalone_research", research_depth="shallow"),
            "messages": [],
        },
        {
            "structured_response": _decision(route="meta", meta_response="No."),
            "messages": [],
        },
    )

    with pytest.raises(RoutingProtocolError, match="changed the request interaction route"):
        await router.run(_state())


@pytest.mark.asyncio
async def test_retry_cannot_change_required_catalog_action():
    router = _router(
        {
            "structured_response": _decision(route="standalone_research", research_depth="shallow"),
            "messages": [],
        },
        {
            "structured_response": _decision(
                route="standalone_research",
                catalog_action="skip",
                research_depth="shallow",
            ),
            "messages": [],
        },
    )

    with pytest.raises(RoutingProtocolError, match="changed the required catalog action"):
        await router.run(_state())


@pytest.mark.asyncio
async def test_catalog_call_without_matching_result_is_rejected():
    call = {
        "name": CATALOG_TOOL,
        "args": {"question": "query"},
        "id": "catalog-1",
        "type": "tool_call",
    }
    router = _router(
        {
            "structured_response": _decision(route="standalone_research", research_depth="shallow"),
            "messages": [
                AIMessage(content="", tool_calls=[call]),
                ToolMessage(content="{}", name=CATALOG_TOOL, tool_call_id="different-id"),
            ],
        }
    )

    with pytest.raises(RoutingProtocolError, match="no matching result"):
        await router.run(_state())


@pytest.mark.asyncio
async def test_catalog_call_rejects_non_verbatim_question():
    messages = _catalog_messages(
        {
            "request_id": "request-5",
            "coverage": 0.5,
            "candidates": [],
        }
    )
    messages[0].tool_calls[0]["args"]["question"] = "different query"
    router = _router(
        {
            "structured_response": _decision(route="standalone_research", research_depth="shallow"),
            "messages": messages,
        }
    )

    with pytest.raises(RoutingProtocolError, match="verbatim span"):
        await router.run(_state())


@pytest.mark.asyncio
async def test_catalog_call_validates_schema_defaults_when_bounds_are_omitted():
    messages = _catalog_messages(
        {
            "request_id": "request-default-bounds",
            "coverage": 1.0,
            "candidates": [CATALOG_CANDIDATE],
        }
    )
    messages[0].tool_calls[0]["args"] = {"question": "query"}
    router = _router(
        {
            "structured_response": _decision(route="hybrid_research"),
            "messages": messages,
        }
    )

    result = await router.run(_state())

    assert result["user_intent"].target == "hybrid_research"


@pytest.mark.asyncio
async def test_omitted_bounds_are_rejected_when_tool_defaults_do_not_match_router_config():
    messages = _catalog_messages(
        {
            "request_id": "request-mismatched-default-bounds",
            "coverage": 1.0,
            "candidates": [CATALOG_CANDIDATE],
        }
    )
    messages[0].tool_calls[0]["args"] = {"question": "query"}
    router = _router(
        {
            "structured_response": _decision(route="hybrid_research"),
            "messages": messages,
        }
    )
    router.max_catalog_results = 5

    with pytest.raises(RoutingProtocolError, match="configured bounds"):
        await router.run(_state())


@pytest.mark.asyncio
async def test_mixed_request_uses_verbatim_enterprise_span_for_catalog_coverage():
    query = (
        "What is the total Sales Amount across all Order records, "
        "and what broad external economic factors commonly influence business sales performance?"
    )
    enterprise_question = "What is the total Sales Amount across all Order records"
    router = _router(
        {
            "structured_response": _decision(route="hybrid_research"),
            "messages": _catalog_messages(
                {
                    "request_id": "request-mixed",
                    "coverage": 0.8,
                    "candidates": [CATALOG_CANDIDATE],
                },
                question=enterprise_question,
            ),
        }
    )

    result = await router.run(_state(query))

    assert result["user_intent"].target == "hybrid_research"
    assert result["catalog_context"].coverage == 0.8
    assert router.agent.contexts[0]["query"] == query


@pytest.mark.asyncio
async def test_catalog_question_cannot_paraphrase_enterprise_clause():
    query = "Calculate recognized sales from internal order records and explain public demand trends"
    paraphrase = "Sum Sales Amount across Order records"
    router = _router(
        {
            "structured_response": _decision(route="hybrid_research"),
            "messages": _catalog_messages(
                {
                    "request_id": "request-paraphrased",
                    "coverage": 0.8,
                    "candidates": [CATALOG_CANDIDATE],
                },
                question=paraphrase,
            ),
        }
    )

    with pytest.raises(RoutingProtocolError, match="verbatim span"):
        await router.run(_state(query))


@pytest.mark.asyncio
async def test_catalog_call_cannot_supply_database_scope():
    messages = _catalog_messages(
        {
            "request_id": "request-database-scope",
            "coverage": 0.5,
            "candidates": [],
        }
    )
    messages[0].tool_calls[0]["args"]["database_name"] = "unconfigured"
    router = _router(
        {
            "structured_response": _decision(route="standalone_research", research_depth="shallow"),
            "messages": messages,
        }
    )

    with pytest.raises(RoutingProtocolError, match="database scope"):
        await router.run(_state())


@pytest.mark.asyncio
async def test_duplicate_catalog_calls_are_rejected():
    calls = [
        {"name": CATALOG_TOOL, "args": {"question": "query"}, "id": call_id, "type": "tool_call"}
        for call_id in ("catalog-1", "catalog-2")
    ]
    router = _router(
        {
            "structured_response": _decision(route="standalone_research", research_depth="shallow"),
            "messages": [AIMessage(content="", tool_calls=calls)],
        }
    )

    with pytest.raises(RoutingProtocolError, match="more than once"):
        await router.run(_state())


@pytest.mark.asyncio
async def test_catalog_call_is_rejected_for_meta_route():
    router = _router(
        {
            "structured_response": _decision(route="meta", meta_response="Hello."),
            "messages": _catalog_messages(
                {
                    "request_id": "request-4",
                    "coverage": 0.5,
                    "candidates": [],
                }
            ),
        }
    )

    with pytest.raises(RoutingProtocolError, match="only allowed"):
        await router.run(_state("Hello"))


@pytest.mark.asyncio
async def test_report_delta_rejects_catalog_call():
    decision = _decision(route="report_delta_research", research_depth="deep")
    router = _router(
        {
            "structured_response": decision,
            "messages": _catalog_messages(
                {
                    "request_id": "request-delta",
                    "coverage": 0.5,
                    "candidates": [],
                }
            ),
        }
    )

    with pytest.raises(RoutingProtocolError, match="only allowed"):
        await router.run(_state(active_report_job_id="report-1"))


@pytest.mark.asyncio
async def test_report_delta_preserves_route_without_catalog():
    router = _router(
        {
            "structured_response": _decision(route="report_delta_research", research_depth="deep"),
            "messages": [],
        }
    )

    result = await router.run(_state(active_report_job_id="report-1"))

    assert result["user_intent"].target == "new_research"
    assert result["user_intent"].use_parent_report_context is True
    assert result["depth_decision"].decision == "deep"


@pytest.mark.asyncio
async def test_report_route_does_not_call_catalog():
    router = _router(
        {
            "structured_response": _decision(route="report_ask"),
            "messages": [],
        }
    )

    result = await router.run(_state(active_report_job_id="report-1"))

    assert result["user_intent"].target == "report"
    assert result["user_intent"].report_action == "ask"


@pytest.mark.asyncio
async def test_report_route_without_active_report_normalizes_to_catalog_skip():
    router = _router(
        {
            "structured_response": _decision(route="report_ask"),
            "messages": [],
        }
    )

    result = await router.run(_state())

    assert result["user_intent"].target == "new_research"
    assert [context["protocol_retry"] for context in router.agent.contexts] == [False]

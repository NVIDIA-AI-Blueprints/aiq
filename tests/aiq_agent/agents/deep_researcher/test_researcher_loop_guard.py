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

"""Tests for the per-researcher loop guard: middleware, wiring, prompts, and config."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import ToolRetryMiddleware
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from pydantic import ValidationError

from aiq_agent.agents.deep_researcher import register as register_module
from aiq_agent.agents.deep_researcher import resource_limits
from aiq_agent.agents.deep_researcher.custom_middleware import ResearcherLoopGuardMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import SourceRegistryMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import StructuredResponseTextFallbackMiddleware
from aiq_agent.agents.deep_researcher.custom_middleware import _canonical_source_signature
from aiq_agent.agents.deep_researcher.factory import build_deep_research_middleware_set
from aiq_agent.agents.deep_researcher.factory import build_deep_research_tool_set
from aiq_agent.agents.deep_researcher.models import ResearcherLoopGuardConfig
from aiq_agent.agents.deep_researcher.models import ResearchNotes
from aiq_agent.agents.deep_researcher.models import loop_guard as loop_guard_module
from aiq_agent.agents.deep_researcher.researcher_context import CURRENT_RESEARCHER_GUARD_STATE
from aiq_agent.agents.deep_researcher.researcher_context import ResearcherRunGuardState
from aiq_agent.agents.deep_researcher.tools import research as research_module
from aiq_agent.common import render_prompt_template

_SOURCE_TOOL = "web_search_tool"
_SOURCE_TOOLS = {_SOURCE_TOOL, "internal_search_tool"}
_RESEARCHER_PROMPT = (
    Path(__file__).parents[4] / "src" / "aiq_agent" / "agents" / "deep_researcher" / "prompts" / "researcher.j2"
).read_text(encoding="utf-8")


@tool
def web_search_tool(query: str) -> str:
    """Search the web for information."""
    return f"Results for: {query}"


class _ProviderStrategyFakeChatModel(FakeMessagesListChatModel):
    """Provider-capable model that rejects the invalid empty-tools request shape."""

    profile: dict[str, bool] = {"structured_output": True}

    def bind_tools(self, tools, **kwargs):
        if not tools and kwargs.get("response_format") is not None:
            raise ValueError("provider does not accept an empty tools array")
        return self


def _guard(**overrides) -> ResearcherLoopGuardMiddleware:
    """Build a guard over the fixed source-tool set with optional config overrides."""
    return ResearcherLoopGuardMiddleware(
        source_tool_names=_SOURCE_TOOLS,
        config=ResearcherLoopGuardConfig(**overrides),
    )


def _request(tool_name: str, *, args: dict | None = None) -> MagicMock:
    """Build a minimal tool-call request the guard can read."""
    request = MagicMock()
    request.tool_call = {"name": tool_name, "args": args or {}, "id": "tc1"}
    return request


def _handler(content: str = "search results") -> AsyncMock:
    """Build a handler returning a mutable ToolMessage result."""
    return AsyncMock(return_value=ToolMessage(content=content, tool_call_id="tc1"))


@pytest.fixture
def state():
    """Install a fresh guard state for one invocation and tear it down afterwards."""
    guard_state = ResearcherRunGuardState(invocation_id="inv-1")
    token = CURRENT_RESEARCHER_GUARD_STATE.set(guard_state)
    yield guard_state
    CURRENT_RESEARCHER_GUARD_STATE.reset(token)


class TestSourceCallBudget:
    """The flat per-query source-call ceiling and what happens when it is reached."""

    @pytest.mark.asyncio
    async def test_configured_budget_is_enforced_and_the_next_call_is_not_executed(self, state):
        """The budget allows exactly N calls; the (N+1)th is blocked without reaching the tool."""
        middleware = _guard(
            max_source_calls_per_query=3, max_identical_source_calls=loop_guard_module.IDENTICAL_SOURCE_CALLS_CEILING
        )
        handler = _handler()

        for i in range(3):
            await middleware.awrap_tool_call(_request(_SOURCE_TOOL, args={"query": f"q{i}"}), handler)
        assert handler.await_count == 3

        blocked = await middleware.awrap_tool_call(_request(_SOURCE_TOOL, args={"query": "q4"}), handler)

        assert handler.await_count == 3
        assert blocked.status == "error"
        assert "budget is exhausted" in str(blocked.content)
        assert state.exhaustion_reason == "total source-call budget"

    @pytest.mark.asyncio
    async def test_every_query_receives_the_same_limit(self):
        """One flat limit applies identically to every ResearchQuery - there is no depth hint."""
        middleware = _guard(
            max_source_calls_per_query=2, max_identical_source_calls=loop_guard_module.IDENTICAL_SOURCE_CALLS_CEILING
        )
        executed = []

        for invocation_id, query in (("inv-a", "quantum error correction"), ("inv-b", "weather")):
            token = CURRENT_RESEARCHER_GUARD_STATE.set(ResearcherRunGuardState(invocation_id=invocation_id))
            handler = _handler()
            try:
                for i in range(4):
                    await middleware.awrap_tool_call(_request(_SOURCE_TOOL, args={"q": f"{query}{i}"}), handler)
            finally:
                CURRENT_RESEARCHER_GUARD_STATE.reset(token)
            executed.append(handler.await_count)

        assert executed == [2, 2]

    @pytest.mark.asyncio
    async def test_exhaustion_appends_the_nudge_and_preserves_the_final_evidence(self, state):
        """The last allowed result survives; the exhaustion notice is appended, never substituted."""
        middleware = _guard(max_source_calls_per_query=1)

        result = await middleware.awrap_tool_call(_request(_SOURCE_TOOL, args={"q": "a"}), _handler("real evidence"))

        assert "real evidence" in str(result.content)
        assert "budget is exhausted" in str(result.content)
        assert state.exhausted is True

    @pytest.mark.asyncio
    async def test_an_immutable_result_still_exhausts_the_budget(self, state):
        """The nudge is best-effort; withdrawing the tools is the hard guarantee."""
        middleware = _guard(max_source_calls_per_query=1)
        handler = AsyncMock(return_value="plain string result")

        result = await middleware.awrap_tool_call(_request(_SOURCE_TOOL, args={"q": "a"}), handler)

        assert result == "plain string result"
        assert state.exhausted is True

    @pytest.mark.asyncio
    async def test_parallel_calls_share_one_ceiling(self, state):
        """Counting before dispatch stops concurrent calls from all passing the same check."""
        middleware = _guard(max_source_calls_per_query=1)
        handler = _handler()

        await asyncio.gather(
            middleware.awrap_tool_call(_request(_SOURCE_TOOL, args={"q": "a"}), handler),
            middleware.awrap_tool_call(_request(_SOURCE_TOOL, args={"q": "b"}), handler),
        )

        assert handler.await_count == 1

    @pytest.mark.asyncio
    async def test_concurrent_invocations_do_not_see_each_other_counts(self):
        """Each researcher worker gets its own budget because state lives in a ContextVar."""
        middleware = _guard(
            max_source_calls_per_query=2, max_identical_source_calls=loop_guard_module.IDENTICAL_SOURCE_CALLS_CEILING
        )

        async def run_worker(invocation_id: str) -> int:
            CURRENT_RESEARCHER_GUARD_STATE.set(ResearcherRunGuardState(invocation_id=invocation_id))
            handler = _handler()
            for i in range(3):
                await middleware.awrap_tool_call(_request(_SOURCE_TOOL, args={"q": f"{invocation_id}{i}"}), handler)
            return handler.await_count

        # asyncio.Task copies the context, so each worker's .set() is invisible to the other.
        counts = await asyncio.gather(
            asyncio.create_task(run_worker("inv-a")),
            asyncio.create_task(run_worker("inv-b")),
        )

        assert counts == [2, 2]

    @pytest.mark.asyncio
    async def test_non_source_tools_are_never_counted(self, state):
        """Helper and filesystem tools do not consume the research budget."""
        middleware = _guard(max_source_calls_per_query=1)
        handler = _handler()

        for name in ("get_verified_sources", "read_file", "ls", "grep"):
            await middleware.awrap_tool_call(_request(name), handler)

        assert handler.await_count == 4
        assert state.source_call_count == 0
        assert state.exhausted is False


class TestIdenticalRequestBlocking:
    """Repeats of the same tool name plus the same arguments are refused."""

    @pytest.mark.asyncio
    async def test_the_third_identical_request_is_blocked(self, state):
        """Two identical attempts are allowed; the third is not executed."""
        middleware = _guard(max_identical_source_calls=2)
        handler = _handler()
        args = {"query": "same question"}

        for _ in range(2):
            await middleware.awrap_tool_call(_request(_SOURCE_TOOL, args=args), handler)
        blocked = await middleware.awrap_tool_call(_request(_SOURCE_TOOL, args=args), handler)

        assert handler.await_count == 2
        assert blocked.status == "error"
        assert state.exhaustion_reason == "repeated source-call signature"

    @pytest.mark.asyncio
    async def test_alternating_think_and_same_search_terminates(self, state):
        """The think->same_search loop is caught by the signature rule, not the think rule."""
        middleware = _guard(
            max_identical_source_calls=2, max_consecutive_thinks=loop_guard_module.CONSECUTIVE_THINKS_CEILING
        )
        handler = _handler()
        args = {"query": "same question"}

        for _ in range(3):
            await middleware.awrap_tool_call(_request("think", args={"thought": "hmm"}), handler)
            await middleware.awrap_tool_call(_request(_SOURCE_TOOL, args=args), handler)

        assert state.exhausted is True
        assert state.exhaustion_reason == "repeated source-call signature"

    def test_signature_is_stable_across_key_order_and_distinct_for_distinct_args(self):
        """Argument key order is canonicalized; different arguments do not collide."""
        assert _canonical_source_signature(_SOURCE_TOOL, {"a": 1, "b": 2}) == _canonical_source_signature(
            _SOURCE_TOOL, {"b": 2, "a": 1}
        )
        assert _canonical_source_signature(_SOURCE_TOOL, {"q": "x"}) != _canonical_source_signature(
            _SOURCE_TOOL, {"q": "y"}
        )

    def test_case_differences_are_distinct_requests(self):
        """Only key order is canonicalized - case and whitespace are not."""
        assert _canonical_source_signature(_SOURCE_TOOL, {"q": "AI research"}) != _canonical_source_signature(
            _SOURCE_TOOL, {"q": "ai research"}
        )


class TestConsecutiveThinkBlocking:
    """Uninterrupted think calls are warned about and then withdrawn."""

    @pytest.mark.asyncio
    async def test_below_the_threshold_the_result_is_unmodified(self, state):
        """Normal thinking passes through untouched."""
        middleware = _guard(max_consecutive_thinks=3)
        handler = _handler("Thought recorded.")

        result = await middleware.awrap_tool_call(_request("think", args={"thought": "a"}), handler)

        assert str(result.content) == "Thought recorded."
        assert state.think_blocked is False

    @pytest.mark.asyncio
    async def test_at_the_threshold_the_result_is_overwritten_and_think_is_blocked(self, state):
        """A think result carries no evidence, so the warning replaces it rather than appending."""
        middleware = _guard(max_consecutive_thinks=3)
        handler = _handler("Thought recorded.")

        for _ in range(3):
            result = await middleware.awrap_tool_call(_request("think", args={"thought": "a"}), handler)

        # Thinking is never blocked - only warned about and then withdrawn.
        assert handler.await_count == 3
        assert str(result.content).startswith("Thought recorded. WARNING:")
        assert "called 'think' 3 times in a row" in str(result.content)
        assert state.think_blocked is True

    @pytest.mark.asyncio
    async def test_an_immutable_think_result_does_not_raise(self, state):
        """The corrective warning is best-effort."""
        middleware = _guard(max_consecutive_thinks=1)
        handler = AsyncMock(return_value="plain string result")

        result = await middleware.awrap_tool_call(_request("think", args={"thought": "a"}), handler)

        assert result == "plain string result"
        assert state.think_blocked is True

    @pytest.mark.asyncio
    async def test_any_other_tool_resets_the_streak(self, state):
        """Only uninterrupted think calls count toward the limit."""
        middleware = _guard(max_consecutive_thinks=3)
        handler = _handler()

        await middleware.awrap_tool_call(_request("think"), handler)
        await middleware.awrap_tool_call(_request("think"), handler)
        assert state.consecutive_think_count == 2

        await middleware.awrap_tool_call(_request("read_file", args={"file_path": "/shared/plan.json"}), handler)

        assert state.consecutive_think_count == 0
        assert state.think_blocked is False

    @pytest.mark.asyncio
    async def test_any_other_tool_reenables_think_after_the_threshold(self, state):
        """A completed think streak does not withdraw think for the rest of the invocation."""
        middleware = _guard(max_consecutive_thinks=2)
        handler = _handler()

        await middleware.awrap_tool_call(_request("think"), handler)
        await middleware.awrap_tool_call(_request("think"), handler)
        assert state.think_blocked is True

        await middleware.awrap_tool_call(_request("read_file", args={"file_path": "/shared/plan.json"}), handler)

        assert state.consecutive_think_count == 0
        assert state.think_blocked is False
        assert "think" in {tool.name for tool in middleware._filter_tools(TestToolWithdrawal._tools())}


class TestToolWithdrawal:
    """What `_filter_tools` removes from later model calls in each state."""

    @staticmethod
    def _tools() -> list[SimpleNamespace]:
        return [
            SimpleNamespace(name=_SOURCE_TOOL),
            SimpleNamespace(name="internal_search_tool"),
            SimpleNamespace(name="think"),
            SimpleNamespace(name="get_verified_sources"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="ls"),
        ]

    def test_exhaustion_withdraws_source_tools_and_think(self, state):
        """An exhausted worker physically cannot search or think again."""
        state.exhausted = True

        names = {t.name for t in _guard()._filter_tools(self._tools())}

        assert names == {"get_verified_sources", "read_file", "ls"}

    def test_think_blocking_alone_withdraws_only_think(self, state):
        """A pure think loop costs the model its scratchpad, not its search tools."""
        state.think_blocked = True

        names = {t.name for t in _guard()._filter_tools(self._tools())}

        assert "think" not in names
        assert _SOURCE_TOOL in names

    def test_a_healthy_invocation_keeps_every_tool(self, state):
        """Nothing is withdrawn before a limit is reached."""
        tools = self._tools()

        assert _guard()._filter_tools(tools) is tools

    def test_filesystem_tools_survive_exhaustion(self, state):
        """Exhaustion ends searching, not reading: /shared context stays reachable.

        This is why the source-call limits alone cannot bound the worker -
        `max_model_turns_per_query` is what closes the loop. See TestTurnCeiling.
        """
        state.exhausted = True

        names = {t.name for t in _guard()._filter_tools(self._tools())}

        assert {"read_file", "ls"} <= names

    def test_no_state_installed_is_a_pass_through(self):
        """Planner, writer, and orchestrator never install guard state, so nothing is withdrawn."""
        tools = self._tools()

        assert _guard()._filter_tools(tools) is tools


class TestTurnCeiling:
    """`max_model_turns_per_query` bounds total turns, not just the searching ones."""

    @staticmethod
    def _model_request() -> MagicMock:
        """Build a model request whose `override` records the kwargs it was given."""
        request = MagicMock()
        request.tools = [SimpleNamespace(name=_SOURCE_TOOL), SimpleNamespace(name="read_file")]
        request.override.side_effect = lambda **kwargs: SimpleNamespace(**kwargs)
        return request

    async def _turn(self, middleware, request=None):
        """Take one model turn and return whatever was handed to the model."""
        seen = {}

        async def handler(passed):
            seen["request"] = passed
            return "response"

        await middleware.awrap_model_call(request or self._model_request(), handler)
        return seen["request"]

    @pytest.mark.asyncio
    async def test_every_model_call_counts_as_one_turn(self, state):
        """Turns are counted at the model call, so non-source turns count too."""
        middleware = _guard(max_model_turns_per_query=10)

        for _ in range(4):
            await self._turn(middleware)

        assert state.model_turn_count == 4

    @pytest.mark.asyncio
    async def test_below_the_ceiling_the_tool_list_is_untouched(self, state):
        """A healthy worker sees exactly the tools it was bound with."""
        middleware = _guard(max_model_turns_per_query=10)
        request = self._model_request()

        passed = await self._turn(middleware, request)

        assert passed.tools is request.tools

    @pytest.mark.asyncio
    async def test_the_final_turn_withdraws_every_tool(self, state):
        """The final request has no tools or provider-native response format."""
        middleware = _guard(max_model_turns_per_query=3)

        for _ in range(2):
            passed = await self._turn(middleware)
            assert passed.tools

        passed = await self._turn(middleware)

        assert passed.tools == []
        assert passed.tool_choice is None
        assert passed.response_format is None

    def test_the_final_turn_returns_notes_with_a_provider_strategy_model(self, state):
        """The final turn omits tools and lets the text fallback recover ResearchNotes."""
        payload = _notes()
        model = _ProviderStrategyFakeChatModel(responses=[AIMessage(content=json.dumps(payload))])
        agent = create_agent(
            model=model,
            tools=[web_search_tool],
            middleware=[
                StructuredResponseTextFallbackMiddleware(ResearchNotes),
                _guard(max_model_turns_per_query=1),
            ],
            response_format=ResearchNotes,
        )

        result = agent.invoke({"messages": [HumanMessage(content="Return the research notes.")]})

        assert result["structured_response"] == ResearchNotes.model_validate(payload)

    @pytest.mark.asyncio
    async def test_the_ceiling_holds_for_a_worker_that_never_searched(self, state):
        """The turn ceiling is independent of the source budget, which is the point of it.

        An exhausted worker looping on `ls` / `read_file` consumes no source budget, so only
        this limit can stop it before the recursion ceiling does.
        """
        middleware = _guard(max_model_turns_per_query=2)
        state.exhausted = True

        await self._turn(middleware)
        passed = await self._turn(middleware)

        assert passed.tools == []
        assert state.source_call_count == 0

    @pytest.mark.asyncio
    async def test_a_disabled_guard_neither_counts_nor_withdraws(self, state):
        """`enabled: false` opts out of the turn ceiling with everything else."""
        middleware = _guard(enabled=False, max_model_turns_per_query=1)
        request = self._model_request()

        passed = await self._turn(middleware, request)

        assert passed is request
        assert state.model_turn_count == 0

    @pytest.mark.asyncio
    async def test_no_state_installed_is_a_pass_through(self):
        """Agents that install no guard state keep their tools at every turn."""
        middleware = _guard(max_model_turns_per_query=1)
        request = self._model_request()

        assert await self._turn(middleware, request) is request


class TestDisabled:
    """`enabled: false` switches off the complete circuit breaker, one test per path."""

    @pytest.mark.asyncio
    async def test_the_source_budget_is_not_enforced(self, state):
        middleware = _guard(
            enabled=False,
            max_source_calls_per_query=1,
            max_identical_source_calls=loop_guard_module.IDENTICAL_SOURCE_CALLS_CEILING,
        )
        handler = _handler()

        for i in range(5):
            await middleware.awrap_tool_call(_request(_SOURCE_TOOL, args={"q": f"q{i}"}), handler)

        assert handler.await_count == 5
        assert state.source_call_count == 0
        assert state.exhausted is False

    @pytest.mark.asyncio
    async def test_identical_requests_are_not_blocked(self, state):
        middleware = _guard(enabled=False, max_identical_source_calls=1)
        handler = _handler()

        for _ in range(4):
            await middleware.awrap_tool_call(_request(_SOURCE_TOOL, args={"q": "same"}), handler)

        assert handler.await_count == 4
        assert state.exhausted is False

    @pytest.mark.asyncio
    async def test_no_think_warning_is_injected(self, state):
        """Regression test for the bug the merged design fixes: a disabled guard stays silent."""
        middleware = _guard(enabled=False, max_consecutive_thinks=1)
        handler = _handler("Thought recorded.")

        for _ in range(4):
            result = await middleware.awrap_tool_call(_request("think"), handler)

        assert str(result.content) == "Thought recorded."
        assert state.think_blocked is False

    def test_no_tool_is_withdrawn_even_when_marked_exhausted(self, state):
        state.exhausted = True
        tools = TestToolWithdrawal._tools()

        assert _guard(enabled=False)._filter_tools(tools) is tools


class TestFactoryWiring:
    """Where the guard is attached and how the researcher subgraph is bounded."""

    @staticmethod
    def _middleware_set(**overrides):
        registry = SourceRegistryMiddleware(source_tool_names={web_search_tool.name})
        tool_set = build_deep_research_tool_set(
            [web_search_tool],
            source_registry_middleware=registry,
            max_concurrent_source_tool_calls=2,
            max_source_tool_batch_size=3,
        )
        return build_deep_research_middleware_set(
            tool_set=tool_set,
            source_registry_middleware=registry,
            **overrides,
        )

    def test_the_guard_sits_before_tool_retry_in_the_researcher_stack(self):
        """Outside the retry, so a retried transient failure costs one unit and not three."""
        researcher = self._middleware_set().researcher
        guard_index = next(i for i, m in enumerate(researcher) if isinstance(m, ResearcherLoopGuardMiddleware))
        retry_index = next(i for i, m in enumerate(researcher) if isinstance(m, ToolRetryMiddleware))

        assert guard_index < retry_index

    def test_the_guard_is_attached_to_no_other_stack(self):
        """Planner, writer, and orchestrator get no think or source guard in this iteration."""
        middleware_set = self._middleware_set()

        for stack in (middleware_set.planner, middleware_set.writer, middleware_set.orchestrator):
            assert not any(isinstance(m, ResearcherLoopGuardMiddleware) for m in stack)

    def test_the_configured_limits_reach_the_middleware(self):
        """A config set on the agent is the one the guard enforces."""
        config = ResearcherLoopGuardConfig(max_source_calls_per_query=4)
        researcher = self._middleware_set(researcher_loop_guard=config).researcher

        guard = next(m for m in researcher if isinstance(m, ResearcherLoopGuardMiddleware))

        assert guard._config is config


class TestResearcherInvokeConfig:
    """The researcher subgraph binds no limit of its own and must inherit the orchestrator's."""

    def test_the_inherited_recursion_limit_is_preserved(self):
        """Dropping it would not leave the subgraph unbounded - it would silently fall to
        LangGraph's own default, a far tighter ceiling than the orchestrator's."""
        runtime = SimpleNamespace(config={"recursion_limit": 2000, "run_id": "r", "configurable": {}})

        config = research_module.researcher_invoke_config(runtime, [])

        assert config["recursion_limit"] == 2000
        # The keys that genuinely must not be shared with the parent run are still dropped.
        assert "run_id" not in config
        assert "configurable" not in config


class TestInvocationScoping:
    """`_run_research_query` owns the guard state's lifetime."""

    @pytest.mark.asyncio
    async def test_a_fresh_state_is_installed_and_reset_on_success(self):
        """Each admitted worker gets its own budget, and none survives the invocation."""
        seen = []

        async def capture(*_args, **_kwargs):
            state = CURRENT_RESEARCHER_GUARD_STATE.get()
            seen.append(state.invocation_id)
            return {"structured_response": _notes()}

        runnable = SimpleNamespace(ainvoke=capture)
        for _ in range(2):
            await research_module._run_research_query(
                query=_query(),
                researcher_runnable=runnable,
                runtime=None,
                callbacks=[],
                semaphore=asyncio.Semaphore(1),
            )

        assert len(set(seen)) == 2
        assert CURRENT_RESEARCHER_GUARD_STATE.get() is None

    @pytest.mark.asyncio
    async def test_the_state_is_reset_on_the_exception_path(self):
        """A failed worker must not leak its guard state to whatever runs next."""
        runnable = SimpleNamespace(ainvoke=AsyncMock(side_effect=RuntimeError("provider down")))

        with pytest.raises(RuntimeError):
            await research_module._run_research_query(
                query=_query(),
                researcher_runnable=runnable,
                runtime=None,
                callbacks=[],
                semaphore=asyncio.Semaphore(1),
            )

        assert CURRENT_RESEARCHER_GUARD_STATE.get() is None

    @pytest.mark.asyncio
    async def test_the_state_is_built_without_reading_the_research_query(self):
        """Structural guarantee that iteration 1 leaves the ResearchQuery schema alone.

        A depth hint would have to be read off the query here. Nothing is, which is why
        `ResearchQuery` is untouched by this change.
        """
        runnable = SimpleNamespace(ainvoke=AsyncMock(return_value={"structured_response": _notes()}))

        with patch.object(
            research_module,
            "ResearcherRunGuardState",
            wraps=ResearcherRunGuardState,
        ) as build_state:
            await research_module._run_research_query(
                query=_query(),
                researcher_runnable=runnable,
                runtime=None,
                callbacks=[],
                semaphore=asyncio.Semaphore(1),
            )

        assert set(build_state.call_args.kwargs) == {"invocation_id"}
        assert not build_state.call_args.args


class TestPromptRendering:
    """The researcher prompt must stay StrictUndefined-safe and keep today's guidance."""

    _SOFT_GUIDANCE = "Default source budget per ResearchQuery"
    _HARD_CEILING = "Hard limit (runtime-enforced)"
    _WITHDRAWAL = "When source tools are withdrawn, research is over"

    @staticmethod
    def _render(**values) -> str:
        return render_prompt_template(
            _RESEARCHER_PROMPT,
            current_datetime="2026-08-10",
            user_info=None,
            available_documents=[],
            execution_enabled=False,
            tools=[{"name": "web_search_tool", "description": "search"}],
            **values,
        )

    def test_it_renders_when_the_new_variables_are_absent(self):
        """`| default(false)` is mandatory: StrictUndefined would raise on a bare `{% if %}`."""
        rendered = self._render()

        assert self._SOFT_GUIDANCE in rendered
        assert self._HARD_CEILING not in rendered

    def test_disabled_mode_retains_todays_guidance_only(self):
        """Turning the guard off must restore exactly today's prompt."""
        rendered = self._render(
            researcher_loop_guard_enabled=False,
            researcher_max_source_calls=10,
            researcher_max_identical_source_calls=2,
        )

        assert self._SOFT_GUIDANCE in rendered
        assert "Do NOT get stuck retrying" in rendered
        assert self._HARD_CEILING not in rendered
        assert self._WITHDRAWAL not in rendered

    def test_enabled_mode_adds_the_ceiling_without_removing_the_guidance(self):
        """The behavioural budget and the backstop are separate instructions."""
        rendered = self._render(
            researcher_loop_guard_enabled=True,
            researcher_max_source_calls=10,
            researcher_max_identical_source_calls=2,
        )

        assert self._SOFT_GUIDANCE in rendered
        assert "at most 10 source-tool calls" in rendered
        assert "at most 2 call(s) with identical tool arguments" in rendered
        assert "a backstop, not a target" in rendered

    def test_enabled_mode_explains_the_graceful_exit(self):
        """The ceiling states the limit; these bullets state what to do when it is reached."""
        rendered = self._render(
            researcher_loop_guard_enabled=True,
            researcher_max_source_calls=10,
            researcher_max_identical_source_calls=2,
        )

        assert self._WITHDRAWAL in rendered
        assert "do not substitute `ls`, `read_file`, `glob`, `grep`" in rendered
        assert "`ResearchGap`" in rendered
        assert "Set `evidence_judgment` to reflect the truncation" in rendered
        # Model-agnostic: never "call the ResearchNotes tool" - provider-strategy models have none.
        assert "call the ResearchNotes tool" not in rendered


class TestAgentConfig:
    """The knob is reachable from YAML and defaults are validated."""

    def test_the_yaml_block_round_trips(self):
        config = register_module.DeepResearchAgentConfig.model_validate(
            {
                "_type": "deep_research_agent",
                "orchestrator_llm": "llm",
                "researcher_loop_guard": {
                    "enabled": True,
                    "max_source_calls_per_query": 25,
                    "max_identical_source_calls": 3,
                    "max_consecutive_thinks": 3,
                    "max_model_turns_per_query": 60,
                },
            }
        )

        assert config.researcher_loop_guard.max_source_calls_per_query == 25
        assert config.researcher_loop_guard.max_identical_source_calls == 3
        assert config.researcher_loop_guard.max_model_turns_per_query == 60

    def test_an_unknown_key_is_rejected(self):
        """extra='forbid' turns a YAML typo into a startup failure rather than a silent no-op."""
        with pytest.raises(ValidationError):
            ResearcherLoopGuardConfig(max_source_calls=10)

    def test_limits_must_be_at_least_one(self):
        with pytest.raises(ValidationError):
            ResearcherLoopGuardConfig(max_source_calls_per_query=0)

    @pytest.mark.parametrize(
        ("field", "ceiling"),
        [
            ("max_source_calls_per_query", loop_guard_module.SOURCE_CALLS_PER_QUERY_CEILING),
            ("max_identical_source_calls", loop_guard_module.IDENTICAL_SOURCE_CALLS_CEILING),
            ("max_consecutive_thinks", loop_guard_module.CONSECUTIVE_THINKS_CEILING),
            ("max_model_turns_per_query", loop_guard_module.MODEL_TURNS_PER_QUERY_CEILING),
        ],
    )
    def test_a_limit_raised_past_its_ceiling_is_rejected(self, field, ceiling):
        """A breaker may be raised, but not so far that it stops being a breaker."""
        assert getattr(ResearcherLoopGuardConfig(**{field: ceiling}), field) == ceiling

        with pytest.raises(ValidationError):
            ResearcherLoopGuardConfig(**{field: ceiling + 1})

    def test_every_ceiling_sits_above_its_default(self):
        """Deliberate divergence from resource_limits, where the default IS the maximum.

        Raising a breaker that fires on healthy runs is the documented tuning path, so a
        ceiling equal to the default would make that path unreachable.
        """
        defaults = ResearcherLoopGuardConfig()

        assert defaults.max_source_calls_per_query < loop_guard_module.SOURCE_CALLS_PER_QUERY_CEILING
        assert defaults.max_identical_source_calls < loop_guard_module.IDENTICAL_SOURCE_CALLS_CEILING
        assert defaults.max_consecutive_thinks < loop_guard_module.CONSECUTIVE_THINKS_CEILING
        assert defaults.max_model_turns_per_query < loop_guard_module.MODEL_TURNS_PER_QUERY_CEILING

    def test_the_source_call_ceiling_matches_the_job_wide_source_call_ceiling(self):
        """One worker must never be budgeted above what the whole job may retrieve."""
        assert loop_guard_module.SOURCE_CALLS_PER_QUERY_CEILING == resource_limits.DEFAULT_MAX_SOURCE_TOOL_CALLS

    def test_omitting_the_block_yields_the_shipped_defaults(self):
        config = register_module.DeepResearchAgentConfig.model_validate(
            {"_type": "deep_research_agent", "orchestrator_llm": "llm"}
        )

        assert config.researcher_loop_guard == ResearcherLoopGuardConfig()
        assert config.researcher_loop_guard.max_source_calls_per_query == 25
        assert config.researcher_loop_guard.max_identical_source_calls == 3


def _query():
    """Build a minimal valid ResearchQuery for the invocation-scoping tests."""
    from aiq_agent.agents.deep_researcher.models import ResearchQuery

    return ResearchQuery(
        query="what is quantum error correction",
        preferred_tools=[_SOURCE_TOOL],
        target_components=["overview"],
        rationale="test",
    )


def _notes() -> dict:
    """Build a minimal valid ResearchNotes payload."""
    return {
        "query_topic": "topic",
        "target_components": ["overview"],
        "summary": "summary",
        "findings": [],
        "gaps": [],
        "sources": [],
        "narrative_notes": "notes",
        "language": "en",
    }

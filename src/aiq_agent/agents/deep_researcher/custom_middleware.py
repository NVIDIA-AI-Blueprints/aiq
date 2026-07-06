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

"""Custom middleware for the deep research agent."""

import asyncio
import json
import logging
from pathlib import Path

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage
from langchain_core.messages import SystemMessage
from langchain_core.messages import ToolMessage

from aiq_agent.common import get_source_id_for_tool
from aiq_agent.common import load_prompt
from aiq_agent.common import render_prompt_template
from aiq_agent.common.citation_verification import SourceEntry
from aiq_agent.common.citation_verification import SourceRegistry
from aiq_agent.common.citation_verification import extract_sources_from_tool_result

logger = logging.getLogger(__name__)

# Path to this agent's prompts directory
_PROMPTS_DIR = Path(__file__).parent / "prompts"
_SOURCE_ROUTING_PATH = "/shared/source_routing.json"
# When a sandbox provider is configured, CompositeBackend strips the /shared/ route
# before delegating to StateBackend, so the router's file is stored under the
# route-local key. The guard reads raw state, so it must accept both forms or it
# blocks the orchestrator forever on sandboxed runs.
_SOURCE_ROUTING_STATE_KEYS = (_SOURCE_ROUTING_PATH, "/source_routing.json")


class SourceRoutingGuardMiddleware(AgentMiddleware):
    """Require the source-router handoff before other orchestrator tool calls."""

    def __init__(self, *, enabled: bool, required_subagent: str = "source-router-agent") -> None:
        self.enabled = enabled
        self.required_subagent = required_subagent

    @staticmethod
    def _routing_complete(state: object) -> bool:
        files = state.get("files", {}) if isinstance(state, dict) else getattr(state, "files", {})
        return isinstance(files, dict) and any(key in files for key in _SOURCE_ROUTING_STATE_KEYS)

    async def awrap_tool_call(self, request, handler):
        """Block out-of-order calls until the source router writes its route file."""
        if not self.enabled or self._routing_complete(request.state):
            return await handler(request)

        tool_call = request.tool_call
        args = tool_call.get("args") or {}
        if tool_call.get("name") == "task" and args.get("subagent_type") == self.required_subagent:
            return await handler(request)

        return ToolMessage(
            content=(
                "Source routing is required before any other tool call. "
                f"Call task with subagent_type={self.required_subagent!r}."
            ),
            tool_call_id=tool_call.get("id", "source-routing-guard"),
            name=tool_call.get("name"),
            status="error",
        )


class EmptyContentFixMiddleware(AgentMiddleware):
    """
    Middleware that fixes empty ToolMessage content.

    Some LLM APIs (e.g., NVIDIA, OpenAI) reject messages with empty content.
    This middleware ensures all ToolMessages have non-empty content by
    replacing empty strings with a placeholder.
    """

    def __init__(self, placeholder: str = "empty content received."):
        """
        Initialize the middleware.

        Args:
            placeholder: Text to use when ToolMessage content is empty.
        """
        self.placeholder = placeholder

    async def awrap_model_call(self, request, handler):
        """Fix empty ToolMessage content before sending to the model."""
        fixed_messages = []
        for msg in request.messages:
            if isinstance(msg, ToolMessage) and not msg.content:
                # Create a new ToolMessage with placeholder content
                fixed_messages.append(
                    ToolMessage(
                        content=self.placeholder,
                        tool_call_id=msg.tool_call_id,
                        name=getattr(msg, "name", None),
                        id=msg.id,
                    )
                )
            else:
                fixed_messages.append(msg)

        return await handler(request.override(messages=fixed_messages))


# Common hallucinated tool name mappings
_TOOL_NAME_ALIASES: dict[str, str] = {
    "open_file": "read_file",
    "find": "grep",
    "find_file": "glob",
}


class ToolNameSanitizationMiddleware(AgentMiddleware):
    """
    Middleware that sanitizes corrupted tool names in LLM responses.

    LLMs sometimes generate malformed tool calls with suffixes like
    <|channel|>commentary or .exec, or hallucinate tool names like
    open_file or find. This middleware intercepts the model response
    and fixes tool names before the framework dispatches them.
    """

    def __init__(self, valid_tool_names: list[str]):
        """Store the set of valid tool names used to correct malformed tool calls."""
        self.valid_tool_names = set(valid_tool_names)

    def _sanitize_tool_name(self, name: str) -> str:
        """Sanitize a potentially corrupted tool name.

        Returns the cleaned name if it maps to a valid tool,
        otherwise returns the original name unchanged.
        """
        # 1. Strip <|channel|> and everything after
        if "<|channel|>" in name:
            candidate = name.split("<|channel|>", maxsplit=1)[0]
            if candidate in self.valid_tool_names:
                logger.info("Sanitized tool name: '%s' -> '%s'", name, candidate)
                return candidate

        # 2. Strip dot suffix if base name is valid
        if "." in name:
            candidate = name.split(".", maxsplit=1)[0]
            if candidate in self.valid_tool_names:
                logger.info("Sanitized tool name: '%s' -> '%s'", name, candidate)
                return candidate

        # 3. Map common hallucinated names
        if name in _TOOL_NAME_ALIASES:
            mapped = _TOOL_NAME_ALIASES[name]
            if mapped in self.valid_tool_names:
                logger.info("Mapped tool name: '%s' -> '%s'", name, mapped)
                return mapped

        return name

    async def awrap_model_call(self, request, handler):
        """Intercept model response and sanitize tool names."""
        response = await handler(request)

        needs_fix = False
        for msg in response.result:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    sanitized = self._sanitize_tool_name(tc["name"])
                    if sanitized != tc["name"]:
                        needs_fix = True
                        break
                if needs_fix:
                    break

        if not needs_fix:
            return response

        new_result = []
        for msg in response.result:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                new_tool_calls = []
                for tc in msg.tool_calls:
                    new_tool_calls.append({**tc, "name": self._sanitize_tool_name(tc["name"])})
                new_msg = AIMessage(
                    content=msg.content,
                    tool_calls=new_tool_calls,
                    id=msg.id,
                )
                new_result.append(new_msg)
            else:
                new_result.append(msg)

        return ModelResponse(result=new_result, structured_response=response.structured_response)


def _request_tool_name(tool: object) -> str | None:
    """Return a LangChain model-request tool name across common tool shapes."""
    name = getattr(tool, "name", None)
    if isinstance(name, str):
        return name
    if isinstance(tool, dict):
        dict_name = tool.get("name")
        if isinstance(dict_name, str):
            return dict_name
        function = tool.get("function")
        if isinstance(function, dict):
            function_name = function.get("name")
            if isinstance(function_name, str):
                return function_name
    return None


class ToolVisibilityMiddleware(AgentMiddleware):
    """Hide selected tools from model requests without removing scaffolding middleware."""

    def __init__(self, hidden_tool_names: set[str]) -> None:
        """Store the tool names to hide from model requests."""
        self.hidden_tool_names = hidden_tool_names

    def _filter_tools(self, tools: list[object]) -> list[object]:
        """Return the tool list with hidden tools removed."""
        if not self.hidden_tool_names:
            return tools
        return [tool for tool in tools if _request_tool_name(tool) not in self.hidden_tool_names]

    def wrap_model_call(self, request, handler):
        """Filter hidden tools before a synchronous model call."""
        return handler(request.override(tools=self._filter_tools(request.tools)))

    async def awrap_model_call(self, request, handler):
        """Filter hidden tools before an asynchronous model call."""
        return await handler(request.override(tools=self._filter_tools(request.tools)))


class TodoSuppressionMiddleware(AgentMiddleware):
    """Strip the framework's ``write_todos`` tool and its injected prompt for a subagent.

    deepagents attaches ``TodoListMiddleware`` to every subagent, which adds the
    ``write_todos`` tool plus a system-prompt block telling the agent to use it.
    Agents that own no progress list - e.g. the planner, which returns a single
    structured ``ResearchPlan`` - should not have it. Placed after the framework's
    ``TodoListMiddleware`` in the stack, this removes both the tool and the injected
    prompt block from the model request, keeping todo tracking solely with the
    orchestrator. It is a no-op when neither is present.
    """

    _TODO_TOOL = "write_todos"
    _TODO_PROMPT_MARKER = "## `write_todos`"

    def _clean_request(self, request: object) -> object:
        """Return the request with the write_todos tool and its prompt block removed."""
        overrides: dict[str, object] = {
            "tools": [tool for tool in request.tools if _request_tool_name(tool) != self._TODO_TOOL]
        }
        system_message = getattr(request, "system_message", None)
        if system_message is not None:
            blocks = system_message.content_blocks
            kept = [
                block
                for block in blocks
                if not (isinstance(block, dict) and self._TODO_PROMPT_MARKER in str(block.get("text", "")))
            ]
            if len(kept) != len(blocks):
                overrides["system_message"] = SystemMessage(content=kept)
        return request.override(**overrides)

    def wrap_model_call(self, request, handler):
        """Strip write_todos and its prompt before a synchronous model call."""
        return handler(self._clean_request(request))

    async def awrap_model_call(self, request, handler):
        """Strip write_todos and its prompt before an asynchronous model call."""
        return await handler(self._clean_request(request))


class ToolRetryMiddleware(AgentMiddleware):
    """Retries failed tool calls with exponential backoff.

    Provides uniform retry coverage for all tools. Some tools (e.g., Tavily)
    have their own internal retry; this middleware wraps the outer call so
    tools without retry (knowledge layer, paper search) are also covered.
    """

    def __init__(
        self,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        initial_delay: float = 1.0,
    ):
        """Configure retry count and exponential backoff for failed tool calls."""
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.initial_delay = initial_delay

    async def awrap_tool_call(self, request, handler):
        """Retry tool calls on failure with exponential backoff."""
        delay = self.initial_delay
        last_exception = None
        for attempt in range(self.max_retries + 1):
            try:
                return await handler(request)
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries:
                    tool_name = request.tool_call.get("name", "?") if hasattr(request, "tool_call") else "?"
                    logger.warning(
                        "Tool %s failed (attempt %d/%d): %s",
                        tool_name,
                        attempt + 1,
                        self.max_retries + 1,
                        e,
                    )
                    await asyncio.sleep(delay)
                    delay *= self.backoff_factor
        raise last_exception


class SourceRegistryMiddleware(AgentMiddleware):
    """Intercepts tool call results to build a registry of actual sources.

    Two responsibilities:
    1. awrap_tool_call: Capture URLs/citation keys from tool results
    2. awrap_model_call: Inject a consolidated source list into the LLM context
       so the orchestrator has a single, authoritative reference list when
       writing the final report (no manual reconciliation across research-note files)

    Source capture is gated only by the agent's loaded tool set
    (``source_tool_names``). Internal scratchpad/runtime tools (think,
    write_file, read_file, etc.) are added by deepagents itself and never
    appear in that set, so they are implicitly excluded. Tools registered as
    configured data sources additionally carry a ``source_id`` label, but a
    tool does *not* have to be declared under ``data_sources`` to contribute
    sources — agents can be passed citable tools directly.

    The registry is also used by verify_citations() to strip fabricated,
    stale, or intermediate-artifact citations from the final report.
    """

    def __init__(self, source_tool_names: set[str] | None = None) -> None:
        """Create a source registry scoped to the given source-producing tool names."""
        self.registry = SourceRegistry()
        self._source_tool_names = source_tool_names or set()
        self._compact_source_keys: set[str] = set()
        self._lock = asyncio.Lock()

    def active_registry(self) -> SourceRegistry:
        """Return the session-scoped registry if set, otherwise the instance registry."""
        from aiq_agent.common.citation_verification import get_session_registry

        return get_session_registry() or self.registry

    def has_sources(self) -> bool:
        """Return True when the active source registry contains captured sources."""
        return bool(self.active_registry().all_sources())

    @staticmethod
    def _locator_key(locator: str) -> str:
        """Return the comparable key used for source locators and registry entries."""
        locator = locator.strip()
        if locator.startswith(("http://", "https://")):
            from aiq_agent.common.citation_verification import _normalize_url

            return _normalize_url(locator)
        return locator

    @classmethod
    def _entry_key(cls, entry: SourceEntry) -> str | None:
        """Return the comparable key for a registered source entry."""
        if entry.url:
            return cls._locator_key(entry.url)
        if entry.citation_key:
            return entry.citation_key.strip()
        return None

    def register_research_note_sources(self, notes: list[object]) -> None:
        """Mark ResearchNotes source locators as the compact writer-facing citation set."""
        for note in notes:
            sources = getattr(note, "sources", None) or []
            for source in sources:
                locator = getattr(source, "locator", "")
                if isinstance(locator, str) and locator.strip():
                    self._compact_source_keys.add(self._locator_key(locator))

    def register_compact_sources(self, sources: list[SourceEntry]) -> int:
        """Register seeded sources and expose them in the compact citation source list."""
        registry = self.active_registry()
        registered = 0
        for source in sources:
            key = self._entry_key(source)
            if not key:
                continue
            registry.add(source)
            self._compact_source_keys.add(key)
            registered += 1
        return registered

    async def awrap_tool_call(self, request, handler):
        """Capture sources from tool results after execution.

        Capture is gated only by the agent's loaded tool set
        (``source_tool_names``). Internal scratchpad/runtime tools (think,
        write_file, read_file, etc.) are added by deepagents itself and never
        appear in that set, so they are implicitly excluded.

        Tools that resolve to a configured data source via
        :func:`get_source_id_for_tool` get a ``source_id`` label. Tools passed
        directly to the agent without a data-source declaration are still
        captured — their results are real, citable evidence even when
        ``data_source_registry`` does not know about them — but their entries
        carry no ``source_id``.
        """
        result = await handler(request)
        if isinstance(result, ToolMessage) and result.content:
            tool_name = ""
            if hasattr(request, "tool_call") and isinstance(request.tool_call, dict):
                tool_name = request.tool_call.get("name", "")
            if tool_name not in self._source_tool_names:
                return result
            source_id = get_source_id_for_tool(tool_name)
            sources = extract_sources_from_tool_result(tool_name, str(result.content), source_id=source_id)
            async with self._lock:
                active_registry = self.active_registry()
                for source in sources:
                    active_registry.add(source)
            if sources:
                logger.info(
                    "[CitationRegistry] Captured %d source(s) from %s: %s",
                    len(sources),
                    tool_name,
                    [s.url or s.citation_key for s in sources],
                )
        return result

    def _render_source_list_text(self, sources: list[SourceEntry]) -> str | None:
        """Render a consolidated source list from registry entries.

        Returns rendered template text, or None if no sources captured.
        Used by agent.run() to include the source list in retry messages
        when citation quality is poor.
        """
        from urllib.parse import urlparse

        from aiq_agent.common.citation_verification import _normalize_url

        if not sources:
            return None

        seen: set[str] = set()
        template_sources = []
        for entry in sources:
            if entry.url:
                normalized = _normalize_url(entry.url)
                if normalized in seen:
                    continue
                seen.add(normalized)
                if entry.title:
                    title = entry.title
                else:
                    try:
                        title = urlparse(entry.url).netloc.replace("www.", "")
                    except Exception:
                        title = entry.url
                template_sources.append({"title": title, "url": entry.url})
            elif entry.citation_key:
                key = entry.citation_key
                if key in seen:
                    continue
                seen.add(key)
                template_sources.append({"title": key, "url": key})

        if not template_sources:
            return None

        try:
            template = load_prompt(_PROMPTS_DIR, "source_registry")
            return render_prompt_template(template, sources=template_sources)
        except Exception:
            logger.warning("Failed to load source_registry prompt template", exc_info=True)
            return None

    def get_source_entries(self, mode: str = "compact") -> list[SourceEntry]:
        """Return the source entries represented by the writer-facing source list."""
        sources = self.active_registry().all_sources()
        if mode == "full" or not self._compact_source_keys:
            return sources
        compact_sources = [source for source in sources if self._entry_key(source) in self._compact_source_keys]
        return compact_sources or sources

    def get_source_list_text(self, mode: str = "compact") -> str | None:
        """Build a writer-facing verified source list.

        Compact mode returns the subset of registered sources that researcher
        workers actually carried forward in structured ResearchNotes. Full mode
        returns the complete registry.
        """
        return self._render_source_list_text(self.get_source_entries(mode=mode))


class PlanPersistenceMiddleware(AgentMiddleware):
    """Persists the planner's structured ResearchPlan to the shared filesystem.

    The planner returns a schema-validated ``ResearchPlan`` (``response_format``).
    This middleware writes that plan to ``/shared/plan.json`` deterministically via
    the overwrite-safe ``backend.upload_files`` (the same state-channel write
    ``run_research_batch`` uses for ResearchNotes), so the planner never performs
    file I/O itself. Keeping the write off the LLM removes the ``write_file`` /
    ``edit_file`` loop the planner otherwise hits when ``/shared/plan.json`` already
    exists, since the LLM ``write_file`` tool refuses to overwrite while
    ``upload_files`` overwrites in place.

    Persistence failures propagate so the planner task fails before the
    orchestrator reads a missing or stale ``/shared/plan.json``.
    """

    def __init__(self, backend: object, *, path: str = "/shared/plan.json") -> None:
        """Initialize the middleware.

        Args:
            backend: Shared filesystem backend exposing ``upload_files``.
            path: Shared path the serialized plan is written to.
        """
        self.backend = backend
        self.path = path

    @staticmethod
    def _plan_from_state(state: object) -> object:
        """Extract the planner's ``structured_response`` from dict or attribute state."""
        if isinstance(state, dict):
            return state.get("structured_response")
        return getattr(state, "structured_response", None)

    def _persist_plan(self, plan: object) -> None:
        """Serialize a structured ResearchPlan and upload it to shared state."""
        if plan is None:
            return
        if hasattr(plan, "model_dump"):
            payload = plan.model_dump(mode="json", exclude_none=True)
        elif isinstance(plan, dict):
            payload = plan
        else:
            return
        content = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        responses = self.backend.upload_files([(self.path, content)])
        errors = [f"{response.path}: {response.error}" for response in responses if getattr(response, "error", None)]
        if errors:
            # Raw backend detail stays in logs; the raised error reaches the job status /
            # caller, so it must not echo backend-internal strings (hostnames, paths, etc.).
            logger.error("Failed to persist plan to %s: %s", self.path, "; ".join(errors))
            raise RuntimeError(f"Failed to persist the research plan to {self.path}")

    def after_agent(self, state, runtime):
        """Persist the plan once the synchronous planner run completes."""
        self._persist_plan(self._plan_from_state(state))

    async def aafter_agent(self, state, runtime):
        """Persist the plan once the asynchronous planner run completes."""
        await asyncio.to_thread(self._persist_plan, self._plan_from_state(state))


class ToolResultPruningMiddleware(AgentMiddleware):
    """Truncates older tool results to keep context manageable.

    Keeps the last N tool results intact and truncates older ones to
    reduce "lost in the middle" degradation. Operates on awrap_model_call
    so the full results are still available for SourceRegistryMiddleware.
    """

    def __init__(self, keep_last_n: int = 3, max_chars: int = 500):
        """Configure how many recent tool results to keep intact and the truncation cap."""
        self.keep_last_n = keep_last_n
        self.max_chars = max_chars

    async def awrap_model_call(self, request, handler):
        """Truncate older ToolMessage content before sending to the model."""
        # Find all ToolMessage indices
        tool_indices = [i for i, msg in enumerate(request.messages) if isinstance(msg, ToolMessage)]

        if len(tool_indices) <= self.keep_last_n:
            return await handler(request)

        # Indices to truncate: all but the last keep_last_n
        truncate_indices = set(tool_indices[: -self.keep_last_n])

        pruned_messages = []
        for i, msg in enumerate(request.messages):
            if i in truncate_indices and isinstance(msg, ToolMessage) and msg.content:
                content = str(msg.content)
                if len(content) > self.max_chars:
                    truncated_content = content[: self.max_chars] + "\n\n[... truncated ...]"
                    pruned_messages.append(
                        ToolMessage(
                            content=truncated_content,
                            tool_call_id=msg.tool_call_id,
                            name=getattr(msg, "name", None),
                            id=msg.id,
                        )
                    )
                else:
                    pruned_messages.append(msg)
            else:
                pruned_messages.append(msg)

        return await handler(request.override(messages=pruned_messages))

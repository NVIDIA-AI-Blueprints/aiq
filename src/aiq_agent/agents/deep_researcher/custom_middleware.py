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
import logging
from pathlib import Path

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage
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


class ToolResultPruningMiddleware(AgentMiddleware):
    """Truncates older tool results to keep context manageable.

    Keeps the last N tool results intact and truncates older ones to
    reduce "lost in the middle" degradation. Operates on awrap_model_call
    so the full results are still available for SourceRegistryMiddleware.
    """

    def __init__(self, keep_last_n: int = 3, max_chars: int = 500):
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

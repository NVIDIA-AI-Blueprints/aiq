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

"""Deep research agent using deepagents library for multi-phase workflow."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.tools import BaseTool

from aiq_agent.common import LLMProvider
from aiq_agent.common import load_prompt
from aiq_agent.common.citation_verification import EmptySourceRegistryError
from aiq_agent.common.citation_verification import sanitize_report
from aiq_agent.common.citation_verification import source_entries_from_parent_context
from aiq_agent.common.citation_verification import verify_citations

from .custom_middleware import SourceRegistryMiddleware
from .deepagents_runtime import DeepAgentsRuntime
from .deepagents_runtime import DeepResearchSandboxConfig
from .deepagents_runtime import DeepResearchSkillsConfig
from .factory import build_deep_research_graph
from .factory import build_deep_research_middleware_set
from .factory import build_deep_research_tool_set
from .models import DeepResearchAgentState
from .tools.source_tool_batching import DEFAULT_MAX_CONCURRENT_SOURCE_TOOL_CALLS
from .tools.source_tool_batching import DEFAULT_MAX_SOURCE_TOOL_BATCH_SIZE

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESEARCH_CONCURRENCY = 6
PARENT_REPORT_CONTEXT_PATH = "/shared/parent_report_context.json"

# Path to this agent's directory (for loading prompts)
AGENT_DIR = Path(__file__).parent

# Salvage gate: when the orchestrator synthesizes the report inline instead of delegating to
# writer-agent, no /shared/output.md is written. We accept the final message as the report only
# when it is clearly a substantive report (long + has a markdown heading), so workflow chatter is
# still rejected and the strict file-first contract is preserved.
_WRITER_COMPLETION_MARKER = "Wrote /shared/output.md"
_MIN_INLINE_REPORT_CHARS = 400
_MD_HEADING_RE = re.compile(r"(?m)^#{1,6}\s")


class DeepResearcherAgent:
    """
    Deep research agent using deepagents library for multi-phase workflow.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        tools: Sequence[BaseTool] | None = None,
        *,
        verbose: bool = True,
        callbacks: list[Any] | None = None,
        domain_catalog_path: str | None = None,
        enable_source_router: bool = True,
        enable_citation_verification: bool = True,
        skills: DeepResearchSkillsConfig | None = None,
        sandbox: DeepResearchSandboxConfig | None = None,
        job_id: str | None = None,
        artifact_db_url: str | None = None,
        artifact_emit: Callable[[dict[str, Any]], None] | None = None,
        max_research_concurrency: int = DEFAULT_MAX_RESEARCH_CONCURRENCY,
        max_concurrent_source_tool_calls: int = DEFAULT_MAX_CONCURRENT_SOURCE_TOOL_CALLS,
        max_source_tool_batch_size: int = DEFAULT_MAX_SOURCE_TOOL_BATCH_SIZE,
    ) -> None:
        """
        Initialize the deep researcher agent.

        Args:
            llm_provider: LLMProvider for role-based LLM access.
            tools: Optional sequence of LangChain tools for research.
            verbose: Enable detailed logging.
            callbacks: Optional list of callbacks.
            domain_catalog_path: Optional YAML/JSON domain catalog path for source-router-agent.
            enable_source_router: Enable the advisory source-router-agent before planning.
            enable_citation_verification: Verify generated citations against the captured source registry.
            skills: Optional DeepAgents skills config.
            sandbox: Optional DeepAgents sandbox config.
            job_id: Optional async job identifier used to scope sandbox backends.
            max_research_concurrency: Maximum ResearchQuery items accepted and run concurrently per
                run_research_batch call.
            max_concurrent_source_tool_calls: Shared source-tool concurrency limit across researcher workers.
            max_source_tool_batch_size: Maximum concrete inputs per batch-capable source tool call.
        """
        self.llm_provider = llm_provider
        self.tools = list(tools) if tools else []
        self.verbose = verbose
        self.callbacks = callbacks or []
        self.max_research_concurrency = max_research_concurrency
        self.max_concurrent_source_tool_calls = max_concurrent_source_tool_calls
        self.max_source_tool_batch_size = max_source_tool_batch_size
        self.domain_catalog_path = domain_catalog_path
        self.enable_source_router = enable_source_router
        self.enable_citation_verification = enable_citation_verification
        self.job_id = str(job_id) if job_id is not None else str(uuid4())

        self.deepagents_runtime = DeepAgentsRuntime(
            skills=skills,
            sandbox=sandbox,
            job_id=self.job_id,
            artifact_db_url=artifact_db_url,
            artifact_emit=artifact_emit,
        )

        self._prompts = self._load_prompts()
        source_tool_names = {tool.name for tool in self.tools}
        self.source_registry_middleware = SourceRegistryMiddleware(source_tool_names=source_tool_names)
        self.tool_set = build_deep_research_tool_set(
            self.tools,
            source_registry_middleware=self.source_registry_middleware,
            max_concurrent_source_tool_calls=self.max_concurrent_source_tool_calls,
            max_source_tool_batch_size=self.max_source_tool_batch_size,
        )
        self.middleware_set = build_deep_research_middleware_set(
            tool_set=self.tool_set,
            source_registry_middleware=self.source_registry_middleware,
        )

        self.source_tool_names = self.tool_set.source_tool_names
        self.tools_info = self.tool_set.tools_info
        self.non_search_tools = self.tool_set.helper_tools
        self.all_tools = self.tool_set.all_tools
        self.research_source_tools = self.tool_set.research_source_tools
        self.researcher_tools = self.tool_set.researcher_tools
        self.writer_tools = self.tool_set.writer_tools
        self.researcher_middleware = self.middleware_set.researcher
        self.writer_middleware = self.middleware_set.writer
        self.orchestrator_middleware = self.middleware_set.orchestrator
        self.middleware = self.researcher_middleware

    def _load_prompts(self) -> dict[str, str]:
        """Load all prompts for subagents."""
        prompts = {}
        prompt_names = ["planner", "researcher", "orchestrator", "writer", "source_router"]

        for name in prompt_names:
            prompts[name] = load_prompt(AGENT_DIR / "prompts", name)

        return prompts

    def _build_orchestrator_agent(self, state: DeepResearchAgentState) -> Any:
        """Build the orchestrator graph for the current state."""
        return build_deep_research_graph(
            llm_provider=self.llm_provider,
            state=state,
            prompts=self._prompts,
            tools=self.tools,
            runtime=self.deepagents_runtime,
            tool_set=self.tool_set,
            middleware_set=self.middleware_set,
            source_registry_middleware=self.source_registry_middleware,
            callbacks=self.callbacks,
            domain_catalog_path=self.domain_catalog_path,
            enable_source_router=self.enable_source_router,
            max_research_concurrency=self.max_research_concurrency,
        )

    def _extract_final_markdown(self, result: dict | Any) -> str | None:
        """Extract final Markdown from output files."""
        output_paths = ("/shared/output.md", "/output.md")
        files = result.get("files", {}) if isinstance(result, dict) else getattr(result, "files", {})
        if isinstance(files, dict):
            for output_path in output_paths:
                output_entry = files.get(output_path)
                if isinstance(output_entry, dict):
                    output_entry = output_entry.get("content")
                if isinstance(output_entry, bytes):
                    output_entry = output_entry.decode("utf-8")
                if isinstance(output_entry, str) and output_entry.strip():
                    return output_entry.strip()
        return self._salvage_inline_report(result)

    @staticmethod
    def _salvage_inline_report(result: dict | Any) -> str | None:
        """Salvage a report the orchestrator wrote inline instead of via writer-agent.

        When the orchestrator skips the writer-agent delegation and emits the full report in its
        final message, no output file exists. Accept that message only when it is clearly a
        substantive report so plain workflow chatter is still rejected.
        """
        messages = result.get("messages") if isinstance(result, dict) else getattr(result, "messages", None)
        if not messages:
            return None
        content = getattr(messages[-1], "content", None)
        if not isinstance(content, str):
            return None
        stripped = content.strip()
        if (
            not stripped
            or stripped == _WRITER_COMPLETION_MARKER
            or len(stripped) < _MIN_INLINE_REPORT_CHARS
            or not _MD_HEADING_RE.search(stripped)
        ):
            return None
        return stripped

    @staticmethod
    def _read_seed_file_text(files: dict[str, Any], path: str) -> str | None:
        entry = files.get(path)
        if isinstance(entry, dict):
            entry = entry.get("content")
        if isinstance(entry, bytes):
            entry = entry.decode("utf-8")
        return entry if isinstance(entry, str) and entry.strip() else None

    def _seed_parent_sources(self, files: dict[str, Any]) -> None:
        """Register parent report sources so preserved citations verify in delta reports."""
        context_text = self._read_seed_file_text(files, PARENT_REPORT_CONTEXT_PATH)
        if not context_text:
            return
        parent_sources = source_entries_from_parent_context(context_text)
        seeded = self.source_registry_middleware.register_compact_sources(parent_sources)
        if seeded:
            logger.info("Seeded %d parent report source(s) into citation registry", seeded)

    @staticmethod
    def _replace_last_message_content(result: dict | Any, content: str) -> None:
        """Overwrite the final message content in-place with post-processed Markdown."""
        messages = result.get("messages") if isinstance(result, dict) else getattr(result, "messages", None)
        if not messages:
            return
        last_msg = messages[-1]
        if hasattr(last_msg, "model_copy"):
            messages[-1] = last_msg.model_copy(update={"content": content})
        else:
            messages[-1] = type(last_msg)(content=content)

    async def run(self, state: DeepResearchAgentState) -> DeepResearchAgentState:
        """
        Execute deep research with multi-phase workflow.
        """
        prepared_files = self.deepagents_runtime.prepare_state_files(dict(state.files))
        if prepared_files != state.files:
            state = state.model_copy(update={"files": prepared_files})
        self._seed_parent_sources(state.files)
        agent = self._build_orchestrator_agent(state)

        messages = state.messages
        if messages:
            query_content = messages[-1].content
            query = query_content if isinstance(query_content, str) else str(query_content)
            logger.info("=" * 80)
            logger.info("Deep Research Subagent: Starting workflow")
            logger.info("Query: %s...", query[:100])
            logger.info("=" * 80)

        try:
            result = await agent.ainvoke(state, config={"callbacks": self.callbacks} if self.callbacks else None)

            final_message = self._extract_final_markdown(result)
            if final_message is None:
                raise ValueError("writer-agent did not produce a final Markdown answer")

            # Post-process: verify citations against source registry
            if self.enable_citation_verification and self.source_registry_middleware.has_sources():
                registry = self.source_registry_middleware.active_registry()
                verification = verify_citations(
                    final_message,
                    registry,
                    reference_sources=self.source_registry_middleware.get_source_entries(mode="compact"),
                )
                if verification.removed_citations:
                    removed_details = []
                    for c in verification.removed_citations:
                        url_match = re.search(r"https?://\S+", c.get("line", ""))
                        url_str = url_match.group(0).rstrip(".,;)") if url_match else "(no url)"
                        removed_details.append(f"[{c['number']}] {c['reason']}: {url_str}")
                    logger.info(
                        "Citation verification removed %d invalid citation(s):\n  %s",
                        len(verification.removed_citations),
                        "\n  ".join(removed_details),
                    )
                final_message = verification.verified_report
                if not verification.valid_citations:
                    logger.warning(
                        "Citation verification found no valid citations in writer-agent output; "
                        "returning the generated report without failing the job. "
                        "This may indicate unsupported citation formatting or over-aggressive verification."
                    )
            elif self.enable_citation_verification:
                from aiq_agent.common.tool_validation import validate_tool_availability

                _, available_count, unavailable = validate_tool_availability(
                    self.tools,
                    research_type="deep research",
                    enable_logging=False,
                )
                raise EmptySourceRegistryError(
                    "deep research",
                    unavailable_tools=unavailable,
                    available_count=available_count,
                )

            # Post-process: sanitize report (strip body URLs, shortened URLs, unsafe URLs)
            sanitization = sanitize_report(final_message)
            final_message = sanitization.sanitized_report

            # Post-process: harvest sandbox artifacts and resolve artifact:// references so
            # generated charts/files render in the report. Inert (manager is None) unless a
            # sandbox + artifact_capture + db_url are configured. Blocking I/O off the loop.
            manager = self.deepagents_runtime.artifact_manager
            if manager is not None:
                try:
                    await asyncio.to_thread(manager.final_harvest)
                    produced = await asyncio.to_thread(manager.store.list, manager.job_id)
                    final_message = await asyncio.to_thread(manager.resolve_report_references, final_message, produced)
                    final_message = await asyncio.to_thread(
                        manager.ensure_inline_artifacts_embedded, final_message, produced
                    )
                    final_message = await asyncio.to_thread(manager.append_artifact_index, final_message, produced)
                except Exception:
                    # Best-effort: never discard an already verified/sanitized report because
                    # artifact harvest or embedding failed. final_message stays as-is.
                    logger.warning(
                        "Artifact post-processing failed; returning report without embedded artifacts",
                        exc_info=True,
                    )

            # Re-emit the verified/sanitized report so the frontend overwrites
            # the raw version that on_llm_end auto-emitted during ainvoke().
            for cb in self.callbacks:
                if hasattr(cb, "emit_final_report"):
                    cb.emit_final_report(final_message)
                    break

            self._replace_last_message_content(result, final_message)

            logger.info("=" * 80)
            logger.info("Deep Research Subagent: Workflow complete")
            logger.info("Final answer length: %d characters", len(final_message))
            logger.info("=" * 80)
            return DeepResearchAgentState.model_validate(result)

        except Exception as ex:
            logger.error("Deep Research Subagent failed: %s", ex, exc_info=True)
            raise

# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Deep research agent using deepagents library for multi-phase workflow."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from deepagents import create_deep_agent
from langchain.agents.middleware import ModelRetryMiddleware
from langchain_core.tools import BaseTool
from langchain_core.tools import tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.memory import InMemoryStore

from aiq_agent.common import LLMProvider
from aiq_agent.common import LLMRole
from aiq_agent.common import get_checkpointer
from aiq_agent.common import load_prompt
from aiq_agent.common import render_prompt_template
from aiq_agent.common.citation_verification import EmptySourceRegistryError
from aiq_agent.common.citation_verification import sanitize_report
from aiq_agent.common.citation_verification import verify_citations

from .custom_middleware import EmptyContentFixMiddleware
from .custom_middleware import SourceRegistryMiddleware
from .custom_middleware import SourceToolConcurrencyLimiter
from .custom_middleware import ToolConcurrencyMiddleware
from .custom_middleware import ToolNameSanitizationMiddleware
from .custom_middleware import ToolResultPruningMiddleware
from .custom_middleware import ToolRetryMiddleware
from .deepagents_runtime import DeepAgentsRuntime
from .deepagents_runtime import SandboxConfig
from .deepagents_runtime import SkillsConfig
from .models import DeepResearchAgentState
from .models import ResearchPlan
from .models import SourceRoutingPlan
from .models import WriterOutput
from .tools.research import build_research_batch_tool as build_research_batch_tool_impl
from .tools.research import build_researcher_runnable as build_researcher_runnable_impl
from .tools.source_routing import build_lookup_source_catalog_tool
from .tools.source_tool_batching import build_batch_source_tools

logger = logging.getLogger(__name__)

DEFAULT_MAX_BATCH_RESEARCH_QUERIES = 6
DEFAULT_MAX_RESEARCH_CONCURRENCY = 3
DEFAULT_RESEARCH_QUERY_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_CONCURRENT_SOURCE_TOOL_CALLS = 5
DEFAULT_MAX_SOURCE_TOOL_BATCH_SIZE = 5
DEFAULT_MAX_WORKFLOW_RESUME_ATTEMPTS = 4

# Path to this agent's directory (for loading prompts)
AGENT_DIR = Path(__file__).parent


@tool
def think(thought: str) -> str:
    """Use this tool to reason through complex decisions, verify constraints, or
    plan next steps before acting. The tool records your thought without taking
    any action or retrieving new information.

    When to use:
    - Before making a decision: reason through options and trade-offs
    - After receiving information: analyze findings and identify gaps
    - For constraint verification: check if a constraint is satisfied and note PASS/FAIL
    - When planning: outline your approach before executing

    Args:
        thought: Your reasoning, analysis, or verification to record.
    """
    logger.info("Thinking: %s", thought)
    return "Thought recorded."


class DeepResearcherAgent:
    """
    Deep research agent using deepagents library for multi-phase workflow.

    This agent produces cited research answers through an iterative process:

    1. **Planning Phase**: Generate a structured research plan with answer strategy
       and queries (planner subagent)
    2. **Research Loops**: Execute queries through the batch research tool, then
       inspect gaps in the orchestrator
    3. **Iteration**: Repeat research and synthesis loops to fill gaps
    4. **Citation Management**: Catalog and number sources in the orchestrator
    5. **Finalization**: Delegate final Markdown synthesis to the writer subagent

    The agent is NAT-independent and receives all dependencies via constructor.

    Example:
        >>> from aiq_agent.common import LLMProvider, LLMRole
        >>> provider = LLMProvider()
        >>> provider.set_default(my_llm)
        >>> provider.configure(LLMRole.ORCHESTRATOR, orchestrator_llm)
        >>> provider.configure(LLMRole.RESEARCHER, researcher_llm)
        >>> provider.configure(LLMRole.PLANNER, planner_llm)
        >>>
        >>> from aiq_agent.agents.deep_researcher.models import DeepResearchAgentState
        >>> agent = DeepResearcherAgent(
        ...     llm_provider=provider,
        ...     tools=[search_tool_a, search_tool_b],
        ... )
        >>> state = DeepResearchAgentState(messages=[HumanMessage(content="Compare CUDA vs OpenCL")])
        >>> result = await agent.run(state)
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        tools: Sequence[BaseTool] | None = None,
        *,
        max_loops: int = 2,
        verbose: bool = True,
        callbacks: list[Any] | None = None,
        domain_catalog_path: str | None = None,
        skills: SkillsConfig | None = None,
        sandbox: SandboxConfig | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        checkpoint_db: str | None = None,
        config: Any | None = None,
        job_id: str | None = None,
        max_batch_research_queries: int = DEFAULT_MAX_BATCH_RESEARCH_QUERIES,
        max_research_concurrency: int = DEFAULT_MAX_RESEARCH_CONCURRENCY,
        research_query_timeout_seconds: float = DEFAULT_RESEARCH_QUERY_TIMEOUT_SECONDS,
        max_concurrent_source_tool_calls: int = DEFAULT_MAX_CONCURRENT_SOURCE_TOOL_CALLS,
        max_source_tool_batch_size: int = DEFAULT_MAX_SOURCE_TOOL_BATCH_SIZE,
        max_workflow_resume_attempts: int = DEFAULT_MAX_WORKFLOW_RESUME_ATTEMPTS,
        evidence_reranking_enabled: bool = True,
    ) -> None:
        """
        Initialize the deep researcher agent.

        Args:
            llm_provider: LLMProvider for role-based LLM access.
            tools: Optional sequence of LangChain tools for research.
            max_loops: Maximum number of research loops (default 2).
            verbose: Enable detailed logging.
            callbacks: Optional list of callbacks.
            domain_catalog_path: Optional YAML/JSON domain catalog path for source-router-agent.
            skills: Optional DeepAgents skills config.
            sandbox: Optional DeepAgents sandbox config.
            checkpointer: Optional LangGraph checkpointer for workflow recovery.
            checkpoint_db: Optional SQLite database path or Postgres DSN for lazy checkpointer creation.
            config: Optional agent config. Used by async workers to pass function config generically.
            job_id: Optional async job identifier used to scope sandbox backends.
            max_batch_research_queries: Maximum curated ResearchQuery items per run_research_batch call.
            max_research_concurrency: Maximum concurrent researcher workers per run_research_batch call.
            research_query_timeout_seconds: Per-ResearchQuery timeout for researcher workers.
            max_concurrent_source_tool_calls: Shared source-tool concurrency limit across researcher workers.
            max_source_tool_batch_size: Maximum concrete inputs per batch-capable source tool call.
            max_workflow_resume_attempts: Maximum graph-level retries from the latest checkpoint.
            evidence_reranking_enabled: Enable the internal post-research evidence curator.
        """
        self.llm_provider = llm_provider
        self.tools = list(tools) if tools else []
        self.max_loops = max_loops
        self.verbose = verbose
        self.callbacks = callbacks or []

        if config is not None:
            skills = skills or getattr(config, "skills", None)
            sandbox = sandbox if sandbox is not None else getattr(config, "sandbox", None)
            checkpointer = checkpointer or getattr(config, "checkpointer", None)
            checkpoint_db = checkpoint_db or getattr(config, "checkpoint_db", None)
            domain_catalog_path = domain_catalog_path or getattr(config, "domain_catalog_path", None)
            max_workflow_resume_attempts = getattr(
                config,
                "max_workflow_resume_attempts",
                max_workflow_resume_attempts,
            )
            evidence_reranking_enabled = getattr(
                config,
                "evidence_reranking_enabled",
                evidence_reranking_enabled,
            )

        self.max_batch_research_queries = max_batch_research_queries
        self.max_research_concurrency = max_research_concurrency
        self.research_query_timeout_seconds = research_query_timeout_seconds
        self.max_concurrent_source_tool_calls = max_concurrent_source_tool_calls
        self.max_source_tool_batch_size = max_source_tool_batch_size
        self.max_workflow_resume_attempts = max(0, max_workflow_resume_attempts)
        self.evidence_reranking_enabled = evidence_reranking_enabled
        self.domain_catalog_path = domain_catalog_path
        self.checkpointer = checkpointer
        self.checkpoint_db = checkpoint_db
        self._explicit_job_id = str(job_id) if job_id is not None else None
        self.job_id = self._explicit_job_id or str(uuid4())

        self.deepagents_runtime = DeepAgentsRuntime(skills=skills, sandbox=sandbox, job_id=self.job_id)

        self._prompts = self._load_prompts()
        self.tools_info = []
        for t in self.tools:
            self.tools_info.append({"name": t.name, "description": t.description})

        self.source_tool_names = {t.name for t in self.tools}
        self.source_registry_middleware = SourceRegistryMiddleware(source_tool_names=self.source_tool_names)
        self.source_tool_limiter = SourceToolConcurrencyLimiter(self.max_concurrent_source_tool_calls)
        batch_source_tools = build_batch_source_tools(
            self.tools,
            source_tool_names=self.source_tool_names,
            limiter=self.source_tool_limiter,
            max_batch_size=self.max_source_tool_batch_size,
        )
        self.research_source_tools = batch_source_tools.tools
        self.batched_source_tool_names = batch_source_tools.wrapped_tool_names

        # Create a tool that gives the orchestrator access to verified sources
        registry_middleware = self.source_registry_middleware

        @tool
        def get_verified_sources() -> str:
            """Returns the list of all verified source URLs captured from search tool calls.

            Call this tool during synthesis BEFORE writing the final answer. It
            returns every URL and citation key that was returned by search tools
            during research. Use ONLY these sources in your final answer
            — any other URL will be automatically removed.

            Returns:
                A numbered list of verified sources with titles and URLs.
            """
            source_list = registry_middleware.get_source_list_text()
            if source_list:
                return source_list
            return "No sources captured yet. Run research queries first."

        self.all_tools = [think, get_verified_sources, *self.tools]
        self.researcher_tools = [think, get_verified_sources, *self.research_source_tools]
        self.planner_tools = self.researcher_tools
        self.writer_tools = [think, get_verified_sources]
        self.researcher_middleware = self._build_middleware(
            exclude_source_throttle_tool_names=self.batched_source_tool_names
        )
        self.writer_middleware = self._build_writer_middleware()
        self.orchestrator_middleware = self._build_middleware(extra_valid_tool_names=["run_research_batch"])
        self.middleware = self.researcher_middleware

    def _load_prompts(self) -> dict[str, str]:
        """Load all prompts for subagents."""
        prompts = {}
        prompt_names = ["planner", "researcher", "orchestrator", "writer", "source_router"]

        for name in prompt_names:
            prompts[name] = load_prompt(AGENT_DIR / "prompts", name)

        return prompts

    def _build_middleware(
        self,
        *,
        extra_valid_tool_names: Sequence[str] = (),
        exclude_source_throttle_tool_names: Sequence[str] = (),
    ) -> list[Any]:
        """Build the common middleware stack with agent-specific tool-name sanitization."""
        return [
            EmptyContentFixMiddleware(),
            ToolNameSanitizationMiddleware(
                valid_tool_names=list({t.name for t in [*self.all_tools, *self.researcher_tools]})
                + list(extra_valid_tool_names)
            ),
            ToolConcurrencyMiddleware(
                tool_names=self.source_tool_names,
                limiter=self.source_tool_limiter,
                excluded_tool_names=set(exclude_source_throttle_tool_names),
            ),
            ToolRetryMiddleware(max_retries=3, backoff_factor=2.0, initial_delay=1.0),
            self.source_registry_middleware,
            ToolResultPruningMiddleware(keep_last_n=10, max_chars=2000),
            ModelRetryMiddleware(max_retries=2, backoff_factor=2.0, initial_delay=1.0),
        ]

    def _build_writer_middleware(self) -> list[Any]:
        """Build writer middleware."""
        return self._build_middleware()

    def _build_source_router_middleware(self, *, extra_valid_tool_names: Sequence[str] = ()) -> list[Any]:
        """Build minimal middleware for source-router-agent."""
        builtin_tool_names = {
            "edit_file",
            "glob",
            "ls",
            "read_file",
            "write_file",
        }
        return [
            EmptyContentFixMiddleware(),
            ToolNameSanitizationMiddleware(
                valid_tool_names=list({think.name, *builtin_tool_names, *extra_valid_tool_names})
            ),
            ToolRetryMiddleware(max_retries=3, backoff_factor=2.0, initial_delay=1.0),
            ModelRetryMiddleware(max_retries=2, backoff_factor=2.0, initial_delay=1.0),
        ]

    def _get_subagents(self, state: DeepResearchAgentState) -> list[dict[str, Any]]:
        """Build subagent configs with state-dependent prompts (e.g. available_documents)."""
        available_docs = [doc.model_dump() for doc in (state.available_documents or [])]
        source_catalog_tool = build_lookup_source_catalog_tool(
            self.tools,
            allowed_source_ids=state.data_sources,
            domain_catalog_path=self.domain_catalog_path,
        )
        source_router_agent: dict[str, Any] = {
            "name": "source-router-agent",
            "description": (
                "Source router - chooses an advisory domain route and configured source set before detailed planning"
            ),
            "system_prompt": render_prompt_template(
                self._prompts["source_router"],
                current_datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                user_info=state.user_info,
                clarifier_result=state.clarifier_result,
                available_documents=available_docs,
            ),
            "tools": [think, source_catalog_tool],
            "model": self.llm_provider.get(LLMRole.ROUTER),
            "middleware": self._build_source_router_middleware(extra_valid_tool_names=[source_catalog_tool.name]),
            "response_format": SourceRoutingPlan,
        }
        writer_skill_sources = self.deepagents_runtime.skill_sources_for("writer-agent")
        planner_agent: dict[str, Any] = {
            "name": "planner-agent",
            "description": (
                "Content-driven research planning - iteratively builds evidence-grounded "
                "answer strategies through interleaved search and planning"
            ),
            "system_prompt": render_prompt_template(
                self._prompts["planner"],
                current_datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                user_info=state.user_info,
                tools=self.tools_info,
                available_documents=available_docs,
            ),
            "tools": self.planner_tools,
            "model": self.llm_provider.get(LLMRole.PLANNER),
            "middleware": self.researcher_middleware,
            "response_format": ResearchPlan,
        }
        writer_tools_info = [{"name": t.name, "description": t.description} for t in self.writer_tools]
        writer_agent: dict[str, Any] = {
            "name": "writer-agent",
            "description": (
                "Final synthesis writer - reads the plan and research notes, then returns "
                "a cited Markdown answer in the requested output shape"
            ),
            "system_prompt": render_prompt_template(
                self._prompts["writer"],
                current_datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                user_info=state.user_info,
                tools=writer_tools_info,
                available_documents=available_docs,
            ),
            "tools": self.writer_tools,
            "model": self.llm_provider.get(LLMRole.REPORT_WRITER),
            "middleware": self.writer_middleware,
        }
        if writer_skill_sources is not None:
            writer_agent["skills"] = writer_skill_sources
        return [source_router_agent, planner_agent, writer_agent]

    def _build_orchestrator_agent(self, state: DeepResearchAgentState) -> str:
        """Get the orchestrator instructions for the deep research agent."""

        available_docs = [doc.model_dump() for doc in (state.available_documents or [])]
        researcher_skill_sources = self.deepagents_runtime.skill_sources_for("researcher")
        orchestrator_instructions = render_prompt_template(
            self._prompts["orchestrator"],
            current_datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            user_info=state.user_info,
            clarifier_result=state.clarifier_result,
            available_documents=available_docs,
            tools=self.tools_info,
        )

        researcher_runnable = build_researcher_runnable_impl(
            llm_provider=self.llm_provider,
            state=state,
            prompt_template=self._prompts["researcher"],
            tools_info=self.tools_info,
            current_datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            researcher_tools=self.researcher_tools,
            researcher_middleware=self.researcher_middleware,
            skill_sources=researcher_skill_sources,
            backend=self.deepagents_runtime.backend,
        )
        research_batch_tool = build_research_batch_tool_impl(
            researcher_runnable=researcher_runnable,
            callbacks=self.callbacks,
            backend=self.deepagents_runtime.backend,
            source_tool_names=self.source_tool_names,
            max_batch_research_queries=self.max_batch_research_queries,
            max_research_concurrency=self.max_research_concurrency,
            research_query_timeout_seconds=self.research_query_timeout_seconds,
            evidence_curator_model=(
                self.llm_provider.get(LLMRole.EVIDENCE_CURATOR) if self.evidence_reranking_enabled else None
            ),
            evidence_reranking_enabled=self.evidence_reranking_enabled,
        )
        orchestrator_tools = [*self.all_tools, research_batch_tool]

        agent = create_deep_agent(
            model=self.llm_provider.get(LLMRole.ORCHESTRATOR),
            tools=orchestrator_tools,
            system_prompt=orchestrator_instructions,
            subagents=self._get_subagents(state),
            store=InMemoryStore(),
            middleware=self.orchestrator_middleware,
            backend=self.deepagents_runtime.backend,
            checkpointer=self.checkpointer,
        )
        return agent.with_config({"recursion_limit": 1000})

    def _extract_final_markdown(self, result: dict | Any) -> str | None:
        """Extract final Markdown from explicit writer output or output files."""
        messages = result.get("messages") if isinstance(result, dict) else getattr(result, "messages", None)
        message_texts: list[tuple[str | None, str]] = []
        for message in messages or []:
            content = getattr(message, "content", "")
            text = content if isinstance(content, str) else str(content or "")
            message_texts.append((getattr(message, "type", None), text.strip()))

        for _, text in reversed(message_texts):
            try:
                output = WriterOutput.model_validate_json(text)
            except ValueError:
                continue
            answer = output.answer_markdown.strip()
            if answer:
                return answer

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

        try:
            downloads = self.deepagents_runtime.backend.download_files(["/shared/output.md"])
        except Exception:  # noqa: BLE001 - final text can still be returned from messages/files
            downloads = []
        for download in downloads:
            if download.error is None and download.content is not None:
                output_file = download.content.decode("utf-8").strip()
                if output_file:
                    return output_file

        return None

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

    def _log_runtime_intermediates(self, state: DeepResearchAgentState) -> None:
        """Log runtime file state when verbose debugging is enabled."""
        if not self.verbose or not logger.isEnabledFor(logging.DEBUG):
            return
        logger.debug("DeepAgents runtime prepared files: %s", sorted(state.files))

    async def _ensure_checkpointer(self) -> None:
        """Create the configured checkpointer before compiling the Deep Agents graph."""
        if self.checkpointer is None and self.checkpoint_db:
            self.checkpointer = await get_checkpointer(self.checkpoint_db)

    def _checkpoint_thread_id(self) -> str:
        """Return the stable thread ID used for Deep Agents checkpoints."""
        if self._explicit_job_id:
            return self._explicit_job_id
        try:
            from nat.builder.context import Context

            context = Context.get()
            return context.workflow_run_id or context.conversation_id or self.job_id
        except Exception:  # noqa: BLE001 - NAT context is absent in unit tests and direct runs
            return self.job_id

    async def _invoke_with_checkpoint_resume(self, agent: Any, state: DeepResearchAgentState) -> dict | Any:
        """Invoke the graph, resuming from checkpoints on workflow-level failures."""
        invoke_config: dict[str, Any] = {"configurable": {"thread_id": self._checkpoint_thread_id()}}
        if self.callbacks:
            invoke_config["callbacks"] = self.callbacks

        resume_existing = False
        if self.checkpointer is not None:
            try:
                snapshot = await agent.aget_state(invoke_config)
                tasks = getattr(snapshot, "tasks", ()) or ()
                resume_existing = bool(tasks)
            except Exception:
                logger.debug("Could not inspect existing Deep Research checkpoint; starting fresh", exc_info=True)
            if resume_existing:
                logger.info(
                    "Resuming Deep Research workflow from existing checkpoint (thread_id=%s)",
                    invoke_config["configurable"]["thread_id"],
                )

        resume_attempts = self.max_workflow_resume_attempts if self.checkpointer is not None else 0
        for attempt in range(resume_attempts + 1):
            graph_input = None if resume_existing or attempt > 0 else state
            try:
                return await agent.ainvoke(graph_input, config=invoke_config)
            except Exception:
                if attempt >= resume_attempts:
                    raise

                try:
                    snapshot = await agent.aget_state(invoke_config)
                    tasks = getattr(snapshot, "tasks", ()) or ()
                except Exception:
                    logger.warning("Deep Research Subagent failed before a checkpoint could be loaded", exc_info=True)
                    raise

                if not tasks:
                    logger.warning("Deep Research Subagent failed without resumable checkpoint tasks", exc_info=True)
                    raise

                task_names = [getattr(task, "name", "<unknown>") for task in tasks]
                logger.warning(
                    "Deep Research Subagent failed; resuming from checkpoint "
                    "(attempt %d/%d, thread_id=%s, pending_tasks=%s)",
                    attempt + 1,
                    resume_attempts,
                    invoke_config["configurable"]["thread_id"],
                    task_names,
                    exc_info=True,
                )

        raise RuntimeError("unreachable workflow resume state")

    async def run(self, state: DeepResearchAgentState) -> DeepResearchAgentState:
        """
        Execute deep research with multi-phase workflow.
        """
        await self._ensure_checkpointer()
        state = self.deepagents_runtime.prepare_state(state)
        self._log_runtime_intermediates(state)
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
            result = await self._invoke_with_checkpoint_resume(agent, state)

            final_message = self._extract_final_markdown(result)
            if final_message is None:
                raise ValueError("writer-agent did not produce a final Markdown answer")

            # Post-process: verify citations against source registry
            if self.source_registry_middleware._get_registry().all_sources():
                registry = self.source_registry_middleware._get_registry()
                verification = verify_citations(final_message, registry)
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
                    raise ValueError("writer-agent output contains no valid citations")
            else:
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
            try:
                uploads = self.deepagents_runtime.backend.upload_files(
                    [("/shared/report.md", final_message.encode("utf-8"))]
                )
                errors = [f"{upload.path}: {upload.error}" for upload in uploads if upload.error]
                if errors:
                    logger.warning("Failed to persist /shared/report.md: %s", "; ".join(errors))
            except Exception as ex:  # noqa: BLE001 - final message remains the source of truth
                logger.warning("Failed to persist /shared/report.md: %s", ex)

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

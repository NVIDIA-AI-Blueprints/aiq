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

"""NAT register function for chat researcher agent."""

import asyncio
import logging
from typing import Any

import aiofiles
from langchain_core.messages import HumanMessage
from pydantic import Field

from aiq_agent.common import VerboseTraceCallback
from aiq_agent.common import _create_chat_response
from aiq_agent.common import format_data_source_tools
from aiq_agent.common import get_checkpointer
from aiq_agent.common import is_verbose
from aiq_agent.common.citation_verification import get_or_create_session_registry
from aiq_agent.common.citation_verification import reset_session_registry
from aiq_agent.common.citation_verification import set_session_registry
from aiq_agent.observability.otel_header_redaction_exporter import (
    ensure_registered as _ensure_otel_redaction_registered,
)
from nat.builder.builder import Builder
from nat.builder.context import Context
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.api_server import ChatResponse
from nat.data_models.component_ref import FunctionGroupRef
from nat.data_models.component_ref import FunctionRef
from nat.data_models.component_ref import LLMRef
from nat.data_models.function import FunctionBaseConfig

from .models import ChatResearcherState
from .utils import _extract_query_context

logger = logging.getLogger(__name__)

# Upper bound on the single bounded report-ask LLM call so a stalled provider
# degrades to a graceful message instead of blocking the whole chat turn.
_REPORT_ASK_TIMEOUT_S = 120

_ensure_otel_redaction_registered()


def _build_report_ask_prompt(
    *,
    question: str,
    report_markdown: str,
    source_summary_markdown: str,
) -> str:
    """Build a bounded QA prompt for questions against an existing report."""

    return (
        "Answer using only the parent report and source summary below. "
        "If the answer is not supported by the parent report, say that the report does not contain enough "
        "information to answer. Keep the answer concise and preserve citations when referencing report claims.\n\n"
        f"Question:\n{question}\n\n"
        f"Parent source summary:\n{source_summary_markdown}\n\n"
        f"Parent report:\n{report_markdown}"
    )


async def _answer_from_report_context(
    llm: Any,
    *,
    question: str,
    report_markdown: str,
    source_summary_markdown: str,
) -> str:
    """Answer a question strictly from parent report context with one bounded LLM call.

    This deliberately does NOT use the shallow/deep research agents or any data-source
    tools: report ask must stay bounded to the parent report and never trigger live
    research (Core Invariant: "answer from parent report context only").
    """
    prompt = _build_report_ask_prompt(
        question=question,
        report_markdown=report_markdown,
        source_summary_markdown=source_summary_markdown,
    )
    try:
        response = await asyncio.wait_for(llm.ainvoke([HumanMessage(content=prompt)]), timeout=_REPORT_ASK_TIMEOUT_S)
    except TimeoutError:
        logger.warning("Report ask LLM call timed out after %ss", _REPORT_ASK_TIMEOUT_S)
        return "The report service took too long to respond. Please try again."
    content = response.content if hasattr(response, "content") else response
    answer = content if isinstance(content, str) else str(content)
    if not answer.strip():
        return "The report does not contain enough information to answer."
    return answer


async def _resolve_effective_report_job_id(
    request_active_id: str | None,
    conversation_id: str | None,
    principal: Any,
    *,
    is_input_mode: bool,
) -> str | None:
    """Resolve which report a follow-up turn should target.

    A client-supplied ``active_report_job_id`` always wins. Otherwise default to the most recent
    completed report in THIS conversation, so any client (CLI, API, UI on reload) gets report
    follow-up without having to track the id. Only falls back for a real, client-supplied
    conversation id — never for --input or server-generated thread ids. Any lookup failure
    degrades silently to None (fresh research).
    """
    if request_active_id:
        return request_active_id
    if is_input_mode or not conversation_id:
        return None
    try:
        import os

        from aiq_api.jobs.access import get_latest_report_job_for_conversation

        db_url = os.environ.get("NAT_JOB_STORE_DB_URL", "sqlite:///./data/jobs.db")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, get_latest_report_job_for_conversation, conversation_id, principal, db_url
        )
    except Exception as e:
        logger.debug("Report-job fallback lookup failed: %s", type(e).__name__)
        return None


########################################################
# Intent Classifier
########################################################


class IntentClassifierConfig(FunctionBaseConfig, name="intent_classifier"):
    """Configuration for the combined orchestration node (intent + meta response + depth)."""

    llm: LLMRef = Field(..., description="LLM to use")
    tools: list[FunctionRef | FunctionGroupRef] = Field(
        default_factory=list,
        description="Explicit tool list. Empty = inherit all from data_source_registry.",
    )
    exclude_tools: list[str] = Field(
        default_factory=list,
        description="Tool names to exclude when inheriting from registry.",
    )
    verbose: bool = Field(default=False)
    llm_timeout: float = Field(
        default=90,
        description="Timeout in seconds for the intent-classification LLM call. Default 90 if not set.",
    )


@register_function(config_type=IntentClassifierConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def intent_classifier(config: IntentClassifierConfig, builder: Builder):
    """Combined orchestration: classifies intent, produces meta response, and routes depth in one node."""
    from .nodes import IntentClassifier

    llm = await builder.get_llm(config.llm, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

    if config.tools:
        tool_refs = config.tools
    else:
        from aiq_agent.common import get_all_tool_refs

        tool_refs = get_all_tool_refs()

    tools = await builder.get_tools(tool_names=tool_refs, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

    if config.exclude_tools:
        excluded = set(config.exclude_tools)
        tools = [t for t in tools if getattr(t, "name", "") not in excluded]

    verbose = is_verbose(config.verbose)
    callbacks = [VerboseTraceCallback()] if verbose else []

    tools_info = [{"name": getattr(t, "name", str(t)), "description": getattr(t, "description", "")} for t in tools]
    classifier = IntentClassifier(
        llm=llm,
        tools_info=tools_info,
        callbacks=callbacks,
        llm_timeout=config.llm_timeout,
    )

    async def _run(state: ChatResearcherState) -> dict[str, Any]:
        if state.data_sources is not None:
            classifier.tools_info = format_data_source_tools(state.data_sources)
        return await classifier.run(state)

    yield FunctionInfo.from_fn(
        _run,
        description="Orchestration: intent classification, meta response, and depth routing.",
    )


########################################################
# Chat Deep Researcher Agent
########################################################
class ChatDeepResearcherConfig(FunctionBaseConfig, name="chat_deepresearcher_agent"):
    """Configuration for the chat deep researcher orchestrator agent."""

    enable_escalation: bool = Field(default=False, description="Enable escalation from shallow to deep research")
    max_history: int = Field(
        default=20, description="Maximum number of messages to keep in history before invoking the agent"
    )
    verbose: bool = Field(default=False, description="Enable verbose logging")
    enable_clarifier: bool = Field(default=False, description="Enable clarification of research queries")
    use_async_deep_research: bool = Field(
        default=False,
        description="Submit deep research as an async job instead of running inline",
    )
    checkpoint_db: str = Field(
        default="./checkpoints.db",
        description="SQLite database path or Postgres DSN for persistent checkpoints.",
    )


@register_function(config_type=ChatDeepResearcherConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def chat_deepresearcher_agent(config: ChatDeepResearcherConfig, builder: Builder):
    """
    Chat deep researcher orchestrator agent.

    Coordinates intent classification, depth routing, and research agents
    to produce research results based on user queries.
    """
    import os
    import sys
    from pathlib import Path

    # Validate API keys early by checking the config file
    # This works for both nat run and interactive CLI
    config_file_path = None

    # Try to get config file path from environment (set by NAT framework)
    config_file_path = os.environ.get("NAT_CONFIG_FILE")

    # If not in env, try to extract from sys.argv (for nat run --config_file)
    if not config_file_path:
        try:
            if "--config_file" in sys.argv:
                idx = sys.argv.index("--config_file")
                if idx + 1 < len(sys.argv):
                    config_file_path = sys.argv[idx + 1]
        except (ValueError, IndexError):
            pass

    # Validate API keys early by checking the config file
    # Store error response to return in _run function if keys are missing
    api_key_error_response = None
    if config_file_path and Path(config_file_path).exists():
        try:
            import yaml

            async with aiofiles.open(config_file_path, encoding="utf-8") as f:
                raw = await f.read()
                config_dict = yaml.safe_load(raw)

            from aiq_agent.common.config_validation import validate_llm_configs

            is_valid, missing_keys = validate_llm_configs(config_dict)
            if not is_valid:
                error_msg = (
                    f"❌ ERROR: Missing Required API Keys\n\n"
                    f"Missing keys: {', '.join(missing_keys)}\n\n"
                    f"Cannot start workflow without required API keys.\n\n"
                    f"To fix this:\n"
                    f"  1. Set these keys in your .env file or environment variables\n"
                    f"  2. Restart the application"
                )
                logger.error("Missing required API keys: %s", ", ".join(missing_keys))
                # Create the error response here to avoid duplication
                api_key_error_response = _create_chat_response(error_msg, response_id="api_key_error")
        except Exception as e:
            # If validation fails for other reasons (e.g., file can't be read), log but don't block
            logger.debug(f"Failed to validate API keys from config: {e}")

    from aiq_agent.common import filter_tools_by_sources

    from .agent import ChatResearcherAgent

    workflow_id = config.name or config.type
    intent_classifier_fn = await builder.get_function("intent_classifier")
    shallow_research_fn = await builder.get_function("shallow_research_agent")
    deep_research_fn = await builder.get_function("deep_research_agent")
    clarifier_fn = await builder.get_function("clarifier_agent") if config.enable_clarifier else None

    # Get deep research tools for early validation
    deep_research_config = builder.get_function_config("deep_research_agent")
    if deep_research_config.tools:
        deep_tool_refs = deep_research_config.tools
    else:
        from aiq_agent.common import get_all_tool_refs

        deep_tool_refs = get_all_tool_refs()
    deep_research_tools = await builder.get_tools(tool_names=deep_tool_refs, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
    if deep_research_config.exclude_tools:
        excluded = set(deep_research_config.exclude_tools)
        deep_research_tools = [t for t in deep_research_tools if getattr(t, "name", "") not in excluded]

    # Create a validation function to check if deep research tools are available
    def validate_deep_research_tools(data_sources: list[str] | None) -> tuple[bool, str]:
        """
        Validate that at least one deep research tool is available.

        Returns:
            Tuple of (is_valid, error_message). If is_valid is False, error_message contains the reason.
        """
        from aiq_agent.common import format_tool_unavailability_error
        from aiq_agent.common import validate_tool_availability

        selected_tools = filter_tools_by_sources(deep_research_tools, data_sources)

        is_valid, _, unavailable_tools = validate_tool_availability(
            selected_tools, research_type="deep research", enable_logging=False
        )

        if not is_valid:
            error_msg = format_tool_unavailability_error("deep research", unavailable_tools)
            return False, error_msg

        return True, ""

    verbose = is_verbose(config.verbose)
    callbacks = [VerboseTraceCallback()] if verbose else []

    # LLM for inline report Q&A: prefer the report writer model, fall back to the
    # deep researcher's orchestrator LLM (always configured). Report ask is a single
    # bounded LLM call and must never run the tool-enabled research agents.
    report_qa_llm = await builder.get_llm(
        deep_research_config.writer_llm or deep_research_config.orchestrator_llm,
        wrapper_type=LLMFrameworkEnum.LANGCHAIN,
    )

    deep_research_job_submitter = None
    # Wired to the async submitter only when a Dask scheduler is available; otherwise edit runs
    # inline via report_edit_fn (synchronous CLI).
    report_edit_job_submitter = None

    async def _resolve_report_context_for_state(state: ChatResearcherState):
        from aiq_api.jobs.access import require_verified_principal
        from aiq_api.jobs.report_context import report_context_from_markdown
        from aiq_api.jobs.report_context import resolve_authorized_report_context

        # Precedence: an explicit job id (UI/server) wins; otherwise use the report produced
        # inline in this session (synchronous CLI), which needs no job store / scheduler.
        if state.active_report_job_id:
            # Same auth contract as the HTTP report endpoints: synthesizes a no-auth principal
            # when REQUIRE_AUTH=false (the public default), a verified principal otherwise.
            principal = require_verified_principal()
            return await resolve_authorized_report_context(state.active_report_job_id, principal)
        if state.last_report_markdown:
            return report_context_from_markdown(state.last_report_markdown)
        raise RuntimeError("Report follow-up requires an active report")

    async def _answer_report_question(state: ChatResearcherState) -> str:
        from aiq_agent.common import get_latest_user_query

        report_context = await _resolve_report_context_for_state(state)
        question = get_latest_user_query(state.messages)
        return await _answer_from_report_context(
            report_qa_llm,
            question=question,
            report_markdown=report_context.report_markdown,
            source_summary_markdown=report_context.source_summary_markdown,
        )

    async def _submit_report_edit_job(state: ChatResearcherState) -> str:
        from aiq_agent.auth import get_auth_token
        from aiq_agent.common import get_latest_user_query
        from aiq_api.jobs.access import require_verified_principal
        from aiq_api.jobs.report_context import report_output_metadata
        from aiq_api.jobs.report_context import to_initial_files
        from aiq_api.jobs.submit import submit_agent_job

        report_context = await _resolve_report_context_for_state(state)
        instruction = get_latest_user_query(state.messages)
        principal = require_verified_principal()
        return await submit_agent_job(
            agent_type="report_rewriter",
            input_text=instruction,
            owner=principal.email or principal.sub,
            principal=principal,
            data_sources=[],
            auth_token=get_auth_token(),
            initial_files=to_initial_files(report_context, instruction=instruction),
            output_metadata=report_output_metadata(report_context.parent_job_id, "edit"),
            allow_internal=True,
        )

    async def _inline_report_edit(state: ChatResearcherState) -> str:
        """Rewrite the in-session report inline (synchronous CLI, no scheduler/job).

        Mirrors the report_rewriter job's single bounded LLM call, sourced from the in-session
        report (or, if present, the explicit job-backed report) resolved by the same precedence
        as report ask.
        """
        from aiq_agent.agents.report_rewriter.agent import rewrite_report
        from aiq_agent.common import get_latest_user_query

        report_context = await _resolve_report_context_for_state(state)
        instruction = get_latest_user_query(state.messages)
        return await rewrite_report(
            llm=report_qa_llm,
            original_report=report_context.report_markdown,
            edit_instruction=instruction,
            source_summary=report_context.source_summary_markdown,
            parent_context=report_context.model_dump_json(indent=2, exclude={"report_markdown"}),
        )

    async def _build_report_seed_files(state: ChatResearcherState) -> dict[str, str]:
        """Seed files for an inline delta: the parent report context as DeepAgents FS files."""
        from aiq_api.jobs.report_context import to_initial_files

        report_context = await _resolve_report_context_for_state(state)
        return to_initial_files(report_context)

    if config.use_async_deep_research:
        import os

        # Check if Dask scheduler is available
        scheduler_address = os.environ.get("NAT_DASK_SCHEDULER_ADDRESS")
        if scheduler_address:
            from aiq_agent.auth import get_auth_token
            from aiq_agent.auth import get_current_principal
            from aiq_api.jobs.submit import submit_agent_job

            async def _submit_deep_job(state: ChatResearcherState) -> str:
                principal = get_current_principal()
                owner = principal.email if principal and principal.email else "anonymous"
                query = state.original_query
                if not query:
                    if not state.messages:
                        raise RuntimeError("Cannot submit deep research job without messages.")
                    query = state.messages[0].content
                input_text = query if isinstance(query, str) else str(query)
                if state.clarifier_result:
                    input_text = f"{input_text}\n\n## Clarification Context\n{state.clarifier_result}"

                # Serialize available_documents for the Dask worker
                available_docs = None
                if state.available_documents:
                    available_docs = [doc.model_dump() for doc in state.available_documents]
                    logger.debug(
                        "Passing %d available documents to deep research job",
                        len(available_docs),
                    )

                initial_files = None
                output_metadata = None
                if state.active_report_job_id and state.user_intent and state.user_intent.use_parent_report_context:
                    from aiq_api.jobs.report_context import report_output_metadata
                    from aiq_api.jobs.report_context import to_initial_files

                    report_context = await _resolve_report_context_for_state(state)
                    initial_files = to_initial_files(report_context)
                    output_metadata = report_output_metadata(report_context.parent_job_id, "research")

                return await submit_agent_job(
                    agent_type="deep_researcher",
                    input_text=input_text,
                    owner=owner,
                    principal=principal,
                    available_documents=available_docs,
                    data_sources=state.data_sources,
                    auth_token=get_auth_token(),
                    initial_files=initial_files,
                    output_metadata=output_metadata,
                )

            deep_research_job_submitter = _submit_deep_job
            report_edit_job_submitter = _submit_report_edit_job
        else:
            logger.info(
                "use_async_deep_research is enabled but NAT_DASK_SCHEDULER_ADDRESS is not set. "
                "Falling back to synchronous deep research execution."
            )

    checkpointer = await get_checkpointer(config.checkpoint_db)

    agent = ChatResearcherAgent(
        intent_classifier_fn=intent_classifier_fn.ainvoke,
        shallow_research_fn=shallow_research_fn.ainvoke,
        deep_research_fn=deep_research_fn.ainvoke,
        clarifier_fn=clarifier_fn.ainvoke if clarifier_fn else None,
        enable_clarifier=config.enable_clarifier,
        enable_escalation=config.enable_escalation,
        callbacks=callbacks,
        max_history=config.max_history,
        deep_research_job_submitter=deep_research_job_submitter,
        report_ask_fn=_answer_report_question,
        report_edit_job_submitter=report_edit_job_submitter,
        report_edit_fn=_inline_report_edit,
        report_seed_files_fn=_build_report_seed_files,
        checkpointer=checkpointer,
        validate_deep_research_tools_fn=validate_deep_research_tools,
    )

    async def _run(query: object) -> ChatResponse:
        import os
        import sys
        import uuid

        # Check if API keys are missing and return graceful error response
        if api_key_error_response:
            # Exit after error message when --input is provided
            if "--input" in sys.argv:
                import threading
                import time

                def exit_after_error():
                    time.sleep(0.2)
                    os._exit(1)

                threading.Thread(target=exit_after_error, daemon=False).start()

            return api_key_error_response

        # For --input mode, use a fresh conversation_id to avoid loading old checkpoint state
        # This ensures each run starts with a clean conversation history
        if "--input" in sys.argv:
            nat_context_conversation_id = str(uuid.uuid4())
            logger.info("Using fresh conversation ID for --input mode: %s", nat_context_conversation_id)
        else:
            nat_context_conversation_id = Context.get().conversation_id
            if not nat_context_conversation_id:
                nat_context_conversation_id = str(uuid.uuid4())
                logger.info("No conversation-id header; generated thread ID: %s", nat_context_conversation_id)
            else:
                logger.info("Thread ID for checkpointing: %s", nat_context_conversation_id)

        from aiq_agent.auth import get_current_principal

        principal = get_current_principal()
        user_info_dict = None
        if principal:
            logger.debug("User authenticated")
            user_info_dict = {
                "name": principal.name,
                "email": principal.email,
            }

        # Decide whether to skip the clarifier for this request.
        # 1. Config (enable_clarifier=false) — operator disabled it entirely.
        # 2. aiq_api.auth.middleware ContextVar — covers X-AIQ-Mode: headless,
        #    anonymous callers, and unauthenticated internal callers.
        skip_clarifier = not config.enable_clarifier
        if not skip_clarifier:
            try:
                from aiq_api.auth.middleware import get_current_user as _get_mw_user

                if _get_mw_user().get("skip_clarifier"):
                    skip_clarifier = True
            except (ImportError, Exception):
                pass
        logger.info("skip_clarifier=%s", skip_clarifier)

        request_context = _extract_query_context(query)
        query_text = request_context.query_text
        data_sources = request_context.data_sources
        logger.info("ChatDeepResearcherAgent: %s", query_text)
        logger.info("ChatDeepResearcherAgent: Data sources: %s", data_sources)

        # Fetch available documents with summaries from SQLite registry
        # The registry is populated by backends during ingestion (backend-agnostic)
        available_documents = None
        try:
            from aiq_agent.knowledge import get_available_documents_async

            # Get collection from session context (conversation_id = collection_name)
            collection_name = Context.get().conversation_id if Context.get() else None

            if collection_name:
                available_documents = await get_available_documents_async(collection_name)
                if available_documents:
                    logger.info(
                        "Loaded %d document summaries from DB for collection %s",
                        len(available_documents),
                        collection_name,
                    )
                    for doc in available_documents:
                        logger.debug("  [summary] [file]: %s", "available" if doc.summary else "none")
                else:
                    logger.info("No document summaries in DB for collection %s", collection_name)
            else:
                logger.debug("No session context - cannot determine collection")
        except Exception as e:
            logger.warning("Could not fetch available documents: %s", e)
        # Resolve the report to follow up on: client-supplied id wins, else default to the last
        # completed report in this conversation (server-side, so any client gets follow-up).
        _ctx = Context.get()
        client_conversation_id = _ctx.conversation_id if _ctx else None
        effective_report_job_id = await _resolve_effective_report_job_id(
            request_context.active_report_job_id,
            client_conversation_id,
            principal,
            is_input_mode="--input" in sys.argv,
        )
        if effective_report_job_id and not request_context.active_report_job_id:
            logger.info("Defaulting report follow-up to last report %s in conversation", effective_report_job_id)

        # Set session-scoped source registry for citation verification across turns.
        # When no conversation ID is available, get_or_create_session_registry returns a
        # fresh per-request registry to prevent anonymous sessions from sharing state.
        session_registry = get_or_create_session_registry(nat_context_conversation_id)
        token = set_session_registry(session_registry)
        try:
            state = ChatResearcherState(
                messages=[HumanMessage(content=query_text)],
                user_info=user_info_dict,
                data_sources=data_sources,
                available_documents=available_documents,
                skip_clarifier=skip_clarifier,
                active_report_job_id=effective_report_job_id,
            )
            result = await agent.run(state, thread_id=nat_context_conversation_id)
        finally:
            reset_session_registry(token)

        if isinstance(result, dict):
            messages = result.get("messages", [])
        else:
            messages = getattr(result, "messages", [])

        if messages:
            response_content = messages[-1].content
        else:
            response_content = "No response generated."
        # return _create_chat_response(response_content, response_id="research_response")

        # Exit after response when --input is provided
        if "--input" in sys.argv:
            import threading
            import time

            def exit_after_response():
                time.sleep(0.2)
                os._exit(0)

            threading.Thread(target=exit_after_response, daemon=False).start()

        return _create_chat_response(response_content, response_id="research_response", model=workflow_id)

    yield FunctionInfo.from_fn(_run, description="Chat deep researcher with intent routing and escalation.")

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

import logging
from typing import Any

from langchain_core.messages import HumanMessage
from pydantic import Field

from aiq_agent.common import VerboseTraceCallback
from aiq_agent.common import _create_chat_response
from aiq_agent.common import format_data_source_tools
from aiq_agent.common import get_checkpointer
from aiq_agent.common import is_verbose
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
from .utils import _extract_query_and_sources

logger = logging.getLogger(__name__)

_ensure_otel_redaction_registered()


########################################################
# Intent Classifier
########################################################


class IntentClassifierConfig(FunctionBaseConfig, name="intent_classifier"):
    """Configuration for the combined orchestration node (intent + meta response + depth)."""

    llm: LLMRef = Field(..., description="LLM to use")
    tools: list[FunctionRef | FunctionGroupRef] = Field(default_factory=list)
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
    tools = await builder.get_tools(tool_names=config.tools, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
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

            with open(config_file_path, encoding="utf-8") as f:
                config_dict = yaml.safe_load(f)

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

    intent_classifier_fn = await builder.get_function("intent_classifier")
    shallow_research_fn = await builder.get_function("shallow_research_agent")
    deep_research_fn = await builder.get_function("deep_research_agent")
    clarifier_fn = await builder.get_function("clarifier_agent") if config.enable_clarifier else None

    # Get deep research tools for early validation
    deep_research_config = builder.get_function_config("deep_research_agent")
    deep_research_tools = await builder.get_tools(
        tool_names=deep_research_config.tools, wrapper_type=LLMFrameworkEnum.LANGCHAIN
    )

    # Create a validation function to check if deep research tools are available
    async def validate_deep_research_tools(data_sources: list[str] | None) -> tuple[bool, str]:
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

    deep_research_job_submitter = None
    if config.use_async_deep_research:
        import os

        # Check if Dask scheduler is available
        scheduler_address = os.environ.get("NAT_DASK_SCHEDULER_ADDRESS")
        if scheduler_address:
            from aiq_api.jobs import submit_agent_job

            from aiq_agent.auth import get_current_user_info

            async def _submit_deep_job(state: ChatResearcherState) -> str:
                user_info = await get_current_user_info()
                owner = user_info.email if user_info and user_info.email else "anonymous"
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

                return await submit_agent_job(
                    agent_type="deep_researcher",
                    input_text=input_text,
                    owner=owner,
                    available_documents=available_docs,
                    data_sources=state.data_sources,
                )

            deep_research_job_submitter = _submit_deep_job
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
            logger.info("Thread ID for checkpointing: %s", nat_context_conversation_id)

        from aiq_agent.auth import get_current_user_info

        user_info = await get_current_user_info()
        user_info_dict = None
        if user_info:
            logger.debug("User authenticated")
            user_info_dict = {
                "name": user_info.name,
                "email": user_info.email,
            }

        query_text, data_sources = _extract_query_and_sources(query)
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
        state = ChatResearcherState(
            messages=[HumanMessage(content=query_text)],
            user_info=user_info_dict,
            data_sources=data_sources,
            available_documents=available_documents,
        )
        result = await agent.run(state, thread_id=nat_context_conversation_id)

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

        return _create_chat_response(response_content, response_id="research_response")

    yield FunctionInfo.from_fn(_run, description="Chat deep researcher with intent routing and escalation.")

# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""NAT workflow loader + invoker used by the FastMCP tool handlers.

Owns the long-lived `load_workflow(...)` context manager so the compiled
LangGraph is built once at server startup and reused across tool calls. Exposes
two operations:

- :meth:`classify` invokes the ``intent_classifier`` NAT function directly to
  decide whether a query is shallow or deep (and surface any meta response).
  Used synchronously in ``submit_query`` to return a depth hint to the caller.
- :meth:`run_query` runs the full ``chat_deepresearcher_agent`` workflow to
  produce the final research answer. Called from the background task that the
  JobManager launches.
"""

import inspect
import logging
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from aiq_agent.common.logging_utils import log_identifier_ref
from nat.builder.context import Context
from nat.runtime.loader import load_workflow
from nat.runtime.session import SessionManager

logger = logging.getLogger(__name__)


class WorkflowRunner:
    """Lifespan-scoped wrapper around a NAT workflow loaded from YAML."""

    def __init__(self, config_file: str | Path):
        self._config_file = Path(config_file)
        self._exit_stack: AsyncExitStack | None = None
        self._session_manager: SessionManager | None = None
        self._owned_checkpointer_keys: set[str] = set()

    async def start(self) -> None:
        if self._session_manager is not None:
            return
        logger.info("Loading NAT workflow from %s", self._config_file)
        checkpointers_before = _current_checkpointer_keys()
        self._exit_stack = AsyncExitStack()
        self._session_manager = await self._exit_stack.enter_async_context(load_workflow(str(self._config_file)))
        self._owned_checkpointer_keys = _current_checkpointer_keys() - checkpointers_before
        logger.info("NAT workflow ready")

    async def stop(self) -> None:
        if self._exit_stack is None:
            return
        logger.info("Shutting down NAT workflow")
        try:
            await self._exit_stack.aclose()
        finally:
            await self._close_owned_checkpointers()
            self._exit_stack = None
            self._session_manager = None

    async def _close_owned_checkpointers(self) -> None:
        if not self._owned_checkpointer_keys:
            return
        try:
            from aiq_agent import common as aiq_common
        except Exception as exc:  # pragma: no cover - defensive shutdown path
            logger.debug("Unable to import aiq_agent.common for checkpointer cleanup: %s", exc)
            self._owned_checkpointer_keys.clear()
            return

        checkpointers = getattr(aiq_common, "_checkpointers", {})
        postgres_pools = getattr(aiq_common, "_postgres_pools", {})
        for key in list(self._owned_checkpointer_keys):
            checkpointer = checkpointers.pop(key, None)
            conn = getattr(checkpointer, "conn", None)
            if conn is not None:
                close = getattr(conn, "close", None)
                if close is not None:
                    await _maybe_await(close())
                    logger.debug("Closed SQLite checkpointer connection: %s", key)

            pool = postgres_pools.pop(key, None)
            if pool is not None:
                await _maybe_await(pool.close())
                logger.debug("Closed Postgres checkpointer pool: %s", key)

        self._owned_checkpointer_keys.clear()

    async def classify(self, query: str) -> dict[str, Any]:
        """Run the intent classifier node as a standalone call.

        Returns a dict containing ``user_intent`` and ``depth_decision`` keys,
        and possibly ``messages`` when the intent is meta.
        """
        if self._session_manager is None:
            raise RuntimeError("WorkflowRunner.start() must be called before classify()")

        from langchain_core.messages import HumanMessage

        from aiq_agent.agents.chat_researcher.models import ChatResearcherState

        intent_fn = await self._session_manager.shared_builder.get_function("intent_classifier")
        state = ChatResearcherState(messages=[HumanMessage(content=query)])
        return await intent_fn.ainvoke(state)

    async def run_query(
        self,
        query: str,
        *,
        conversation_id: str,
    ) -> str:
        """Run the full workflow.

        ``conversation_id`` is also LangGraph's checkpoint ``thread_id``; MCP
        async jobs pass their ``job_id`` so NAT resume/checkpoint state lines up
        with the MCP job ledger.
        """
        if self._session_manager is None:
            raise RuntimeError("WorkflowRunner.start() must be called before run_query()")

        logger.info("Running NAT workflow: conversation_ref=%s", log_identifier_ref(conversation_id))

        with Context.scope(conversation_id=conversation_id):
            async with self._session_manager.session(conversation_id=conversation_id) as session:
                async with session.run(query) as runner:
                    result = await runner.result(to_type=str)

        return result


def _current_checkpointer_keys() -> set[str]:
    try:
        from aiq_agent import common as aiq_common
    except Exception:
        return set()
    return set(getattr(aiq_common, "_checkpointers", {}).keys())


async def _maybe_await(value: Any) -> None:
    if inspect.isawaitable(value):
        await value

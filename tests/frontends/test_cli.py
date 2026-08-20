# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from aiq_research_cli import cli


@pytest.mark.asyncio
async def test_interactive_loop_flushes_relay_before_display_and_next_prompt(monkeypatch) -> None:
    events: list[str] = []
    responses = iter(["research this", "q"])

    async def prompt_async(*args, **kwargs):  # noqa: ARG001
        events.append("prompt")
        return next(responses)

    async def flush_async() -> None:
        events.append("flush")

    class Runner:
        async def result(self, *, to_type):  # noqa: ARG002
            events.append("result")
            return "answer"

    class Session:
        @asynccontextmanager
        async def run(self, user_input):  # noqa: ARG002
            yield Runner()
            events.append("run-exit")

    class SessionManager:
        @asynccontextmanager
        async def session(self, *, user_input_callback):  # noqa: ARG002
            yield Session()

    monkeypatch.setattr(cli.prompt_session, "prompt_async", prompt_async)
    monkeypatch.setattr(cli.nemo_relay.subscribers, "flush_async", flush_async)
    monkeypatch.setattr(cli.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "parse_and_display_response", lambda *args, **kwargs: events.append("display"))
    monkeypatch.setattr(
        cli.ContextState,
        "get",
        lambda: SimpleNamespace(conversation_id=SimpleNamespace(set=lambda value: None)),
    )

    await cli.interactive_loop(SessionManager(), verbose=True)

    assert events == ["prompt", "result", "run-exit", "flush", "display", "prompt"]

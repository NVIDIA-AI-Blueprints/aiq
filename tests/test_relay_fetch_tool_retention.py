# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

"""Pin the Relay retention contract documented for the web fetch tool.

``sources/tavily_web_fetch/README.md`` tells operators that the URL they let the tool fetch and the
page content it returns are retained by Relay and exported wherever Relay exports, and it names the
controls that change that. Those are claims about the running system, not about this module, so the
module's own logger tests cannot support them: they would keep passing if Relay's behavior changed
underneath the documentation.

These tests drive the real tool through the real Relay runtime, write a real ATOF trace, and read
it back looking for two canaries -- a credential-shaped token in the requested URL, and a marker in
the page body. Both must be found by default and both must disappear under the control the README
points at, so the documentation fails with the system rather than drifting away from it.
"""

import contextlib
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from langchain_core.tools import StructuredTool

from aiq_agent.relay.bootstrap import ensure_started
from aiq_agent.relay.bootstrap import shutdown_async
from aiq_agent.relay.config import RelayConfig
from aiq_agent.relay.privacy import request_privacy_context
from aiq_agent.relay.runtime import ainvoke_tool_with_relay
from aiq_agent.relay.runtime import run_workflow

# A signed download URL is the case the README warns about: the credential is in the URL itself, so
# it is carried by the tool input rather than by anything a detector would recognize as a secret.
URL_TOKEN = "sig-canary-0a1b2c3d4e5f"  # pragma: allowlist secret
FETCH_URL = f"https://files.example/quarterly.pdf?expires=1799999999&signature={URL_TOKEN}"
PAGE_CANARY = "page-content-canary-do-not-export"
PAGE_BODY = f"first line {PAGE_CANARY}\nsecond line"


@pytest.fixture
def fetch_tool(monkeypatch):
    """Return the real fetch tool wired to a stubbed extraction provider."""
    module = types.ModuleType("langchain_tavily")
    instance = MagicMock()
    instance.ainvoke = AsyncMock(
        return_value={"results": [{"url": FETCH_URL, "title": "Quarterly", "raw_content": PAGE_BODY, "images": []}]}
    )
    module.TavilyExtract = MagicMock(return_value=instance)
    monkeypatch.setitem(sys.modules, "langchain_tavily", module)
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")  # pragma: allowlist secret


async def _fetch_under_relay(tmp_path: Path, filename: str, *, configure=None, privacy: bool | None = False) -> str:
    """Fetch one page through Relay and return the exported ATOF trace."""
    from tavily_web_fetch.register import FetchUrlInput
    from tavily_web_fetch.register import TavilyWebFetchToolConfig
    from tavily_web_fetch.register import tavily_web_fetch

    config = RelayConfig()
    config.logging = False
    config.observability.atof.output_directory = str(tmp_path)
    config.observability.atof.filename = filename
    config.observability.opentelemetry.enabled = False
    if configure:
        configure(config)

    await ensure_started(config)
    try:
        async with tavily_web_fetch(TavilyWebFetchToolConfig(), None) as info:

            async def _fetch(urls: list[str]) -> str:
                return await info.single_fn(FetchUrlInput(urls=urls))

            # Relay observes tools through its middleware, so the call has to go through it the way
            # a workflow's does; invoking the function directly would bypass what is being pinned.
            tool = StructuredTool.from_function(coroutine=_fetch, name="fetch_url_tool", description="Fetch a page.")

            async def operation():
                return await ainvoke_tool_with_relay(tool, {"urls": [FETCH_URL]})

            # None leaves the surrounding request context in charge, so a caller that bound
            # trace tags is exercising its own decision rather than this one.
            with contextlib.ExitStack() as stack:
                if privacy is not None:
                    stack.enter_context(request_privacy_context(privacy))
                await run_workflow("fetch-retention", operation, input_value="fetch-retention-input")
    finally:
        await shutdown_async()

    exported = tmp_path / filename
    return exported.read_text(encoding="utf-8") if exported.exists() else ""


async def _fetch_with_request_tags(tmp_path: Path, filename: str, tags: dict[str, str]) -> str:
    """Fetch one page with request trace tags bound the way the API middleware binds them."""
    from aiq_api.auth.request_trace import request_trace_tag_context

    # request_trace_tag_context is what middleware.py wraps every request in; it derives the
    # privacy decision from the tags rather than taking it as an argument.
    with request_trace_tag_context(tags):
        return await _fetch_under_relay(tmp_path, filename, privacy=None)


class TestFetchToolRelayRetention:
    async def test_the_url_and_the_page_content_are_retained_by_default(self, tmp_path, fetch_tool):
        """The README's central disclosure: with stock settings, both are in the trace."""
        exported = await _fetch_under_relay(tmp_path, "default.jsonl")

        assert URL_TOKEN in exported, "the signed-URL token the README warns about was not retained"
        assert PAGE_CANARY in exported, "returned page content was not retained"

    async def test_request_privacy_removes_both(self, tmp_path, fetch_tool):
        """The control the README points operators at has to actually remove this data."""
        exported = await _fetch_under_relay(tmp_path, "private.jsonl", privacy=True)

        assert URL_TOKEN not in exported
        assert PAGE_CANARY not in exported
        # The trace is still written, so the assertions above are not passing on an empty file.
        assert "fetch-retention" in exported

    async def test_request_privacy_is_inert_when_redaction_is_disabled(self, tmp_path, fetch_tool):
        """Pin the dependency between the two settings, because it fails open.

        Request privacy is implemented by sanitizers that are only registered when
        ``redaction.enabled`` is true. Turning redaction off therefore silently disarms the header
        as well: the request still asks for privacy and the payloads are still exported. An
        operator reading the two settings as independent would get the opposite of what they
        intended, so the README states the dependency and this holds it in place.
        """

        def disable_redaction(config: RelayConfig) -> None:
            config.redaction.enabled = False

        exported = await _fetch_under_relay(tmp_path, "inert.jsonl", configure=disable_redaction, privacy=True)

        assert URL_TOKEN in exported
        assert PAGE_CANARY in exported

    async def test_full_payloads_disabled_does_not_remove_them(self, tmp_path, fetch_tool):
        """Pin the negative claim, so the README cannot quietly become wrong.

        ``enable_full_payloads`` reads like the control for this and is documented generally as
        preserving inputs and outputs for export, but AI-Q passes tool payloads to Relay as
        explicit scope values, which it does not govern. Turning it off leaves the URL and the page
        content in the trace. The README says so; if that ever stops being true, this test fails
        and the wording gets revisited rather than staying misleading in the other direction.
        """

        def disable_full_payloads(config: RelayConfig) -> None:
            config.observability.enable_full_payloads = False

        exported = await _fetch_under_relay(tmp_path, "nofull.jsonl", configure=disable_full_payloads)

        assert URL_TOKEN in exported
        assert PAGE_CANARY in exported

    async def test_the_documented_header_is_what_turns_request_privacy_on(self, tmp_path, fetch_tool):
        """Close the gap between what operators are told to send and what the tests exercise.

        The other tests here enter ``request_privacy_context`` directly, which is the internal
        switch. What the documentation tells an operator to do is send a header. This walks the
        path the served API walks -- header to trace tag to privacy decision to redacted trace --
        so the instruction in the README is the thing under test.
        """
        from aiq_api.auth.utils import TRACE_REDACTION_HEADER
        from aiq_api.auth.utils import build_request_trace_tags

        def tags_for(header_value: bytes | None) -> dict[str, str]:
            headers = {b"host": b"localhost"}
            if header_value is not None:
                headers[TRACE_REDACTION_HEADER.encode()] = header_value
            return build_request_trace_tags(
                headers,
                {"type": "http", "headers": [], "client": ("127.0.0.1", 1234)},
                {"type": "user", "verified": True},
                trust_access_channel_override=False,
                user_identity_mode="none",
                user_identity_secret=None,
                client_id_mode="none",
                client_id_secret=None,
                client_ip_headers=[],
            )

        assert tags_for(b"true").get("aiq.telemetry.redact") == "true"
        assert "aiq.telemetry.redact" not in tags_for(None)

        # The tag alone is inert; binding it to the request is what arms the sanitizers.
        redacted = await _fetch_with_request_tags(tmp_path, "header-on.jsonl", tags_for(b"true"))
        assert URL_TOKEN not in redacted
        assert PAGE_CANARY not in redacted

        retained = await _fetch_with_request_tags(tmp_path, "header-off.jsonl", tags_for(None))
        assert URL_TOKEN in retained
        assert PAGE_CANARY in retained

    async def test_disabling_atof_writes_no_trace_file(self, tmp_path, fetch_tool):
        """The other documented control: no local sink, no local retention."""

        def disable_atof(config: RelayConfig) -> None:
            config.observability.atof.enabled = False

        exported = await _fetch_under_relay(tmp_path, "off.jsonl", configure=disable_atof)

        assert exported == ""
        assert not (tmp_path / "off.jsonl").exists()

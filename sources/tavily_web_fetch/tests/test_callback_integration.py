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

"""End-to-end checks that the provider adapter never emits citation artifacts of its own.

``test_register.py`` covers the parser path: what
``citation_verification.extract_sources_from_tool_result`` is willing to return for a rendered
result. That is not the only way a URL becomes a source. AI-Q's event callback runs a second,
independent pipeline -- it watches LangChain tool runs, decides a tool produces URLs by matching
its *name* against a substring set that includes ``tavily``, and scrapes every URL out of the raw
result into durable ``citation_source`` artifacts. Nothing in that pipeline consults the parser
registry or the run ledger.

The provider adapter this tool calls is named ``tavily_extract`` and returns whole pages, so if it
ran as a visible tool the callback would register every hyperlink inside a fetched page as a source
the agent never read. These tests drive the real callback to prove it does not.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from tavily_web_fetch.register import FetchUrlInput
from tavily_web_fetch.register import TavilyWebFetchToolConfig
from tavily_web_fetch.register import tavily_web_fetch

# The callback lives in the API frontend package, which is a workspace sibling rather than a
# dependency of this one. Skip rather than fail when the tool is tested outside an AI-Q install.
callbacks_module = pytest.importorskip("aiq_api.jobs.callbacks")

AgentEventCallback = callbacks_module.AgentEventCallback

# The reviewer's reproduction, kept verbatim: fetching the first page returns a body whose only
# hyperlink is the second, which is never fetched and must never become a source.
FETCHED_URL = "https://example.com/"
OUTBOUND_URL = "https://iana.org/domains/example"
PAGE_BODY = f'Example Domain. More information at <a href="{OUTBOUND_URL}">{OUTBOUND_URL}</a>.'

RAW_RESPONSE: dict[str, Any] = {
    "results": [{"url": FETCHED_URL, "title": "Example Domain", "raw_content": PAGE_BODY, "images": []}],
    "failed_results": [],
}


class _RecordingExtract:
    """Stand-in built as a real LangChain tool so callback inheritance actually happens.

    The ``fake_tavily`` fixture swaps in a ``MagicMock``, which is enough to assert on the payload
    but cannot answer the question these tests ask: a mock has no callback machinery, so it would
    report "no events emitted" whether or not the adapter is suppressed. Only a genuine ``BaseTool``
    resolves a run config and fires ``on_tool_start`` / ``on_tool_end``.
    """

    def __new__(cls, **kwargs):
        """Build the tool class lazily so importing this module does not require LangChain."""
        from langchain_core.tools import BaseTool

        class _Extract(BaseTool):
            name: str = "tavily_extract"
            description: str = "Extract page content."
            extract_depth: str = "advanced"

            def _run(self, urls, extract_depth=None, **_):
                raise NotImplementedError("the tool is only called asynchronously")

            async def _arun(self, urls, extract_depth=None, **_):
                return RAW_RESPONSE

        return _Extract(**kwargs)


@pytest.fixture
def real_tavily(monkeypatch):
    """Install a genuine LangChain tool as ``langchain_tavily.TavilyExtract``."""
    import sys
    import types

    module = types.ModuleType("langchain_tavily")
    module.TavilyExtract = _RecordingExtract
    monkeypatch.setitem(sys.modules, "langchain_tavily", module)
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")  # pragma: allowlist secret


@pytest.fixture
def recorded_events():
    """Return a (callback, events) pair whose events list mirrors what would be persisted."""
    event_store = MagicMock()
    # A real store carries a job id that keys process-global URL caches. Leaving it unset keeps
    # each test on its own instance-level cache so one test's URLs cannot mask another's.
    event_store.job_id = None
    callback = AgentEventCallback(event_store=event_store)

    def events():
        return [call.args[0] for call in event_store.store.call_args_list]

    return callback, events


def _citation_source_urls(events):
    """Return the URLs of every durable citation_source artifact in the event list."""
    urls = []
    for event in events:
        if event.get("type") != "artifact.update":
            continue
        data = event.get("data") or {}
        if data.get("type") == "citation_source":
            urls.append(data.get("url") or data.get("content"))
    return urls


async def _fetch_under_callback(callback, urls):
    """Invoke the tool the way a workflow does, with the callback set on the surrounding run."""
    from langchain_core.runnables import RunnableLambda

    async with tavily_web_fetch(TavilyWebFetchToolConfig(), None) as info:
        # A workflow does not hand callbacks to the tool directly; LangChain puts them in a
        # contextvar that anything running underneath picks up. Running through a RunnableLambda
        # reproduces that, so the adapter has a real opportunity to inherit them.
        async def _run(payload):
            return await info.single_fn(FetchUrlInput(urls=payload))

        return await RunnableLambda(_run).ainvoke(urls, config={"callbacks": [callback]})


class TestProviderAdapterIsInvisible:
    async def test_an_outbound_link_in_page_content_never_becomes_a_citation_source(self, real_tavily, recorded_events):
        """The link the page points at was never fetched, so nothing may register it."""
        callback, events = recorded_events

        output = await _fetch_under_callback(callback, [FETCHED_URL])

        assert OUTBOUND_URL not in _citation_source_urls(events())
        # The page really was read; the assertion above is not passing because nothing happened.
        assert "Example Domain" in output

    async def test_the_adapter_reports_no_tool_lifecycle_of_its_own(self, real_tavily, recorded_events):
        """Pin the mechanism, not just the symptom.

        Asserting only on the missing citation would still pass if a future LangChain release
        changed how a run config merges and quietly re-enabled inheritance while some unrelated
        detail suppressed the artifact. Requiring the adapter to emit no lifecycle events at all
        fails loudly the moment it becomes visible again.
        """
        callback, events = recorded_events

        await _fetch_under_callback(callback, [FETCHED_URL])

        assert not [
            event
            for event in events()
            if event.get("type") in {"tool.start", "tool.end"} and event.get("name") == "tavily_extract"
        ]

    async def test_the_same_adapter_left_visible_does_leak(self, real_tavily, recorded_events):
        """Positive control: the harness can see the failure it is guarding against.

        This drives the adapter the way the tool used to -- inheriting the run's callbacks -- and
        shows the outbound link becoming a durable source. Without it, the tests above would keep
        passing if the harness silently stopped observing anything.
        """
        callback, events = recorded_events
        extractor = _RecordingExtract(extract_depth="advanced")

        await extractor.ainvoke(
            {"urls": [FETCHED_URL], "extract_depth": "advanced"},
            config={"callbacks": [callback]},
        )

        assert OUTBOUND_URL in _citation_source_urls(events())

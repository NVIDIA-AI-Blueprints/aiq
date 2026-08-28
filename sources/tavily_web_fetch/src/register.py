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

"""Register a tool that opens HTTP(S) pages through Tavily Extract.

The adapter does not forward ``query`` because extraction must remain complete before local windowing. It also
detects soft 404 pages and handles the ``AttributeError`` raised by ``langchain_tavily`` for string error payloads.
"""

import asyncio
import hashlib
import logging
import os
import re
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel
from pydantic import Field
from pydantic import SecretStr

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

from .formatting import WRAP_WIDTH
from .formatting import FetchedPage
from .formatting import compact
from .formatting import looks_like_our_output
from .formatting import render_page_section
from .formatting import render_result
from .formatting import render_skipped_section
from .formatting import select_window

if TYPE_CHECKING:
    from aiq_agent.common.citation_verification import SourceEntry

logger = logging.getLogger(__name__)

_missing_key_warned = False
_parser_registered = False

# Which pages each workflow run read, as {run id: {exact result returned: pages read}}.
#
# Ownership has to answer "did an invocation belonging to *this* workflow produce this result?",
# and neither half of what parser dispatch hands us can answer it. The tool name cannot: the
# parser is registered process-globally and two concurrent workflows may use the same YAML key for
# different tools, so a name-based check lets either vouch for the other's output. The content
# cannot either: any string can be replayed by whoever has seen it, so a check that reduces to
# "some invocation somewhere once produced these bytes" is a process-wide bearer token.
#
# The run id supplies the missing identity. NAT mints one per workflow run and contextvars are
# inherited by the tasks a run spawns, so an invocation and the citation middleware that later
# inspects its result read the same value, while a concurrent run reads a different one. Scoping
# the ledger by it makes a record unreachable outside the run that created it -- replayed bytes
# included. Within a run the result string then selects which record applies, and the citable URLs
# come from that record rather than from re-reading the text.
#
# Both levels are bounded because nothing else prunes them. Capture runs immediately after the
# tool returns, in the same middleware that awaited it, so a record only has to outlive that
# hand-off.
_RUN_LEDGER_MAX = 32
_OUTPUTS_PER_RUN_MAX = 256
_run_ledgers: OrderedDict[str, OrderedDict[str, list[tuple[str, str]]]] = OrderedDict()
_ledger_lock = threading.Lock()

_SOFT_404_MARKERS = (
    "page not found",
    "404 not found",
    "page cannot be found",
    "page could not be found",
    "page you requested could not be found",
    "page doesn't exist",
    "page does not exist",
    "no longer exists",
    "error 404",
)
_SOFT_404_MAX_CHARS = 6000


class FetchUrlInput(BaseModel):
    """Model-facing input schema for exact URLs and local content windowing."""

    urls: list[str] = Field(
        ...,
        description=(
            "Exact, complete URLs to open, for example "
            "['https://www.iea.nl/sites/default/files/ICILS_2023_report.pdf']. NOT search "
            "keywords - every item must start with http:// or https://. Pass several URLs to open "
            "them in one call."
        ),
    )
    query: str | None = Field(
        default=None,
        description=(
            "Optional. What you are looking for on these pages, for example 'table 2.2 computer "
            "literacy by country'. Used ONLY to choose which part of a long page to show you. It "
            "does not search the web and does not change which pages are opened."
        ),
    )
    start_line: int = Field(
        default=0,
        ge=0,
        description=(
            "Optional. Line number to resume from when continuing a page that was truncated; the "
            "truncation note tells you which line to pass. Applies to every URL in this call."
        ),
    )


class TavilyWebFetchToolConfig(FunctionBaseConfig, name="tavily_web_fetch"):
    """Configuration for opening web pages with Tavily Extract."""

    max_urls_per_call: int = Field(default=4, ge=1, description="Maximum URLs accepted in one call")
    max_chars_per_page: int = Field(
        default=10000,
        ge=WRAP_WIDTH,
        description=(
            "Maximum characters shown per page. This is a prompt-context budget, not a download "
            "limit: pages are extracted in full and then windowed. The floor is one wrapped line, "
            "so a window always holds at least one whole line."
        ),
    )
    max_chars_per_call: int = Field(
        default=24000,
        ge=WRAP_WIDTH,
        description="Maximum characters shown across all URLs in one call, spent in request order.",
    )
    extract_depth: Literal["basic", "advanced"] = Field(
        default="advanced",
        description="Tavily extraction depth: 'basic' or 'advanced'.",
    )
    timeout_seconds: int = Field(default=30, ge=1, description="Per-call extraction timeout")
    api_key: SecretStr | None = Field(default=None, description="API key for the Tavily service")


def _validate_url(candidate: str) -> tuple[str, str]:
    """Return a normalized HTTP(S) URL or a model-facing validation error."""
    text = (candidate or "").strip()
    if not text:
        return "", "Empty URL. Pass a complete address starting with http:// or https://."

    parsed = urlparse(text)
    # Check the scheme first so non-web schemes receive an explicit refusal rather than search guidance.
    if parsed.scheme and parsed.scheme not in ("http", "https"):
        return "", (
            f"Only http:// and https:// URLs can be opened (got '{parsed.scheme}://'). This tool reads web pages only."
        )
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "", (
            f'"{text[:120]}" is not a URL. This tool opens pages you already have the address for; '
            "use web_search_tool to find one first, then pass the URL it returns."
        )
    return text, ""


def _looks_like_soft_404(text: str) -> bool:
    """Return whether short extracted content resembles a soft 404 page."""
    if not text or len(text) > _SOFT_404_MAX_CHARS:
        return False
    lowered = re.sub(r"\s+", " ", text.lower())
    return any(marker in lowered for marker in _SOFT_404_MARKERS)


def _page_from_result(requested: str, result: dict) -> FetchedPage:
    """Build a fetched page from one Tavily result."""
    text = compact((result.get("raw_content") or "").strip())
    final_url = (result.get("url") or requested).strip()
    title = (result.get("title") or "").strip()

    if not text:
        return FetchedPage(
            url=requested,
            status="failed",
            reason="Could not read this page: the extractor returned no content for it.",
        )
    if _looks_like_soft_404(text):
        return FetchedPage(
            url=requested,
            final_url=final_url,
            title=title,
            text=text,
            status="suspect",
            reason=(
                "[Caution: this looks like a 'page not found' page rather than the document you "
                "asked for. Do not cite it. Search for the current location of this page instead.]"
            ),
        )
    return FetchedPage(url=requested, final_url=final_url, title=title, text=text, status="ok")


def _exact_key(url: str) -> str:
    """Return a strict comparison key for one URL.

    Scheme and host are case-insensitive per RFC 3986, so lowercasing them lets a provider that
    echoes a normalized host still match the request. Path, query, and fragment keep their case
    because they address distinct resources.
    """
    text = url.strip()
    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return text
    return parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower()).geturl()


def _relaxed_key(url: str) -> str:
    """Return a comparison key that also ignores one trailing slash on the path.

    Stripping slashes off the whole URL would reach into the query and fragment, where a slash is
    an ordinary character: it would make ``?redirect=/`` and ``?redirect=`` the same key, and the
    fallback would then serve one request the other's content. Only the path is relaxed, and only
    by a single slash, so ``/a//`` and ``/a/`` stay distinct too.
    """
    parsed = urlparse(_exact_key(url))
    path = parsed.path[:-1] if parsed.path.endswith("/") else parsed.path
    return parsed._replace(path=path).geturl()


def _digest(content: str) -> str:
    """Return the within-run ledger key for one rendered result."""
    return hashlib.sha256(content.encode("utf-8", "surrogatepass")).hexdigest()


def _current_run_id() -> str | None:
    """Return the NAT workflow run this call belongs to, or ``None`` outside a run.

    NAT sets this once per run -- ``NatRunner`` mints a UUID when a request carries none, and the
    AI-Q job runner sets it to the job id -- so it names the workflow instance rather than the
    process. Reading it from the ambient context is what lets ownership be established without the
    parser API carrying an identity argument.
    """
    try:
        from nat.builder.context import Context

        return Context.get().workflow_run_id
    except Exception:  # noqa: BLE001 - no NAT context means no run to scope ownership to
        return None


def _record_output(rendered: str, citable: list[tuple[str, str]]) -> None:
    """Record the pages one invocation read, under the run that invoked it.

    A call outside any NAT run records nothing. There is no session to scope ownership to, so
    keeping the record would put it where every other run could reach it -- which is the bearer
    token this design exists to avoid. Every path that serves a workflow (``nat run``, ``nat
    serve``, ``nat eval``, the async job runner) establishes a run id first.
    """
    run_id = _current_run_id()
    if run_id is None:
        logger.debug("tavily_web_fetch: no workflow run in context; fetched pages will not be citable")
        return

    key = _digest(rendered)
    with _ledger_lock:
        ledger = _run_ledgers.setdefault(run_id, OrderedDict())
        _run_ledgers.move_to_end(run_id)
        ledger[key] = citable
        ledger.move_to_end(key)
        while len(ledger) > _OUTPUTS_PER_RUN_MAX:
            ledger.popitem(last=False)
        while len(_run_ledgers) > _RUN_LEDGER_MAX:
            _run_ledgers.popitem(last=False)


def _recorded_pages(content: str) -> list[tuple[str, str]] | None:
    """Return the pages this run recorded for this exact result, or ``None`` if there is no record.

    Another run's record is not consulted even when the bytes match, so replaying a result
    captured from a different workflow finds nothing.
    """
    run_id = _current_run_id()
    if run_id is None:
        return None

    key = _digest(content)
    with _ledger_lock:
        ledger = _run_ledgers.get(run_id)
        if ledger is None:
            return None
        recorded = ledger.get(key)
        if recorded is not None:
            _run_ledgers.move_to_end(run_id)
            ledger.move_to_end(key)
    return recorded


def _parse_owned_pages(content: str, tool_name: str) -> "list[SourceEntry] | None":
    """Return citations only for a result this workflow run's own invocations produced.

    Ownership is settled by the run-scoped ledger, not by the tool name and not by the content:
    only an invocation belonging to this run can put a record there, and the URLs come from that
    record rather than from parsing the text back out. A result another run produced is not ours
    even byte for byte, so replaying one earns nothing.

    An unrecorded result is normally declined with ``None`` so its own parser, or the generic URL
    extractor, still handles it with its sources intact. The exception is a result wearing our
    preamble that we have no record of -- a forgery, or output altered between the tool and the
    registry. Declining that would hand it to the generic extractor, which reads every URL in the
    body, so it is claimed and yields nothing instead. Fail closed: a page the agent read may lose
    its citation, but no page it never read gains one.
    """
    recorded = _recorded_pages(content)
    if recorded is None:
        return [] if looks_like_our_output(content) else None

    try:
        from aiq_agent.common.citation_verification import SourceEntry
    except ImportError:  # pragma: no cover - package used outside an AI-Q install
        return []

    return [
        SourceEntry(url=url, title=title or None, source_type="url", tool_name=tool_name) for url, title in recorded
    ]


async def _extract(tool, urls: list[str], *, extract_depth: str, timeout_seconds: int) -> tuple[list[dict], str]:
    """Call Tavily Extract without relevance filtering and return results or an error."""
    try:
        # Do not forward query: local windowing must operate on the complete extraction so misses are recoverable.
        payload = {"urls": urls, "extract_depth": extract_depth}
        response = await asyncio.wait_for(tool.ainvoke(payload), timeout=timeout_seconds)
    except TimeoutError:
        return [], f"the extraction service did not respond within {timeout_seconds} seconds"
    except AttributeError:
        # langchain_tavily calls .get() on bare string errors instead of returning them.
        return [], "the extraction service returned an error response"
    except Exception as exc:  # noqa: BLE001 - tools return errors rather than raising into the agent
        logger.warning("tavily_web_fetch extraction failed: %s", type(exc).__name__)
        return [], f"the extraction request failed ({type(exc).__name__})"

    if isinstance(response, str):
        return [], "the extraction service returned an error response"
    if not isinstance(response, dict) or response.get("error"):
        return [], "the extraction service returned an error response"
    results = response.get("results")
    return (results if isinstance(results, list) else []), ""


@register_function(config_type=TavilyWebFetchToolConfig)
async def tavily_web_fetch(tool_config: TavilyWebFetchToolConfig, builder: Builder):
    """Register the Tavily web fetch tool with NAT."""
    from langchain_tavily import TavilyExtract

    if not os.environ.get("TAVILY_API_KEY") and tool_config.api_key:
        os.environ["TAVILY_API_KEY"] = tool_config.api_key.get_secret_value()

    if not os.environ.get("TAVILY_API_KEY"):
        global _missing_key_warned
        if not _missing_key_warned:
            logger.warning("TAVILY_API_KEY not found. Page fetching will return an error until the key is configured.")
            _missing_key_warned = True

        async def _fetch_url_stub(urls: list[str], query: str | None = None, start_line: int = 0) -> str:
            """Page fetch tool (unavailable - missing TAVILY_API_KEY)."""
            return (
                "Error: Page fetching is unavailable because TAVILY_API_KEY is not set. "
                "Set the key and restart the application."
            )

        yield FunctionInfo.from_fn(
            _fetch_url_stub,
            input_schema=FetchUrlInput,
            description=_fetch_url_stub.__doc__,
        )
        return

    # Replace the generic URL scraper so outbound links do not become sources the agent never read.
    # The matcher accepts every name because the operator picks the YAML key and the name carries
    # no authority anyway; ``_parse_owned_pages`` settles ownership against the ledger instead.
    # Every other tool's output is declined with None and falls through to the next parser or the
    # generic extractor with its own sources intact.
    global _parser_registered
    if not _parser_registered:
        try:
            from aiq_agent.common.citation_verification import register_source_parser

            register_source_parser(lambda _name: True, _parse_owned_pages)
            _parser_registered = True
        except ImportError:  # pragma: no cover - package used outside an AI-Q install
            logger.debug("aiq_agent not importable; skipping source-parser registration")

    extractor = TavilyExtract(extract_depth=tool_config.extract_depth)

    async def _fetch_url(urls: list[str], query: str | None = None, start_line: int = 0) -> str:
        """Opens web pages you already have the URL for and returns their text.

        This is a READER, not a FINDER. Give it exact URLs to read full page content instead of
        truncated search snippets.

        USE THIS TOOL WHEN:
        - The question supplies a URL or names a specific page, report, filing, table, or PDF.
        - A search result looks relevant and you need its exact numbers, rows, dates, or wording.

        DO NOT USE THIS TOOL WHEN:
        - You do not have a URL. Call web_search_tool first, then open the result.
        - You would pass keywords, a question, or a site name instead of a URL.

        Search finds pages; fetch_url_tool opens a selected page. The normal loop is search, pick
        a URL, then fetch it.

        Examples:
            urls=["https://pmc.ncbi.nlm.nih.gov/articles/PMC9506306/"]
            web_search_tool("ICILS 2023 report") -> URL; then pass that URL with query="table 2.2"
            WRONG: urls=["maple syrup production by state 2017"]

        Args:
            urls: Exact, complete URLs to open. Not search terms.
            query: Optional text used only to select a window within long pages.
            start_line: Optional line from which to continue a truncated page.

        Returns:
            One section per URL with page text or a reason the page could not be read.
        """
        requested = list(urls or [])
        if not requested:
            return (
                "Error: No URLs provided. Pass one or more exact URLs, for example "
                "urls=['https://www.example.gov/report']. To find a URL first, use web_search_tool."
            )
        if len(requested) > tool_config.max_urls_per_call:
            return (
                f"Error: this tool accepts at most {tool_config.max_urls_per_call} URLs per call; "
                f"received {len(requested)}. Split them across calls, most important first."
            )

        valid: list[str] = []
        pages: dict[str, FetchedPage] = {}
        for candidate in requested:
            normalized, reason = _validate_url(candidate)
            if reason:
                pages[candidate] = FetchedPage(url=candidate, status="failed", reason=reason)
            # A URL repeated in one call would otherwise be extracted, billed, and rendered twice.
            elif normalized not in valid:
                valid.append(normalized)

        if valid:
            results, error = await _extract(
                extractor,
                valid,
                extract_depth=tool_config.extract_depth,
                timeout_seconds=tool_config.timeout_seconds,
            )
            entries = [item for item in results if isinstance(item, dict)]
            by_exact = {_exact_key(str(item.get("url", ""))): item for item in entries}

            # A relaxed key is only safe to use when it identifies one result and one requested
            # URL. Two requests differing solely by a trailing slash share a relaxed key, and
            # letting either borrow the other's result would cite content it never returned.
            relaxed_results: dict[str, list[dict]] = {}
            for item in entries:
                relaxed_results.setdefault(_relaxed_key(str(item.get("url", ""))), []).append(item)
            relaxed_requests: dict[str, set[str]] = {}
            for url in valid:
                relaxed_requests.setdefault(_relaxed_key(url), set()).add(_exact_key(url))

            for url in valid:
                match = by_exact.get(_exact_key(url))
                if match is None:
                    relaxed = _relaxed_key(url)
                    candidates = relaxed_results.get(relaxed, [])
                    if len(candidates) == 1 and len(relaxed_requests[relaxed]) == 1:
                        match = candidates[0]
                if match is not None:
                    pages[url] = _page_from_result(url, match)
                elif error:
                    pages[url] = FetchedPage(url=url, status="failed", reason=f"Could not read this page: {error}.")
                else:
                    pages[url] = FetchedPage(
                        url=url,
                        status="failed",
                        reason=(
                            "Could not read this page: the extractor returned nothing for this URL. "
                            "It may be unreachable, blocked, or not a readable document."
                        ),
                    )

        sections: list[str] = []
        remaining = tool_config.max_chars_per_call
        any_success = False
        rendered: set[str] = set()
        # The pages this call genuinely read and showed, in the order they were rendered. This
        # list -- not the rendered text -- is what the citation registry is later handed.
        citable: list[tuple[str, str]] = []
        cited: set[str] = set()
        for candidate in requested:
            page = pages.get(candidate) or pages.get((candidate or "").strip())
            if page is None:  # pragma: no cover - every requested URL receives a result above
                continue
            # A URL repeated in one call has a single result. Rendering it again would spend the
            # call budget on content the model already has in this same output.
            if page.url in rendered:
                continue
            rendered.add(page.url)
            if page.status == "failed":
                sections.append(render_page_section(page, None))
                continue

            any_success = True
            budget = min(tool_config.max_chars_per_page, remaining)
            # Skip rather than render a sliver: a window narrower than one wrapped line could not
            # hold a whole line, and windowing never splits one.
            if budget < WRAP_WIDTH:
                sections.append(render_skipped_section(page, max_chars_per_call=tool_config.max_chars_per_call))
                continue
            window = select_window(page.text, max_chars=budget, query=query or "", start_line=start_line)
            remaining -= window.shown_chars
            sections.append(render_page_section(page, window))
            # Only a page shown in full confidence is citable: failures never reach here, skipped
            # pages returned above, and a suspect soft 404 is content the model was told not to
            # cite. Two requested URLs can redirect to one resolved page, so dedupe on that.
            if page.status == "ok" and page.citable_url not in cited:
                cited.add(page.citable_url)
                citable.append((page.citable_url, page.title))

        if not any_success:
            # The prefix keeps a wholly failed fetch non-citable and feeds the source-tool circuit breaker.
            reasons = "\n".join(
                f"- {page.url}: {page.reason}" for page in (pages.get(url) for url in requested) if page
            )
            return f"Error: none of the requested URLs could be read.\n{reasons}"

        result = render_result(sections)
        # Record before returning. The registry resolves ownership by looking this exact string
        # up, so the record has to exist by the time the caller can hand the string over.
        _record_output(result, citable)
        return result

    yield FunctionInfo.from_fn(
        _fetch_url,
        input_schema=FetchUrlInput,
        description=_fetch_url.__doc__,
    )

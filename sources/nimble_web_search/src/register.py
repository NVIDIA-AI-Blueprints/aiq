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

import asyncio
import html
import logging
import os
from collections.abc import AsyncGenerator
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field
from pydantic import SecretStr

from nat.builder.builder import Builder
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)

_missing_key_warned = False


class NimbleWebSearchToolConfig(FunctionBaseConfig, name="nimble_web_search"):
    """
    Tool that retrieves relevant contexts from web search (using Nimble) for the given question.
    Requires a NIMBLE_API_KEY environment variable or api_key config.
    """

    max_results: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Maximum number of search results to return (Nimble accepts 1-100).",
    )
    api_key: SecretStr | None = Field(default=None, description="The API key for the Nimble service")
    max_retries: int = Field(
        default=3, ge=1, le=10, description="Maximum number of retries for the search request (1-10)."
    )
    search_depth: Literal["lite", "fast", "deep"] = Field(
        default="lite",
        description=(
            "Nimble search depth. 'lite' returns metadata only and is the safe default. "
            "'fast' is an Enterprise-tier feature and raises a 403 ToolException on "
            "non-enterprise accounts. 'deep' returns full page content."
        ),
    )
    # Mirrors langchain-nimble's SearchFocus modes (general, news, location,
    # shopping, geo, social). Declared locally because the SDK does not export
    # the enum publicly; swap for a direct import if it becomes public.
    focus: Literal["general", "news", "location", "shopping", "geo", "social"] = Field(
        default="general",
        description=(
            "Nimble search focus mode. 'general' (default) covers broad web/research "
            "queries and is the right choice for almost all agent use. 'news' restricts "
            "results to news-publisher sources ordered by recency (it is not a recency "
            "filter -- older articles still appear); the rest are domain-specific "
            "(location, shopping, geo, social). Leave as 'general' unless the tool is "
            "dedicated to one of those."
        ),
    )
    country: str = Field(
        default="US",
        description="ISO 3166 country code passed to Nimble (e.g. 'US', 'GB', 'FR').",
    )
    locale: str = Field(
        default="en",
        description="Language/locale passed to Nimble (e.g. 'en', 'fr', 'es').",
    )
    max_content_length: int | None = Field(
        default=10000,
        ge=1,
        description=(
            "Max characters per result's page content. Truncates each result to reduce "
            "token usage. Set to None to disable truncation."
        ),
    )


@register_function(config_type=NimbleWebSearchToolConfig)
async def nimble_web_search(
    tool_config: NimbleWebSearchToolConfig,
    builder: Builder,
) -> AsyncGenerator[FunctionInfo, None]:
    """Register the Nimble web search tool with NAT.

    Wraps ``langchain_nimble.NimbleSearchRetriever`` in a NAT function so agents
    can query the Nimble Search API. If ``NIMBLE_API_KEY`` is not available
    (via environment or ``tool_config.api_key``), a stub function is registered
    that returns an informative error instead of failing at import time.

    Args:
        tool_config: Configuration controlling result count, retries, search
            depth, geographic filters, and optional content truncation.
        builder: NAT builder handle (unused; accepted for interface parity).

    Yields:
        A ``FunctionInfo`` wrapping either the live Nimble search callable or
        the missing-key stub.
    """
    from langchain_nimble import NimbleSearchRetriever

    # Resolve the key from config or environment. A config-supplied key is passed
    # straight to the retriever below (never written to os.environ), so the secret
    # does not enter process-global state where it could leak to child processes.
    api_key = tool_config.api_key

    if api_key is None and not os.environ.get("NIMBLE_API_KEY"):
        global _missing_key_warned
        if not _missing_key_warned:
            logger.warning(
                "NIMBLE_API_KEY not found. The web search tool will be registered but will "
                "return an error when called. To enable: set NIMBLE_API_KEY in your environment, "
                ".env file, or specify api_key in your workflow config."
            )
            _missing_key_warned = True

        async def _nimble_web_search_stub(question: str) -> str:
            """Web search tool (unavailable - missing NIMBLE_API_KEY)."""
            return (
                "Error: Nimble web search is unavailable because NIMBLE_API_KEY is not set.\n"
                "To enable this tool:\n"
                "1. Get an API key from https://nimbleway.com/\n"
                "2. Set the API key in your environment or in your .env file\n"
                "3. Restart the application"
            )

        yield FunctionInfo.from_fn(
            _nimble_web_search_stub,
            description=_nimble_web_search_stub.__doc__,
        )
        return

    # The constructor kwargs below (max_results / search_depth / focus / country /
    # locale) match langchain-nimble>=3.0.0,<4.0.0; this signature contract is
    # exercised by the live smoke (see PR description), since the unit tests mock
    # the retriever. `focus` is passed explicitly so the default is provably
    # "general" rather than relying on the SDK's (unvalidated) field default.
    # `include_answer` is intentionally not exposed in this initial integration.
    retriever_kwargs = {
        "max_results": tool_config.max_results,
        "search_depth": tool_config.search_depth,
        "focus": tool_config.focus,
        "country": tool_config.country,
        "locale": tool_config.locale,
    }
    # Pass the configured key through the SDK's `api_key` field instead of the
    # environment; when no config key is set, the SDK resolves NIMBLE_API_KEY
    # from the environment itself.
    if api_key is not None:
        retriever_kwargs["api_key"] = api_key
    retriever = NimbleSearchRetriever(**retriever_kwargs)

    async def _nimble_web_search(question: str) -> str:
        """Search the web with Nimble and return relevant sources for a question.

        General-purpose web/research search: pass a natural-language question and
        get back the most relevant pages with their URLs and content. Use it for
        broad informational and technical research queries.

        Args:
            question (str): The question to answer. Truncated to 400 characters if longer.

        Returns:
            str: Relevant documents and their URLs, rendered as XML <Document> blocks.
        """
        if len(question) > 400:
            question = question[:397] + "..."

        def _truncate_content(content: str) -> str:
            limit = tool_config.max_content_length
            if limit is not None and len(content) > limit:
                # For very small limits there is no room for the ellipsis; hard-cut
                # so the result never exceeds the configured budget.
                if limit <= 3:
                    return content[:limit]
                return content[: limit - 3] + "..."
            return content

        def _has_resolvable_url(doc) -> bool:
            """Return True when the result carries a resolvable absolute URL.

            The API intermittently returns results whose URL is empty or a
            server-relative redirect token (e.g. "/goto?url=...") -- observed in
            ~2% of calls during a 100-run soak. Those break citation downstream,
            so they are dropped by the caller.
            """
            url = str((getattr(doc, "metadata", {}) or {}).get("url", "") or "")
            try:
                parsed = urlparse(url)
                return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)
            except ValueError:
                return False

        def _render(doc) -> str:
            """Render one result as an escaped XML ``<Document>`` block."""
            metadata = getattr(doc, "metadata", {}) or {}
            url = metadata.get("url", "") or ""
            title = metadata.get("title", "") or ""
            page_content = getattr(doc, "page_content", "") or ""
            description = metadata.get("description", "") or ""
            body = _truncate_content(page_content if page_content else description)
            # Escape untrusted API fields so they can't break the <Document>
            # markup or inject into downstream renderers/parsers.
            return (
                f'<Document href="{html.escape(url, quote=True)}">\n'
                f"<title>\n{html.escape(title)}\n</title>\n"
                f"{html.escape(body)}\n</Document>"
            )

        for attempt in range(tool_config.max_retries):
            try:
                docs = await retriever.ainvoke(question)

                if not docs:
                    raise ValueError("Search returned no results")

                # Drop results without a resolvable URL; if none remain, treat the
                # response as transient so the retry loop re-queries instead of
                # rendering unusable documents.
                usable_docs = [doc for doc in docs if _has_resolvable_url(doc)]
                if not usable_docs:
                    raise RuntimeError("Search returned only results without resolvable URLs")
                docs = usable_docs

                web_search_results = "\n\n---\n\n".join(_render(doc) for doc in docs)
                return web_search_results if web_search_results else "Search returned no results"

            except Exception as e:
                error_msg = str(e)
                # Non-transient errors can't be resolved by retrying, so return
                # immediately instead of sleeping through the remaining attempts.
                if isinstance(e, ValueError):
                    return error_msg
                if "401" in error_msg or "Unauthorized" in error_msg:
                    return (
                        "Error: Web search failed due to invalid API key (401 Unauthorized).\n"
                        "Please check your NIMBLE_API_KEY and ensure it is valid.\n"
                    )
                if "403" in error_msg:
                    return (
                        "Error: Web search failed due to a Nimble entitlement restriction (403).\n"
                        "The configured `search_depth` may require an enterprise Nimble account. "
                        "Try `search_depth: lite` or contact Nimble.\n"
                    )
                # Transient error: retry with backoff, or give up on the last attempt.
                if attempt == tool_config.max_retries - 1:
                    return f"Error: Web search failed - {error_msg}"
                # Cap the exponential delay so a large max_retries can't produce
                # an unbounded wait.
                await asyncio.sleep(min(2**attempt, 30))

        return "Error: Search failed after all retries"

    yield FunctionInfo.from_fn(
        _nimble_web_search,
        description=_nimble_web_search.__doc__,
    )

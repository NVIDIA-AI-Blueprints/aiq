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

"""Deterministic citation verification for research agent reports.

This module provides:
- SourceRegistry: captures URLs/citation keys from tool call results
- verify_citations(): validates report citations against the registry
- Extensible parser registry for adding new source types

Usage:
    registry = SourceRegistry()
    # ... populate via SourceRegistryMiddleware or manually ...
    result = verify_citations(report_text, registry)
    clean_report = result.verified_report
"""

from __future__ import annotations

import contextvars
import logging
import re
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from html import unescape
from urllib.parse import parse_qs
from urllib.parse import unquote
from urllib.parse import urlparse
from urllib.parse import urlunparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SourceEntry:
    """A single source captured from a tool call result."""

    url: str | None = None
    title: str | None = None
    citation_key: str | None = None
    source_type: str = ""
    tool_name: str = ""


@dataclass
class CitationVerificationResult:
    """Result of running verify_citations()."""

    verified_report: str
    removed_citations: list[dict] = field(default_factory=list)
    valid_citations: list[dict] = field(default_factory=list)


class EmptySourceRegistryError(Exception):
    """Raised when no sources were captured during research."""

    def __init__(self, agent_type: str = "research") -> None:
        self.agent_type = agent_type
        super().__init__(
            f"Research failed: no sources were captured during {agent_type}. "
            "All tool calls may have failed or returned no results. "
            "Please try again."
        )


_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "ref",
        "source",
    }
)


def _normalize_url(url: str) -> str:
    """Normalize a URL for comparison.

    Lowercases scheme/host, strips trailing slash, removes fragments
    and common tracking parameters.
    """
    url = unescape(url).strip()
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = unquote(parsed.path).rstrip("/") or "/"
    # Remove tracking params
    qs = parse_qs(parsed.query, keep_blank_values=True)
    filtered_qs = {k: v for k, v in qs.items() if k.lower() not in _TRACKING_PARAMS}
    query_str = "&".join(f"{k}={v[0]}" for k, v in sorted(filtered_qs.items()) if v)
    return urlunparse((scheme, netloc, path, "", query_str, ""))


# ---------------------------------------------------------------------------
# Knowledge-layer fuzzy matching helpers
# ---------------------------------------------------------------------------

_PAGE_RE = re.compile(r"(?:p\.?|page)\s*(\d+)", re.IGNORECASE)


def _parse_citation_key(key: str) -> tuple[str, int | None]:
    """Extract (filename, page_number) from a citation key.

    Handles: "report.pdf, p.15", "report.pdf, page 15", "report.pdf"
    """
    page_match = _PAGE_RE.search(key)
    page = int(page_match.group(1)) if page_match else None
    # Filename is everything before the page reference (or the whole key)
    if page_match:
        filename = key[: page_match.start()].rstrip(", ").strip()
    else:
        filename = key.strip()
    return filename, page


@dataclass
class _ParsedURL:
    """Pre-parsed URL components cached at registration time."""

    host: str
    path: str
    path_segments: list[str]
    query: dict[str, list[str]]
    entry: SourceEntry


# ---------------------------------------------------------------------------
# SourceRegistry
# ---------------------------------------------------------------------------


class SourceRegistry:
    """Registry of sources captured from tool call results.

    Not thread-safe — this is intentional.  All access happens on a single
    asyncio event loop (cooperative concurrency), and Python's GIL already
    protects the underlying dict/list/set operations from corruption.
    The module-level ``_session_registries`` dict *is* lock-protected because
    it is accessed across event loops when creating/looking up sessions.
    """

    def __init__(self) -> None:
        self._urls: dict[str, SourceEntry] = {}
        self._parsed_urls: dict[str, _ParsedURL] = {}
        self._citation_keys: list[SourceEntry] = []
        self._citation_key_files: set[str] = set()
        self._all: list[SourceEntry] = []

    def add(self, entry: SourceEntry) -> None:
        """Register a source entry. One entry per logical URL (dedup by normalized form).

        Raw URL = entry.url (exactly as the tool returned it); that is what we
        retain in the report. Normalized URL is used only as a key for dedup
        and matching. Both raw and normalized are stored as keys to the same
        entry so we never have duplicate entries and lookups find the tool URL.
        """
        added = False
        if entry.url:
            raw = entry.url
            normalized = _normalize_url(raw)
            if normalized not in self._urls:
                self._urls[normalized] = entry
                parsed = urlparse(normalized)
                self._parsed_urls[normalized] = _ParsedURL(
                    host=parsed.netloc,
                    path=parsed.path,
                    path_segments=[s for s in parsed.path.split("/") if s],
                    query=parse_qs(parsed.query, keep_blank_values=True),
                    entry=entry,
                )
                added = True
            if raw != normalized:
                self._urls[raw] = self._urls[normalized]
        if entry.citation_key:
            filename, _ = _parse_citation_key(entry.citation_key)
            key_lower = filename.lower()
            if key_lower not in self._citation_key_files:
                self._citation_key_files.add(key_lower)
                self._citation_keys.append(entry)
                if not added:
                    added = True
        if added:
            self._all.append(entry)

    def has_url(self, url: str) -> bool:
        """Check if a URL (after normalization) is in the registry."""
        return _normalize_url(url) in self._urls

    @staticmethod
    def _pick_unique(candidates: list[SourceEntry], strategy: str, url: str) -> str | None:
        """Return the registry URL when exactly one candidate matches.

        The references section can only show one URL per citation. If multiple
        registry URLs match (e.g. same path, different query), we cannot know
        which one the author meant, so we reject.
        """
        if len(candidates) == 1:
            logger.debug("[CitationVerify] %s match: '%s' → '%s'", strategy, url, candidates[0].url)
            return candidates[0].url
        if len(candidates) > 1:
            logger.debug(
                "[CitationVerify] Ambiguous %s match for '%s' — %d candidates, rejecting",
                strategy,
                url,
                len(candidates),
            )
        return None

    def resolve_url(self, url: str) -> str | None:
        """Return the registry URL (full, as returned by the tool) when the report URL matches.

        Matching strategy (first unambiguous match wins):
        1. Exact match — raw or normalized
        2. Truncation — report URL is a prefix of exactly one registry URL (raw)
        3. Prefix — report normalized is prefix of registry normalized
        4. Child-path — report path is a subpath of exactly one registry URL
        5. Query-subset — same host+path, report params subset of one registry URL

        Always returns the tool's URL (with query params etc.). If multiple
        registry URLs match, we reject (ambiguous).
        """
        # 1. Exact match — raw or normalized; retain the tool's URL
        if url in self._urls:
            return self._urls[url].url
        normalized = _normalize_url(url)
        if normalized in self._urls:
            return self._urls[normalized].url

        # 2. Truncation — report URL is a prefix of exactly one registry URL (raw).
        #    Normalized match fails when the report is cut mid-query (param order differs).
        truncation_entries = [e for e in self._urls.values() if e.url and e.url.startswith(url)]
        result = self._pick_unique(list({e.url: e for e in truncation_entries}.values()), "truncation", url)
        if result:
            return result

        # 3. Prefix match — report normalized is prefix of registry normalized
        #    Deduplicate by url to avoid raw+normalized keys for the same entry
        #    being counted as ambiguous.
        prefix_entries = [e for n, e in self._urls.items() if n.startswith(normalized)]
        result = self._pick_unique(
            list({e.url: e for e in prefix_entries}.values()),
            "prefix",
            url,
        )
        if result:
            return result

        parsed = urlparse(normalized)
        host, path = parsed.netloc, parsed.path
        same_host = [p for p in self._parsed_urls.values() if p.host == host]

        # 4. Child-path match — report path extends a registry path (subpage)
        #    Use rstrip("/") + "/" to enforce segment boundaries (prevents
        #    /us/benefits matching /us/benefitsOther).
        result = self._pick_unique(
            [
                p.entry
                for p in same_host
                if len(p.path_segments) >= 2 and path != p.path and path.startswith(p.path.rstrip("/") + "/")
            ],
            "child-path",
            url,
        )
        if result:
            return result

        # 5. Query-subset match — same host+path, report params are a subset of registry params
        report_qs = parse_qs(parsed.query, keep_blank_values=True)
        if report_qs:
            result = self._pick_unique(
                [
                    p.entry
                    for p in same_host
                    if p.path == path and p.query and all(p.query.get(k) == v for k, v in report_qs.items())
                ],
                "query-subset",
                url,
            )
            if result:
                return result

        return None

    def has_citation_key(self, key: str) -> bool:
        """Lenient match of a citation key against registry entries.

        Matches if filename (case-insensitive) matches ANY registry entry.
        Page numbers are not required to match — the LLM may cite a different
        page than what the knowledge layer returned, and that's acceptable
        since the document itself was verified as a real source.
        """
        target_file, _ = _parse_citation_key(key)
        target_lower = target_file.lower()
        for entry in self._citation_keys:
            entry_file, _ = _parse_citation_key(entry.citation_key)
            if entry_file.lower() == target_lower:
                return True
        return False

    def all_sources(self) -> list[SourceEntry]:
        """Return all registered sources."""
        return list(self._all)

    def clear(self) -> None:
        """Reset the registry."""
        self._urls.clear()
        self._parsed_urls.clear()
        self._citation_keys.clear()
        self._citation_key_files.clear()
        self._all.clear()


# ---------------------------------------------------------------------------
# Session-scoped registry (ContextVar)
# ---------------------------------------------------------------------------

_session_source_registry: contextvars.ContextVar[SourceRegistry | None] = contextvars.ContextVar(
    "_session_source_registry", default=None
)

_MAX_SESSION_REGISTRIES = 1000
_session_registries: OrderedDict[str, SourceRegistry] = OrderedDict()
_session_registries_lock = threading.Lock()


def get_or_create_session_registry(session_id: str | None) -> SourceRegistry:
    """Get or create a session-scoped SourceRegistry (LRU, max 1000 sessions).

    When session_id is None (e.g. CLI or batch modes with no conversation context),
    a fresh isolated SourceRegistry is returned on every call to prevent anonymous
    sessions from sharing state and leaking citations across concurrent requests.
    """
    if session_id is None:
        return SourceRegistry()
    with _session_registries_lock:
        if session_id in _session_registries:
            _session_registries.move_to_end(session_id)
            return _session_registries[session_id]
        registry = SourceRegistry()
        _session_registries[session_id] = registry
        while len(_session_registries) > _MAX_SESSION_REGISTRIES:
            _session_registries.popitem(last=False)
        return registry


def set_session_registry(registry: SourceRegistry | None) -> contextvars.Token:
    """Set the session-scoped SourceRegistry for the current async context."""
    return _session_source_registry.set(registry)


def reset_session_registry(token: contextvars.Token) -> None:
    """Restore the session-scoped SourceRegistry to its previous value."""
    _session_source_registry.reset(token)


def get_session_registry() -> SourceRegistry | None:
    """Get the session-scoped SourceRegistry for the current async context."""
    return _session_source_registry.get()


# ---------------------------------------------------------------------------
# Parser registry
# ---------------------------------------------------------------------------

SourceParser = Callable[[str, str], list[SourceEntry]]

_PARSER_REGISTRY: list[tuple[Callable[[str], bool], SourceParser]] = []


def register_source_parser(
    match_fn: Callable[[str], bool],
    parser_fn: SourceParser,
) -> None:
    """Register a parser for a tool name pattern.

    Args:
        match_fn: Predicate on lowercase tool name.
        parser_fn: (content, tool_name) -> list[SourceEntry]
    """
    _PARSER_REGISTRY.append((match_fn, parser_fn))


def extract_sources_from_tool_result(tool_name: str, content: str) -> list[SourceEntry]:
    """Extract sources from a tool's output.

    Strategy:
    1. If a registered parser matches the tool name, use it (for special
       formats like knowledge layer citation keys).
    2. Otherwise, fall back to the generic URL extractor which finds all
       URLs in any tool output regardless of format.

    This means new sources (Bing, Perplexity, etc.) work automatically
    without any parser registration — as long as their output contains URLs.
    """
    name_lower = tool_name.lower()
    for match_fn, parser_fn in _PARSER_REGISTRY:
        if match_fn(name_lower):
            try:
                return parser_fn(content, tool_name)
            except Exception:
                logger.warning("Parser failed for tool %s, falling back to generic", tool_name, exc_info=True)
                break
    # Generic fallback: extract all URLs from content
    return _parse_generic_urls(content, tool_name)


# ---------------------------------------------------------------------------
# Built-in parsers
# ---------------------------------------------------------------------------

# Generic URL extractor — works for any tool output format
_GENERIC_URL_RE = re.compile(r"https?://[^\s<>\"',\]]+")


# Patterns for extracting titles near URLs in common tool output formats
_TITLE_NEAR_URL_PATTERNS = [
    # Tavily: <title>\nSome Title\n</title>
    re.compile(r"<title>\s*\n?(.*?)\n?\s*</title>", re.DOTALL | re.IGNORECASE),
    # Paper search: N. **Title** (Year)
    re.compile(r"^\d+\.\s+\*\*(.+?)\*\*", re.MULTILINE),
    # Additional title patterns: --- Title ---
    re.compile(r"^---\s+(.+?)\s+---$", re.MULTILINE),
    # Key-value: Title: Some Title
    re.compile(r"^Title:\s*(.+)$", re.MULTILINE),
]


def _extract_title_for_url(content: str, url: str) -> str | None:
    """Try to extract a title associated with a URL from the surrounding content.

    Looks in the text block containing the URL for common title patterns.
    """
    # Find the block of text containing this URL (split by --- or double newlines)
    blocks = re.split(r"\n\n---\n\n|\n\n\n", content)
    for block in blocks:
        if url not in block:
            continue
        for pattern in _TITLE_NEAR_URL_PATTERNS:
            title_match = pattern.search(block)
            if title_match:
                title = title_match.group(1).strip()
                if title and title != url:
                    return title
    return None


def _parse_generic_urls(content: str, tool_name: str) -> list[SourceEntry]:
    """Extract all URLs from any tool output, regardless of format.

    This is the universal fallback. It finds every URL in the content
    and registers it. Works for Tavily XML, paper search markdown,
    plain text with links, or any future source format. Also attempts to
    extract titles from common patterns near each URL.
    """
    seen: set[str] = set()
    entries: list[SourceEntry] = []
    for match in _GENERIC_URL_RE.finditer(content):
        url = unescape(match.group(0)).rstrip(".,;)")
        normalized = _normalize_url(url)
        if normalized not in seen:
            seen.add(normalized)
            title = _extract_title_for_url(content, url)
            entries.append(SourceEntry(url=url, title=title, source_type="generic", tool_name=tool_name))
    return entries


# Knowledge layer is the only source that needs a specific parser because
# it uses citation keys (e.g., "report.pdf, p.15") instead of URLs.
_KL_CITATION_RE = re.compile(r"^Citation:\s*(.+)$", re.MULTILINE)
_KL_SOURCE_RE = re.compile(r"^Source:\s*(.+)$", re.MULTILINE)


def _parse_knowledge_layer(content: str, tool_name: str) -> list[SourceEntry]:
    """Parse knowledge layer retrieval output.

    Extracts citation keys (filename + page) AND any URLs present.
    Falls back to generic URL extraction if no Citation: fields found.
    """
    entries: list[SourceEntry] = []
    citations = _KL_CITATION_RE.findall(content)
    sources = _KL_SOURCE_RE.findall(content)
    for i, citation_key in enumerate(citations):
        title = sources[i].strip() if i < len(sources) else None
        entries.append(
            SourceEntry(
                citation_key=citation_key.strip(), title=title, source_type="knowledge_layer", tool_name=tool_name
            )
        )
    if not entries:
        return _parse_generic_urls(content, tool_name)
    return entries


# Register knowledge layer as the only special-case parser.
# All other tools (Tavily, paper search, etc.) use the generic URL fallback.
register_source_parser(lambda name: "knowledge" in name, _parse_knowledge_layer)

# ---------------------------------------------------------------------------
# Citation verification
# ---------------------------------------------------------------------------

_REFERENCE_SECTION_RE = re.compile(
    r"^(?:#{2,3}\s+(?:Sources|References)|Reference\s+List|\*\*References:?\*\*)",
    re.MULTILINE | re.IGNORECASE,
)

_CITATION_LINE_RE = re.compile(r"^\s*[-*]?\s*\[(\d+)\]\s*(.+)$", re.MULTILINE)

_URL_IN_LINE_RE = re.compile(r"https?://\S+")

# Knowledge-layer citation pattern: "filename.ext" optionally followed by ", p.N" or ", page N"
_KL_CITATION_PATTERN_RE = re.compile(r"^(.+\.\w{2,5})(?:,\s*(?:p\.?|page)\s*\d+)?$", re.IGNORECASE)


def _is_knowledge_citation(ref_text: str, registry: SourceRegistry | None = None) -> tuple[bool, str | None]:
    """Check if reference text looks like a knowledge-layer citation.

    Uses a lenient matching strategy:
    1. Try exact pattern match (filename.ext, p.N) after stripping markdown
    2. If a registry is provided, check if ANY registered citation key's
       filename appears anywhere in the reference text (very lenient —
       handles all formatting variations the LLM might produce)

    Returns (is_kl, citation_key_or_none).
    """
    # Strip trailing "(Internal)" or similar parenthetical
    cleaned = re.sub(r"\s*\(.*?\)\s*$", "", ref_text).strip()
    # Strip markdown bold/italic markers only (*, **) — preserve underscores in filenames
    cleaned = re.sub(r"\*+", "", cleaned).strip()
    # Remove leading "Title - " or "Title: " prefix by taking last segment
    # if it contains a filename pattern
    for segment in [cleaned, cleaned.split(" - ")[-1].strip(), cleaned.split(": ")[-1].strip()]:
        if _KL_CITATION_PATTERN_RE.match(segment):
            return True, segment

    # Lenient fallback: check if any registered knowledge-layer filename
    # appears in the reference text (handles arbitrary LLM formatting)
    if registry is not None:
        ref_lower = cleaned.lower()
        for entry in registry._citation_keys:
            entry_file, _ = _parse_citation_key(entry.citation_key)
            if entry_file.lower() in ref_lower:
                return True, entry.citation_key

    return False, None


def _renumber_citations(body: str, ref_section: str) -> tuple[str, str, dict[int, int]]:
    """Renumber [N] citations sequentially, closing any gaps.

    Scans the references section for citation numbers, builds a mapping
    from old to new sequential numbers, and applies it to both body and
    references via collision-safe placeholders.

    Returns:
        (body, ref_section, renumber_map) where renumber_map maps every
        old citation number to its new sequential number.
    """
    remaining = sorted(int(m.group(1)) for m in _CITATION_LINE_RE.finditer(ref_section))
    renumber_map: dict[int, int] = {old: new for new, old in enumerate(remaining, 1)}

    # Nothing to do if already sequential
    if all(old == new for old, new in renumber_map.items()):
        return body, ref_section, renumber_map

    # Apply renumbering via placeholders (descending order avoids [1] matching inside [10])
    for old_num in sorted(renumber_map, reverse=True):
        new_num = renumber_map[old_num]
        if old_num != new_num:
            placeholder = f"__CITE_{new_num}__"
            body = body.replace(f"[{old_num}]", placeholder)
            ref_section = ref_section.replace(f"[{old_num}]", placeholder)

    for new_num in sorted(renumber_map.values()):
        placeholder = f"__CITE_{new_num}__"
        body = body.replace(placeholder, f"[{new_num}]")
        ref_section = ref_section.replace(placeholder, f"[{new_num}]")

    return body, ref_section, renumber_map


def verify_citations(report_text: str, registry: SourceRegistry) -> CitationVerificationResult:
    """Verify citations in a report against the source registry.

    Algorithm:
    1. Find the references section
    2. Parse each [N] reference line
    3. Validate URL or citation_key against registry
    4. Remove invalid references and orphaned inline citations

    Renumbering is NOT done here — it is deferred to sanitize_report()
    which always runs after this function and handles it in a single pass.

    Args:
        report_text: The full report text with citations.
        registry: SourceRegistry populated from tool call results.

    Returns:
        CitationVerificationResult with cleaned report and audit trail.
    """
    # Normalize Unicode fullwidth brackets to ASCII (LLMs sometimes use 【N】 instead of [N])
    report_text = report_text.replace("【", "[").replace("】", "]")

    # Early exit: nothing to validate against
    all_sources = registry.all_sources()
    if not all_sources:
        logger.debug("[CitationVerify] Skipping — registry is empty (no tool calls captured)")
        return CitationVerificationResult(verified_report=report_text)

    logger.info(
        "[CitationVerify] Starting verification against %d registered source(s)",
        len(all_sources),
    )
    logger.debug(
        "[CitationVerify] Registered URLs: %s",
        [s.url for s in all_sources if s.url],
    )

    # Find references section
    ref_match = _REFERENCE_SECTION_RE.search(report_text)
    if not ref_match:
        logger.warning("[CitationVerify] No references section found in report; skipping")
        return CitationVerificationResult(verified_report=report_text)

    ref_start = ref_match.start()
    body = report_text[:ref_start]
    ref_section = report_text[ref_start:]

    # Parse citation lines in the references section
    valid_citations: list[dict] = []
    removed_citations: list[dict] = []
    url_replacements: dict[str, str] = {}  # garbled_url -> canonical_url

    for line_match in _CITATION_LINE_RE.finditer(ref_section):
        num = int(line_match.group(1))
        ref_text = line_match.group(2).strip()
        full_line = line_match.group(0)

        # Try URL match first
        url_match = _URL_IN_LINE_RE.search(ref_text)
        if url_match:
            url = url_match.group(0).rstrip(".,;)")
            canonical = registry.resolve_url(url)
            if canonical:
                if canonical != url:
                    logger.debug("[CitationVerify]   [%d] VALID  — %s (repaired from: %s)", num, canonical, url)
                    url_replacements[url] = canonical
                else:
                    logger.debug("[CitationVerify]   [%d] VALID  — %s", num, url)
                valid_citations.append({"number": num, "url": canonical, "citation_key": None, "line": full_line})
            else:
                logger.info("[CitationVerify]   [%d] REMOVE — url_not_in_registry: %s", num, url)
                removed_citations.append({"number": num, "line": full_line, "reason": "url_not_in_registry"})
            continue

        # Try knowledge-layer citation key (lenient — passes registry for fuzzy filename match)
        is_kl, citation_key = _is_knowledge_citation(ref_text, registry)
        if is_kl and citation_key:
            if registry.has_citation_key(citation_key):
                logger.debug("[CitationVerify]   [%d] VALID  — %s", num, citation_key)
                valid_citations.append({"number": num, "url": None, "citation_key": citation_key, "line": full_line})
            else:
                logger.debug("[CitationVerify]   [%d] REMOVE — citation_key_not_in_registry: %s", num, citation_key)
                removed_citations.append({"number": num, "line": full_line, "reason": "citation_key_not_in_registry"})
            continue

        # Neither URL nor recognizable citation key
        logger.debug("[CitationVerify]   [%d] REMOVE — unverifiable: %s", num, ref_text[:80])
        removed_citations.append({"number": num, "line": full_line, "reason": "unverifiable"})

    # Apply URL replacements (garbled -> canonical) in the references section
    if url_replacements:
        for garbled, canonical in url_replacements.items():
            ref_section = ref_section.replace(garbled, canonical)

    if not removed_citations:
        logger.debug("[CitationVerify] Result: all %d citation(s) valid — no changes", len(valid_citations))
        verified = body + ref_section if url_replacements else report_text
        return CitationVerificationResult(
            verified_report=verified,
            valid_citations=valid_citations,
        )

    removed_numbers = {c["number"] for c in removed_citations}

    # Remove invalid reference lines from the references section
    cleaned_ref_lines = []
    for line in ref_section.split("\n"):
        line_match = _CITATION_LINE_RE.match(line)
        if line_match and int(line_match.group(1)) in removed_numbers:
            continue
        cleaned_ref_lines.append(line)
    cleaned_ref_section = "\n".join(cleaned_ref_lines)

    # Remove orphaned inline citations from body
    cleaned_body = body
    for num in removed_numbers:
        cleaned_body = re.sub(rf"\[{num}\]", "", cleaned_body)

    # Note: renumbering is deferred to sanitize_report() which always runs after
    # this function and handles renumbering in a single pass.
    verified_report = cleaned_body + cleaned_ref_section

    logger.debug(
        "[CitationVerify] Result: kept %d, removed %d",
        len(valid_citations),
        len(removed_citations),
    )

    return CitationVerificationResult(
        verified_report=verified_report,
        removed_citations=removed_citations,
        valid_citations=valid_citations,
    )


# ---------------------------------------------------------------------------
# Report sanitization (deterministic post-processing)
# ---------------------------------------------------------------------------

# Known URL shortener domains
_SHORTENER_DOMAINS = frozenset(
    {
        "bit.ly",
        "tinyurl.com",
        "t.co",
        "goo.gl",
        "ow.ly",
        "is.gd",
        "buff.ly",
        "short.io",
        "rb.gy",
        "cutt.ly",
        "lnkd.in",
        "soo.gd",
        "s.coop",
        "cli.gs",
        "budurl.com",
        "yourls.org",
    }
)

# Patterns indicating a truncated/garbled URL
_TRUNCATED_URL_RE = re.compile(r"\.\.\.$|…$")  # ends in ... or ellipsis

# Suspicious URL patterns
_IP_ADDRESS_RE = re.compile(r"^https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")
_SUSPICIOUS_SCHEMES_RE = re.compile(r"^(?:javascript|data|vbscript|file):", re.IGNORECASE)
_BARE_URL_RE = re.compile(r"https?://[^\s<>\"',\]]+")

# Body URL patterns (used by sanitize_report)
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(\s*\w+://[^\s)]+\)")
_BODY_URL_RE = re.compile(r"\w+://[^\s<>\"',\]]+")


@dataclass
class ReportSanitizationResult:
    """Result of running sanitize_report()."""

    sanitized_report: str
    body_urls_removed: int
    body_urls_replaced: int
    shortened_urls_removed: list[str]
    truncated_urls_removed: list[str]
    unsafe_urls_removed: list[str]


def sanitize_report(report_text: str) -> ReportSanitizationResult:
    """Deterministic sanitization of a research report.

    Checks:
    1. Strip body URLs — collapse markdown links to display text, replace
       bare URLs that match a reference with ``[N]``, remove the rest.
    2. Remove shortened/obfuscated URLs from References — all URLs must
       be fully expanded (no bit.ly, t.co, etc.).
    3. Remove truncated/garbled URLs — URLs ending in '...' or with no
       path (domain-only like 'https://arxiv.org') are incomplete.
    4. Block unsafe URLs — no IP-address URLs, no non-http schemes.

    Args:
        report_text: Report text (ideally after verify_citations()).

    Returns:
        ReportSanitizationResult with cleaned report and audit trail.
    """
    body_urls_removed = 0
    body_urls_replaced = 0
    shortened_urls_removed: list[str] = []
    truncated_urls_removed: list[str] = []
    unsafe_urls_removed: list[str] = []

    # Split into body and references section
    ref_match = _REFERENCE_SECTION_RE.search(report_text)
    if ref_match:
        body = report_text[: ref_match.start()]
        ref_section = report_text[ref_match.start() :]
    else:
        body = report_text
        ref_section = ""

    # --- Check 1: Strip body URLs ---
    # Build URL → citation number map from references so matching body
    # URLs are replaced with [N] instead of being deleted entirely.
    url_to_citation: dict[str, int] = {}
    if ref_section:
        for m in _CITATION_LINE_RE.finditer(ref_section):
            num = int(m.group(1))
            url_m = _BARE_URL_RE.search(m.group(2))
            if url_m:
                url_to_citation[_normalize_url(url_m.group(0).rstrip(".,;)"))] = num

    def _replace_body_url(match: re.Match) -> str:
        nonlocal body_urls_removed, body_urls_replaced
        url = match.group(0).rstrip(".,;)")
        normalized = _normalize_url(url)
        if normalized in url_to_citation:
            body_urls_replaced += 1
            return f"[{url_to_citation[normalized]}]"
        body_urls_removed += 1
        return ""

    # Collapse markdown links to display text
    cleaned_body = _MD_LINK_RE.sub(r"\1", body)
    # Replace matching bare URLs with [N], strip the rest
    cleaned_body = _BODY_URL_RE.sub(_replace_body_url, cleaned_body)
    # Clean up leftover empty parentheses and extra spaces
    cleaned_body = re.sub(r"\(\s*\)", "", cleaned_body)
    cleaned_body = re.sub(r"  +", " ", cleaned_body)

    if body_urls_replaced:
        logger.debug("[ReportSanitize] Replaced %d body URL(s) with citation numbers", body_urls_replaced)
    if body_urls_removed:
        logger.debug("[ReportSanitize] Removed %d unmatched URL(s) from report body", body_urls_removed)

    # --- Checks 2 & 3: Validate URLs in references section ---
    if ref_section:
        lines_to_remove: set[int] = set()
        ref_lines = ref_section.split("\n")

        for i, line in enumerate(ref_lines):
            url_match = _BARE_URL_RE.search(line)
            if not url_match:
                continue
            url = url_match.group(0).rstrip(".,;)")

            # Check for non-http schemes embedded in text
            if _SUSPICIOUS_SCHEMES_RE.search(line):
                unsafe_urls_removed.append(url)
                lines_to_remove.add(i)
                continue

            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            # Check 2: shortened URLs
            # Strip www. and port for comparison
            bare_domain = domain.split(":")[0]
            if bare_domain.startswith("www."):
                bare_domain = bare_domain[4:]
            if bare_domain in _SHORTENER_DOMAINS:
                shortened_urls_removed.append(url)
                lines_to_remove.add(i)
                continue

            # Check 3: truncated/garbled URLs — only catch obvious truncation markers
            raw_url = url_match.group(0)
            if _TRUNCATED_URL_RE.search(raw_url) or "…" in raw_url:
                truncated_urls_removed.append(raw_url)
                lines_to_remove.add(i)
                continue

            # Check 4: IP address URLs
            if _IP_ADDRESS_RE.match(url):
                unsafe_urls_removed.append(url)
                lines_to_remove.add(i)
                continue

            # Check 4: non-http schemes
            if parsed.scheme not in ("http", "https"):
                unsafe_urls_removed.append(url)
                lines_to_remove.add(i)
                continue

        if lines_to_remove:
            # Collect which [N] numbers were removed
            removed_numbers: set[int] = set()
            for i in lines_to_remove:
                line_m = _CITATION_LINE_RE.match(ref_lines[i])
                if line_m:
                    removed_numbers.add(int(line_m.group(1)))

            cleaned_ref_lines = [line for i, line in enumerate(ref_lines) if i not in lines_to_remove]
            ref_section = "\n".join(cleaned_ref_lines)

            # Strip orphaned inline [N] from body
            if removed_numbers:
                for num in removed_numbers:
                    cleaned_body = re.sub(rf"\[{num}\]", "", cleaned_body)

        if shortened_urls_removed:
            logger.debug(
                "[ReportSanitize] Removed %d shortened URL(s) from references: %s",
                len(shortened_urls_removed),
                shortened_urls_removed,
            )
        if truncated_urls_removed:
            logger.debug(
                "[ReportSanitize] Removed %d truncated/incomplete URL(s) from references: %s",
                len(truncated_urls_removed),
                truncated_urls_removed,
            )
        if unsafe_urls_removed:
            logger.debug(
                "[ReportSanitize] Removed %d unsafe URL(s) from references: %s",
                len(unsafe_urls_removed),
                unsafe_urls_removed,
            )

    # Renumber citations to close any gaps (from verify_citations and/or sanitize removals)
    if ref_section:
        cleaned_body, ref_section, _ = _renumber_citations(cleaned_body, ref_section)

    sanitized_report = cleaned_body + ref_section

    # --- Strip leaked tool-call XML fragments ---
    # LLMs sometimes output raw tool-call syntax as text
    sanitized_report = re.sub(
        r"</?(parameter|function|tool_call|tool_use|invoke|antml:[\w]+)[\s>].*",
        "",
        sanitized_report,
        flags=re.DOTALL,
    )

    # --- Trim everything after the last citation in the Sources section ---
    # The LLM often appends meta-commentary after the references (e.g.,
    # "All citations refer to...", "This report meets..."). Rather than
    # pattern-matching specific phrases, just cut after the last [N] line.
    if ref_section:
        last_citation_end = None
        for m in _CITATION_LINE_RE.finditer(sanitized_report):
            last_citation_end = m.end()
        if last_citation_end is not None:
            sanitized_report = sanitized_report[:last_citation_end].rstrip() + "\n"

    return ReportSanitizationResult(
        sanitized_report=sanitized_report,
        body_urls_removed=body_urls_removed,
        body_urls_replaced=body_urls_replaced,
        shortened_urls_removed=shortened_urls_removed,
        truncated_urls_removed=truncated_urls_removed,
        unsafe_urls_removed=unsafe_urls_removed,
    )

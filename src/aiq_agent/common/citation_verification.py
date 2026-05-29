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
from typing import Any
from typing import Literal
from urllib.parse import parse_qs
from urllib.parse import unquote
from urllib.parse import urlparse
from urllib.parse import urlunparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OpenTelemetry counter (soft-imported)
# ---------------------------------------------------------------------------
# OTel API is a transitive dep through NAT. If a Meter Provider has been
# configured by the runtime, this Counter records per-match-kind verification
# outcomes; otherwise it's a no-op. Either way the structured `extra=` logs
# (info-level summary, debug-level per-citation) carry the same information.
try:
    from opentelemetry import metrics as _otel_metrics

    _citation_counter = _otel_metrics.get_meter(__name__).create_counter(
        name="aiq.citation.verifications",
        description="Citation verification outcomes by match_kind and verified status.",
        unit="1",
    )
except Exception:  # noqa: BLE001 — OTel optional; fall through to logs only
    _citation_counter = None


def _emit_citation_metric(match_kind: str, verified: bool, resolved: bool) -> None:
    """Record one citation outcome to the OTel counter when available."""
    if _citation_counter is None:
        return
    try:
        _citation_counter.add(
            1,
            attributes={
                "match_kind": match_kind,
                "verified": str(verified).lower(),
                "resolved": str(resolved).lower(),
            },
        )
    except Exception:  # noqa: BLE001 — never let telemetry break verification
        logger.debug("Failed to record citation metric", exc_info=True)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

# Match kinds — what strategy resolved a citation against the registry.
# Confidence for each is fixed; see _MATCH_CONFIDENCE below.
MatchKind = Literal[
    "exact",
    "normalized",
    "truncation",
    "prefix",
    "child_path",
    "query_subset",
    "citation_key",
    "unmatched",
    "ambiguous",
    "unverifiable",
]

# Fixed confidence per match kind. The value of the strategy IS the score —
# we don't compute per-URL fuzzy scores. Keeps verification deterministic.
_MATCH_CONFIDENCE: dict[str, float] = {
    "exact": 1.0,
    "normalized": 0.95,
    "citation_key": 0.90,
    "truncation": 0.85,
    "prefix": 0.75,
    "query_subset": 0.70,
    "child_path": 0.60,
    "unmatched": 0.0,
    "ambiguous": 0.0,
    "unverifiable": 0.0,
}


@dataclass
class SourceEntry:
    """A single source captured from a tool call result."""

    url: str | None = None
    title: str | None = None
    citation_key: str | None = None
    source_type: str = ""
    tool_name: str = ""


@dataclass
class _ResolveMatch:
    """Result of SourceRegistry.resolve_url()."""

    url: str
    kind: MatchKind
    confidence: float
    diagnostics: dict[str, Any] = field(default_factory=dict)


_UNRESOLVED_KINDS: frozenset[str] = frozenset({"unmatched", "ambiguous", "unverifiable"})


@dataclass
class VerifiedCitation:
    """Per-citation verification record produced by verify_citations().

    Two related booleans:

    - ``resolved`` (derived from ``match_kind``) — True when *some* registry
      source matched, even weakly. Citations that didn't resolve at all are
      genuinely fabricated and get stripped from the report.
    - ``verified`` — True when ``confidence >= passthrough_threshold``. This
      is a UI hint about *strength* of the match, not a strip gate. Resolved
      but below-threshold citations stay in the report; the UI renders them
      with a low-confidence badge.
    """

    number: int
    line: str
    url: str | None
    citation_key: str | None
    verified: bool
    confidence: float
    match_kind: MatchKind
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def resolved(self) -> bool:
        """True when the citation matched the registry (any kind, even weakly)."""
        return self.match_kind not in _UNRESOLVED_KINDS


@dataclass
class CitationVerificationResult:
    """Result of running verify_citations()."""

    verified_report: str
    removed_citations: list[dict] = field(default_factory=list)
    valid_citations: list[dict] = field(default_factory=list)
    verifications: list[VerifiedCitation] = field(default_factory=list)


class EmptySourceRegistryError(Exception):
    """Raised when no sources were captured during research."""

    def __init__(
        self,
        agent_type: str = "research",
        unavailable_tools: list[str] | None = None,
        available_count: int = 0,
    ) -> None:
        self.agent_type = agent_type
        self.unavailable_tools = unavailable_tools or []
        self.available_count = available_count
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
        """Check if a URL resolves unambiguously against the registry.

        Returns True for any matched strategy (exact, normalized, truncation,
        prefix, child-path, query-subset). False for unmatched or ambiguous.
        """
        match = self.resolve_url(url)
        return match is not None and match.kind != "ambiguous"

    @staticmethod
    def _pick_unique(
        candidates: list[SourceEntry],
        kind: MatchKind,
        url: str,
    ) -> _ResolveMatch | None:
        """Return a _ResolveMatch when exactly one candidate matches, ambiguous when multiple.

        The references section can only show one URL per citation. If multiple
        registry URLs match (e.g. same path, different query), we cannot know
        which one the author meant, so we surface ambiguity rather than silently
        rejecting.
        """
        if len(candidates) == 1:
            registry_url = candidates[0].url or ""
            logger.debug("[CitationVerify] %s match: '%s' → '%s'", kind, url, registry_url)
            return _ResolveMatch(
                url=registry_url,
                kind=kind,
                confidence=_MATCH_CONFIDENCE[kind],
                diagnostics={"strategy": kind},
            )
        if len(candidates) > 1:
            logger.debug(
                "[CitationVerify] Ambiguous %s match for '%s' — %d candidates, rejecting",
                kind,
                url,
                len(candidates),
            )
            return _ResolveMatch(
                url="",
                kind="ambiguous",
                confidence=_MATCH_CONFIDENCE["ambiguous"],
                diagnostics={
                    "attempted_kind": kind,
                    "candidate_count": len(candidates),
                    "report_url": url,
                },
            )
        return None

    def resolve_url(self, url: str) -> _ResolveMatch | None:
        """Resolve a report URL against the registry with a confidence-scored result.

        Matching strategy (first match wins):
        1. ``exact`` / ``normalized`` — raw or normalized hit
        2. ``truncation`` — report URL is a prefix of exactly one registry URL
        3. ``prefix`` — report normalized is prefix of registry normalized
        4. ``child_path`` — report path is a subpath of exactly one registry URL
        5. ``query_subset`` — same host+path, report params subset

        Returns None when nothing matches. Returns a ``_ResolveMatch`` with
        ``kind="ambiguous"`` when a strategy found multiple candidates — the
        caller can then decide whether to drop the citation or downgrade it.
        """
        # 1. Exact match — raw or normalized; retain the tool's URL
        if url in self._urls:
            entry_url = self._urls[url].url or ""
            return _ResolveMatch(url=entry_url, kind="exact", confidence=_MATCH_CONFIDENCE["exact"])
        normalized = _normalize_url(url)
        if normalized in self._urls:
            entry_url = self._urls[normalized].url or ""
            return _ResolveMatch(url=entry_url, kind="normalized", confidence=_MATCH_CONFIDENCE["normalized"])

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
            "child_path",
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
                "query_subset",
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


def extract_sources_from_tool_result(
    tool_name: str,
    content: str,
    source_id: str | None = None,
) -> list[SourceEntry]:
    """Extract sources from a tool's output.

    Strategy:
    1. If a registered parser matches the tool name, use it (for special
       formats like knowledge layer citation keys).
    2. Otherwise, fall back to the generic URL extractor which finds all
       URLs in any tool output regardless of format.
    3. If neither produces entries, register the tool result itself as a
       non-URL citation source.

    This means new sources (Bing, Perplexity, etc.) work automatically
    without any parser registration — as long as their output contains URLs.

    The non-URL fallback is permissive on purpose: callers (the shallow and
    deep researchers) are responsible for deciding which tool calls are
    eligible to contribute sources, typically by limiting capture to the
    agent's loaded tool set. The optional ``source_id`` is stored on the
    returned entries when callers have resolved this tool to a configured
    data source via
    :func:`aiq_agent.common.data_source_registry.get_source_id_for_tool`,
    but it does not gate the fallback.
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
    entries = _parse_generic_urls(content, tool_name)
    if entries:
        return entries

    # Non-URL fallback: register the tool result itself as a source whenever
    # the tool produced non-empty output. The caller has already decided
    # this tool is eligible to contribute sources (typically by limiting
    # capture to the agent's loaded tool set).
    if content.strip():
        return [SourceEntry(citation_key=tool_name, source_type="tool_result", tool_name=tool_name)]

    return []


# ---------------------------------------------------------------------------
# Built-in parsers
# ---------------------------------------------------------------------------

# Generic URL extractor — works for any tool output format.
# Commas are valid URL path characters (RFC 3986 sub-delim) and appear in real
# URLs like https://weathercams.faa.gov/map/-122.31167,47.22287,10/...; we
# include them in the match and rely on _URL_TRIM_CHARS below to strip any
# comma that's actually sentence punctuation. ``]`` stays excluded here
# because it almost always terminates a markdown link rather than appearing
# in a path.
_GENERIC_URL_RE = re.compile(r"https?://[^\s<>\"'\]]+")

# Trailing characters to strip from a captured URL.  Covers sentence
# punctuation and the closing chars of common Markdown wrappers — ``]`` for
# ``[https://...]`` and ``>`` for ``<https://...>``.  Used at every site that
# captures a URL via a permissive regex (registration and verification).
_URL_TRIM_CHARS = ".,;)]>"


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

    Finds the title pattern **closest to** (and preceding) the URL within its
    text block.  This prevents a single block containing multiple search
    results from assigning the first result's title to every URL.
    """
    # Find the block of text containing this URL (split by --- or double newlines)
    blocks = re.split(r"\n\n---\n\n|\n\n\n", content)
    for block in blocks:
        if url not in block:
            continue
        url_pos = block.index(url)
        best_title: str | None = None
        best_distance = float("inf")
        for pattern in _TITLE_NEAR_URL_PATTERNS:
            for title_match in pattern.finditer(block):
                title = title_match.group(1).strip()
                if not title or title == url:
                    continue
                # Prefer titles that appear before (and closest to) the URL
                distance = url_pos - title_match.end()
                if distance < 0:
                    # Title appears after the URL — use large penalty
                    distance = abs(distance) + 10000
                if distance < best_distance:
                    best_distance = distance
                    best_title = title
        if best_title:
            return best_title
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
        url = unescape(match.group(0)).rstrip(_URL_TRIM_CHARS)
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


def _citation_to_dict(v: VerifiedCitation, *, include_reason: bool = False) -> dict:
    """Convert a VerifiedCitation to the historical list-of-dicts shape.

    Preserves the original keys callers (and tests) already iterate, while
    adding ``confidence``, ``match_kind``, ``verified``, and ``resolved`` so
    downstream consumers can read them without depending on the dataclass.
    """
    d: dict = {
        "number": v.number,
        "line": v.line,
        "url": v.url,
        "citation_key": v.citation_key,
        "confidence": v.confidence,
        "match_kind": v.match_kind,
        "verified": v.verified,
        "resolved": v.resolved,
    }
    if include_reason:
        # Map match_kind to the legacy short reason strings tests expect.
        # ``ambiguous`` is split out from ``url_not_in_registry`` so audit
        # logs can distinguish multi-candidate collisions from genuinely
        # missing URLs.
        if v.url is None and v.citation_key is None:
            d["reason"] = "unverifiable"
        elif v.citation_key is not None:
            d["reason"] = "citation_key_not_in_registry"
        elif v.match_kind == "ambiguous":
            d["reason"] = "url_ambiguous"
        else:
            d["reason"] = "url_not_in_registry"
    return d


def verify_citations(
    report_text: str,
    registry: SourceRegistry,
    *,
    passthrough_threshold: float = 0.0,
) -> CitationVerificationResult:
    """Verify citations in a report against the source registry.

    Each citation is scored against the registry and gets a structured
    ``VerifiedCitation`` record. Only *unresolved* citations
    (``unmatched`` / ``ambiguous`` / ``unverifiable``) are stripped from
    the report; every resolved citation passes through regardless of
    confidence, carrying its score so the UI can render a badge.

    Renumbering is NOT done here — it is deferred to ``sanitize_report()``
    which always runs after this function and handles it in a single pass.

    Args:
        report_text: The full report text with citations.
        registry: SourceRegistry populated from tool call results.
        passthrough_threshold: Sets the ``verified`` flag on each
            ``VerifiedCitation`` (``True`` when ``confidence >= threshold``).
            This is a UI display hint only — it does **not** filter which
            citations remain in the report. Default 0.0 marks every
            resolved citation as verified.

    Returns:
        CitationVerificationResult with cleaned report, per-citation
        ``verifications`` records, and legacy ``valid_citations`` /
        ``removed_citations`` lists (now with confidence/match_kind fields).
    """
    # Normalize Unicode fullwidth brackets to ASCII (LLMs sometimes use 【N】 instead of [N])
    report_text = report_text.replace("【", "[").replace("】", "]")

    # Early exit: nothing to validate against
    all_sources = registry.all_sources()
    if not all_sources:
        logger.debug("[CitationVerify] Skipping — registry is empty (no tool calls captured)")
        return CitationVerificationResult(verified_report=report_text)

    logger.info(
        "[CitationVerify] Starting verification against %d registered source(s) (threshold=%.2f)",
        len(all_sources),
        passthrough_threshold,
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

    # Per-citation records; the rest is derived from these.
    verifications: list[VerifiedCitation] = []
    url_replacements: dict[str, str] = {}  # garbled_url -> canonical_url

    for line_match in _CITATION_LINE_RE.finditer(ref_section):
        num = int(line_match.group(1))
        ref_text = line_match.group(2).strip()
        full_line = line_match.group(0)

        # Try URL match first
        url_match = _URL_IN_LINE_RE.search(ref_text)
        if url_match:
            url = url_match.group(0).rstrip(_URL_TRIM_CHARS)
            match = registry.resolve_url(url)
            if match is not None and match.kind != "ambiguous":
                canonical = match.url
                if canonical != url:
                    url_replacements[url] = canonical
                verified = match.confidence >= passthrough_threshold
                verifications.append(
                    VerifiedCitation(
                        number=num,
                        line=full_line,
                        url=canonical,
                        citation_key=None,
                        verified=verified,
                        confidence=match.confidence,
                        match_kind=match.kind,
                        diagnostics={**match.diagnostics, "report_url": url},
                    )
                )
            else:
                kind: MatchKind = "ambiguous" if (match is not None and match.kind == "ambiguous") else "unmatched"
                verifications.append(
                    VerifiedCitation(
                        number=num,
                        line=full_line,
                        url=url,
                        citation_key=None,
                        verified=False,
                        confidence=_MATCH_CONFIDENCE[kind],
                        match_kind=kind,
                        diagnostics=(match.diagnostics if match is not None else {"report_url": url}),
                    )
                )
            continue

        # Try knowledge-layer citation key (lenient — passes registry for fuzzy filename match)
        is_kl, citation_key = _is_knowledge_citation(ref_text, registry)
        if is_kl and citation_key:
            if registry.has_citation_key(citation_key):
                conf = _MATCH_CONFIDENCE["citation_key"]
                verifications.append(
                    VerifiedCitation(
                        number=num,
                        line=full_line,
                        url=None,
                        citation_key=citation_key,
                        verified=conf >= passthrough_threshold,
                        confidence=conf,
                        match_kind="citation_key",
                    )
                )
            else:
                verifications.append(
                    VerifiedCitation(
                        number=num,
                        line=full_line,
                        url=None,
                        citation_key=citation_key,
                        verified=False,
                        confidence=_MATCH_CONFIDENCE["unmatched"],
                        match_kind="unmatched",
                    )
                )
            continue

        # Neither URL nor recognizable citation key
        verifications.append(
            VerifiedCitation(
                number=num,
                line=full_line,
                url=None,
                citation_key=None,
                verified=False,
                confidence=_MATCH_CONFIDENCE["unverifiable"],
                match_kind="unverifiable",
                diagnostics={"ref_text_preview": ref_text[:80]},
            )
        )

    # Per-citation structured log — one record per outcome. Kept at debug for
    # volume reasons; the `extra=` payload is the structured part that log
    # pipelines (Loki / Datadog / Splunk) index and that monitoring can alert on.
    # Also record to the OTel counter (no-op when no Meter provider is wired).
    for v in verifications:
        logger.debug(
            "[CitationVerify] citation outcome",
            extra={
                "citation_number": v.number,
                "match_kind": v.match_kind,
                "confidence": v.confidence,
                "verified": v.verified,
                "resolved": v.resolved,
                "url": v.url,
                "citation_key": v.citation_key,
                "diagnostics": v.diagnostics,
            },
        )
        _emit_citation_metric(v.match_kind, v.verified, v.resolved)

    # The report keeps every citation that resolved, even with low confidence.
    # Only genuinely unresolved (unmatched / ambiguous / unverifiable) entries
    # get stripped — those are likely fabrications. ``verified`` is reported
    # separately on each record so the UI can render strength.
    valid_citations = [_citation_to_dict(v) for v in verifications if v.resolved]
    removed_records = [v for v in verifications if not v.resolved]
    removed_citations = [_citation_to_dict(v, include_reason=True) for v in removed_records]

    # Dedup: collapse multiple [N] reference lines that resolve to the same
    # registry source. The model often makes the same tool call twice (e.g.
    # ``mcp_time__get_current_time`` for two timezones) and emits a separate
    # ``[N] tool_name`` line for each call; without this pass both lines
    # survive verification because each is independently valid. We keep the
    # lowest-numbered occurrence and rewrite later inline citations to that
    # number so the prose still cites the source.
    seen_keys: dict[str, int] = {}  # canonical_key -> kept citation number
    duplicate_rewrites: dict[int, int] = {}  # duplicate_num -> canonical_num
    deduped_valid: list[dict] = []
    for c in valid_citations:
        key = c["url"] or c["citation_key"]
        if key is None:
            # Defensive: a valid citation must have one of url/citation_key.
            # If neither is set we cannot dedup, so keep the entry.
            deduped_valid.append(c)
            continue
        canonical_num = seen_keys.get(key)
        if canonical_num is None:
            seen_keys[key] = c["number"]
            deduped_valid.append(c)
            continue
        duplicate_rewrites[c["number"]] = canonical_num
        removed_citations.append(
            {
                "number": c["number"],
                "line": c["line"],
                "reason": f"duplicate_of_citation_{canonical_num}",
            }
        )
        logger.debug(
            "[CitationVerify]   [%d] REMOVE — duplicate of [%d]: %s",
            c["number"],
            canonical_num,
            key,
        )
    valid_citations = deduped_valid

    # Apply URL replacements (garbled -> canonical) in the references section
    if url_replacements:
        for garbled, canonical in url_replacements.items():
            ref_section = ref_section.replace(garbled, canonical)

    # Aggregate counters for telemetry. Cardinality is bounded (10 match_kinds),
    # safe to ship to a metrics backend keyed by these tags.
    counts_by_kind: dict[str, int] = {}
    for v in verifications:
        counts_by_kind[v.match_kind] = counts_by_kind.get(v.match_kind, 0) + 1
    kept_below_threshold = sum(1 for v in verifications if v.resolved and not v.verified)

    summary_extra = {
        "total": len(verifications),
        "kept": len(valid_citations),
        "stripped": len(removed_citations),
        "kept_below_threshold": kept_below_threshold,
        "passthrough_threshold": passthrough_threshold,
        "counts_by_match_kind": counts_by_kind,
    }
    logger.info(
        "[CitationVerify] summary: kept=%d (below_threshold=%d) stripped=%d threshold=%.2f",
        len(valid_citations),
        kept_below_threshold,
        len(removed_citations),
        passthrough_threshold,
        extra=summary_extra,
    )

    # Nothing to strip or rewrite: no unresolved citations *and* no duplicates.
    # ``removed_citations`` is the superset (unresolved records + dedup dups),
    # so an empty list means the report body/references need no changes.
    if not removed_citations:
        verified_report = body + ref_section if url_replacements else report_text
        return CitationVerificationResult(
            verified_report=verified_report,
            valid_citations=valid_citations,
            verifications=verifications,
        )

    # Strip both genuinely-removed (unresolved) and duplicate reference lines.
    removed_numbers = {c["number"] for c in removed_citations}

    # Remove invalid (and duplicate) reference lines from the references section.
    cleaned_ref_lines = []
    for line in ref_section.split("\n"):
        line_match = _CITATION_LINE_RE.match(line)
        if line_match and int(line_match.group(1)) in removed_numbers:
            continue
        cleaned_ref_lines.append(line)
    cleaned_ref_section = "\n".join(cleaned_ref_lines)

    # Body fixups:
    #  * Duplicate citations get rewritten to the canonical number — the
    #    cited source is real, only the [N] label is wrong.
    #  * Genuinely invalid citations get stripped — the source is fabricated
    #    or unverifiable.
    cleaned_body = body
    for old_num, canonical_num in duplicate_rewrites.items():
        cleaned_body = re.sub(rf"\[{old_num}\]", f"[{canonical_num}]", cleaned_body)
    invalid_numbers = removed_numbers - set(duplicate_rewrites)
    for num in invalid_numbers:
        cleaned_body = re.sub(rf"\[{num}\]", "", cleaned_body)

    # Note: renumbering is deferred to sanitize_report() which always runs after
    # this function and handles renumbering in a single pass.
    verified_report = cleaned_body + cleaned_ref_section

    return CitationVerificationResult(
        verified_report=verified_report,
        removed_citations=removed_citations,
        valid_citations=valid_citations,
        verifications=verifications,
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
# See _GENERIC_URL_RE for the rationale on why ``,`` is matched and stripped
# via _URL_TRIM_CHARS rather than excluded in the character class.
_BARE_URL_RE = re.compile(r"https?://[^\s<>\"'\]]+")

# Body URL patterns (used by sanitize_report)
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(\s*\w+://[^\s)]+\)")
_BODY_URL_RE = re.compile(r"\w+://[^\s<>\"'\]]+")


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
                url_to_citation[_normalize_url(url_m.group(0).rstrip(_URL_TRIM_CHARS))] = num

    def _replace_body_url(match: re.Match) -> str:
        nonlocal body_urls_removed, body_urls_replaced
        url = match.group(0).rstrip(_URL_TRIM_CHARS)
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
            url = url_match.group(0).rstrip(_URL_TRIM_CHARS)

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

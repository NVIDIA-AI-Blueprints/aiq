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

"""Tests for citation verification module."""

import pytest

from aiq_agent.common.citation_verification import _PARSER_REGISTRY
from aiq_agent.common.citation_verification import EmptySourceRegistryError
from aiq_agent.common.citation_verification import SourceEntry
from aiq_agent.common.citation_verification import SourceRegistry
from aiq_agent.common.citation_verification import _normalize_url
from aiq_agent.common.citation_verification import _parse_citation_key
from aiq_agent.common.citation_verification import extract_sources_from_tool_result
from aiq_agent.common.citation_verification import register_source_parser
from aiq_agent.common.citation_verification import sanitize_report
from aiq_agent.common.citation_verification import verify_citations


@pytest.fixture(autouse=True)
def fixture_restore_parser_registry():
    """Restore the parser registry after each test to prevent leaks."""
    original = list(_PARSER_REGISTRY)
    yield
    _PARSER_REGISTRY.clear()
    _PARSER_REGISTRY.extend(original)


# ---------------------------------------------------------------------------
# URL normalization tests
# ---------------------------------------------------------------------------


class TestNormalizeUrl:
    """Tests for URL normalization."""

    def test_lowercase_scheme_and_host(self):
        assert _normalize_url("HTTPS://Example.COM/path") == "https://example.com/path"

    def test_strip_trailing_slash(self):
        assert _normalize_url("https://example.com/path/") == "https://example.com/path"

    def test_strip_fragment(self):
        assert _normalize_url("https://example.com/page#section") == "https://example.com/page"

    def test_remove_utm_params(self):
        result = _normalize_url("https://example.com/page?utm_source=twitter&key=val")
        assert "utm_source" not in result
        assert "key=val" in result

    def test_unescape_html_entities(self):
        assert _normalize_url("https://example.com/page?a=1&amp;b=2") == "https://example.com/page?a=1&b=2"

    def test_root_path_preserved(self):
        assert _normalize_url("https://example.com") == "https://example.com/"

    def test_identical_urls_match(self):
        url1 = "https://example.com/article?id=42"
        url2 = "https://example.com/article?id=42"
        assert _normalize_url(url1) == _normalize_url(url2)


# ---------------------------------------------------------------------------
# Citation key parsing tests
# ---------------------------------------------------------------------------


class TestParseCitationKey:
    """Tests for knowledge-layer citation key parsing."""

    def test_filename_with_page(self):
        filename, page = _parse_citation_key("report.pdf, p.15")
        assert filename == "report.pdf"
        assert page == 15

    def test_filename_with_page_word(self):
        filename, page = _parse_citation_key("report.pdf, page 15")
        assert filename == "report.pdf"
        assert page == 15

    def test_filename_only(self):
        filename, page = _parse_citation_key("report.pdf")
        assert filename == "report.pdf"
        assert page is None

    def test_filename_with_spaces(self):
        filename, page = _parse_citation_key("my report.pdf, p.3")
        assert filename == "my report.pdf"
        assert page == 3


# ---------------------------------------------------------------------------
# SourceRegistry tests
# ---------------------------------------------------------------------------


class TestSourceRegistry:
    """Tests for SourceRegistry."""

    @pytest.fixture(name="registry")
    def fixture_registry(self):
        return SourceRegistry()

    def test_add_and_has_url(self, registry):
        registry.add(SourceEntry(url="https://example.com/article", source_type="tavily"))
        assert registry.has_url("https://example.com/article")

    def test_url_normalization_on_lookup(self, registry):
        registry.add(SourceEntry(url="https://Example.COM/path/"))
        assert registry.has_url("https://example.com/path")

    def test_missing_url_returns_false(self, registry):
        registry.add(SourceEntry(url="https://example.com/a"))
        assert not registry.has_url("https://example.com/b")

    def test_has_citation_key_exact(self, registry):
        registry.add(SourceEntry(citation_key="report.pdf, p.15", source_type="knowledge_layer"))
        assert registry.has_citation_key("report.pdf, p.15")

    def test_has_citation_key_fuzzy_page_format(self, registry):
        registry.add(SourceEntry(citation_key="report.pdf, p.15"))
        assert registry.has_citation_key("report.pdf, page 15")

    def test_has_citation_key_case_insensitive(self, registry):
        registry.add(SourceEntry(citation_key="Report.PDF, p.15"))
        assert registry.has_citation_key("report.pdf, p.15")

    def test_has_citation_key_no_page(self, registry):
        registry.add(SourceEntry(citation_key="report.pdf"))
        assert registry.has_citation_key("report.pdf")

    def test_has_citation_key_different_page_matches(self, registry):
        """Same file, different page — still matches (lenient)."""
        registry.add(SourceEntry(citation_key="report.pdf, p.15"))
        assert registry.has_citation_key("report.pdf, p.5")

    def test_has_citation_key_different_file_no_match(self, registry):
        registry.add(SourceEntry(citation_key="report.pdf, p.15"))
        assert not registry.has_citation_key("other.pdf, p.15")

    def test_all_sources(self, registry):
        e1 = SourceEntry(url="https://a.com")
        e2 = SourceEntry(citation_key="doc.pdf")
        registry.add(e1)
        registry.add(e2)
        assert len(registry.all_sources()) == 2

    def test_clear(self, registry):
        registry.add(SourceEntry(url="https://a.com"))
        registry.clear()
        assert not registry.has_url("https://a.com")
        assert len(registry.all_sources()) == 0

    def test_deduplicates_urls(self, registry):
        registry.add(SourceEntry(url="https://example.com/page"))
        registry.add(SourceEntry(url="https://example.com/page"))
        assert registry.has_url("https://example.com/page")
        assert len(registry.all_sources()) == 1  # deduplicated by normalized URL

    def test_deduplicates_citation_keys_by_filename(self, registry):
        registry.add(SourceEntry(citation_key="report.pdf, p.5"))
        registry.add(SourceEntry(citation_key="report.pdf, p.10"))
        # Same file, different pages — deduplicated by filename
        assert len(registry.all_sources()) == 1
        assert registry.has_citation_key("report.pdf")

    def test_different_citation_key_files_not_deduped(self, registry):
        registry.add(SourceEntry(citation_key="report.pdf, p.5"))
        registry.add(SourceEntry(citation_key="other.pdf, p.5"))
        assert len(registry.all_sources()) == 2

    def test_resolve_url_exact_match(self, registry):
        registry.add(SourceEntry(url="https://arxiv.org/abs/1706.03762"))
        assert registry.resolve_url("https://arxiv.org/abs/1706.03762") == "https://arxiv.org/abs/1706.03762"

    def test_resolve_url_truncated_path(self, registry):
        """LLM truncated the URL path — resolve to full canonical URL."""
        registry.add(SourceEntry(url="https://arxiv.org/abs/1706.03762"))
        assert registry.resolve_url("https://arxiv.org/abs/1706") == "https://arxiv.org/abs/1706.03762"

    def test_resolve_url_domain_only(self, registry):
        """LLM kept domain but dropped entire path."""
        registry.add(SourceEntry(url="https://arxiv.org/abs/1706.03762"))
        assert registry.resolve_url("https://arxiv.org") == "https://arxiv.org/abs/1706.03762"

    def test_resolve_url_no_match(self, registry):
        registry.add(SourceEntry(url="https://arxiv.org/abs/1706.03762"))
        assert registry.resolve_url("https://totally-different.com") is None

    def test_resolve_url_with_ellipsis_truncation(self, registry):
        """LLM wrote URL with trailing '...' which gets stripped."""
        registry.add(SourceEntry(url="https://example.com/very/long/path/article"))
        # After stripping "...", the truncated URL should match
        resolved = registry.resolve_url("https://example.com/very/long")
        assert resolved == "https://example.com/very/long/path/article"

    def test_resolve_url_truncated_mid_query(self, registry):
        """Report URL cut mid-query (e.g. copy-paste); match by raw prefix."""
        full = "https://example.sharepoint.com/sites/foo/_layouts/15/Doc.aspx?sourcedoc=%7BGUID%7D&file=US%20Benefits%20Open%20Enrollment.pptx&action=edit"
        registry.add(SourceEntry(url=full))
        truncated = (
            "https://example.sharepoint.com/sites/foo/_layouts/15/Doc.aspx?sourcedoc=%7BGUID%7D&file=US%20Benefit"
        )
        resolved = registry.resolve_url(truncated)
        assert resolved == full

    def test_resolve_url_ambiguous_returns_none(self, registry):
        """Shallow ambiguous prefix (e.g. arxiv abs/1706) — reject."""
        registry.add(SourceEntry(url="https://arxiv.org/abs/1706.03762"))
        registry.add(SourceEntry(url="https://arxiv.org/abs/1706.08500"))
        # path "abs/1706" has only 2 segments — too shallow to treat as parent
        assert registry.resolve_url("https://arxiv.org/abs/1706") is None

    def test_resolve_url_prefix_ambiguous_rejected(self, registry):
        """Report URL is prefix of multiple registry URLs — ambiguous, reject."""
        registry.add(SourceEntry(url="https://example.sharepoint.com/sites/hr/Pages/New-Employees.aspx"))
        registry.add(SourceEntry(url="https://example.sharepoint.com/sites/hr/Pages/ourculture.aspx"))
        assert registry.resolve_url("https://example.sharepoint.com/sites/hr/") is None

    def test_resolve_url_unique_prefix_succeeds(self, registry):
        """Single registry URL matches the prefix — unambiguous, return it."""
        registry.add(SourceEntry(url="https://arxiv.org/abs/1706.03762"))
        registry.add(SourceEntry(url="https://arxiv.org/abs/2301.00001"))
        # "https://arxiv.org/abs/1706" only matches the first
        assert registry.resolve_url("https://arxiv.org/abs/1706") == "https://arxiv.org/abs/1706.03762"

    def test_resolve_url_child_path_single_match(self, registry):
        """LLM expanded a registry URL to a subpage — child-path match."""
        registry.add(SourceEntry(url="https://www.example.com/us/benefits/"))
        resolved = registry.resolve_url("https://www.example.com/us/benefits/healthcare/")
        assert resolved == "https://www.example.com/us/benefits/"

    def test_resolve_url_child_path_requires_depth(self, registry):
        """Domain-only registry URLs (< 2 path segments) should NOT child-match."""
        registry.add(SourceEntry(url="https://example.com/"))
        assert registry.resolve_url("https://example.com/us/benefits/") is None

    def test_resolve_url_child_path_single_parent(self, registry):
        """Report URL is a child of only one registry path — match succeeds."""
        registry.add(SourceEntry(url="https://example.com/us/benefits/"))
        registry.add(SourceEntry(url="https://example.com/us/benefits/time-off/"))
        # "healthcare/" is under "benefits/" but not under "time-off/"
        # Only one match, so this should succeed
        resolved = registry.resolve_url("https://example.com/us/benefits/healthcare/")
        assert resolved == "https://example.com/us/benefits/"

    def test_resolve_url_child_path_different_domain(self, registry):
        """Child-path match requires same domain."""
        registry.add(SourceEntry(url="https://example.com/us/benefits/"))
        assert registry.resolve_url("https://other.com/us/benefits/healthcare/") is None

    def test_resolve_url_query_subset_match(self, registry):
        """LLM dropped some query params — query-subset match recovers it."""
        full_url = (
            "https://example.sharepoint.com/:p:/r/sites/benefits/_layouts/15/Doc.aspx"
            "?sourcedoc=%7BGUID-AAA%7D&file=Benefits.pptx&action=edit&mobileredirect=true"
        )
        registry.add(SourceEntry(url=full_url))
        partial_url = (
            "https://example.sharepoint.com/:p:/r/sites/benefits/_layouts/15/Doc.aspx?sourcedoc=%7BGUID-AAA%7D"
        )
        assert registry.resolve_url(partial_url) == full_url

    def test_resolve_url_query_subset_disambiguates_by_params(self, registry):
        """Multiple SharePoint docs with same path — query-subset uses params to pick the right one."""
        url_a = (
            "https://example.sharepoint.com/:p:/r/sites/benefits/_layouts/15/Doc.aspx"
            "?sourcedoc=%7BGUID-AAA%7D&file=Benefits.pptx&action=edit"
        )
        url_b = (
            "https://example.sharepoint.com/:p:/r/sites/benefits/_layouts/15/Doc.aspx"
            "?sourcedoc=%7BGUID-BBB%7D&file=HSA.pptx&action=edit"
        )
        registry.add(SourceEntry(url=url_a))
        registry.add(SourceEntry(url=url_b))
        partial = "https://example.sharepoint.com/:p:/r/sites/benefits/_layouts/15/Doc.aspx?sourcedoc=%7BGUID-BBB%7D"
        assert registry.resolve_url(partial) == url_b

    def test_resolve_url_query_subset_no_match_wrong_value(self, registry):
        """Query-subset rejects when param values differ."""
        registry.add(SourceEntry(url="https://example.com/doc?id=123&mode=view"))
        assert registry.resolve_url("https://example.com/doc?id=999") is None

    def test_resolve_url_query_subset_reordered_params(self, registry):
        """Report URL has a subset of params in different order — only Strategy 5 can match."""
        full_url = (
            "https://example.sharepoint.com/sites/hr/_layouts/15/Doc.aspx"
            "?sourcedoc=%7BGUID-X%7D&file=Handbook.pptx&action=edit&mobileredirect=true"
        )
        registry.add(SourceEntry(url=full_url))
        # Reordered param (action before sourcedoc) — not a raw prefix, so Strategy 2 won't match.
        # Normalization sorts params, so if the subset params match, Strategy 5 picks it up.
        reordered = "https://example.sharepoint.com/sites/hr/_layouts/15/Doc.aspx?action=edit&sourcedoc=%7BGUID-X%7D"
        assert registry.resolve_url(reordered) == full_url

    def test_resolve_url_no_query_params_matched_by_prefix(self, registry):
        """Dropping ALL query params is handled by prefix match (step 2), not query-subset."""
        registry.add(SourceEntry(url="https://example.com/doc?id=123&mode=view"))
        # The path-only URL is a prefix of the full normalized URL → prefix match succeeds
        assert registry.resolve_url("https://example.com/doc") == "https://example.com/doc?id=123&mode=view"


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestGenericUrlExtractor:
    """Tests for the generic URL extractor (works for all tool output formats)."""

    def test_tavily_xml_format(self):
        content = (
            '<Document href="https://example.com/article">\n'
            "<title>\nTest Article\n</title>\n"
            "Some content here.\n</Document>"
        )
        entries = extract_sources_from_tool_result("tavily_web_search", content)
        assert len(entries) == 1
        assert entries[0].url == "https://example.com/article"

    def test_multiple_urls_deduplicated(self):
        content = (
            '<Document href="https://a.com">\nContent A\n</Document>'
            "\n\n---\n\n"
            '<Document href="https://b.com">\nContent B\n</Document>'
        )
        entries = extract_sources_from_tool_result("any_tool", content)
        assert len(entries) == 2
        assert entries[0].url == "https://a.com"
        assert entries[1].url == "https://b.com"

    def test_paper_search_markdown_format(self):
        content = (
            "1. **Attention Is All You Need** (2017)\n"
            "   - **Publication**: NeurIPS\n"
            "   - **Link**: https://arxiv.org/abs/1706.03762"
        )
        entries = extract_sources_from_tool_result("paper_search_tool", content)
        assert len(entries) == 1
        assert entries[0].url == "https://arxiv.org/abs/1706.03762"

    def test_plain_text_with_urls(self):
        """Generic extractor works even for unknown tool formats."""
        content = "Check out https://example.com/page and also https://other.com/doc for details."
        entries = extract_sources_from_tool_result("totally_new_tool", content)
        assert len(entries) == 2

    def test_config_tool_names_work(self):
        """Tools named 'web_search_tool' or 'advanced_web_search_tool' work."""
        content = '<Document href="https://example.com">\nContent\n</Document>'
        for name in ["web_search_tool", "advanced_web_search_tool", "my_custom_search"]:
            entries = extract_sources_from_tool_result(name, content)
            assert len(entries) == 1, f"Failed for tool name: {name}"

    def test_empty_content_returns_empty(self):
        entries = extract_sources_from_tool_result("any_tool", "Search returned no results")
        assert len(entries) == 0

    def test_duplicate_urls_deduplicated(self):
        content = "See https://example.com/page and also https://example.com/page for reference."
        entries = extract_sources_from_tool_result("any_tool", content)
        assert len(entries) == 1


class TestKnowledgeLayerParser:
    """Tests for knowledge layer output parser."""

    def test_parse_single_result(self):
        content = (
            "Found 1 relevant document(s):\n\n"
            "--- Result 1 ---\n"
            "Source: report.pdf\n"
            "Page: 15\n"
            "Citation: report.pdf, p.15\n"
            "Content Type: text\n"
            "Relevance Score: 0.85\n\n"
            "Some content from the document."
        )
        entries = extract_sources_from_tool_result("knowledge_retrieval", content)
        assert len(entries) == 1
        assert entries[0].citation_key == "report.pdf, p.15"
        assert entries[0].title == "report.pdf"
        assert entries[0].url is None
        assert entries[0].source_type == "knowledge_layer"

    def test_parse_multiple_results(self):
        content = (
            "Found 2 relevant document(s):\n\n"
            "--- Result 1 ---\n"
            "Source: doc1.pdf\n"
            "Citation: doc1.pdf\n\n"
            "Content 1.\n\n"
            "--- Result 2 ---\n"
            "Source: doc2.pdf\n"
            "Page: 3\n"
            "Citation: doc2.pdf, p.3\n\n"
            "Content 2."
        )
        entries = extract_sources_from_tool_result("knowledge_retrieval", content)
        assert len(entries) == 2
        assert entries[0].citation_key == "doc1.pdf"
        assert entries[1].citation_key == "doc2.pdf, p.3"


class TestParserDispatcher:
    """Tests for parser dispatcher and fallback behavior."""

    def test_unknown_tool_no_urls_returns_empty(self):
        entries = extract_sources_from_tool_result("totally_unknown_tool", "some content without links")
        assert entries == []

    def test_unknown_tool_with_urls_extracts_them(self):
        """Generic fallback extracts URLs from any unknown tool."""
        entries = extract_sources_from_tool_result("future_tool", "See https://example.com for details")
        assert len(entries) == 1
        assert entries[0].url == "https://example.com"

    def test_custom_parser_takes_priority(self):
        """Registered parsers take priority over generic fallback."""

        def _parse_custom(content: str, tool_name: str) -> list[SourceEntry]:
            return [SourceEntry(url="https://custom.com", source_type="custom", tool_name=tool_name)]

        register_source_parser(lambda name: "my_custom" in name, _parse_custom)
        entries = extract_sources_from_tool_result("my_custom_tool", "anything")
        assert len(entries) == 1
        assert entries[0].url == "https://custom.com"
        assert entries[0].source_type == "custom"


# ---------------------------------------------------------------------------
# verify_citations tests
# ---------------------------------------------------------------------------


class TestVerifyCitations:
    """Tests for verify_citations()."""

    @pytest.fixture(name="registry")
    def fixture_registry(self):
        reg = SourceRegistry()
        reg.add(SourceEntry(url="https://valid.com/article1", title="Article 1", source_type="tavily"))
        reg.add(SourceEntry(url="https://valid.com/article2", title="Article 2", source_type="tavily"))
        reg.add(SourceEntry(citation_key="report.pdf, p.15", title="report.pdf", source_type="knowledge_layer"))
        return reg

    def test_empty_registry_returns_unchanged(self):
        registry = SourceRegistry()
        report = "Some report with [1] citations.\n\n## Sources\n[1] Fake: https://fake.com"
        result = verify_citations(report, registry)
        assert result.verified_report == report
        assert len(result.removed_citations) == 0

    def test_no_references_section_returns_unchanged(self, registry):
        report = "A report without any references section."
        result = verify_citations(report, registry)
        assert result.verified_report == report

    def test_valid_citations_preserved(self, registry):
        report = (
            "Finding one [1]. Finding two [2].\n\n"
            "## Sources\n"
            "[1] Article 1: https://valid.com/article1\n"
            "[2] Article 2: https://valid.com/article2"
        )
        result = verify_citations(report, registry)
        assert "[1]" in result.verified_report
        assert "[2]" in result.verified_report
        assert len(result.valid_citations) == 2
        assert len(result.removed_citations) == 0

    def test_invalid_citation_removed(self, registry):
        report = (
            "Good finding [1]. Bad finding [2].\n\n"
            "## Sources\n"
            "[1] Article 1: https://valid.com/article1\n"
            "[2] Fake Source: https://fake.com/nonexistent"
        )
        result = verify_citations(report, registry)
        assert len(result.removed_citations) == 1
        assert result.removed_citations[0]["number"] == 2
        assert result.removed_citations[0]["reason"] == "url_not_in_registry"
        # Body should have [2] removed
        assert "[2]" not in result.verified_report
        # [1] stays as [1]
        assert "[1]" in result.verified_report

    def test_removal_leaves_gaps_for_sanitize(self, registry):
        """verify_citations removes invalid refs but does NOT renumber — gaps are left for sanitize_report."""
        report = (
            "A [1]. B [2]. C [3].\n\n"
            "## Sources\n"
            "[1] Article 1: https://valid.com/article1\n"
            "[2] Fake: https://fake.com\n"
            "[3] Article 2: https://valid.com/article2"
        )
        result = verify_citations(report, registry)
        assert "A [1]" in result.verified_report
        assert "[2]" not in result.verified_report
        # [3] is NOT renumbered — gaps are closed by sanitize_report()
        assert "C [3]" in result.verified_report

    def test_knowledge_layer_citation_validated(self, registry):
        report = "Internal finding [1].\n\n## Sources\n[1] report.pdf, p.15"
        result = verify_citations(report, registry)
        assert len(result.valid_citations) == 1
        assert len(result.removed_citations) == 0

    def test_knowledge_layer_citation_fuzzy_match(self, registry):
        report = "Finding [1].\n\n## Sources\n[1] report.pdf, page 15"
        result = verify_citations(report, registry)
        assert len(result.valid_citations) == 1

    def test_all_citations_removed(self, registry):
        report = "Bad finding [1].\n\n## Sources\n[1] Totally Fake: https://fake.com/nothing"
        result = verify_citations(report, registry)
        assert len(result.valid_citations) == 0
        assert len(result.removed_citations) == 1
        assert "[1]" not in result.verified_report

    def test_grouped_inline_citations(self, registry):
        report = (
            "Finding [1][2][3].\n\n"
            "## Sources\n"
            "[1] Article 1: https://valid.com/article1\n"
            "[2] Fake: https://fake.com\n"
            "[3] Article 2: https://valid.com/article2"
        )
        result = verify_citations(report, registry)
        # [2] removed, [3] stays (renumbering deferred to sanitize_report)
        assert "Finding [1][3]." in result.verified_report

    def test_references_with_dashes(self, registry):
        """Shallow researcher uses '- [N] Title - URL' format."""
        report = "Finding [1].\n\n**References:**\n- [1] Article 1 - https://valid.com/article1"
        result = verify_citations(report, registry)
        assert len(result.valid_citations) == 1

    def test_references_bold_without_colon(self, registry):
        """Model sometimes outputs **References** without the colon."""
        report = "Finding [1].\n\n**References**\n- [1] Article 1 - https://valid.com/article1"
        result = verify_citations(report, registry)
        assert len(result.valid_citations) == 1

    def test_references_bold_with_trailing_spaces(self, registry):
        """Model outputs **References** followed by trailing spaces."""
        report = "Finding [1].\n\n**References**  \n- [1] Article 1 - https://valid.com/article1"
        result = verify_citations(report, registry)
        assert len(result.valid_citations) == 1

    def test_references_with_hash_header_variants(self, registry):
        """Test ### Sources header variant."""
        report = "Finding [1].\n\n### Sources\n[1] Article 1: https://valid.com/article1"
        result = verify_citations(report, registry)
        assert len(result.valid_citations) == 1

    def test_unverifiable_citation_removed(self, registry):
        """Citation with no URL and no recognizable citation key is removed."""
        report = (
            "Finding [1]. Other [2].\n\n"
            "## Sources\n"
            "[1] Article 1: https://valid.com/article1\n"
            "[2] Some vague reference with no URL"
        )
        result = verify_citations(report, registry)
        assert len(result.removed_citations) == 1
        assert result.removed_citations[0]["reason"] == "unverifiable"

    def test_knowledge_citation_with_internal_label(self, registry):
        """Knowledge citation with '(Internal)' suffix."""
        report = "Finding [1].\n\n**References:**\n- [1] report.pdf, p.15 (Internal)"
        result = verify_citations(report, registry)
        assert len(result.valid_citations) == 1

    def test_knowledge_citation_with_markdown_italics(self, registry):
        """LLM wraps citation in markdown italics *filename.pdf*."""
        report = "Finding [1].\n\n**References**\n- [1] *report.pdf*, p.15"
        result = verify_citations(report, registry)
        assert len(result.valid_citations) == 1
        assert len(result.removed_citations) == 0

    def test_garbled_url_repaired_to_canonical(self):
        """LLM truncated a URL — verify_citations repairs it to the full canonical URL."""
        reg = SourceRegistry()
        reg.add(SourceEntry(url="https://example.com/papers/deep-learning-2024", source_type="generic"))
        report = "Finding [1].\n\n## Sources\n[1] Paper: https://example.com/papers/deep-learning"
        result = verify_citations(report, reg)
        assert len(result.valid_citations) == 1
        # The truncated URL should be repaired to the full canonical URL
        assert "https://example.com/papers/deep-learning-2024" in result.verified_report

    def test_garbled_url_domain_only_repaired(self):
        """LLM dropped entire path — repair to full URL."""
        reg = SourceRegistry()
        reg.add(SourceEntry(url="https://arxiv.org/abs/1706.03762", source_type="generic"))
        report = "Finding [1].\n\n## Sources\n[1] Paper: https://arxiv.org"
        result = verify_citations(report, reg)
        assert len(result.valid_citations) == 1
        assert "https://arxiv.org/abs/1706.03762" in result.verified_report


# ---------------------------------------------------------------------------
# sanitize_report tests
# ---------------------------------------------------------------------------


class TestSanitizeReport:
    """Tests for deterministic report sanitization."""

    def test_body_url_not_in_refs_stripped(self):
        """Bare body URL with no matching reference is removed."""
        report = (
            "NVIDIA is great (see https://nvidia.com/gpus for details) [1].\n\n"
            "## Sources\n"
            "[1] NVIDIA: https://nvidia.com/article"
        )
        result = sanitize_report(report)
        assert "https://nvidia.com/gpus" not in result.sanitized_report
        # URL in references preserved
        assert "https://nvidia.com/article" in result.sanitized_report
        assert result.body_urls_removed == 1
        assert result.body_urls_replaced == 0

    def test_body_url_matching_ref_replaced_with_citation(self):
        """Bare body URL matching a reference is replaced with [N]."""
        report = (
            "Visit https://arxiv.org/abs/1706.03762 for the paper [1].\n\n"
            "## Sources\n"
            "[1] Paper: https://arxiv.org/abs/1706.03762"
        )
        result = sanitize_report(report)
        # Body URL replaced with citation number
        assert "Visit [1] for the paper [1]" in result.sanitized_report
        # Reference section URL preserved
        assert "[1] Paper: https://arxiv.org/abs/1706.03762" in result.sanitized_report
        assert result.body_urls_replaced == 1
        assert result.body_urls_removed == 0

    def test_markdown_links_collapsed_to_text_in_body(self):
        """Markdown hyperlinks [text](url) should be collapsed to display text."""
        report = (
            "Read the [NVIDIA docs](https://nvidia.com/docs/guide) for details [1].\n\n"
            "## Sources\n"
            "[1] Article: https://example.com/article"
        )
        result = sanitize_report(report)
        assert "NVIDIA docs" in result.sanitized_report
        assert "https://nvidia.com/docs/guide" not in result.sanitized_report

    def test_body_without_urls_unchanged(self):
        report = (
            "Finding [1]. Another finding [2].\n\n"
            "## Sources\n"
            "[1] Title: https://example.com/article\n"
            "[2] Title: https://other.com/page"
        )
        result = sanitize_report(report)
        assert result.body_urls_removed == 0
        assert "Finding [1]" in result.sanitized_report

    def test_shortened_url_removed_from_references(self):
        report = "Finding [1].\n\n## Sources\n[1] Article: https://bit.ly/abc123"
        result = sanitize_report(report)
        assert "bit.ly" not in result.sanitized_report
        assert len(result.shortened_urls_removed) == 1
        assert "bit.ly" in result.shortened_urls_removed[0]

    def test_tco_shortened_url_removed(self):
        report = "Finding [1].\n\n## Sources\n[1] Tweet: https://t.co/xyz789"
        result = sanitize_report(report)
        assert "t.co" not in result.sanitized_report
        assert len(result.shortened_urls_removed) == 1

    def test_ip_address_url_removed(self):
        report = "Finding [1].\n\n## Sources\n[1] Suspicious: https://192.168.1.1/malware"
        result = sanitize_report(report)
        assert "192.168.1.1" not in result.sanitized_report
        assert len(result.unsafe_urls_removed) == 1

    def test_legitimate_urls_preserved(self):
        report = (
            "Finding [1] and [2].\n\n"
            "## Sources\n"
            "[1] Paper: https://arxiv.org/abs/1706.03762\n"
            "[2] News: https://www.reuters.com/technology/nvidia-2026"
        )
        result = sanitize_report(report)
        assert "arxiv.org" in result.sanitized_report
        assert "reuters.com" in result.sanitized_report
        assert result.body_urls_removed == 0
        assert len(result.shortened_urls_removed) == 0
        assert len(result.unsafe_urls_removed) == 0

    def test_multiple_shorteners_all_removed(self):
        report = (
            "Finding [1][2][3].\n\n"
            "## Sources\n"
            "[1] A: https://bit.ly/abc\n"
            "[2] B: https://tinyurl.com/def\n"
            "[3] C: https://arxiv.org/real-paper"
        )
        result = sanitize_report(report)
        assert "bit.ly" not in result.sanitized_report
        assert "tinyurl.com" not in result.sanitized_report
        assert "arxiv.org" in result.sanitized_report
        assert len(result.shortened_urls_removed) == 2

    def test_no_references_section(self):
        """Report without references — only body URL stripping applies."""
        report = "Check https://example.com for more info."
        result = sanitize_report(report)
        assert "https://example.com" not in result.sanitized_report
        assert result.body_urls_removed == 1

    def test_truncated_url_with_ellipsis_removed(self):
        """URL ending in ... is truncated/garbled — entire reference line removed."""
        report = "Finding [1].\n\n## Sources\n[1] Paper: https://arxiv.org/abs/1706.037..."
        result = sanitize_report(report)
        # The entire reference line with the truncated URL should be gone
        assert "[1] Paper:" not in result.sanitized_report
        assert len(result.truncated_urls_removed) == 1

    def test_domain_only_url_preserved(self):
        """Domain-only URLs are legitimate if they came from tool results."""
        report = "Finding [1].\n\n## Sources\n[1] Weather API: https://www.weatherapi.com/"
        result = sanitize_report(report)
        assert "weatherapi.com" in result.sanitized_report
        assert len(result.truncated_urls_removed) == 0

    def test_full_url_not_flagged_as_truncated(self):
        """URLs with actual paths are fine."""
        report = "Finding [1].\n\n## Sources\n[1] Paper: https://arxiv.org/abs/1706.03762"
        result = sanitize_report(report)
        assert "arxiv.org/abs/1706.03762" in result.sanitized_report
        assert len(result.truncated_urls_removed) == 0

    def test_renumbering_closes_gaps_from_verify(self):
        """sanitize_report renumbers to close gaps left by verify_citations."""
        # Simulate output of verify_citations that removed [2]: gaps [1], [3]
        report = (
            "A [1]. C [3].\n\n"
            "## Sources\n"
            "[1] Article 1: https://valid.com/article1\n"
            "[3] Article 2: https://valid.com/article2"
        )
        result = sanitize_report(report)
        assert "A [1]" in result.sanitized_report
        assert "C [2]" in result.sanitized_report
        assert "[3]" not in result.sanitized_report

    def test_full_pipeline_verify_then_sanitize(self):
        """End-to-end: verify removes invalid, sanitize renumbers and cleans."""
        registry = SourceRegistry()
        registry.add(SourceEntry(url="https://valid.com/article1", source_type="tavily"))
        registry.add(SourceEntry(url="https://valid.com/article2", source_type="tavily"))
        report = (
            "A [1]. B [2]. C [3].\n\n"
            "## Sources\n"
            "[1] Article 1: https://valid.com/article1\n"
            "[2] Fake: https://fake.com\n"
            "[3] Article 2: https://valid.com/article2"
        )
        verified = verify_citations(report, registry).verified_report
        sanitized = sanitize_report(verified).sanitized_report
        assert "A [1]" in sanitized
        assert "C [2]" in sanitized
        assert "[3]" not in sanitized

    def test_mixed_issues(self):
        """Body URL + shortened reference + valid references."""
        report = (
            "See https://nvidia.com/gpus inline [1][2].\n\n"
            "## Sources\n"
            "[1] Good: https://arxiv.org/abs/paper\n"
            "[2] Short: https://bit.ly/short"
        )
        result = sanitize_report(report)
        assert "https://nvidia.com" not in result.sanitized_report
        assert "arxiv.org/abs/paper" in result.sanitized_report
        assert "bit.ly" not in result.sanitized_report
        # nvidia.com/gpus doesn't match any reference → removed
        assert result.body_urls_removed == 1
        assert len(result.shortened_urls_removed) == 1

    def test_mixed_body_urls_some_match_some_not(self):
        """Body has two URLs: one matches a reference, one doesn't."""
        report = (
            "See https://arxiv.org/abs/paper and https://unknown.com for details [1].\n\n"
            "## Sources\n"
            "[1] Paper: https://arxiv.org/abs/paper"
        )
        result = sanitize_report(report)
        # Matching URL replaced with [1], unknown URL stripped
        assert "See [1] and for details [1]" in result.sanitized_report
        assert "https://unknown.com" not in result.sanitized_report
        assert result.body_urls_replaced == 1
        assert result.body_urls_removed == 1


# ---------------------------------------------------------------------------
# EmptySourceRegistryError
# ---------------------------------------------------------------------------


class TestEmptySourceRegistryError:
    """Tests for EmptySourceRegistryError."""

    def test_default_message(self):
        err = EmptySourceRegistryError()
        assert "no sources were captured" in str(err)
        assert "research" in str(err)

    def test_custom_agent_type(self):
        err = EmptySourceRegistryError("deep research")
        assert "deep research" in str(err)
        assert err.agent_type == "deep research"

    def test_is_exception(self):
        with pytest.raises(EmptySourceRegistryError):
            raise EmptySourceRegistryError("test")


# ---------------------------------------------------------------------------
# Session Registry
# ---------------------------------------------------------------------------


class TestSessionRegistry:
    """Tests for session-scoped registry management."""

    def setup_method(self):
        """Clear session registries before each test."""
        from aiq_agent.common.citation_verification import _session_registries
        from aiq_agent.common.citation_verification import _session_registries_lock

        with _session_registries_lock:
            _session_registries.clear()

    def test_get_or_create_returns_same_instance(self):
        from aiq_agent.common.citation_verification import get_or_create_session_registry

        r1 = get_or_create_session_registry("session-1")
        r2 = get_or_create_session_registry("session-1")
        assert r1 is r2

    def test_different_sessions_different_registries(self):
        from aiq_agent.common.citation_verification import get_or_create_session_registry

        r1 = get_or_create_session_registry("session-a")
        r2 = get_or_create_session_registry("session-b")
        assert r1 is not r2

    def test_contextvar_set_and_get(self):
        from aiq_agent.common.citation_verification import get_session_registry
        from aiq_agent.common.citation_verification import set_session_registry

        assert get_session_registry() is None
        reg = SourceRegistry()
        set_session_registry(reg)
        assert get_session_registry() is reg
        set_session_registry(None)
        assert get_session_registry() is None

    def test_lru_eviction(self):
        from aiq_agent.common.citation_verification import _MAX_SESSION_REGISTRIES
        from aiq_agent.common.citation_verification import _session_registries
        from aiq_agent.common.citation_verification import _session_registries_lock
        from aiq_agent.common.citation_verification import get_or_create_session_registry

        # Fill to max + 10
        for i in range(_MAX_SESSION_REGISTRIES + 10):
            get_or_create_session_registry(f"evict-{i}")
        with _session_registries_lock:
            assert len(_session_registries) == _MAX_SESSION_REGISTRIES

    def test_sources_persist_across_calls(self):
        """Sources added to a session registry persist when retrieved again."""
        from aiq_agent.common.citation_verification import get_or_create_session_registry

        reg = get_or_create_session_registry("persist-test")
        reg.add(SourceEntry(url="https://example.com/first"))

        reg2 = get_or_create_session_registry("persist-test")
        assert reg2.has_url("https://example.com/first")
        assert len(reg2.all_sources()) == 1

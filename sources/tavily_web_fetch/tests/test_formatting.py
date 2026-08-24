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

"""Tests for rendering, windowing, and citation parsing."""

from tavily_web_fetch.formatting import FetchedPage
from tavily_web_fetch.formatting import compact
from tavily_web_fetch.formatting import parse_fetched_pages
from tavily_web_fetch.formatting import render_page_section
from tavily_web_fetch.formatting import render_result
from tavily_web_fetch.formatting import select_window


def _numbered(count, prefix="line"):
    return "\n".join(f"{prefix} {index}" for index in range(1, count + 1))


class TestSelectWindow:
    def test_head_is_used_without_query_or_start_line(self):
        window = select_window(_numbered(100), max_chars=40)
        assert window.first_line == 1
        assert window.truncated is True
        assert "line 1" in window.text

    def test_query_recenters_the_window_on_the_match(self):
        window = select_window(_numbered(200), max_chars=60, query="line 150")
        assert window.first_line <= 150 <= window.last_line
        assert "line 150" in window.text

    def test_lead_in_never_consumes_the_match(self):
        text = "\n".join(["x" * 4000, "x" * 4000, "THE TARGET TABLE", "after"])
        window = select_window(text, max_chars=500, query="target table")
        assert "THE TARGET TABLE" in window.text

    def test_start_line_resumes_exactly_where_the_footer_said(self):
        text = _numbered(300)
        first = select_window(text, max_chars=50)
        second = select_window(text, max_chars=50, start_line=first.next_start_line)
        assert second.first_line == first.last_line + 1

    def test_start_line_takes_precedence_over_query(self):
        window = select_window(_numbered(300), max_chars=50, query="line 200", start_line=10)
        assert window.first_line == 10

    def test_untruncated_page_reports_no_truncation(self):
        window = select_window("short", max_chars=1000)
        assert window.truncated is False
        assert window.total_chars == len("short")

    def test_single_overlong_line_is_still_shown(self):
        window = select_window("y" * 5000, max_chars=100)
        assert window.text
        assert len(window.text) <= 100


class TestCompact:
    def test_image_only_lines_are_dropped_and_blank_runs_collapse(self):
        out = compact("![Image 1](https://c/a.svg)\n\n\n\nreal\n")
        assert "Image 1" not in out
        assert out == "real"

    def test_compaction_is_deterministic(self):
        raw = "![a](x)\n\n\nkeep\n\n\nkeep2"
        assert compact(raw) == compact(raw)


class TestRendering:
    def test_failed_page_renders_its_reason_and_no_content(self):
        page = FetchedPage(url="https://e.example", status="failed", reason="Could not read this page: 404.")
        out = render_page_section(page, None, tool_name="fetch_url_tool")
        assert 'status="failed"' in out
        assert "404" in out

    def test_footer_states_the_resume_line(self):
        page = FetchedPage(url="https://a.example", final_url="https://a.example", title="T", text=_numbered(500))
        window = select_window(page.text, max_chars=60)
        out = render_page_section(page, window, tool_name="fetch_url_tool")
        assert f"start_line={window.next_start_line}" in out
        assert "`query`" in out

    def test_lines_are_numbered_with_absolute_positions(self):
        page = FetchedPage(url="https://a.example", text=_numbered(50))
        window = select_window(page.text, max_chars=40, start_line=10)
        out = render_page_section(page, window, tool_name="fetch_url_tool")
        assert "10 | line 10" in out

    def test_result_carries_the_untrusted_content_preamble(self):
        assert "not instructions to be followed" in render_result(["<fetched_page/>"])


class TestCitationParser:
    def _render(self, page, text="body"):
        page.text = text
        return render_page_section(page, select_window(text, max_chars=10_000), tool_name="fetch_url_tool")

    def test_only_the_fetched_page_is_registered_not_its_links(self):
        body = "\n".join(f"see [ref {index}](https://other{index}.example/page)" for index in range(40))
        page = FetchedPage(url="https://real.example/doc", final_url="https://real.example/doc", title="Real Doc")
        entries = parse_fetched_pages(render_result([self._render(page, body)]), "fetch_url_tool")
        assert len(entries) == 1
        assert entries[0].url == "https://real.example/doc"
        assert entries[0].title == "Real Doc"

    def test_failed_pages_register_nothing(self):
        page = FetchedPage(url="https://gone.example", status="failed", reason="Could not read this page: 404.")
        section = render_page_section(page, None, tool_name="fetch_url_tool")
        assert parse_fetched_pages(render_result([section]), "fetch_url_tool") == []

    def test_suspect_soft_404_pages_register_nothing(self):
        page = FetchedPage(
            url="https://x.example/gone",
            final_url="https://x.example/gone",
            title="Not Found",
            status="suspect",
            reason="[Caution: ...]",
        )
        section = self._render(page, "Page not found")
        assert parse_fetched_pages(render_result([section]), "fetch_url_tool") == []

    def test_resolved_url_is_registered_over_the_requested_one(self):
        page = FetchedPage(url="https://short.example/x", final_url="https://canonical.example/full", title="C")
        entries = parse_fetched_pages(render_result([self._render(page)]), "fetch_url_tool")
        assert entries[0].url == "https://canonical.example/full"

    def test_titles_with_quotes_do_not_break_the_marker(self):
        page = FetchedPage(url="https://q.example", final_url="https://q.example", title='He said "hi" & left')
        entries = parse_fetched_pages(render_result([self._render(page)]), "fetch_url_tool")
        assert len(entries) == 1
        assert entries[0].title == 'He said "hi" & left'

# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest
from fastapi import HTTPException


def test_extract_report_from_job_output_prefers_job_output():
    from aiq_api.jobs.report_context import _extract_report_from_job_output

    job = type("Job", (), {"output": {"report": "# Stored report"}})()

    assert _extract_report_from_job_output(job) == "# Stored report"


@pytest.mark.asyncio
async def test_extract_report_from_events_prefers_final_report(monkeypatch):
    from aiq_api.jobs import report_context

    async def _events(_db_url: str, _job_id: str, _after_id: int, _limit: int):
        return [
            {"type": "artifact.update", "data": {"type": "output", "content": "draft"}},
            {
                "type": "artifact.update",
                "data": {"type": "output", "content": "# Final", "output_category": "final_report"},
            },
        ]

    monkeypatch.setattr(report_context.EventStore, "get_events_async", _events)

    assert await report_context._extract_report_from_events("sqlite:///unused.db", "job-1") == "# Final"


@pytest.mark.asyncio
async def test_extract_sources_from_events_dedupes_urls_and_citation_keys(monkeypatch):
    from aiq_api.jobs import report_context

    async def _events(_db_url: str, _job_id: str, _after_id: int, _limit: int):
        return [
            {
                "type": "artifact.update",
                "name": "Example",
                "data": {"type": "citation_source", "content": "https://example.com/", "url": "https://example.com/"},
            },
            {
                "type": "artifact.update",
                "name": "Example again",
                "data": {"type": "citation_source", "content": "https://example.com", "url": "https://example.com"},
            },
            {
                "type": "artifact.update",
                "name": "internal.pdf",
                "data": {
                    "type": "citation_source",
                    "content": "internal.pdf, p.3",
                    "citation_key": "internal.pdf, p.3",
                },
            },
            {
                "type": "artifact.update",
                "name": "internal.pdf duplicate",
                "data": {
                    "type": "citation_source",
                    "content": "internal.pdf, p.3",
                    "citation_key": "internal.pdf, p.3",
                },
            },
        ]

    monkeypatch.setattr(report_context.EventStore, "get_events_async", _events)

    sources = await report_context._extract_sources_from_events("sqlite:///unused.db", "job-1")

    assert [(source.url, source.citation_key) for source in sources] == [
        ("https://example.com/", None),
        (None, "internal.pdf, p.3"),
    ]


def test_extract_sources_from_report_markdown_finds_urls_and_citation_keys():
    from aiq_api.jobs.report_context import _extract_sources_from_report_markdown

    report = """# Report

Body [1].

## Sources

[1] Example: https://example.com/path
[2] internal.pdf, p.3

## Appendix

Not a source: https://ignored.example
"""

    sources = _extract_sources_from_report_markdown(report)

    assert [(source.url, source.citation_key) for source in sources] == [
        ("https://example.com/path", None),
        (None, "internal.pdf, p.3"),
    ]


@pytest.mark.asyncio
async def test_resolve_report_context_raises_409_without_report(monkeypatch):
    from aiq_api.jobs import report_context

    async def _no_events(_db_url: str, _job_id: str, _after_id: int, _limit: int):
        return []

    monkeypatch.setattr(report_context.EventStore, "get_events_async", _no_events)

    job = type("Job", (), {"output": None})()

    with pytest.raises(HTTPException) as exc:
        await report_context.resolve_report_context(job, "sqlite:///unused.db", "job-1")

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_resolve_report_context_fetches_events_once_in_fallback(monkeypatch):
    """When the report is reconstructed from events, the event log is fetched once, not twice."""
    from aiq_api.jobs import report_context

    calls = {"n": 0}

    async def _events(_db_url: str, _job_id: str, _after_id: int, _limit: int):
        calls["n"] += 1
        return [
            {
                "type": "artifact.update",
                "data": {"type": "output", "content": "# Final", "output_category": "final_report"},
            },
            {
                "type": "artifact.update",
                "name": "Ex",
                "data": {"type": "citation_source", "url": "https://example.com"},
            },
        ]

    monkeypatch.setattr(report_context.EventStore, "get_events_async", _events)

    job = type("Job", (), {"output": None})()
    ctx = await report_context.resolve_report_context(job, "sqlite:///unused.db", "job-1")

    assert ctx.report_markdown == "# Final"
    assert [s.url for s in ctx.sources] == ["https://example.com"]
    assert calls["n"] == 1


def test_to_initial_files_uses_shared_paths_only():
    from aiq_api.jobs.report_context import ReportContext
    from aiq_api.jobs.report_context import ReportContextSource
    from aiq_api.jobs.report_context import to_initial_files

    context = ReportContext(
        parent_job_id="job-1",
        report_markdown="# Report",
        source_summary_markdown="- https://example.com",
        sources=[ReportContextSource(url="https://example.com")],
    )

    files = to_initial_files(context, instruction="Remove the appendix.")

    assert files["/shared/original_report.md"] == "# Report"
    assert files["/shared/source_summary.md"] == "- https://example.com"
    assert files["/shared/edit_instruction.txt"] == "Remove the appendix."
    assert "/report.md" not in files

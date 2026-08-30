# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for Foundational RAG summary-store integration."""

from knowledge_layer.foundational_rag import adapter as foundational_rag_adapter
from knowledge_layer.foundational_rag.adapter import FoundationalRagIngestor


class _SuccessfulUploadResponse:
    def raise_for_status(self) -> None:
        """Simulate a successful HTTP response."""

    def json(self) -> dict[str, str]:
        """Return the asynchronous task identifier."""
        return {"task_id": "task-1"}


class _SuccessfulUploadSession:
    def post(self, *args, **kwargs) -> _SuccessfulUploadResponse:
        """Return a successful upload response."""
        del args, kwargs
        return _SuccessfulUploadResponse()


def test_upload_without_summary_generation_registers_placeholder(tmp_path, monkeypatch):
    """Every accepted upload must be available to the summary-store workflow."""
    monkeypatch.setattr(FoundationalRagIngestor, "_start_ttl_cleanup_task", lambda *args: None)
    registered = []
    monkeypatch.setattr(
        foundational_rag_adapter,
        "register_summary",
        lambda collection, file_name, summary: registered.append((collection, file_name, summary)),
    )
    file_path = tmp_path / "table.csv"
    file_path.write_text("column,value\nfoo,1\n", encoding="utf-8")
    ingestor = FoundationalRagIngestor({"generate_summary": False})
    ingestor.session = _SuccessfulUploadSession()

    file_info = ingestor.upload_file(str(file_path), "docs")

    assert file_info.metadata["summary"] is None
    assert registered == [("docs", "table.csv", "No summary available")]

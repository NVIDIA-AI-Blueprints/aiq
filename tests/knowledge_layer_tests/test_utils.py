# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for shared Knowledge Layer utilities."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from knowledge_layer.utils import summarize_document


class TestSummarizeDocument:
    """Tests for document summary generation."""

    def test_returns_none_without_llm(self):
        """Skip summarization when no LLM is configured."""
        assert summarize_document("Document content", None) is None

    def test_returns_none_for_blank_document_without_invoking_llm(self):
        """Skip summarization when the document has no content."""
        llm = MagicMock()

        assert summarize_document(" \n\t ", llm) is None
        llm.invoke.assert_not_called()

    def test_invokes_llm_with_trimmed_truncated_content_and_filename(self):
        """Build the expected prompt from normalized document content."""
        llm = MagicMock()
        llm.invoke.return_value = SimpleNamespace(content="  Summary of the document.  ")

        result = summarize_document(
            "  Important research findings beyond the limit  ",
            llm,
            input_max_chars=18,
        )

        assert result == "Summary of the document."
        llm.invoke.assert_called_once_with(
            "Summarize this uploaded document in one concise sentence for a research assistant. "
            "Focus on the document's topic and likely usefulness.\n\n"
            "Content Excerpt:\nImportant research"
        )

    def test_returns_none_for_empty_llm_response(self):
        """Treat empty LLM output as no available summary."""
        llm = MagicMock()
        llm.invoke.return_value = SimpleNamespace(content=" \n ")

        assert summarize_document("Document content", llm) is None

    def test_returns_none_when_llm_invocation_fails(self):
        """Contain LLM failures so document ingestion can continue."""
        llm = MagicMock()
        llm.invoke.side_effect = RuntimeError("LLM unavailable")

        assert summarize_document("Document content", llm) is None

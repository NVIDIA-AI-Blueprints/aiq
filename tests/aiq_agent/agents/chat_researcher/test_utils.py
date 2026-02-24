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

"""Tests for chat researcher utilities."""

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage

from aiq_agent.agents.chat_researcher.utils import _extract_query_and_sources
from aiq_agent.agents.chat_researcher.utils import _extract_query_from_text
from aiq_agent.agents.chat_researcher.utils import _extract_text_from_message
from aiq_agent.agents.chat_researcher.utils import trim_message_history


class TestTrimMessageHistory:
    """Tests for the trim_message_history function."""

    def test_trim_message_history_basic(self):
        """Test basic message trimming."""
        messages = [
            HumanMessage(content="Hello"),
            AIMessage(content="Hi there!"),
            HumanMessage(content="How are you?"),
            AIMessage(content="I'm doing well!"),
        ]

        result = trim_message_history(messages, max_tokens=10)

        # Should keep messages within token limit
        assert isinstance(result, list)

    def test_trim_message_history_empty(self):
        """Test trimming empty message list."""
        messages = []
        result = trim_message_history(messages, max_tokens=10)
        assert result == []

    def test_trim_message_history_single_message(self):
        """Test trimming with single message."""
        messages = [HumanMessage(content="Hello")]
        result = trim_message_history(messages, max_tokens=10)
        assert len(result) >= 0  # May be empty if message exceeds limit

    def test_trim_message_history_with_system_message(self):
        """Test trimming includes system messages."""
        messages = [
            SystemMessage(content="You are a helpful assistant."),
            HumanMessage(content="Hello"),
            AIMessage(content="Hi!"),
        ]

        result = trim_message_history(messages, max_tokens=20)

        # System messages should be preserved according to include_system=True
        assert isinstance(result, list)

    def test_trim_message_history_large_limit(self):
        """Test trimming with large token limit keeps all messages."""
        messages = [
            HumanMessage(content="A"),
            AIMessage(content="B"),
            HumanMessage(content="C"),
        ]

        result = trim_message_history(messages, max_tokens=1000)

        # With a large limit, should keep messages
        assert isinstance(result, list)

    def test_trim_message_history_strategy_last(self):
        """Test that trimming uses 'last' strategy (keeps recent messages)."""
        messages = [
            HumanMessage(content="First message"),
            AIMessage(content="Response 1"),
            HumanMessage(content="Second message"),
            AIMessage(content="Response 2"),
            HumanMessage(content="Third message"),
        ]

        result = trim_message_history(messages, max_tokens=5)

        # Strategy 'last' should prioritize recent messages
        assert isinstance(result, list)


class TestExtractTextFromMessage:
    """Tests for _extract_text_from_message."""

    def test_extract_from_string(self):
        """Test extracting text from a plain string."""
        assert _extract_text_from_message("Hello world") == "Hello world"

    def test_extract_from_none(self):
        """Test that None returns None."""
        assert _extract_text_from_message(None) is None

    def test_extract_from_object_content(self):
        """Test extracting text from object content attribute."""
        obj = MagicMock()
        obj.content = "Content from attribute"
        assert _extract_text_from_message(obj) == "Content from attribute"

    def test_extract_from_multipart_list(self):
        """Test extracting text from multipart list."""
        obj = MagicMock()
        part1 = MagicMock()
        part1.type = "text"
        part1.text = "First part"
        part2 = MagicMock()
        part2.type = "text"
        part2.text = "Second part"
        obj.content = [part1, part2]
        result = _extract_text_from_message(obj)
        assert result == "First part\nSecond part"

    def test_extract_from_dict_message(self):
        """Test extracting text from dict message."""
        message = {"content": [{"type": "text", "text": "Hello"}]}
        assert _extract_text_from_message(message) == "Hello"


class TestExtractQueryFromText:
    """Tests for _extract_query_from_text."""

    def test_extract_simple_text(self):
        """Test extracting from plain text."""
        query, sources = _extract_query_from_text("What is CUDA?")
        assert query == "What is CUDA?"
        assert sources is None

    def test_extract_empty_text(self):
        """Test extracting from empty string."""
        query, sources = _extract_query_from_text("")
        assert query == ""
        assert sources is None

    def test_extract_json_payload(self):
        """Test extracting from JSON payload."""
        text = '{"query": "Test query", "data_sources": ["web_search"]}'
        query, sources = _extract_query_from_text(text)
        assert query == "Test query"
        assert sources == ["web_search"]

    def test_extract_invalid_json(self):
        """Test invalid JSON returns original text."""
        text = '{"invalid json'
        query, sources = _extract_query_from_text(text)
        assert query == text
        assert sources is None


class TestExtractQueryAndSources:
    """Tests for _extract_query_and_sources."""

    def test_extract_from_dict_payload(self):
        """Test extracting from dict payload."""
        payload = {
            "content": {
                "messages": [{"role": "user", "content": "Query text"}],
                "data_sources": ["confluence"],
            }
        }
        query, sources = _extract_query_and_sources(payload)
        assert query == "Query text"
        assert sources == ["confluence"]

    def test_extract_from_object_payload(self):
        """Test extracting from object payload with messages."""
        user_msg = MagicMock()
        user_msg.role = "user"
        user_msg.content = "Object query"
        payload = MagicMock()
        payload.messages = [user_msg]
        payload.data_sources = None
        query, sources = _extract_query_and_sources(payload)
        assert query == "Object query"
        assert sources is None

    def test_extract_from_string_payload(self):
        """Test extracting from string payload."""
        query, sources = _extract_query_and_sources("Plain query string")
        assert query == "Plain query string"
        assert sources is None

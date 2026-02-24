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

"""Tests for chat_researcher register.py helper functions."""

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage

from aiq_agent.agents.chat_researcher.utils import _extract_query_and_sources
from aiq_agent.agents.chat_researcher.utils import _extract_query_from_text
from aiq_agent.agents.chat_researcher.utils import _extract_text_from_message


class TestExtractTextFromMessageString:
    """Tests for _extract_text_from_message with string inputs."""

    def test_extract_from_string(self):
        """Test extracting text from a plain string."""
        result = _extract_text_from_message("Hello world")
        assert result == "Hello world"

    def test_extract_from_none(self):
        """Test that None returns None."""
        result = _extract_text_from_message(None)
        assert result is None

    def test_extract_from_empty_string(self):
        """Test extracting from empty string."""
        result = _extract_text_from_message("")
        assert result == ""


class TestExtractTextFromMessageObject:
    """Tests for _extract_text_from_message with message objects."""

    def test_extract_from_human_message(self):
        """Test extracting from HumanMessage."""
        message = HumanMessage(content="User query")
        result = _extract_text_from_message(message)
        assert result == "User query"

    def test_extract_from_ai_message(self):
        """Test extracting from AIMessage."""
        message = AIMessage(content="AI response")
        result = _extract_text_from_message(message)
        assert result == "AI response"

    def test_extract_from_object_with_content_attribute(self):
        """Test extracting from object with content attribute."""
        obj = MagicMock()
        obj.content = "Content from attribute"
        result = _extract_text_from_message(obj)
        assert result == "Content from attribute"


class TestExtractTextFromMessageMultipart:
    """Tests for _extract_text_from_message with multipart content."""

    def test_extract_from_multipart_content_list(self):
        """Test extracting from message with list content."""
        obj = MagicMock()
        part1 = MagicMock()
        part1.type = "text"
        part1.text = "First part"
        part2 = MagicMock()
        part2.type = "text"
        part2.text = "Second part"
        obj.content = [part1, part2]

        result = _extract_text_from_message(obj)
        assert "First part" in result
        assert "Second part" in result

    def test_extract_from_dict_multipart(self):
        """Test extracting from dict with multipart content."""
        message = {
            "content": [
                {"type": "text", "text": "Hello"},
                {"type": "image", "url": "http://example.com"},
                {"type": "text", "text": "World"},
            ]
        }
        result = _extract_text_from_message(message)
        assert "Hello" in result
        assert "World" in result

    def test_extract_skips_non_text_parts(self):
        """Test that non-text parts are skipped."""
        obj = MagicMock()
        text_part = MagicMock()
        text_part.type = "text"
        text_part.text = "Text content"
        image_part = MagicMock()
        image_part.type = "image"
        obj.content = [text_part, image_part]

        result = _extract_text_from_message(obj)
        assert result == "Text content"


class TestExtractTextFromMessageDict:
    """Tests for _extract_text_from_message with dict inputs."""

    def test_extract_from_dict_with_content(self):
        """Test extracting from dict with content key."""
        message = {"content": "Dict content"}
        result = _extract_text_from_message(message)
        assert result == "Dict content"

    def test_extract_from_dict_with_text_key(self):
        """Test extracting from dict with text key."""
        message = {"text": "Text value"}
        result = _extract_text_from_message(message)
        assert result == "Text value"

    def test_extract_from_dict_content_takes_precedence(self):
        """Test that content key is preferred over text key in dict lists."""
        message = {"content": "Content value", "text": "Text value"}
        result = _extract_text_from_message(message)
        assert result == "Content value"


class TestExtractQueryFromText:
    """Tests for _extract_query_from_text function."""

    def test_extract_plain_text(self):
        """Test that plain text is returned as-is."""
        query, sources = _extract_query_from_text("What is CUDA?")
        assert query == "What is CUDA?"
        assert sources is None

    def test_extract_empty_text(self):
        """Test extracting from empty text."""
        query, sources = _extract_query_from_text("")
        assert query == ""
        assert sources is None

    def test_extract_json_payload_with_query(self):
        """Test extracting from JSON payload with query key."""
        text = '{"query": "What is CUDA?", "data_sources": ["web_search"]}'
        query, sources = _extract_query_from_text(text)
        assert query == "What is CUDA?"
        assert sources == ["web_search"]

    def test_extract_json_payload_with_text_key(self):
        """Test extracting from JSON payload with text key."""
        text = '{"text": "Hello world", "data_sources": "confluence"}'
        query, sources = _extract_query_from_text(text)
        assert query == "Hello world"
        assert sources == ["confluence"]

    def test_extract_json_payload_no_data_sources(self):
        """Test extracting from JSON without data_sources."""
        text = '{"query": "Simple query"}'
        query, sources = _extract_query_from_text(text)
        assert query == "Simple query"
        assert sources is None

    def test_extract_invalid_json_returns_original(self):
        """Test that invalid JSON returns original text."""
        text = '{"invalid json'
        query, sources = _extract_query_from_text(text)
        assert query == '{"invalid json'
        assert sources is None

    def test_extract_json_with_whitespace(self):
        """Test extracting from JSON with surrounding whitespace."""
        text = '  {"query": "Test"}  '
        query, sources = _extract_query_from_text(text)
        assert query == "Test"
        assert sources is None

    def test_extract_json_missing_query_returns_none_text(self):
        """Test JSON without query or text returns None query."""
        text = '{"data_sources": ["web_search"]}'
        query, sources = _extract_query_from_text(text)
        assert query == '{"data_sources": ["web_search"]}'
        assert sources is None


class TestExtractQueryAndSourcesDict:
    """Tests for _extract_query_and_sources with dict payloads."""

    def test_extract_from_simple_dict(self):
        """Test extracting from simple dict structure."""
        payload = {
            "content": {
                "messages": [{"role": "user", "content": "What is AI?"}],
                "data_sources": ["web_search"],
            }
        }
        query, sources = _extract_query_and_sources(payload)
        assert query == "What is AI?"
        assert sources == ["web_search"]

    def test_extract_from_dict_with_message_key(self):
        """Test extracting from dict with message key."""
        payload = {"message": "Direct message"}
        query, sources = _extract_query_and_sources(payload)
        assert query == "Direct message"
        assert sources is None

    def test_extract_from_dict_with_text_key(self):
        """Test extracting from dict with text key."""
        payload = {"text": "Text message"}
        query, sources = _extract_query_and_sources(payload)
        assert query == "Text message"
        assert sources is None

    def test_extract_prefers_last_user_message(self):
        """Test that last user message is preferred."""
        payload = {
            "content": {
                "messages": [
                    {"role": "user", "content": "First question"},
                    {"role": "assistant", "content": "First answer"},
                    {"role": "user", "content": "Second question"},
                ]
            }
        }
        query, sources = _extract_query_and_sources(payload)
        assert query == "Second question"
        assert sources is None

    def test_extract_data_sources_from_payload_level(self):
        """Test extracting data_sources from payload level."""
        payload = {
            "data_sources": ["confluence", "sharepoint"],
            "content": {
                "messages": [{"role": "user", "content": "Query"}],
            },
        }
        query, sources = _extract_query_and_sources(payload)
        assert query == "Query"
        assert sources == ["confluence", "sharepoint"]

    def test_extract_data_sources_from_content_level(self):
        """Test extracting data_sources from content level."""
        payload = {
            "content": {
                "messages": [{"role": "user", "content": "Query"}],
                "data_sources": ["google_drive"],
            },
        }
        query, sources = _extract_query_and_sources(payload)
        assert query == "Query"
        assert sources == ["google_drive"]


class TestExtractQueryAndSourcesObject:
    """Tests for _extract_query_and_sources with object payloads."""

    def test_extract_from_object_with_messages(self):
        """Test extracting from object with messages attribute."""
        user_msg = MagicMock()
        user_msg.role = "user"
        user_msg.content = "Object query"

        payload = MagicMock()
        payload.messages = [user_msg]
        payload.data_sources = None

        query, sources = _extract_query_and_sources(payload)
        assert query == "Object query"
        assert sources is None

    def test_extract_from_object_with_data_sources(self):
        """Test extracting from object with data_sources attribute."""
        user_msg = MagicMock()
        user_msg.role = "user"
        user_msg.content = "Query with sources"

        payload = MagicMock()
        payload.messages = [user_msg]
        payload.data_sources = ["web_search", "confluence"]

        query, sources = _extract_query_and_sources(payload)
        assert query == "Query with sources"
        assert sources == ["web_search", "confluence"]


class TestExtractQueryAndSourcesString:
    """Tests for _extract_query_and_sources with string payloads."""

    def test_extract_from_plain_string(self):
        """Test extracting from plain string (no inline JSON)."""
        query, sources = _extract_query_and_sources("Plain query string")
        assert query == "Plain query string"
        assert sources is None

    def test_extract_from_json_string(self):
        """Test extracting from JSON string."""
        payload = '{"query": "JSON query", "data_sources": ["web_search"]}'
        query, sources = _extract_query_and_sources(payload)
        assert query == "JSON query"
        assert sources == ["web_search"]


class TestExtractQueryAndSourcesInlineJson:
    """Tests for inline JSON extraction in messages."""

    def test_extract_inline_json_in_message_content(self):
        """Test extracting inline JSON from message content."""
        payload = {
            "content": {
                "messages": [
                    {
                        "role": "user",
                        "content": ('{"query": "Inline JSON", "data_sources": ["sharepoint"]}'),
                    }
                ]
            }
        }
        query, sources = _extract_query_and_sources(payload)
        assert query == "Inline JSON"
        assert sources == ["sharepoint"]

    def test_inline_sources_used_when_payload_sources_missing(self):
        """Test inline sources are used when payload has no sources."""
        payload = {
            "content": {
                "messages": [
                    {
                        "role": "user",
                        "content": ('{"query": "Test", "data_sources": ["jira"]}'),
                    }
                ]
            }
        }
        query, sources = _extract_query_and_sources(payload)
        assert query == "Test"
        assert sources == ["jira"]

    def test_payload_sources_take_precedence_over_inline(self):
        """Test that payload-level sources take precedence."""
        payload = {
            "data_sources": ["confluence"],
            "content": {
                "messages": [
                    {
                        "role": "user",
                        "content": ('{"query": "Test", "data_sources": ["jira"]}'),
                    }
                ]
            },
        }
        query, sources = _extract_query_and_sources(payload)
        assert query == "Test"
        assert sources == ["confluence"]


class TestExtractQueryAndSourcesEdgeCases:
    """Edge case tests for _extract_query_and_sources."""

    def test_extract_empty_messages_list(self):
        """Test with empty messages list."""
        payload = {"content": {"messages": []}}
        query, sources = _extract_query_and_sources(payload)
        assert query == ""
        assert sources is None

    def test_extract_no_user_messages(self):
        """Test with no user messages in list."""
        payload = {
            "content": {
                "messages": [
                    {"role": "assistant", "content": "AI response"},
                    {"role": "system", "content": "System prompt"},
                ]
            }
        }
        query, sources = _extract_query_and_sources(payload)
        assert query == "System prompt"
        assert sources is None

    def test_extract_with_langchain_messages(self):
        """Test with actual LangChain message objects in dict payload."""
        payload = {
            "content": {
                "messages": [
                    {"role": "user", "content": "LangChain query"},
                    {"role": "assistant", "content": "LangChain response"},
                ]
            }
        }

        query, sources = _extract_query_and_sources(payload)
        assert query == "LangChain query"
        assert sources is None

    def test_extract_with_explicit_data_sources_list(self):
        """Test with explicitly specified data sources list."""
        payload = {
            "data_sources": ["web_search", "confluence"],
            "content": {
                "messages": [{"role": "user", "content": "Query"}],
            },
        }
        query, sources = _extract_query_and_sources(payload)
        assert query == "Query"
        assert sources == ["web_search", "confluence"]

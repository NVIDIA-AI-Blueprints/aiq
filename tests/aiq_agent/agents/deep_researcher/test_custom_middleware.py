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

"""Tests for custom middleware."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from aiq_agent.agents.deep_researcher.custom_middleware import ToolNameSanitizationMiddleware


class TestToolNameSanitizationMiddleware:
    """Tests for ToolNameSanitizationMiddleware."""

    @pytest.fixture
    def valid_tool_names(self):
        return ["advanced_web_search_tool", "paper_search_tool", "read_file", "write_file", "grep", "glob", "think"]

    @pytest.fixture
    def middleware(self, valid_tool_names):
        return ToolNameSanitizationMiddleware(valid_tool_names=valid_tool_names)

    def test_sanitize_channel_suffix(self, middleware):
        """Strip <|channel|> and everything after it."""
        assert (
            middleware._sanitize_tool_name("advanced_web_search_tool<|channel|>commentary")
            == "advanced_web_search_tool"
        )

    def test_sanitize_channel_json_suffix(self, middleware):
        """Strip <|channel|>json suffix."""
        assert middleware._sanitize_tool_name("advanced_web_search_tool<|channel|>json") == "advanced_web_search_tool"

    def test_sanitize_dot_suffix(self, middleware):
        """Strip .commentary suffix when base name is valid."""
        assert middleware._sanitize_tool_name("advanced_web_search_tool.commentary") == "advanced_web_search_tool"

    def test_sanitize_dot_exec_suffix(self, middleware):
        """Strip .exec suffix when base name is valid."""
        assert middleware._sanitize_tool_name("advanced_web_search_tool.exec") == "advanced_web_search_tool"

    def test_sanitize_paper_search_channel(self, middleware):
        """Strip channel suffix from paper_search_tool too."""
        assert middleware._sanitize_tool_name("paper_search_tool<|channel|>commentary") == "paper_search_tool"

    def test_map_open_file_to_read_file(self, middleware):
        """Map hallucinated open_file to read_file."""
        assert middleware._sanitize_tool_name("open_file") == "read_file"

    def test_map_find_to_grep(self, middleware):
        """Map hallucinated find to grep."""
        assert middleware._sanitize_tool_name("find") == "grep"

    def test_map_find_file_to_glob(self, middleware):
        """Map hallucinated find_file to glob."""
        assert middleware._sanitize_tool_name("find_file") == "glob"

    def test_passthrough_valid_name(self, middleware):
        """Valid tool names pass through unchanged."""
        assert middleware._sanitize_tool_name("advanced_web_search_tool") == "advanced_web_search_tool"

    def test_passthrough_unknown_invalid_name(self, middleware):
        """Unknown invalid names pass through unchanged (let framework report the error)."""
        assert middleware._sanitize_tool_name("totally_fake_tool") == "totally_fake_tool"

    def test_dot_suffix_with_invalid_base_passes_through(self, middleware):
        """Dot suffix stripping only applies when base name is valid."""
        assert middleware._sanitize_tool_name("fake_tool.commentary") == "fake_tool.commentary"

    @pytest.mark.asyncio
    async def test_awrap_model_call_sanitizes_tool_calls(self, middleware):
        """Integration: middleware sanitizes tool_calls in AIMessage."""
        from langchain.agents.middleware.types import ModelResponse

        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {"name": "advanced_web_search_tool<|channel|>commentary", "args": {"question": "test"}, "id": "tc1"},
            ],
        )
        mock_response = ModelResponse(result=[ai_msg])
        mock_handler = AsyncMock(return_value=mock_response)
        mock_request = MagicMock()

        result = await middleware.awrap_model_call(mock_request, mock_handler)

        assert result.result[0].tool_calls[0]["name"] == "advanced_web_search_tool"

    @pytest.mark.asyncio
    async def test_awrap_model_call_no_tool_calls_passthrough(self, middleware):
        """Messages without tool_calls pass through unchanged."""
        from langchain.agents.middleware.types import ModelResponse

        ai_msg = AIMessage(content="Just text, no tools")
        mock_response = ModelResponse(result=[ai_msg])
        mock_handler = AsyncMock(return_value=mock_response)
        mock_request = MagicMock()

        result = await middleware.awrap_model_call(mock_request, mock_handler)

        assert result.result[0].content == "Just text, no tools"
        assert not result.result[0].tool_calls

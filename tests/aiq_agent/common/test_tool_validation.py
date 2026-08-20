# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for tool availability classification."""

from types import SimpleNamespace

from aiq_agent.common.tool_validation import validate_tool_availability


def test_explicit_unavailable_stub_is_rejected() -> None:
    """Recognize the marker used by credential-gated stub tools."""

    tool = SimpleNamespace(
        name="web_search",
        description="Web search tool (unavailable - missing TEST_API_KEY).",
    )

    is_valid, available_count, unavailable = validate_tool_availability([tool], enable_logging=False)

    assert is_valid is False
    assert available_count == 0
    assert unavailable == ["web_search (missing TEST_API_KEY)"]


def test_capability_description_can_say_access_is_unavailable() -> None:
    """Do not mistake a sandbox restriction for an unavailable tool."""

    tool = SimpleNamespace(
        name="analysis_workspace",
        description="Filesystem and network access are unavailable inside this bounded workspace.",
    )

    is_valid, available_count, unavailable = validate_tool_availability([tool], enable_logging=False)

    assert is_valid is True
    assert available_count == 1
    assert unavailable == []

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

"""Tool validation utilities for checking tool availability."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def validate_tool_availability(
    tools: list[Any],
    research_type: str = "research",
    enable_logging: bool = True,
) -> tuple[bool, int, list[str]]:
    """
    Validate that at least one tool is available.

    Args:
        tools: List of tools to validate
        research_type: Type of research (e.g., "shallow research", "deep research") for logging
        enable_logging: Whether to log tool availability information

    Returns:
        Tuple of (is_valid, available_count, unavailable_tools):
        - is_valid: True if at least one tool is available
        - available_count: Number of available tools
        - unavailable_tools: List of unavailable tool names with reasons
    """
    available_tools_count = 0
    unavailable_tools = []

    if enable_logging:
        logger.info("Checking %d tools for %s", len(tools), research_type)

    for tool in tools:
        tool_name = getattr(tool, "name", "").lower()
        tool_desc = getattr(tool, "description", "").lower() or ""

        # Check if tool is unavailable (stub)
        is_unavailable = "unavailable" in tool_desc or "missing" in tool_desc

        if is_unavailable:
            reason = "missing or invalid API key or config error"
            if enable_logging:
                logger.info("Tool %s is unavailable: %s", tool_name, reason)
            unavailable_tools.append(f"{tool_name} - {reason}")
        else:
            available_tools_count += 1
            if enable_logging:
                logger.info("Found available tool: %s", tool_name)

    if enable_logging:
        logger.info(
            "Tool availability check: %d available tools out of %d",
            available_tools_count,
            len(tools),
        )

    return available_tools_count > 0, available_tools_count, unavailable_tools


def format_tool_unavailability_error(
    research_type: str,
    unavailable_tools: list[str],
) -> str:
    """
    Format an error message for unavailable tools.

    Args:
        research_type: Type of research (e.g., "shallow research", "deep research")
        unavailable_tools: List of unavailable tool names with reasons

    Returns:
        Formatted error message string
    """
    unavailable_info = ""
    if unavailable_tools:
        unavailable_info = f"\nUnavailable tools: {', '.join(unavailable_tools)}.\n"

    error_msg = (
        f"Cannot start {research_type}: No tools are available."
        f" At least one tool must be configured and available.{unavailable_info}\n"
    )
    return error_msg

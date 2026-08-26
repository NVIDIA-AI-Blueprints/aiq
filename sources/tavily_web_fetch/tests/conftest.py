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

"""Fixtures for network-free tavily_web_fetch tests."""

import sys
import types
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_tavily(monkeypatch):
    """Install a fake langchain_tavily module and return its extractor instance."""
    module = types.ModuleType("langchain_tavily")
    instance = MagicMock()
    instance.ainvoke = AsyncMock()
    module.TavilyExtract = MagicMock(return_value=instance)
    monkeypatch.setitem(sys.modules, "langchain_tavily", module)
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")  # pragma: allowlist secret
    return instance


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    """Reset process-global registration state between tests."""
    from tavily_web_fetch import register

    monkeypatch.setattr(register, "_missing_key_warned", False)
    monkeypatch.setattr(register, "_parser_registered", False)

    # Building the tool appends to a module-global registry that nothing removes from. Swapping in
    # a copy keeps registrations from one test leaking into the rest of the session.
    try:
        from aiq_agent.common import citation_verification
    except ImportError:  # pragma: no cover - package used outside an AI-Q install
        return
    monkeypatch.setattr(citation_verification, "_PARSER_REGISTRY", list(citation_verification._PARSER_REGISTRY))

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

import contextlib
import sys
import types
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def workflow_run():
    """Run every test inside a NAT workflow run, the way a served request does.

    Citations are scoped to the run that fetched them, so a test invoking the tool outside a run
    would exercise the uncitable path by accident. Tests that need a second workflow enter
    ``workflow_run_scope`` themselves.
    """
    with workflow_run_scope("test-run"):
        yield


@contextlib.contextmanager
def workflow_run_scope(run_id):
    """Set NAT's workflow run id for the duration of the block."""
    from nat.builder.context import ContextState

    token = ContextState.get().workflow_run_id.set(run_id)
    try:
        yield run_id
    finally:
        ContextState.get().workflow_run_id.reset(token)


@pytest.fixture
def run_scope():
    """Return a context manager that runs a block inside a different workflow run."""
    return workflow_run_scope


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

    # The ledger outlives any one tool instance by design, so give each test an empty one rather
    # than letting an earlier test's result stay citable.
    monkeypatch.setattr(register, "_run_ledgers", type(register._run_ledgers)())

    # Building the tool appends to a module-global registry that nothing removes from. Swapping in
    # a copy keeps registrations from one test leaking into the rest of the session.
    try:
        from aiq_agent.common import citation_verification
    except ImportError:  # pragma: no cover - package used outside an AI-Q install
        return
    monkeypatch.setattr(citation_verification, "_PARSER_REGISTRY", list(citation_verification._PARSER_REGISTRY))

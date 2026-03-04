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

"""AI-Q Blueprint core package.

This module uses lazy imports to avoid loading heavy dependencies (langchain, etc.)
"""

__all__ = [
    "deep_research_agent",
    "ensemble_research_workflow",
]

from typing import Any

# Cache for lazy-loaded modules to avoid repeated imports
_lazy_imports: dict[str, Any] = {}


def __getattr__(name: str):
    """Lazy import agents to avoid loading langgraph/ray dependencies unnecessarily.

    This allows `from aiq_agent.knowledge import ...` to work without pulling in
    the full agent stack and its heavy dependencies (langgraph, etc.).
    """
    if name in _lazy_imports:
        return _lazy_imports[name]

    if name == "ensemble_research_workflow":
        from .agents import ensemble_research_workflow

        _lazy_imports[name] = ensemble_research_workflow
        return ensemble_research_workflow

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

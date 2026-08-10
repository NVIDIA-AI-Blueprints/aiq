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

"""Per-invocation loop-guard context for reusable deep researcher workers."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from dataclasses import field


@dataclass
class ResearcherRunGuardState:
    """Mutable loop-guard state isolated to one researcher invocation.

    One instance tracks a single ``ResearchQuery`` executed by a ``run_research_batch``
    worker: how many model turns it has taken, how many source-tool invocations it has
    issued, how often it repeated an identical request, whether either limit has been
    reached, and how long its current uninterrupted ``think`` streak is.

    The state deliberately lives on a :class:`~contextvars.ContextVar` rather than on the
    middleware instance. ``DeepResearcherAgent`` builds its middleware set once and reuses
    those instances for every run, so a counter stored on ``self`` would leak across
    concurrent researcher workers and across requests.
    """

    invocation_id: str
    model_turn_count: int = 0
    source_call_count: int = 0
    source_signature_counts: dict[str, int] = field(default_factory=dict)
    exhausted: bool = False
    exhaustion_reason: str | None = None
    consecutive_think_count: int = 0
    think_blocked: bool = False


# Set and reset per researcher invocation in tools/research.py::_run_research_query, so N
# concurrent workers each get their own budget and no state survives the invocation.
CURRENT_RESEARCHER_GUARD_STATE: ContextVar[ResearcherRunGuardState | None] = ContextVar(
    "current_researcher_guard_state",
    default=None,
)

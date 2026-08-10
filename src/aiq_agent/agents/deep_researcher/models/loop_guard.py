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

"""Validated configuration for the deep researcher loop guard."""

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

# Upper bounds, not defaults. ``DeepResearchResourceLimits`` caps every field at its own
# default (``le=DEFAULT_*``) because those limits may only ever be tightened. This config is
# the opposite case: the documented tuning path is to *raise* a breaker that fires on healthy
# runs, so each ceiling sits above its default and only bounds how far it can be raised.
#
# Matches ``resource_limits.DEFAULT_MAX_SOURCE_TOOL_CALLS`` (the job-wide ceiling on concrete
# source calls), so one worker's logical-invocation budget can never be configured above what
# the whole job is allowed to retrieve.
SOURCE_CALLS_PER_QUERY_CEILING = 100
# Past a handful of repeats the rule has stopped being a loop breaker, so the ceiling only has
# to keep a typo from disabling it outright.
IDENTICAL_SOURCE_CALLS_CEILING = 10
CONSECUTIVE_THINKS_CEILING = 10
# The turn ceiling also derives the researcher subgraph's recursion limit, so its bound is what
# keeps a worker-scoped limit from being configured above the orchestrator's own 2000. At this
# ceiling the derived limit is 250 * 2 + 10 = 510.
MODEL_TURNS_PER_QUERY_CEILING = 250


class ResearcherLoopGuardConfig(BaseModel):
    """Hard limits for one deep researcher worker invocation.

    Bounds a single ``ResearchQuery`` executed inside ``run_research_batch``. The guard is a
    deterministic circuit breaker that runs underneath the model, so it does not depend on the
    model obeying prompt guidance. It complements ``DeepResearchResourceLimits``, which bounds
    the whole job rather than one worker.

    Every limit is enforced by a single middleware, so ``enabled=False`` switches off the
    complete circuit breaker rather than any one behavior.

    Every limit is bounded on both sides. Unlike ``DeepResearchResourceLimits``, whose defaults
    are also its maxima, these ceilings sit above their defaults: raising a breaker that fires
    on healthy runs is the supported tuning path, so the bound exists to stop a config from
    raising one so far that it stops being a breaker.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = Field(
        default=True,
        description=(
            "Enable the per-researcher circuit breaker. False disables every behavior at once "
            "(source-call budget, repeated-request blocking, consecutive-think blocking, and "
            "the turn ceiling), withdraws no tool, and binds no recursion limit - the "
            "researcher subgraph then inherits the orchestrator's, which is the deliberate "
            "opt-out. Only turn this off if the guard is truncating healthy runs and raising "
            "the individual limits did not help."
        ),
    )
    max_source_calls_per_query: int = Field(
        default=25,
        ge=1,
        le=SOURCE_CALLS_PER_QUERY_CEILING,
        description=(
            "Maximum model-issued source-tool invocations for one ResearchQuery. Counts logical "
            "invocations, not concrete provider calls: one batch-capable invocation carrying N "
            "queries costs one unit. This bounds model search iterations, not retrieval volume "
            "- resource_limits.max_source_tool_calls bounds that. Applied identically to every "
            "ResearchQuery. Bounds searching only - max_model_turns_per_query bounds the "
            f"worker's total turns. May not exceed {SOURCE_CALLS_PER_QUERY_CEILING}, the "
            "job-wide concrete source-call ceiling."
        ),
    )
    max_model_turns_per_query: int = Field(
        default=60,
        ge=1,
        le=MODEL_TURNS_PER_QUERY_CEILING,
        description=(
            "Maximum model calls for one ResearchQuery, counting every turn rather than only "
            "the searching ones. On the final turn the guard withdraws all tools and native "
            "structured-output binding; the text fallback promotes or corrects JSON into "
            "ResearchNotes before the graph's recursion ceiling. Also derives "
            "that recursion limit, which is therefore a backstop rather than the operative "
            "bound. The default covers the worst path the other limits still permit: 25 source "
            "calls, a think between each, plus orientation and synthesis turns. May not exceed "
            f"{MODEL_TURNS_PER_QUERY_CEILING}."
        ),
    )
    max_identical_source_calls: int = Field(
        default=3,
        ge=1,
        le=IDENTICAL_SOURCE_CALLS_CEILING,
        description=(
            "Maximum invocations of one source tool with identical tool arguments. Argument key "
            "ORDER is canonicalized; case and whitespace are not, so 'AI research' and "
            "'ai research' are distinct requests. Matching is per logical invocation: an "
            "identical batch is caught, but two different batches sharing some queries are not "
            f"deduplicated item by item. May not exceed {IDENTICAL_SOURCE_CALLS_CEILING}."
        ),
    )
    max_consecutive_thinks: int = Field(
        default=3,
        ge=1,
        le=CONSECUTIVE_THINKS_CEILING,
        description=(
            "Maximum uninterrupted `think` calls before the guard rewrites the think result "
            "into a corrective warning and withdraws `think` from later model calls. Any other "
            f"tool call resets the streak. May not exceed {CONSECUTIVE_THINKS_CEILING}."
        ),
    )

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

"""Register Deep Research Bench evaluators for NAT."""

import os

from pydantic import Field

from nat.builder.builder import EvalBuilder
from nat.builder.evaluator import EvaluatorInfo
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.cli.register_workflow import register_evaluator
from nat.data_models.component_ref import LLMRef
from nat.data_models.evaluator import EvaluatorBaseConfig

from .evaluator import DRBFactEvaluator
from .evaluator import DRBRaceEvaluator
from .evaluator import load_criteria_data


class DRBRaceEvaluatorConfig(EvaluatorBaseConfig, name="drb_race_evaluator"):
    """Configuration for Deep Research Bench RACE evaluator."""

    llm_name: LLMRef = Field(description="LLM to use as judge")
    criteria_file: str | None = Field(default=None, description="Path to criteria JSON file")


class DRBFactEvaluatorConfig(EvaluatorBaseConfig, name="drb_fact_evaluator"):
    """Configuration for Deep Research Bench FACT evaluator."""

    llm_name: LLMRef = Field(description="LLM to use for validation")
    jina_api_key: str | None = Field(default=None, description="Jina API key for web scraping")


@register_evaluator(config_type=DRBRaceEvaluatorConfig)
async def register_drb_race_evaluator(config: DRBRaceEvaluatorConfig, builder: EvalBuilder):
    """Register DRB RACE evaluator."""
    llm = await builder.get_llm(config.llm_name, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
    criteria_data = load_criteria_data(config.criteria_file)

    evaluator = DRBRaceEvaluator(llm=llm, criteria_data=criteria_data, max_concurrency=builder.get_max_concurrency())

    yield EvaluatorInfo(config=config, evaluate_fn=evaluator.evaluate, description="DRB RACE Evaluator")


@register_evaluator(config_type=DRBFactEvaluatorConfig)
async def register_drb_fact_evaluator(config: DRBFactEvaluatorConfig, builder: EvalBuilder):
    """Register DRB FACT evaluator."""
    llm = await builder.get_llm(config.llm_name, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

    jina_key = config.jina_api_key or os.environ.get("JINA_API_KEY")
    if not jina_key:
        raise ValueError("JINA_API_KEY not provided in config or environment")

    evaluator = DRBFactEvaluator(llm=llm, jina_api_key=jina_key, max_concurrency=min(builder.get_max_concurrency(), 2))

    yield EvaluatorInfo(config=config, evaluate_fn=evaluator.evaluate, description="DRB FACT Evaluator")

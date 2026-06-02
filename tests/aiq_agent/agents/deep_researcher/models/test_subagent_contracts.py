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

"""Tests for deep researcher structured response contracts."""

import pytest
from pydantic import ValidationError

from aiq_agent.agents.deep_researcher.models import ResearchNotes
from aiq_agent.agents.deep_researcher.models import ResearchPlan
from aiq_agent.agents.deep_researcher.models import WriterOutput


def _answer_strategy() -> dict:
    return {
        "answer_type": "comparison",
        "title": "CUDA and OpenCL Trade-offs",
        "response_shape": "Markdown comparison with concise summary and citations.",
        "selection_mode": "none",
        "expected_count": None,
        "options": [],
        "required_components": [
            {
                "id": "programming_model",
                "name": "Programming model",
                "description": "Compare kernel, memory, and execution models.",
            }
        ],
        "assembly_instruction": "Compare practical trade-offs and cite every material claim.",
    }


def _task_analysis() -> dict:
    return {
        "user_intent": "Understand CUDA and OpenCL trade-offs.",
        "explicit_requirements": ["Compare CUDA and OpenCL"],
        "implicit_requirements": ["Cover ecosystem and portability"],
        "out_of_scope": ["General GPU purchasing advice"],
        "language": "English",
    }


def test_research_plan_contract_validates_expected_shape():
    plan = ResearchPlan.model_validate(
        {
            "task_analysis": _task_analysis(),
            "answer_strategy": _answer_strategy(),
            "constraints": [
                {
                    "category": "content",
                    "constraint": "Compare portability, performance, and ecosystem maturity.",
                    "rationale": "These dimensions determine practical adoption.",
                    "verification": "Each dimension appears in the final answer.",
                }
            ],
            "queries": [
                {
                    "query": "CUDA OpenCL portability performance ecosystem comparison",
                    "subqueries": ["CUDA OpenCL portability", "CUDA OpenCL benchmark comparison"],
                    "tool": "web_search_tool",
                    "target_components": ["programming_model"],
                    "rationale": "Supports the comparison component.",
                }
            ],
        }
    )

    assert plan.answer_strategy.required_components[0].id == "programming_model"
    assert plan.constraints[0].category == "content"
    assert plan.queries[0].target_components == ["programming_model"]
    assert plan.queries[0].subqueries == ["CUDA OpenCL portability", "CUDA OpenCL benchmark comparison"]


def test_research_notes_contract_validates_expected_shape():
    notes = ResearchNotes.model_validate(
        {
            "query_topic": "CUDA vs OpenCL portability",
            "target_components": ["programming_model"],
            "summary": "CUDA is NVIDIA-specific while OpenCL targets cross-vendor portability.",
            "findings": [
                {
                    "claim": "OpenCL is designed for cross-vendor heterogeneous compute.",
                    "evidence": "The source describes OpenCL as an open standard for heterogeneous platforms.",
                    "source_ids": [1],
                    "confidence": "high",
                    "caveats": ["Portability does not guarantee equal performance across vendors."],
                }
            ],
            "gaps": [
                {
                    "description": "Recent benchmark coverage is sparse.",
                    "impact": "Limits quantitative comparison.",
                    "suggested_follow_up_queries": ["CUDA OpenCL benchmark 2026"],
                }
            ],
            "sources": [
                {
                    "id": 1,
                    "title": "OpenCL Overview",
                    "source_type": "url",
                    "locator": "https://example.test/opencl",
                }
            ],
            "narrative_notes": "OpenCL offers broader portability, while CUDA typically has deeper vendor tooling.",
            "language": "English",
        }
    )

    assert notes.target_components == ["programming_model"]
    assert notes.findings[0].source_ids == [1]
    assert notes.sources[0].source_type == "url"
    assert notes.sources[0].locator == "https://example.test/opencl"


def test_writer_output_contract_validates_expected_shape():
    writer_output = WriterOutput.model_validate(
        {
            "answer_markdown": "CUDA is NVIDIA-specific, while OpenCL is cross-vendor [1].\n\n## Sources\n[1] OpenCL: https://example.test/opencl",
            "answer_type": "comparison",
            "citations_used": [1],
            "gaps": [],
            "confidence": "high",
        }
    )

    assert writer_output.answer_type == "comparison"
    assert writer_output.citations_used == [1]


def test_subagent_contracts_reject_extra_fields_and_old_plan_shape():
    with pytest.raises(ValidationError):
        ResearchPlan.model_validate(
            {
                "task_analysis": _task_analysis(),
                "answer_strategy": _answer_strategy(),
                "constraints": [],
                "queries": [],
                "unexpected": "value",
            }
        )

    with pytest.raises(ValidationError):
        ResearchPlan.model_validate(
            {
                "task_analysis": _task_analysis(),
                "report_title": "Title",
                "report_toc": [],
                "constraints": [],
                "queries": [],
            }
        )

    with pytest.raises(ValidationError):
        ResearchNotes.model_validate(
            {
                "query_topic": "CUDA vs OpenCL portability",
                "target_sections": ["Programming Model Differences"],
                "summary": "Old field should fail.",
                "findings": [],
                "gaps": [],
                "sources": [],
                "narrative_notes": "",
                "language": "English",
            }
        )

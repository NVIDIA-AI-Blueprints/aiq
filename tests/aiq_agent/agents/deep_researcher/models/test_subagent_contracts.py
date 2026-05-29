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

"""Tests for deep researcher subagent structured response contracts."""

import pytest
from pydantic import ValidationError

from aiq_agent.agents.deep_researcher.models import ResearchNotes
from aiq_agent.agents.deep_researcher.models import ResearchPlan


def test_research_plan_contract_validates_expected_shape():
    plan = ResearchPlan.model_validate(
        {
            "task_analysis": {
                "user_intent": "Understand CUDA and OpenCL trade-offs.",
                "explicit_requirements": ["Compare CUDA and OpenCL"],
                "implicit_requirements": ["Cover ecosystem and portability"],
                "out_of_scope": ["General GPU purchasing advice"],
                "language": "English",
            },
            "report_title": "CUDA and OpenCL Trade-offs",
            "report_toc": [
                {
                    "id": "1",
                    "title": "Programming Model Differences",
                    "subsections": [{"id": "1.1", "title": "Kernel and Memory Models"}],
                }
            ],
            "constraints": [
                {
                    "category": "content",
                    "constraint": "Compare portability, performance, and ecosystem maturity.",
                    "rationale": "These dimensions determine practical adoption.",
                    "verification": "Each dimension appears in the final report.",
                }
            ],
            "queries": [
                {
                    "query": "CUDA OpenCL portability performance ecosystem comparison",
                    "tool": "web_search_tool",
                    "target_sections": ["Programming Model Differences"],
                    "rationale": "Supports the comparison section.",
                }
            ],
        }
    )

    assert plan.report_toc[0].subsections[0].id == "1.1"
    assert plan.constraints[0].category == "content"


def test_research_notes_contract_validates_expected_shape():
    notes = ResearchNotes.model_validate(
        {
            "query_topic": "CUDA vs OpenCL portability",
            "target_sections": ["Programming Model Differences"],
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

    assert notes.findings[0].source_ids == [1]
    assert notes.sources[0].source_type == "url"
    assert notes.sources[0].locator == "https://example.test/opencl"


def test_subagent_contracts_reject_extra_fields():
    with pytest.raises(ValidationError):
        ResearchPlan.model_validate(
            {
                "task_analysis": {
                    "user_intent": "Research topic",
                    "explicit_requirements": [],
                    "implicit_requirements": [],
                    "out_of_scope": [],
                    "language": "English",
                },
                "report_title": "Title",
                "report_toc": [],
                "constraints": [],
                "queries": [],
                "unexpected": "value",
            }
        )

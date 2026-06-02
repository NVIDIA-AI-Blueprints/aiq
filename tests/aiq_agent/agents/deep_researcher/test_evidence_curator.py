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

"""Tests for the internal evidence curator."""

import json
from types import SimpleNamespace
from typing import Any

import pytest

from aiq_agent.agents.deep_researcher.models import EvidenceDigest
from aiq_agent.agents.deep_researcher.models import ResearchBatchResult
from aiq_agent.agents.deep_researcher.models import ResearchNotes
from aiq_agent.agents.deep_researcher.models import ResearchPlan
from aiq_agent.agents.deep_researcher.tools.evidence_curator import EVIDENCE_DIGEST_PATH
from aiq_agent.agents.deep_researcher.tools.evidence_curator import build_evidence_digest


def _plan() -> ResearchPlan:
    return ResearchPlan.model_validate(
        {
            "task_analysis": {
                "user_intent": "Compare CUDA and OpenCL trade-offs.",
                "explicit_requirements": ["Compare CUDA and OpenCL"],
                "implicit_requirements": ["Cover portability and caveats"],
                "out_of_scope": [],
                "language": "English",
            },
            "answer_strategy": {
                "answer_type": "comparison",
                "title": "CUDA and OpenCL Trade-offs",
                "response_shape": "Markdown comparison.",
                "selection_mode": "none",
                "expected_count": None,
                "options": [],
                "required_components": [
                    {
                        "id": "programming_model",
                        "name": "Programming model",
                        "description": "Compare portability and execution model evidence.",
                    }
                ],
                "assembly_instruction": "Synthesize evidence into a comparison.",
            },
            "constraints": [],
            "queries": [],
        }
    )


def _notes() -> ResearchNotes:
    return ResearchNotes.model_validate(
        {
            "query_topic": "CUDA OpenCL",
            "target_components": ["programming_model"],
            "summary": "OpenCL is portable; CUDA has ecosystem depth.",
            "findings": [
                {
                    "claim": "OpenCL is designed for cross-vendor heterogeneous compute.",
                    "evidence": "The source describes OpenCL as an open standard for heterogeneous platforms.",
                    "source_ids": [1],
                    "confidence": "high",
                    "caveats": [],
                },
                {
                    "claim": "Portability does not guarantee equal performance across vendors.",
                    "evidence": "The benchmark source reports device-specific variance.",
                    "source_ids": [2],
                    "confidence": "medium",
                    "caveats": ["This caveat should survive into synthesis."],
                },
            ],
            "gaps": [],
            "sources": [
                {
                    "id": 1,
                    "title": "OpenCL Overview",
                    "source_type": "url",
                    "locator": "https://example.test/opencl",
                },
                {
                    "id": 2,
                    "title": "Benchmark",
                    "source_type": "url",
                    "locator": "https://example.test/bench",
                },
            ],
            "narrative_notes": "Useful synthesis details.",
            "language": "English",
        }
    )


class FakeBackend:
    def __init__(self, files: dict[str, str]) -> None:
        self.files = {path: content.encode("utf-8") for path, content in files.items()}

    def download_files(self, paths: list[str]) -> list[Any]:
        responses = []
        for path in paths:
            if path not in self.files:
                responses.append(SimpleNamespace(path=path, content=None, error=f"File '{path}' not found"))
            else:
                responses.append(SimpleNamespace(path=path, content=self.files[path], error=None))
        return responses

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[Any]:
        for path, content in files:
            self.files[path] = content
        return [SimpleNamespace(path=path, error=None) for path, _content in files]


class FakeCuratorRunnable:
    async def ainvoke(self, messages: list[Any]) -> dict[str, Any]:
        prompt = messages[-1].content
        candidates_text = prompt.split("CANDIDATES JSON:\n", maxsplit=1)[1].split("\n\nReturn JSON", maxsplit=1)[0]
        candidates = json.loads(candidates_text)
        decisions = []
        for index, candidate in enumerate(candidates):
            is_caveat = bool(candidate["caveats"])
            decisions.append(
                {
                    "finding_ref": candidate["finding_ref"],
                    "inclusion": "caveat" if is_caveat else ("core" if index == 0 else "supporting"),
                    "relevance": "direct",
                    "evidence_strength": "adequate" if is_caveat else "strong",
                    "reason": "Preserve caveat." if is_caveat else "Directly supports the component.",
                }
            )
        return {"decisions": decisions, "coverage_gaps": []}


class FakeCuratorModel:
    def with_structured_output(self, _schema: Any) -> FakeCuratorRunnable:
        return FakeCuratorRunnable()


@pytest.mark.asyncio
async def test_build_evidence_digest_persists_component_attention_map():
    batch = ResearchBatchResult(
        status="succeeded",
        total=1,
        succeeded=1,
        failed=0,
        timed_out=0,
        files=["/shared/00_cuda_opencl.json"],
        results=[],
    )
    backend = FakeBackend(
        {
            "/shared/plan.json": _plan().model_dump_json(),
            "/shared/research_batch_result.json": batch.model_dump_json(),
            "/shared/00_cuda_opencl.json": _notes().model_dump_json(),
        }
    )

    digest = await build_evidence_digest(backend=backend, model=FakeCuratorModel())

    assert digest.status == "succeeded"
    assert EVIDENCE_DIGEST_PATH in backend.files
    persisted = EvidenceDigest.model_validate_json(backend.files[EVIDENCE_DIGEST_PATH].decode("utf-8"))
    decisions = persisted.component_rankings[0].decisions
    assert [decision.inclusion for decision in decisions] == ["core", "caveat"]
    assert decisions[0].finding_ref == "/shared/00_cuda_opencl.json#finding-0"
    assert decisions[1].caveats == ["This caveat should survive into synthesis."]


@pytest.mark.asyncio
async def test_build_evidence_digest_marks_missing_note_partial():
    batch = ResearchBatchResult(
        status="partial",
        total=2,
        succeeded=1,
        failed=1,
        timed_out=0,
        files=["/shared/00_cuda_opencl.json", "/shared/missing.json"],
        results=[],
    )
    backend = FakeBackend(
        {
            "/shared/plan.json": _plan().model_dump_json(),
            "/shared/research_batch_result.json": batch.model_dump_json(),
            "/shared/00_cuda_opencl.json": _notes().model_dump_json(),
        }
    )

    digest = await build_evidence_digest(backend=backend, model=FakeCuratorModel())

    assert digest.status == "partial"
    assert digest.failed_note_paths == ["/shared/missing.json"]
    assert digest.component_rankings[0].decisions

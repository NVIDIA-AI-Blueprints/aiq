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

"""Internal evidence curation for deep research writer attention maps."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import UTC
from datetime import datetime
from typing import Any
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from ..models import AnswerComponent
from ..models import EvidenceComponentDigest
from ..models import EvidenceDigest
from ..models import EvidenceFindingDecision
from ..models import ResearchBatchResult
from ..models import ResearchNotes
from ..models import ResearchPlan

logger = logging.getLogger(__name__)

PLAN_PATH = "/shared/plan.json"
BATCH_SUMMARY_PATH = "/shared/research_batch_result.json"
EVIDENCE_DIGEST_PATH = "/shared/evidence_digest.json"
DEFAULT_MAX_CANDIDATES_PER_COMPONENT = 40
DEFAULT_EVIDENCE_CHARS = 900


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _EvidenceCandidate(_StrictModel):
    """Compact existing finding passed to the curator model."""

    finding_ref: str
    note_path: str
    finding_index: int
    claim: str
    evidence: str
    source_ids: list[int]
    researcher_confidence: Literal["low", "medium", "high"]
    caveats: list[str]
    target_components: list[str]


class _CuratorDecision(_StrictModel):
    """LLM decision fields only; Python fills the immutable finding metadata."""

    finding_ref: str = Field(description="Exact finding_ref from the candidate list.")
    inclusion: Literal["core", "supporting", "caveat", "background", "exclude"]
    relevance: Literal["direct", "indirect", "low"]
    evidence_strength: Literal["strong", "adequate", "weak"]
    reason: str


class _CuratorComponentResponse(_StrictModel):
    """Structured response for one answer component."""

    decisions: list[_CuratorDecision]
    coverage_gaps: list[str] = Field(default_factory=list)


_SYSTEM_PROMPT = """\
You are an internal evidence curator for a deep research report.

You receive one answer component and a compact list of existing research
findings. Decide how the writer should prioritize each finding for that
component. Do not fetch sources, add facts, rewrite claims, or invent finding
references.

Return a decision for every candidate you review, in recommended reading order.
Use:
- inclusion=core for evidence the writer should definitely use.
- inclusion=supporting for useful detail, examples, or elaboration.
- inclusion=caveat for contradictions, risks, uncertainty, or limitations that
  should be preserved.
- inclusion=background for context that is optional.
- inclusion=exclude for duplicates or findings that do not help this component.

Use relevance and evidence_strength as categorical judgments, not numeric scores.
"""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _trim(text: str, max_chars: int) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "..."


def _response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part) for part in content)
    return str(content)


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("curator response must be a JSON object")
    return payload


def _download_text(backend: Any, path: str) -> tuple[str | None, str | None]:
    try:
        downloads = backend.download_files([path])
    except Exception as exc:  # noqa: BLE001 - caller turns this into digest status
        return None, str(exc)
    if not downloads:
        return None, f"File '{path}' not found"

    response = downloads[0]
    error = getattr(response, "error", None)
    if error:
        return None, str(error)
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return content.decode("utf-8"), None
    if isinstance(content, str):
        return content, None
    return None, f"File '{path}' had no downloadable content"


def _persist_digest(backend: Any, digest: EvidenceDigest) -> None:
    try:
        uploads = backend.upload_files([(EVIDENCE_DIGEST_PATH, digest.model_dump_json(indent=2).encode("utf-8"))])
    except Exception:  # noqa: BLE001 - digest generation should never fail research
        logger.warning("Failed to persist %s", EVIDENCE_DIGEST_PATH, exc_info=True)
        return

    errors = [getattr(upload, "error", None) for upload in uploads if getattr(upload, "error", None)]
    if errors:
        logger.warning("Failed to persist %s: %s", EVIDENCE_DIGEST_PATH, "; ".join(str(error) for error in errors))


def _failed_digest(error: str) -> EvidenceDigest:
    return EvidenceDigest(
        status="failed",
        generated_at=_utc_now(),
        answer_title="",
        answer_type="",
        source_note_paths=[],
        failed_note_paths=[],
        component_rankings=[],
        error=error,
    )


def _load_plan_and_batch(backend: Any) -> tuple[ResearchPlan | None, ResearchBatchResult | None, str | None]:
    plan_text, plan_error = _download_text(backend, PLAN_PATH)
    if plan_error is not None or plan_text is None:
        return None, None, f"Failed to read {PLAN_PATH}: {plan_error}"
    batch_text, batch_error = _download_text(backend, BATCH_SUMMARY_PATH)
    if batch_error is not None or batch_text is None:
        return None, None, f"Failed to read {BATCH_SUMMARY_PATH}: {batch_error}"
    try:
        return ResearchPlan.model_validate_json(plan_text), ResearchBatchResult.model_validate_json(batch_text), None
    except Exception as exc:  # noqa: BLE001 - caller records a failed digest
        return None, None, f"Failed to parse plan or batch summary: {exc}"


def _note_paths(batch_result: ResearchBatchResult) -> list[str]:
    paths = list(batch_result.files)
    for item in batch_result.results:
        if item.file_path:
            paths.append(item.file_path)
    return list(dict.fromkeys(paths))


def _load_notes(backend: Any, paths: Sequence[str]) -> tuple[list[tuple[str, ResearchNotes]], list[str]]:
    loaded: list[tuple[str, ResearchNotes]] = []
    failed: list[str] = []
    for path in paths:
        text, error = _download_text(backend, path)
        if error is not None or text is None:
            failed.append(path)
            continue
        try:
            loaded.append((path, ResearchNotes.model_validate_json(text)))
        except Exception:  # noqa: BLE001 - malformed notes should not block the whole digest
            logger.warning("Failed to parse research note for evidence digest: %s", path, exc_info=True)
            failed.append(path)
    return loaded, failed


def _flatten_candidates(notes: Sequence[tuple[str, ResearchNotes]], evidence_chars: int) -> list[_EvidenceCandidate]:
    candidates: list[_EvidenceCandidate] = []
    for note_path, note in notes:
        for index, finding in enumerate(note.findings):
            candidates.append(
                _EvidenceCandidate(
                    finding_ref=f"{note_path}#finding-{index}",
                    note_path=note_path,
                    finding_index=index,
                    claim=finding.claim,
                    evidence=_trim(finding.evidence, evidence_chars),
                    source_ids=finding.source_ids,
                    researcher_confidence=finding.confidence,
                    caveats=finding.caveats,
                    target_components=note.target_components,
                )
            )
    return candidates


def _candidates_for_component(
    component: AnswerComponent,
    candidates: Sequence[_EvidenceCandidate],
    max_candidates: int,
) -> list[_EvidenceCandidate]:
    component_matches = [candidate for candidate in candidates if component.id in candidate.target_components]
    if component_matches:
        remaining = [
            candidate
            for candidate in candidates
            if candidate.finding_ref not in {c.finding_ref for c in component_matches}
        ]
        ordered = [*component_matches, *remaining]
    else:
        ordered = list(candidates)
    return ordered[:max_candidates]


def _component_prompt(component: AnswerComponent, candidates: Sequence[_EvidenceCandidate]) -> str:
    candidate_payload = [candidate.model_dump(mode="json") for candidate in candidates]
    return (
        "ANSWER COMPONENT:\n"
        f"{json.dumps(component.model_dump(mode='json'), indent=2, ensure_ascii=False)}\n\n"
        "CANDIDATES JSON:\n"
        f"{json.dumps(candidate_payload, indent=2, ensure_ascii=False)}\n\n"
        "Return JSON with shape: "
        '{"decisions":[{"finding_ref":"...","inclusion":"core|supporting|caveat|background|exclude",'
        '"relevance":"direct|indirect|low","evidence_strength":"strong|adequate|weak","reason":"..."}],'
        '"coverage_gaps":["..."]}'
    )


async def _invoke_curator_model(
    model: BaseChatModel,
    component: AnswerComponent,
    candidates: Sequence[_EvidenceCandidate],
) -> _CuratorComponentResponse:
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=_component_prompt(component, candidates)),
    ]

    try:
        structured_model = model.with_structured_output(_CuratorComponentResponse)
        result = await structured_model.ainvoke(messages)
        return _CuratorComponentResponse.model_validate(result)
    except (AttributeError, NotImplementedError, ValueError):
        pass

    result = await model.ainvoke(messages)
    return _CuratorComponentResponse.model_validate(_parse_json_object(_response_text(result)))


def _fallback_decision(candidate: _EvidenceCandidate) -> EvidenceFindingDecision:
    return EvidenceFindingDecision(
        finding_ref=candidate.finding_ref,
        note_path=candidate.note_path,
        finding_index=candidate.finding_index,
        claim=candidate.claim,
        evidence=candidate.evidence,
        source_ids=candidate.source_ids,
        researcher_confidence=candidate.researcher_confidence,
        caveats=candidate.caveats,
        inclusion="exclude",
        relevance="low",
        evidence_strength="weak",
        reason="The curator did not return a decision for this reviewed finding.",
    )


def _merge_decision(candidate: _EvidenceCandidate, decision: _CuratorDecision) -> EvidenceFindingDecision:
    return EvidenceFindingDecision(
        finding_ref=candidate.finding_ref,
        note_path=candidate.note_path,
        finding_index=candidate.finding_index,
        claim=candidate.claim,
        evidence=candidate.evidence,
        source_ids=candidate.source_ids,
        researcher_confidence=candidate.researcher_confidence,
        caveats=candidate.caveats,
        inclusion=decision.inclusion,
        relevance=decision.relevance,
        evidence_strength=decision.evidence_strength,
        reason=decision.reason,
    )


async def _curate_component(
    *,
    model: BaseChatModel,
    component: AnswerComponent,
    candidates: Sequence[_EvidenceCandidate],
    max_candidates_per_component: int,
) -> EvidenceComponentDigest:
    reviewed = _candidates_for_component(component, candidates, max_candidates_per_component)
    if not reviewed:
        return EvidenceComponentDigest(
            component_id=component.id,
            component_name=component.name,
            component_description=component.description,
            candidate_count=0,
            reviewed_count=0,
            decisions=[],
            coverage_gaps=["No research findings were available for this component."],
        )

    response = await _invoke_curator_model(model, component, reviewed)
    candidate_by_ref = {candidate.finding_ref: candidate for candidate in reviewed}
    decisions: list[EvidenceFindingDecision] = []
    seen_refs: set[str] = set()
    for raw_decision in response.decisions:
        candidate = candidate_by_ref.get(raw_decision.finding_ref)
        if candidate is None or raw_decision.finding_ref in seen_refs:
            continue
        decisions.append(_merge_decision(candidate, raw_decision))
        seen_refs.add(raw_decision.finding_ref)

    for candidate in reviewed:
        if candidate.finding_ref not in seen_refs:
            decisions.append(_fallback_decision(candidate))

    return EvidenceComponentDigest(
        component_id=component.id,
        component_name=component.name,
        component_description=component.description,
        candidate_count=len(candidates),
        reviewed_count=len(reviewed),
        decisions=decisions,
        coverage_gaps=response.coverage_gaps,
    )


async def build_evidence_digest(
    *,
    backend: Any,
    model: BaseChatModel,
    max_candidates_per_component: int = DEFAULT_MAX_CANDIDATES_PER_COMPONENT,
    evidence_chars: int = DEFAULT_EVIDENCE_CHARS,
) -> EvidenceDigest:
    """Build and persist the internal evidence attention map for writer synthesis."""
    plan, batch_result, load_error = _load_plan_and_batch(backend)
    if load_error is not None or plan is None or batch_result is None:
        digest = _failed_digest(load_error or "Failed to load plan and batch summary")
        _persist_digest(backend, digest)
        return digest

    note_paths = _note_paths(batch_result)
    loaded_notes, failed_note_paths = _load_notes(backend, note_paths)
    candidates = _flatten_candidates(loaded_notes, evidence_chars)
    component_rankings: list[EvidenceComponentDigest] = []
    component_errors: list[str] = []

    for component in plan.answer_strategy.required_components:
        try:
            component_rankings.append(
                await _curate_component(
                    model=model,
                    component=component,
                    candidates=candidates,
                    max_candidates_per_component=max_candidates_per_component,
                )
            )
        except Exception as exc:  # noqa: BLE001 - keep research batch success intact
            logger.warning("Evidence curator failed for component %s", component.id, exc_info=True)
            component_errors.append(f"{component.id}: {exc}")
            component_rankings.append(
                EvidenceComponentDigest(
                    component_id=component.id,
                    component_name=component.name,
                    component_description=component.description,
                    candidate_count=len(candidates),
                    reviewed_count=0,
                    decisions=[],
                    coverage_gaps=[f"Evidence curator failed for this component: {exc}"],
                )
            )

    status: Literal["succeeded", "partial", "failed"]
    if component_errors or failed_note_paths:
        status = "partial"
    else:
        status = "succeeded"

    digest = EvidenceDigest(
        status=status,
        generated_at=_utc_now(),
        answer_title=plan.answer_strategy.title,
        answer_type=plan.answer_strategy.answer_type,
        source_note_paths=[path for path, _note in loaded_notes],
        failed_note_paths=failed_note_paths,
        component_rankings=component_rankings,
        error="; ".join([*component_errors, *(f"failed note: {path}" for path in failed_note_paths)]) or None,
    )
    _persist_digest(backend, digest)
    return digest

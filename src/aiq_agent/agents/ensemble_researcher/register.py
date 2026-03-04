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

"""NAT register function for ensemble deep research workflow.

Runs N deep_research_agent instances in parallel with different LLMs/search backends,
then merges their reports via a dedicated merger LLM call.
"""

import asyncio
import logging
import re

from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from pydantic import Field

from aiq_agent.agents.deep_researcher.models import DeepResearchAgentState
from aiq_agent.common import _create_chat_response
from nat.builder.builder import Builder
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.builder.function_info import FunctionInfo
from nat.cli.register_workflow import register_function
from nat.data_models.component_ref import FunctionRef
from nat.data_models.component_ref import LLMRef
from nat.data_models.function import FunctionBaseConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

MERGER_SYSTEM_PROMPT = """\
You are a senior research editor merging multiple independently-researched reports \
into one.

Your editorial principles:

- PRESERVE DEPTH: The merged report must be at least as analytically deep as \
the stronger input. When in doubt, keep the bolder claim with its evidence \
chain rather than hedging it.
- PRESERVE ARTIFACTS: Every table, matrix, checklist, code block, and \
structured framework from either input must survive in the output.
- ONE VOICE: The output must read as a single original work. No references to \
source reports, pipelines, or the merge process.
- COMMIT: When the user asks for a recommendation or ranking, take a position. \
Do not present alternatives as co-equal.
- DISCIPLINE: Build on the stronger report's existing sections rather than \
rewriting them — weave in new substance from the other report so the result \
reads as a coherent, continuous narrative."""

MERGER_PROMPT = """\
<user_request>
{user_request}
</user_request>

{reports}

Merge these {report_count} reports into a single, high-quality report. Work \
ONLY with information already in the reports.

STEP 1 — ASSESS:
Read both reports. If one is clearly stronger (answers the question more \
directly, deeper analysis, covers most of what the other covers), use it as \
the base and surgically add only genuinely new content from the weaker report. \
Do not rewrite or reorganize the stronger report.

If both are comparable, pick the one that better answers the user's question \
as the structural base. Fix its structure in place and integrate the other \
report's content into it.

STEP 2 — MERGE:
- Keep the deeper analytical version when both cover the same topic.
- Preserve all unique content from each report at its original detail.
- When reports contradict on the primary answer, commit to the better-supported \
one. Present the alternative as a caveat.
- Synthesize a central thesis in the executive summary. The conclusion must tie \
back to it and directly answer the user's question.
- Preserve all [N] citations. Deduplicate by URL, renumber sequentially, and \
maintain a Sources section at the end.

CONSTRAINTS:
- Use ONLY facts from the input reports.
- Preserve all tables, checklists, frameworks, code blocks, equations, and \
structured artifacts. Never convert tables to prose.
- If the user names specific entities or deliverables, every one must appear \
in the output.
- No meta-commentary. No self-referential language.
- Keep the same language as the input reports.

<analysis>
- Does one report clearly dominate? If so, which?
- What unique content from each report must survive?
- Any contradictions to resolve?
- Base choice and merge plan.
</analysis>

<final_report>
[The merged report. Start with # title.]
</final_report>"""

PROOFREAD_PROMPT = """\
<user_request>
{user_request}
</user_request>

<draft_report>
{draft}
</draft_report>

You are proofreading a research report. Make ONLY these changes:
1. If the executive summary lists topics instead of stating a thesis, sharpen \
it into 3-5 synthesizing sentences.
2. The final report should read as a single authored work. Remove any process \
artifacts from ensembling of two reports such as "Report 1", "Report 2", \
"both reports", "pipeline", or "source A/B".

Do NOT remove names, figures, tables, code blocks, deep synthesis, \
explanations, or analytical claims.
Do NOT remove atomic facts.
Do NOT change the report's language.

Output the improved report starting with # title."""


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

_FINAL_REPORT_RE = re.compile(r"<final_report>\s*\n?(.*?)\s*</final_report>", re.DOTALL)
_FINAL_REPORT_UNCLOSED_RE = re.compile(r"<final_report>\s*\n?(.*)", re.DOTALL)


def extract_report(raw: str) -> str:
    """Extract content from <final_report> tags. Falls back to full text."""
    m = _FINAL_REPORT_RE.search(raw)
    if m:
        return m.group(1).strip()
    m = _FINAL_REPORT_UNCLOSED_RE.search(raw)
    if m:
        return m.group(1).strip()
    cleaned = re.sub(r"<analysis>.*?</analysis>", "", raw, flags=re.DOTALL).strip()
    return cleaned if cleaned else raw.strip()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class EnsembleResearchConfig(FunctionBaseConfig, name="ensemble_research_workflow"):
    """Ensemble workflow: runs N deep_research_agent instances in parallel and merges reports."""

    agents: list[FunctionRef] = Field(
        ...,
        description="List of deep_research_agent instance names to run in parallel",
    )
    merger_llm: LLMRef = Field(
        ...,
        description="LLM for merging/polishing reports (e.g. openai_gpt_5_2)",
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@register_function(
    config_type=EnsembleResearchConfig,
    framework_wrappers=[LLMFrameworkEnum.LANGCHAIN],
)
async def ensemble_research_workflow(config: EnsembleResearchConfig, builder: Builder):
    """Ensemble deep research: N pipelines in parallel, merged by a dedicated LLM."""

    # Resolve all agent functions and merger LLM at build time
    agent_fns = []
    for ref in config.agents:
        fn = await builder.get_function(ref)
        agent_fns.append((str(ref), fn))
    merger_llm = await builder.get_llm(config.merger_llm, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

    logger.info(
        "EnsembleWorkflow: %d pipelines configured: %s",
        len(agent_fns),
        [name for name, _ in agent_fns],
    )

    async def _run(query: str) -> str:
        """Run all pipelines in parallel and merge their reports."""

        # 1. Run all pipelines concurrently
        async def _safe_invoke(name: str, fn, state: DeepResearchAgentState) -> str | None:
            """Run one pipeline, return report content or None on failure."""
            try:
                result = await fn.ainvoke(state)
                content = result.messages[-1].content
                if content and len(content.strip()) > 0:
                    logger.info(
                        "EnsembleWorkflow: pipeline '%s' produced %d chars",
                        name,
                        len(content),
                    )
                    return content.strip()
                logger.warning(
                    "EnsembleWorkflow: pipeline '%s' returned empty content",
                    name,
                )
                return None
            except Exception as e:
                logger.warning("EnsembleWorkflow: pipeline '%s' failed: %s", name, e)
                return None

        states = [DeepResearchAgentState(messages=[HumanMessage(content=query)]) for _ in agent_fns]
        raw_reports = await asyncio.gather(
            *[_safe_invoke(name, fn, state) for (name, fn), state in zip(agent_fns, states)]
        )
        reports = [r for r in raw_reports if r]

        # 2. Handle edge cases
        if not reports:
            logger.error("EnsembleWorkflow: all %d pipelines failed", len(agent_fns))
            return _create_chat_response("", response_id="ensemble_empty")

        if len(reports) == 1:
            # Polish mode — single surviving report
            logger.info(
                "EnsembleWorkflow: 1/%d pipelines succeeded, polish mode",
                len(agent_fns),
            )
            try:
                proofread_input = PROOFREAD_PROMPT.format(
                    user_request=query,
                    draft=reports[0],
                )
                polished = await merger_llm.ainvoke(
                    [
                        SystemMessage(content="You are a senior research editor proofreading a research report."),
                        HumanMessage(content=proofread_input),
                    ]
                )
                polished_content = str(polished.content or "").strip()
                if len(polished_content) < len(reports[0]) * 0.80:
                    logger.warning(
                        "EnsembleWorkflow: polish too short (%d vs %d chars), keeping original",
                        len(polished_content),
                        len(reports[0]),
                    )
                    return _create_chat_response(reports[0], response_id="ensemble_response")
                logger.info(
                    "EnsembleWorkflow: polish complete (%d chars)",
                    len(polished_content),
                )
                return _create_chat_response(polished_content, response_id="ensemble_response")
            except Exception as e:
                logger.warning(
                    "EnsembleWorkflow: polish failed (%s), returning original",
                    e,
                )
                return _create_chat_response(reports[0], response_id="ensemble_response")

        # 3. Merge multiple reports
        logger.info(
            "EnsembleWorkflow: %d/%d pipelines succeeded, merging",
            len(reports),
            len(agent_fns),
        )
        avg_len = sum(len(r) for r in reports) / len(reports)
        reports_xml = "\n\n".join(f"<report_{i + 1}>\n{r}\n</report_{i + 1}>" for i, r in enumerate(reports))
        merger_prompt = MERGER_PROMPT.format(
            user_request=query,
            reports=reports_xml,
            report_count=len(reports),
        )
        try:
            raw_merged = await merger_llm.ainvoke(
                [
                    SystemMessage(content=MERGER_SYSTEM_PROMPT),
                    HumanMessage(content=merger_prompt),
                ]
            )
            merged_content = extract_report(str(raw_merged.content or ""))

            # Fallback: if extract_report returned empty, use raw
            if not merged_content:
                merged_content = str(raw_merged.content or "").strip()

            # Length floor on round 1
            if len(merged_content) < avg_len * 0.7:
                longest = max(reports, key=len)
                logger.warning(
                    "EnsembleWorkflow: merge too short (%d vs avg %d), keeping longest",
                    len(merged_content),
                    int(avg_len),
                )
                return _create_chat_response(longest, response_id="ensemble_response")

            logger.info(
                "EnsembleWorkflow: round 1 done (%d chars from %d reports)",
                len(merged_content),
                len(reports),
            )

            # Round 2: proofread pass
            try:
                proofread_input = PROOFREAD_PROMPT.format(
                    user_request=query,
                    draft=merged_content,
                )
                proofread_raw = await merger_llm.ainvoke(
                    [
                        SystemMessage(content=MERGER_SYSTEM_PROMPT),
                        HumanMessage(content=proofread_input),
                    ]
                )
                proofread_content = str(proofread_raw.content or "").strip()
                # Strip any stray XML tags
                proofread_content = re.sub(r"^<[^>]+>\s*", "", proofread_content)
                proofread_content = re.sub(r"\s*<[^>]+>$", "", proofread_content)

                # Accept only if within ±20% of round 1
                if 0.75 * len(merged_content) <= len(proofread_content) <= 1.25 * len(merged_content):
                    logger.info(
                        "EnsembleWorkflow: round 2 done (%d -> %d chars)",
                        len(merged_content),
                        len(proofread_content),
                    )
                    merged_content = proofread_content
                else:
                    logger.warning(
                        "EnsembleWorkflow: round 2 length out of bounds (%d vs %d), keeping round 1",
                        len(proofread_content),
                        len(merged_content),
                    )
            except Exception as e:
                logger.warning(
                    "EnsembleWorkflow: round 2 failed (%s), keeping round 1",
                    e,
                )

            return _create_chat_response(merged_content, response_id="ensemble_response")

        except Exception as e:
            longest = max(reports, key=len)
            logger.warning("EnsembleWorkflow: merge failed (%s), keeping longest", e)
            return _create_chat_response(longest, response_id="ensemble_response")

    yield FunctionInfo.from_fn(
        _run,
        description="Ensemble deep research: N pipelines in parallel, merged by LLM.",
    )

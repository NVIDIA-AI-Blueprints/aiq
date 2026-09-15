"""Score every completed answer using an LLM and an external Markdown prompt."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import httpx

from .agent_api import APIOptions
from .agent_api import request_answer


async def judge_answer(
    client: httpx.AsyncClient,
    row: dict[str, str],
    answer: str,
    api: APIOptions,
    prompt: str,
    *,
    numeric_tolerance: float = 0.000001,
    date_order: str = "dmy",
) -> dict[str, Any]:
    payload = {
        "question": row["question"],
        "expected_answer": row["expected_answer"],
        "candidate_answer": answer,
        "answer_type": row["answer_type"],
        "notes": row.get("notes", ""),
        "numeric_tolerance": numeric_tolerance,
        "date_order": date_order,
    }
    response = await request_answer(
        client,
        json.dumps(payload, ensure_ascii=False),
        replace(api, system_prompt=prompt, follow_report_jobs=False),
    )
    error = response["error"]
    if not error:
        try:
            content = response["agent_answer"].strip()
            if content.startswith("```json") and content.endswith("```"):
                content = content[7:-3].strip()
            result = json.loads(content)
            score, correct, reason = result["score"], result["is_correct"], result["reason"]
            # Validate the response format only. All answer judgments belong to the LLM.
            if (
                type(score) not in (int, float)
                or not 0 <= score <= 1
                or type(correct) is not bool
                or correct != (score == 1)
                or not isinstance(reason, str)
                or not reason.strip()
            ):
                raise ValueError("Invalid judge verdict.")
            return {
                "score": score,
                "is_correct": correct,
                "scoring_method": "llm_judge",
                "scoring_reason": reason,
                "judge_error": "",
                "needs_review": False,
                "judge_latency_ms": response["latency_ms"],
            }
        except (ValueError, KeyError, TypeError):
            error = "Judge returned invalid scoring JSON."
    return {
        "score": 0,
        "is_correct": False,
        "scoring_method": "judge_error",
        "scoring_reason": error,
        "judge_error": error,
        "needs_review": True,
        "judge_latency_ms": response["latency_ms"],
    }

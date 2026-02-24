#!/usr/bin/env python3
"""Deep Research Bench (DRB) evaluators for NAT.

Implements the exact evaluation methodology from:
https://github.com/Ayanami0730/deep_research_bench

- DRBRaceEvaluator: RACE (Reference-based Adaptive Criteria-driven Evaluation)
- DRBFactEvaluator: FACT (Framework for Factual Abundance and Citation Trustworthiness)
"""

import json
import re
from pathlib import Path
from typing import Any

import httpx
from pydantic import Field

from nat.eval.evaluator.base_evaluator import BaseEvaluator
from nat.eval.evaluator.evaluator_model import EvalInput
from nat.eval.evaluator.evaluator_model import EvalInputItem
from nat.eval.evaluator.evaluator_model import EvalOutput
from nat.eval.evaluator.evaluator_model import EvalOutputItem

RACE_SCORE_PROMPT = """<system_role>You are a strict, meticulous, and objective research article evaluation expert. You excel at using specific assessment criteria to deeply compare two articles on the same task, providing precise scores and clear justifications.</system_role>

<user_prompt>
**Task Background**
There is a deep research task, and you need to evaluate two research articles written for this task. We will assess the articles across four dimensions: Comprehensiveness, Insight, Instruction Following, and Readability. The content is as follows:
<task>
"{task_prompt}"
</task>

**Articles to Evaluate**
<article_1>
"{article_1}"
</article_1>

<article_2>
"{article_2}"
</article_2>

**Evaluation Criteria**
Now, you need to evaluate and compare these two articles based on the following **evaluation criteria list**, providing comparative analysis and scoring each on a scale of 0-10. Each criterion includes an explanation, please understand carefully.

<criteria_list>
{criteria_list}
</criteria_list>

<Instruction>
**Your Task**
Please strictly evaluate and compare `<article_1>` and `<article_2>` based on **each criterion** in the `<criteria_list>`. You need to:
1.  **Analyze Each Criterion**: Consider how each article fulfills the requirements of each criterion.
2.  **Comparative Evaluation**: Analyze how the two articles perform on each criterion, referencing the content and criterion explanation.
3.  **Score Separately**: Based on your comparative analysis, score each article on each criterion (0-10 points).

**Scoring Rules**
For each criterion, score both articles on a scale of 0-10 (continuous values). The score should reflect the quality of performance on that criterion:
*   0-2 points: Very poor performance. Almost completely fails to meet the criterion requirements.
*   2-4 points: Poor performance. Minimally meets the criterion requirements with significant deficiencies.
*   4-6 points: Average performance. Basically meets the criterion requirements, neither good nor bad.
*   6-8 points: Good performance. Largely meets the criterion requirements with notable strengths.
*   8-10 points: Excellent/outstanding performance. Fully meets or exceeds the criterion requirements.

**Output Format Requirements**
Please **strictly** follow the `<output_format>` below for each criterion evaluation. **Do not include any other unrelated content, introduction, or summary**. Start with "Standard 1" and proceed sequentially through all criteria:
</Instruction>

<output_format>
{{
    "comprehensiveness": [
        {{
            "criterion": [Text content of the first comprehensiveness evaluation criterion],
            "analysis": [Comparative analysis],
            "article_1_score": [Continuous score 0-10],
            "article_2_score": [Continuous score 0-10]
}},
{{
            "criterion": [Text content of the second comprehensiveness evaluation criterion],
            "analysis": [Comparative analysis],
            "article_1_score": [Continuous score 0-10],
            "article_2_score": [Continuous score 0-10]
        }},
        ...
    ],
    "insight": [
        {{
            "criterion": [Text content of the first insight evaluation criterion],
            "analysis": [Comparative analysis],
            "article_1_score": [Continuous score 0-10],
            "article_2_score": [Continuous score 0-10]
        }},
        ...
    ],
    ...
}}
</output_format>

Now, please evaluate the two articles based on the research task and criteria, providing detailed comparative analysis and scores according to the requirements above. Ensure your output follows the specified `<output_format>` and that the JSON format is parsable, with all characters that might cause JSON parsing errors properly escaped.
</user_prompt>
"""  # noqa: E501

DEFAULT_CRITERIA = {
    "comprehensiveness": [
        {
            "criterion": "Information Coverage Breadth",
            "explanation": "Covers all key areas related to the topic",
            "weight": 0.25,
        },
        {
            "criterion": "Information Depth and Detail",
            "explanation": "Provides sufficiently detailed information",
            "weight": 0.25,
        },
        {
            "criterion": "Data and Factual Support",
            "explanation": "Provides data, facts, cases to support arguments",
            "weight": 0.25,
        },
        {
            "criterion": "Multiple Perspectives and Balance",
            "explanation": "Considers issues from multiple angles",
            "weight": 0.25,
        },
    ],
    "insight": [
        {
            "criterion": "Analysis Depth and Originality",
            "explanation": "Provides deep analysis and original insights",
            "weight": 0.25,
        },
        {"criterion": "Logical Reasoning", "explanation": "Demonstrates clear logical reasoning", "weight": 0.25},
        {
            "criterion": "Problem Insight and Solutions",
            "explanation": "Identifies key issues and provides solutions",
            "weight": 0.25,
        },
        {
            "criterion": "Forward-Looking Thinking",
            "explanation": "Anticipates trends and provides inspiring perspectives",
            "weight": 0.25,
        },
    ],
    "instruction_following": [
        {
            "criterion": "Response to Task Objectives",
            "explanation": "Directly responds to core objectives",
            "weight": 0.34,
        },
        {"criterion": "Adherence to Scope", "explanation": "Adheres to scope limitations", "weight": 0.33},
        {"criterion": "Complete Coverage", "explanation": "Covers all aspects raised in the task", "weight": 0.33},
    ],
    "readability": [
        {
            "criterion": "Clear Structure and Logic",
            "explanation": "Has clear structure and logical organization",
            "weight": 0.25,
        },
        {"criterion": "Language Expression", "explanation": "Language is clear, accurate, and fluent", "weight": 0.25},
        {"criterion": "Technical Terms", "explanation": "Appropriately uses technical terminology", "weight": 0.25},
        {
            "criterion": "Information Presentation",
            "explanation": "Effectively uses formatting and visual elements",
            "weight": 0.25,
        },
    ],
}

DEFAULT_DIMENSION_WEIGHTS = {
    "comprehensiveness": 0.30,
    "insight": 0.35,
    "instruction_following": 0.20,
    "readability": 0.15,
}


def extract_json_from_text(text: str) -> dict | None:
    """Extract JSON from LLM response using multiple methods."""
    if not isinstance(text, str):
        return None

    text = text.strip()

    if text.startswith("{") and text.endswith("}"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end > start:
            try:
                return json.loads(text[start:end].strip())
            except json.JSONDecodeError:
                pass

    match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    if start != -1:
        level = 0
        for i, char in enumerate(text[start:]):
            if char == "{":
                level += 1
            elif char == "}":
                level -= 1
                if level == 0:
                    try:
                        return json.loads(text[start : start + i + 1])
                    except json.JSONDecodeError:
                        break

    return None


def format_criteria_list(criteria_data: dict) -> str:
    """Format criteria data as JSON string for prompt."""
    criterions = criteria_data.get("criterions", {})
    if not criterions:
        criterions = DEFAULT_CRITERIA

    criteria_for_prompt = {}
    for dim, crit_list in criterions.items():
        criteria_for_prompt[dim] = [
            {"criterion": c["criterion"], "explanation": c.get("explanation", "")} for c in crit_list
        ]

    return json.dumps(criteria_for_prompt, ensure_ascii=False, indent=2)


def calculate_weighted_scores(llm_output: dict, criteria_data: dict) -> dict:
    """Calculate weighted scores from LLM output."""
    criterions = criteria_data.get("criterions", DEFAULT_CRITERIA)
    dimension_weights = criteria_data.get("dimension_weight", DEFAULT_DIMENSION_WEIGHTS)

    criterion_weights = {}
    for dim, crit_list in criterions.items():
        criterion_weights[dim] = {c["criterion"]: c.get("weight", 0.25) for c in crit_list}

    results = {"target": {"dims": {}, "total": 0.0}, "reference": {"dims": {}, "total": 0.0}}

    for dim, scores_list in llm_output.items():
        if not isinstance(scores_list, list) or dim not in dimension_weights:
            continue

        dim_criteria = criterion_weights.get(dim, {})
        if not dim_criteria:
            continue

        target_weighted_sum = 0.0
        ref_weighted_sum = 0.0
        total_weight = 0.0

        for score_item in scores_list:
            if not isinstance(score_item, dict):
                continue

            criterion_text = score_item.get("criterion", "").strip() if score_item.get("criterion") else ""
            art1_score = score_item.get("article_1_score")
            art2_score = score_item.get("article_2_score")

            try:
                art1_score = float(art1_score) if art1_score is not None else None
                art2_score = float(art2_score) if art2_score is not None else None
            except (ValueError, TypeError):
                continue

            if art1_score is None:
                continue

            weight = dim_criteria.get(criterion_text)
            if weight is None:
                for key, val in dim_criteria.items():
                    if key.lower() in criterion_text.lower() or criterion_text.lower() in key.lower():
                        weight = val
                        break
            if weight is None:
                weight = sum(dim_criteria.values()) / len(dim_criteria) if dim_criteria else 0.25

            target_weighted_sum += art1_score * weight
            total_weight += weight
            if art2_score is not None:
                ref_weighted_sum += art2_score * weight

        if total_weight > 0:
            target_avg = target_weighted_sum / total_weight
            ref_avg = ref_weighted_sum / total_weight
        else:
            target_avg = ref_avg = 0.0

        results["target"]["dims"][dim] = target_avg
        results["reference"]["dims"][dim] = ref_avg

        dim_weight = dimension_weights.get(dim, 0.25)
        results["target"]["total"] += target_avg * dim_weight
        results["reference"]["total"] += ref_avg * dim_weight

    return results


class DRBRaceEvalOutput(EvalOutput):
    """Extended output model with dimension averages."""

    dimension_averages: dict[str, float] = Field(default_factory=dict)
    total_evaluated: int = 0


class DRBRaceEvaluator(BaseEvaluator):
    """RACE evaluator using exact DRB methodology."""

    def __init__(self, llm: Any, criteria_data: dict, max_concurrency: int = 4, max_retries: int = 3):
        super().__init__(max_concurrency=max_concurrency, tqdm_desc="RACE Evaluation")
        self.llm = llm
        self.criteria_data = criteria_data
        self.max_retries = max_retries

    def _get_criteria_for_task(self, task_id: str) -> dict:
        return self.criteria_data.get(
            str(task_id), {"criterions": DEFAULT_CRITERIA, "dimension_weight": DEFAULT_DIMENSION_WEIGHTS}
        )

    async def evaluate(self, eval_input: EvalInput) -> DRBRaceEvalOutput:
        """Override to compute dimension averages."""
        import asyncio

        from tqdm import tqdm

        from nat.eval.utils.tqdm_position_registry import TqdmPositionRegistry

        pbar = None
        try:
            tqdm_position = TqdmPositionRegistry.claim()
            pbar = tqdm(total=len(eval_input.eval_input_items), desc=self.tqdm_desc, position=tqdm_position)

            async def wrapped(item):
                async with self.semaphore:
                    try:
                        output_item = await self.evaluate_item(item)
                        pbar.update(1)
                        return output_item
                    except Exception as e:
                        pbar.update(1)
                        return EvalOutputItem(id=item.id, score=0.0, reasoning={"error": f"Evaluator error: {str(e)}"})

            output_items = await asyncio.gather(*[wrapped(item) for item in eval_input.eval_input_items])
        finally:
            pbar.close()
            TqdmPositionRegistry.release(tqdm_position)

        numeric_scores = [item.score for item in output_items if isinstance(item.score, int | float)]
        avg_score = round(sum(numeric_scores) / len(numeric_scores), 2) if numeric_scores else None

        totals = {
            "overall_score": 0,
            "comprehensiveness": 0,
            "insight": 0,
            "instruction_following": 0,
            "readability": 0,
        }
        count = 0

        for item in output_items:
            reasoning = item.reasoning if isinstance(item.reasoning, dict) else {}
            if "error" not in reasoning:
                totals["overall_score"] += reasoning.get("overall_score", 0)
                totals["comprehensiveness"] += reasoning.get("comprehensiveness", 0)
                totals["insight"] += reasoning.get("insight", 0)
                totals["instruction_following"] += reasoning.get("instruction_following", 0)
                totals["readability"] += reasoning.get("readability", 0)
                count += 1

        dimension_averages = {dim: round((totals[dim] / count) * 100, 2) if count > 0 else 0.0 for dim in totals}

        return DRBRaceEvalOutput(
            average_score=avg_score,
            dimension_averages=dimension_averages,
            total_evaluated=count,
            eval_output_items=output_items,
        )

    async def _call_llm(self, prompt: str) -> str:
        response = await self.llm.ainvoke(prompt)
        return response.content if hasattr(response, "content") else str(response)

    async def evaluate_item(self, item: EvalInputItem) -> EvalOutputItem:
        task_id = str(item.id)
        generated = item.output_obj or ""
        reference = item.expected_output_obj or ""
        question = item.input_obj or ""

        if not generated:
            return EvalOutputItem(id=task_id, score=0.0, reasoning={"error": "No generated output"})

        if not reference:
            return EvalOutputItem(id=task_id, score=None, reasoning={"error": "No reference article"})

        criteria_data = self._get_criteria_for_task(task_id)
        criteria_list_str = format_criteria_list(criteria_data)

        prompt = RACE_SCORE_PROMPT.format(
            task_prompt=question[:10000],
            article_1=generated[:50000],
            article_2=reference[:50000],
            criteria_list=criteria_list_str,
        )

        llm_output = None
        last_error = None

        for retry in range(self.max_retries):
            try:
                response = await self._call_llm(prompt)
                llm_output = extract_json_from_text(response)

                if llm_output is None:
                    raise ValueError("Failed to extract JSON from response")

                expected_dims = ["comprehensiveness", "insight", "instruction_following", "readability"]
                if not all(dim in llm_output for dim in expected_dims):
                    missing = [d for d in expected_dims if d not in llm_output]
                    raise ValueError(f"Missing dimensions: {missing}")

                break

            except Exception as e:
                last_error = str(e)
                if retry < self.max_retries - 1:
                    import asyncio

                    await asyncio.sleep(1.5**retry)

        if llm_output is None:
            return EvalOutputItem(
                id=task_id, score=0.0, reasoning={"error": f"Failed after {self.max_retries} retries: {last_error}"}
            )

        try:
            scores = calculate_weighted_scores(llm_output, criteria_data)

            target_total = scores["target"]["total"]
            reference_total = scores["reference"]["total"]

            overall_score = 0.0
            if target_total + reference_total > 0:
                overall_score = target_total / (target_total + reference_total)

            normalized_dims = {}
            for dim in ["comprehensiveness", "insight", "instruction_following", "readability"]:
                target_dim = scores["target"]["dims"].get(dim, 0)
                ref_dim = scores["reference"]["dims"].get(dim, 0)
                if target_dim + ref_dim > 0:
                    normalized_dims[dim] = target_dim / (target_dim + ref_dim)
                else:
                    normalized_dims[dim] = 0.0

            return EvalOutputItem(
                id=task_id,
                score=overall_score * 100,
                reasoning={
                    "overall_score": overall_score,
                    "comprehensiveness": normalized_dims.get("comprehensiveness", 0),
                    "insight": normalized_dims.get("insight", 0),
                    "instruction_following": normalized_dims.get("instruction_following", 0),
                    "readability": normalized_dims.get("readability", 0),
                    "target_total": target_total,
                    "reference_total": reference_total,
                    "raw_scores": llm_output,
                },
            )

        except Exception as e:
            return EvalOutputItem(id=task_id, score=0.0, reasoning={"error": f"Score calculation error: {str(e)}"})


class DRBFactEvaluator(BaseEvaluator):
    """FACT evaluator for citation verification."""

    def __init__(self, llm: Any, jina_api_key: str, max_concurrency: int = 2):
        super().__init__(max_concurrency=max_concurrency, tqdm_desc="FACT Evaluation")
        self.llm = llm
        self.jina_api_key = jina_api_key

    def _extract_citations(self, text: str) -> list[dict]:
        url_pattern = r"https?://[^\s\)\]\"\'<>]+"
        urls = re.findall(url_pattern, text)

        citations = []
        seen_urls = set()

        for url in urls:
            url = url.rstrip(".,;:")
            if url not in seen_urls:
                seen_urls.add(url)
                context_match = re.search(rf"([^.!?]*{re.escape(url[:50])}[^.!?]*[.!?]?)", text, re.IGNORECASE)
                citations.append({"url": url, "context": (context_match.group(1) if context_match else "")[:500]})

        return citations

    async def _scrape_url(self, url: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"https://r.jina.ai/{url}", headers={"Authorization": f"Bearer {self.jina_api_key}"}
                )
                if response.status_code == 200:
                    return response.text[:10000]
        except Exception:
            pass
        return ""

    async def _validate_citation(self, citation: dict, scraped_content: str) -> dict:
        if not scraped_content:
            return {"valid": False, "reason": "Could not scrape URL"}

        prompt = f"""Verify if the following claim is supported by the source content.

Claim/Context: {citation["context"]}
Source URL: {citation["url"]}
Source Content (excerpt): {scraped_content[:5000]}

Respond with JSON: {{"supported": true/false, "confidence": 0.0-1.0, "reason": "brief explanation"}}"""

        try:
            response = await self.llm.ainvoke(prompt)
            text = response.content if hasattr(response, "content") else str(response)

            result = extract_json_from_text(text)
            if result:
                return {
                    "valid": result.get("supported", False),
                    "confidence": result.get("confidence", 0.0),
                    "reason": result.get("reason", ""),
                }
        except Exception as e:
            return {"valid": False, "reason": str(e)}

        return {"valid": False, "reason": "Could not parse validation response"}

    async def evaluate_item(self, item: EvalInputItem) -> EvalOutputItem:
        task_id = str(item.id)
        generated = item.output_obj or ""

        if not generated:
            return EvalOutputItem(id=task_id, score=0.0, reasoning={"error": "No generated output"})

        citations = self._extract_citations(generated)

        if not citations:
            return EvalOutputItem(
                id=task_id,
                score=0.0,
                reasoning={
                    "total_citations": 0,
                    "valid_citations": 0,
                    "citation_accuracy": 0.0,
                    "message": "No citations found",
                },
            )

        valid_count = 0
        citation_results = []

        for citation in citations[:20]:
            scraped = await self._scrape_url(citation["url"])
            validation = await self._validate_citation(citation, scraped)

            citation_results.append(
                {
                    "url": citation["url"],
                    "valid": validation.get("valid", False),
                    "confidence": validation.get("confidence", 0.0),
                    "reason": validation.get("reason", ""),
                }
            )

            if validation.get("valid"):
                valid_count += 1

        citation_accuracy = valid_count / len(citations) if citations else 0.0

        return EvalOutputItem(
            id=task_id,
            score=citation_accuracy * 100,
            reasoning={
                "total_citations": len(citations),
                "valid_citations": valid_count,
                "citation_accuracy": citation_accuracy,
                "citation_details": citation_results[:10],
            },
        )


def load_criteria_data(criteria_file: str | None) -> dict:
    """Load criteria data from JSON/JSONL file."""
    if not criteria_file or not Path(criteria_file).exists():
        return {}

    criteria_map = {}

    with open(criteria_file, encoding="utf-8") as f:
        content = f.read().strip()

        if content.startswith("["):
            data = json.loads(content)
        else:
            data = [json.loads(line) for line in content.split("\n") if line.strip()]

    for item in data:
        task_id = str(item.get("id", item.get("task_id", "")))
        if task_id:
            criteria_map[task_id] = item

    return criteria_map

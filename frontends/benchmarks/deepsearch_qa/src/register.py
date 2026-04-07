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

#!/usr/bin/env python3
"""DeepSearchQA Evaluator for NAT.

Implements the official DeepSearchQA evaluation methodology from DeepMind:
https://www.kaggle.com/datasets/deepmind/deepsearchqa/data

The evaluator uses LLM-as-judge to assess:
- Answer correctness for Single Answer and Set Answer types
- Correctness details per answer component
- Excessive answers detection
- Precision, Recall, and F1 scores
"""

import csv
import json
import logging
import math
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

from pydantic import Field

from nat.builder.builder import EvalBuilder
from nat.builder.evaluator import EvaluatorInfo
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.cli.register_workflow import register_evaluator
from nat.data_models.component_ref import LLMRef
from nat.data_models.evaluator import EvalInput
from nat.data_models.evaluator import EvalInputItem
from nat.data_models.evaluator import EvalOutput
from nat.data_models.evaluator import EvalOutputItem
from nat.data_models.evaluator import EvaluatorBaseConfig
from nat.plugins.eval.evaluator.base_evaluator import BaseEvaluator

logger = logging.getLogger(__name__)

DEEPSEARCH_QA_PROMPT = """\
Your task is to evaluate whether a given "AI Response" for a specific "User Prompt" \
arrived at the correct answer.

**Answer Correctness Task**

*   **Purpose:** Assess whether the AI response provides the correct answer(s) based on \
the provided "Correct Answer" and "Prompt Type".
*   **Process:**
    *   Identify the "Prompt Type": "<prompt_type>".
    *   Refer to the "Correct Answer": "<answer>".
    *   Based on the "Prompt Type", determine if the "AI Response" contains the expected answer(s).
        *   **'Single Answer'**: Check if the response provides the answer that addresses \
the user's question. It does not have to match the exact wording of the provided answer.
        *   **'Set Answer'**: Check if the response includes *each* item from the provided \
ground truth answers. The order might not matter unless specified otherwise. The response \
might include more answers than the list. Determine the correctness *only* based on the \
list first and then check if the response includes answers not in the list.
    *   **Explanation:** Provide a brief explanation justifying your assessment of answer \
correctness, referencing specific parts of the AI response and the correct answer.
    *   **Correctness Details:** Provide a dictionary, one key for each expected answer \
part, and value is a boolean indicating whether each expected answer part was found.
        *   For 'Set Answer', this will be a list of attributes, one for each item/part \
in the "Correct Answer". Each key will be a string indicating the expected answer part, \
and the value will be a boolean indicating whether that part was found in the response.
    *   **Excessive Answers:** Provide a list of strings, each indicating an excessive \
answer part. If the response provides answers that are **not** in the "Correct Answer" \
list, add these answers as excessive answers. Return an empty list when there's no \
excessive answers in the response.


**Output Format:**

Your evaluation *must* be structured as a nested JSON dictionary with the following \
top-level keys: `"Answer Correctness"`. Please return NULL if any of "Prompt", \
"AI Response" or "Correct Answer" is empty.
The value for `"Answer Correctness"` should be a dictionary containing `"Explanation"` \
(a string), `"Correctness Details"` (a dictionary where each key is the expected correct \
answer, and the value is a boolean indicating whether the response contains the correct \
answer), and `"Excessive Answers"` (a list of strings indicating the excessive answers).

Make sure you return a valid JSON string. Pay special attention to quotes, commas and \
special characters in the JSON string. Make sure to escape all special characters and \
quotes in the JSON string.

"""

GRADER_RATING_OUTPUT_EXAMPLE = r"""**Example (Partial):**

"```json
{{
  "Answer Correctness": {{
    "Explanation": "The response correctly identified Belgium and France but also includes an excessive answer, Italy.",
    "Correctness Details": {{
      "Belgium": true,
      "France": true,
    }},
    "Excessive Answers": [ "Italy" ]
  }}
}}
```"

**Now, proceed with the evaluation using the provided User Prompt, AI Response, and Correct Answer.**

User Prompt (Wrapped in <prompt> and </prompt>):
<prompt>
{prompt}
</prompt>
--------------------
**  Correct Answer (Wrapped in <answer> and </answer>):
Prompt Type: {prompt_type}
<answer>
{answer}
</answer>
--------------------
AI assistant response (Wrapped in <response> and </response>):
<response>
{response}
</response>

--------------------
Rating:"""


@dataclass
class ItemRating:
    """Individual item rating result."""

    original_index: int | None = None
    example_id: str = ""
    query: str = ""
    response: str = ""
    category_type: str | None = None
    expected_correct_answer: str | None = None
    answer_correctness_explanation: str | None = None
    expected_correct_answer_list: list[str] | None = None
    response_wrong_answers_list: list[str] | None = None
    grader_ratings_list: list[bool] | None = None
    empty_model_response: bool = False
    empty_auto_rater_response: bool = False
    invalid_auto_rater_response: bool = False
    rating_response: str = ""
    rating_prompt: str = ""
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LeaderboardEntry:
    """Leaderboard-compatible output format matching DeepSearchQA benchmark."""

    model: str = ""
    fully_correct: str = ""
    fully_correct_pct: float = 0.0
    fully_correct_ci: float = 0.0
    fully_incorrect: str = ""
    fully_incorrect_pct: float = 0.0
    fully_incorrect_ci: float = 0.0
    correct_with_excessive: str = ""
    correct_with_excessive_pct: float = 0.0
    correct_with_excessive_ci: float = 0.0
    f1: str = ""
    f1_pct: float = 0.0
    precision: str = ""
    precision_pct: float = 0.0
    recall: str = ""
    recall_pct: float = 0.0
    num_evaluated: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_table_row(self) -> str:
        """Format as a table row for display."""
        return (
            f"| {self.model:<30} | {self.fully_correct:>12} | "
            f"{self.fully_incorrect:>12} | {self.correct_with_excessive:>12} | {self.f1:>8} |"
        )

    @staticmethod
    def table_header() -> str:
        return (
            "| Model                          | Fully Correct | Fully Incorrect | "
            "Correct w/ Excessive | F1       |\n"
            "|--------------------------------|---------------|-----------------|---------------------|----------|"
        )


@dataclass
class ProjectRating:
    """Aggregated project-level rating."""

    num_total_ratings: int = 0
    num_empty_model_response: int = 0
    num_invalid_auto_rater_response: int = 0
    num_empty_auto_rater_response: int = 0
    num_valid_ratings: int = 0
    num_answer_correctness_evaluated: int = 0
    pct_w_ci_all_answers_correct: str = ""
    pct_w_ci_fully_incorrect_items: str = ""
    pct_w_ci_correct_with_excessive_answers: str = ""
    pct_empty_model_response: float = 0.0
    pct_invalid_auto_rater_response: float = 0.0
    pct_empty_auto_rater_response: float = 0.0
    precision: str = ""
    recall: str = ""
    f1_score: str = ""
    category_breakdown: dict[str, dict[str, Any]] = field(default_factory=dict)
    fully_correct_count: int = 0
    fully_incorrect_count: int = 0
    correct_with_excessive_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_leaderboard_entry(self, model_name: str = "NeAR Agent") -> LeaderboardEntry:
        """Convert to leaderboard-compatible format."""
        entry = LeaderboardEntry(model=model_name, num_evaluated=self.num_answer_correctness_evaluated)

        entry.fully_correct = self.pct_w_ci_all_answers_correct
        entry.fully_incorrect = self.pct_w_ci_fully_incorrect_items
        entry.correct_with_excessive = self.pct_w_ci_correct_with_excessive_answers
        entry.f1 = self.f1_score
        entry.precision = self.precision
        entry.recall = self.recall

        if self.num_answer_correctness_evaluated > 0:
            n = self.num_answer_correctness_evaluated
            entry.fully_correct_pct = round(self.fully_correct_count / n * 100, 1)
            entry.fully_incorrect_pct = round(self.fully_incorrect_count / n * 100, 1)
            entry.correct_with_excessive_pct = round(self.correct_with_excessive_count / n * 100, 1)

            try:
                entry.f1_pct = float(self.f1_score.rstrip("%"))
                entry.precision_pct = float(self.precision.rstrip("%"))
                entry.recall_pct = float(self.recall.rstrip("%"))
            except (ValueError, AttributeError):
                pass

        return entry


def _parse_json_response(ori_json_response: str) -> Any:
    """Parse JSON from LLM response, handling markdown code blocks."""
    try:
        json_str = ori_json_response.strip()
        start_marker = "```json"
        start_idx = json_str.find(start_marker)

        if start_idx != -1:
            json_str = json_str[start_idx + len(start_marker) :].strip()
            end_marker = "```"
            end_idx = json_str.rfind(end_marker)
            if end_idx != -1:
                json_str = json_str[:end_idx].strip()

        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.debug("json.JSONDecodeError: %s for response: %s", e, ori_json_response[:200])
        return None


def _get_answer_correctness_details(json_response: Any) -> dict[str, bool] | None:
    """Extract correctness details from parsed JSON."""
    try:
        details = json_response["Answer Correctness"]["Correctness Details"]
        if isinstance(details, dict):
            all_keys_are_strings = all(isinstance(key, str) for key in details.keys())
            all_values_are_booleans = all(isinstance(value, bool) for value in details.values())
            if all_keys_are_strings and all_values_are_booleans:
                return details
        logger.warning("Invalid format for Answer Correctness Details: %s", details)
        return None
    except (KeyError, TypeError) as e:
        logger.debug("Error extracting Correctness Details: %s", e)
        return None


def _get_excessive_answers(json_response: Any) -> list[str] | None:
    """Extract excessive answers from parsed JSON."""
    try:
        excessive_answers = json_response["Answer Correctness"]["Excessive Answers"]
        if isinstance(excessive_answers, list):
            all_items_are_strings = all(isinstance(item, str) for item in excessive_answers)
            if all_items_are_strings:
                return excessive_answers
        logger.warning("Invalid format for Excessive Answers: %s", excessive_answers)
        return None
    except KeyError:
        return []
    except TypeError:
        return None


def _calculate_ci_str(count: int, total: int, z: float = 1.96) -> str:
    """Calculate confidence interval string."""
    if total == 0:
        return f"N/A ({count}/{total})"
    count = max(count, 0)
    count = min(count, total)

    p = count / total
    p_percent = p * 100.0

    try:
        variance = p * (1.0 - p)
        margin_of_error = z * math.sqrt(variance / total)
        moe_percent = margin_of_error * 100.0
        result_str = f"{round(p_percent, 2):.2f} ± {round(moe_percent, 2):.2f} ({count}/{total})"
        if total <= 5:
            result_str += " (CI not robust for n<=5)"
        return result_str
    except (ValueError, ZeroDivisionError):
        return "N/A"


def _calculate_metric(true_positives: int, false_positives: int, false_negatives: int) -> dict[str, float]:
    """Calculate precision, recall, and F1."""
    precision_val = 0.0
    if (true_positives + false_positives) > 0:
        precision_val = true_positives / (true_positives + false_positives)

    recall_val = 0.0
    if (true_positives + false_negatives) > 0:
        recall_val = true_positives / (true_positives + false_negatives)

    f1_score_val = 0.0
    if (precision_val + recall_val) > 0:
        f1_score_val = 2 * (precision_val * recall_val) / (precision_val + recall_val)

    return {
        "precision": precision_val,
        "recall": recall_val,
        "f1_score": f1_score_val,
    }


def aggregate_ratings(item_ratings: list[ItemRating]) -> ProjectRating:
    """Aggregate item-level ratings into project-level statistics."""
    if not item_ratings:
        return ProjectRating()

    from collections import defaultdict

    import numpy as np

    total_items = len(item_ratings)
    project_rating = ProjectRating(num_total_ratings=total_items)

    num_answer_correctness_evaluated = 0
    num_answer_correctness_all_correct = 0
    num_fully_incorrect_items = 0
    num_items_correct_with_excessive_answers = 0

    category_stats = defaultdict(lambda: {"evaluated": 0, "all_correct": 0})
    per_item_metrics = {"precision": [], "recall": [], "f1_score": []}

    for item_rating in item_ratings:
        if item_rating.invalid_auto_rater_response:
            project_rating.num_invalid_auto_rater_response += 1
            continue
        if item_rating.empty_auto_rater_response:
            project_rating.num_empty_auto_rater_response += 1
            continue
        if item_rating.empty_model_response:
            project_rating.num_empty_model_response += 1
            continue

        project_rating.num_valid_ratings += 1
        current_category = item_rating.category_type if item_rating.category_type else "Unknown"

        if item_rating.grader_ratings_list is not None:
            num_answer_correctness_evaluated += 1
            category_stats[current_category]["evaluated"] += 1
            ratings = item_rating.grader_ratings_list
            num_correct = sum(1 for r in ratings if r)

            true_positives = num_correct
            false_negatives = len(ratings) - num_correct
            has_expected_answers = bool(ratings)

            all_expected_answers_correct = False
            if has_expected_answers:
                all_expected_answers_correct = num_correct == len(ratings)
                if num_correct == 0:
                    num_fully_incorrect_items += 1

            excessive_answers = item_rating.response_wrong_answers_list
            has_excessive_answers = bool(excessive_answers)
            false_positives = 0
            if has_excessive_answers:
                false_positives = len(excessive_answers)
                if all_expected_answers_correct or not has_expected_answers:
                    num_items_correct_with_excessive_answers += 1

            is_all_correct = (all_expected_answers_correct or not has_expected_answers) and not has_excessive_answers

            if is_all_correct:
                num_answer_correctness_all_correct += 1
                category_stats[current_category]["all_correct"] += 1

            per_item_metric = _calculate_metric(true_positives, false_positives, false_negatives)
            for key, value in per_item_metric.items():
                per_item_metrics[key].append(value)

    if total_items > 0:
        project_rating.pct_empty_model_response = round(
            project_rating.num_empty_model_response * 100.0 / total_items, 2
        )
        project_rating.pct_invalid_auto_rater_response = round(
            project_rating.num_invalid_auto_rater_response * 100.0 / total_items, 2
        )
        project_rating.pct_empty_auto_rater_response = round(
            project_rating.num_empty_auto_rater_response * 100.0 / total_items, 2
        )

    if num_answer_correctness_evaluated > 0:
        project_rating.num_answer_correctness_evaluated = num_answer_correctness_evaluated
        project_rating.fully_correct_count = num_answer_correctness_all_correct
        project_rating.fully_incorrect_count = num_fully_incorrect_items
        project_rating.correct_with_excessive_count = num_items_correct_with_excessive_answers

        project_rating.pct_w_ci_all_answers_correct = _calculate_ci_str(
            num_answer_correctness_all_correct, num_answer_correctness_evaluated
        )
        project_rating.pct_w_ci_fully_incorrect_items = _calculate_ci_str(
            num_fully_incorrect_items, num_answer_correctness_evaluated
        )
        project_rating.pct_w_ci_correct_with_excessive_answers = _calculate_ci_str(
            num_items_correct_with_excessive_answers, num_answer_correctness_evaluated
        )

        project_rating.precision = f"{np.mean(per_item_metrics['precision']):.2%}"
        project_rating.recall = f"{np.mean(per_item_metrics['recall']):.2%}"
        project_rating.f1_score = f"{np.mean(per_item_metrics['f1_score']):.2%}"

        for category, stats in category_stats.items():
            if stats["evaluated"] > 0:
                project_rating.category_breakdown[category] = {
                    "evaluated": stats["evaluated"],
                    "all_correct": stats["all_correct"],
                    "accuracy": f"{stats['all_correct'] / stats['evaluated']:.2%}",
                }

    return project_rating


def load_deepsearchqa_dataset(csv_path: str | Path, max_samples: int | None = None) -> list[dict]:
    """Load DeepSearchQA dataset from CSV file."""
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Dataset not found: {csv_path}")

    items = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            if max_samples and idx >= max_samples:
                break
            items.append(
                {
                    "id": str(idx + 1),
                    "problem": row.get("problem", ""),
                    "problem_category": row.get("problem_category", ""),
                    "answer": row.get("answer", ""),
                    "answer_type": row.get("answer_type", "Single Answer"),
                }
            )
    return items


class DeepSearchQAEvaluatorConfig(EvaluatorBaseConfig, name="deepsearchqa_evaluator"):
    """Configuration for DeepSearchQA evaluator."""

    llm_name: LLMRef = Field(description="LLM to use as judge for quality evaluation")
    max_retries: int = Field(default=5, description="Maximum retries for LLM calls")


class DeepSearchQAEvalOutput(EvalOutput):
    """Extended output model with DeepSearchQA-specific metrics."""

    project_rating: dict[str, Any] = Field(default_factory=dict)
    leaderboard: dict[str, Any] = Field(default_factory=dict)


class DeepSearchQAEvaluator(BaseEvaluator):
    """DeepSearchQA evaluator using the official DeepMind evaluation methodology."""

    def __init__(self, llm: Any, max_concurrency: int = 5, max_retries: int = 5):
        super().__init__(max_concurrency=max_concurrency, tqdm_desc="DeepSearchQA Evaluation")
        self.llm = llm
        self.max_retries = max_retries

    def _build_grader_prompt(self, problem: str, answer: str, answer_type: str, response: str) -> str:
        """Build the grader prompt for LLM evaluation."""
        template = DEEPSEARCH_QA_PROMPT
        template += GRADER_RATING_OUTPUT_EXAMPLE.format(
            prompt=problem,
            prompt_type=answer_type,
            answer=answer,
            response=response,
        )
        return template

    async def _call_llm(self, prompt: str) -> str:
        response = await self.llm.ainvoke(prompt)
        return response.content if hasattr(response, "content") else str(response)

    def _reduce_llm_response_to_item_rating(
        self, item_rating: ItemRating, grader_llm_response_text: str, grader_llm_prompt_text: str
    ) -> ItemRating:
        """Parse the AutoRater LLM's response and populate an ItemRating object."""
        item_rating.rating_prompt = grader_llm_prompt_text
        item_rating.rating_response = grader_llm_response_text

        if not item_rating.response:
            item_rating.empty_model_response = True
            item_rating.error_message = "AI response was empty."
            return item_rating

        if not grader_llm_response_text:
            item_rating.empty_auto_rater_response = True
            item_rating.error_message = "Auto-rater response was empty."
            return item_rating

        parsed_json_response = _parse_json_response(grader_llm_response_text)
        if not parsed_json_response:
            item_rating.invalid_auto_rater_response = True
            item_rating.error_message = "Invalid JSON response from auto-rater."
            return item_rating

        try:
            answer_correctness_node = parsed_json_response.get("Answer Correctness")
            if not isinstance(answer_correctness_node, dict):
                item_rating.invalid_auto_rater_response = True
                item_rating.error_message = "Missing or malformed 'Answer Correctness' node."
                return item_rating

            grader_explanation = answer_correctness_node.get("Explanation")
            if not isinstance(grader_explanation, str):
                item_rating.invalid_auto_rater_response = True
                item_rating.error_message = "Missing or malformed 'Explanation' in Answer Correctness."
                return item_rating
            item_rating.answer_correctness_explanation = grader_explanation

            details = _get_answer_correctness_details(parsed_json_response)
            if details is None:
                item_rating.invalid_auto_rater_response = True
                item_rating.error_message = "Invalid 'Correctness Details' in Answer Correctness."
                return item_rating
            item_rating.expected_correct_answer_list = list(details.keys())
            item_rating.grader_ratings_list = list(details.values())

            excessive_answers = _get_excessive_answers(parsed_json_response)
            if excessive_answers is None:
                item_rating.invalid_auto_rater_response = True
                item_rating.error_message = "Invalid 'Excessive Answers' in Answer Correctness."
                return item_rating
            if excessive_answers:
                item_rating.response_wrong_answers_list = excessive_answers

        except (KeyError, TypeError, ValueError) as e:
            logger.exception("Error processing parsed JSON: %s", e)
            item_rating.invalid_auto_rater_response = True
            item_rating.error_message = f"Error during JSON processing: {e}"
            return item_rating

        return item_rating

    async def evaluate_item(self, item: EvalInputItem) -> EvalOutputItem:
        task_id = str(item.id)

        input_obj = item.input_obj if isinstance(item.input_obj, dict) else {}
        problem = input_obj.get("problem", str(item.input_obj) if item.input_obj else "")
        problem_category = input_obj.get("problem_category", "")
        answer = item.expected_output_obj or ""
        answer_type = input_obj.get("answer_type", "Single Answer")
        response = item.output_obj or ""

        item_rating = ItemRating(
            original_index=int(task_id) if task_id.isdigit() else None,
            example_id=task_id,
            query=problem,
            response=response,
            category_type=problem_category,
            expected_correct_answer=answer,
        )

        if not response:
            item_rating.empty_model_response = True
            item_rating.error_message = "No generated response"
            return EvalOutputItem(id=task_id, score=0.0, reasoning=item_rating.to_dict())

        rating_prompt_text = self._build_grader_prompt(problem, answer, answer_type, response)

        grader_llm_response_str = None
        import asyncio
        import random

        for i in range(self.max_retries):
            try:
                grader_llm_response_str = await self._call_llm(rating_prompt_text)
                break
            except Exception as e:
                logger.error(f"LLM call failed (attempt {i + 1}/{self.max_retries}) for id {task_id}: {e}")
                if i == self.max_retries - 1:
                    item_rating.error_message = f"LLM call failed after {self.max_retries} attempts: {e}"
                    return EvalOutputItem(id=task_id, score=0.0, reasoning=item_rating.to_dict())
                await asyncio.sleep(1 + (2 ** (i + random.random())))

        if grader_llm_response_str is None:
            item_rating.error_message = "LLM response was None after retries."
            return EvalOutputItem(id=task_id, score=0.0, reasoning=item_rating.to_dict())

        item_rating = self._reduce_llm_response_to_item_rating(item_rating, grader_llm_response_str, rating_prompt_text)

        score = 0.0
        if item_rating.grader_ratings_list:
            num_correct = sum(1 for r in item_rating.grader_ratings_list if r)
            total = len(item_rating.grader_ratings_list)
            has_excessive = bool(item_rating.response_wrong_answers_list)

            if num_correct == total and not has_excessive:
                score = 100.0
            elif num_correct == total and has_excessive:
                score = 75.0
            elif num_correct > 0:
                score = (num_correct / total) * 50.0
            else:
                score = 0.0

        return EvalOutputItem(id=task_id, score=round(score, 2), reasoning=item_rating.to_dict())

    async def evaluate(self, eval_input: EvalInput) -> DeepSearchQAEvalOutput:
        """Evaluate all items and compute aggregate statistics."""
        import asyncio

        from tqdm import tqdm

        from nat.plugins.eval.utils.tqdm_position_registry import TqdmPositionRegistry

        pbar = None
        tqdm_position = None
        try:
            tqdm_position = TqdmPositionRegistry.claim()
            pbar = tqdm(
                total=len(eval_input.eval_input_items),
                desc=self.tqdm_desc,
                position=tqdm_position,
            )

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
            if pbar:
                pbar.close()
            if tqdm_position is not None:
                TqdmPositionRegistry.release(tqdm_position)

        item_ratings = []
        for output_item in output_items:
            reasoning = output_item.reasoning if isinstance(output_item.reasoning, dict) else {}
            item_rating = ItemRating(
                example_id=str(output_item.id),
                query=reasoning.get("query", ""),
                response=reasoning.get("response", ""),
                category_type=reasoning.get("category_type"),
                expected_correct_answer=reasoning.get("expected_correct_answer"),
                answer_correctness_explanation=reasoning.get("answer_correctness_explanation"),
                expected_correct_answer_list=reasoning.get("expected_correct_answer_list"),
                response_wrong_answers_list=reasoning.get("response_wrong_answers_list"),
                grader_ratings_list=reasoning.get("grader_ratings_list"),
                empty_model_response=reasoning.get("empty_model_response", False),
                empty_auto_rater_response=reasoning.get("empty_auto_rater_response", False),
                invalid_auto_rater_response=reasoning.get("invalid_auto_rater_response", False),
                rating_response=reasoning.get("rating_response", ""),
                error_message=reasoning.get("error_message"),
            )
            item_ratings.append(item_rating)

        project_rating = aggregate_ratings(item_ratings)
        leaderboard_entry = project_rating.to_leaderboard_entry(model_name="NeAR Agent")

        numeric_scores = [item.score for item in output_items if isinstance(item.score, int | float)]
        avg_score = round(sum(numeric_scores) / len(numeric_scores), 2) if numeric_scores else None

        return DeepSearchQAEvalOutput(
            average_score=avg_score,
            project_rating=project_rating.to_dict(),
            leaderboard=leaderboard_entry.to_dict(),
            eval_output_items=output_items,
        )


@register_evaluator(config_type=DeepSearchQAEvaluatorConfig)
async def register_deepsearchqa_evaluator(config: DeepSearchQAEvaluatorConfig, builder: EvalBuilder):
    """Register DeepSearchQA evaluator with official DeepMind methodology."""
    llm = await builder.get_llm(config.llm_name, wrapper_type=LLMFrameworkEnum.LANGCHAIN)

    evaluator = DeepSearchQAEvaluator(
        llm=llm, max_concurrency=builder.get_max_concurrency(), max_retries=config.max_retries
    )

    yield EvaluatorInfo(
        config=config,
        evaluate_fn=evaluator.evaluate,
        description="DeepSearchQA Evaluator (Official DeepMind Methodology)",
    )

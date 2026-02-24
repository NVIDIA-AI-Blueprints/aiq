#!/usr/bin/env python3
"""FreshQA evaluator for NAT.

Implements the FreshEval Relaxed evaluation methodology from:
https://github.com/freshllms/freshqa

Evaluates model responses under relaxed evaluation criteria where hallucinations,
outdated information, and ill-formed answers are allowed, as long as the primary
answer is accurate.

Computes comprehensive accuracy metrics across various dimensions:
- Overall accuracy (all, test, dev splits)
- By fact type (fast-changing, slow-changing, never-changing)
- By premise type (valid premise vs false premise)
- By question complexity (one-hop vs multi-hop)
- By time period (old vs new questions)
"""

import datetime
import json
import logging
from pathlib import Path
from typing import Any

import pytz
from pydantic import BaseModel
from pydantic import Field

from nat.builder.builder import EvalBuilder
from nat.builder.evaluator import EvaluatorInfo
from nat.builder.framework_enum import LLMFrameworkEnum
from nat.cli.register_workflow import register_evaluator
from nat.data_models.component_ref import LLMRef
from nat.data_models.evaluator import EvaluatorBaseConfig
from nat.eval.evaluator.base_evaluator import BaseEvaluator
from nat.eval.evaluator.evaluator_model import EvalInput
from nat.eval.evaluator.evaluator_model import EvalInputItem
from nat.eval.evaluator.evaluator_model import EvalOutput
from nat.eval.evaluator.evaluator_model import EvalOutputItem

logger = logging.getLogger(__name__)


def get_current_date() -> str:
    """Get current date in Pacific timezone."""
    return datetime.datetime.now(pytz.timezone("America/Los_Angeles")).strftime("%B %d, %Y")


# FreshEval Relaxed evaluation prompt prefix
FRESHEVAL_PREFIX = (
    "Please evaluate the response to a question under relaxed evaluation, where"
    " hallucinations, outdated information, and ill-formed answers are allowed,"
    " as long as the primary answer is accurate. Please credit the response"
    " only if it provides a confident and definitive answer, or the correct"
    " answer can be obviously inferred from the response. The primary or final"
    " answer when standing alone must be accurate. Any additional information"
    " that is provided must not contradict the primary answer or reshape one's"
    " perception of it. For false-premise questions, the response must point"
    " out the presence of a false premise to receive credit. For answers that"
    " involve names of entities (e.g., people), complete names or commonly"
    " recognized names are expected. Regarding numerical answers, approximate"
    " numbers are generally not accepted unless explicitly included in the"
    " ground-truth answers. We accept ill-formed responses (including those in"
    " a non-English language), as well as hallucinated or outdated information"
    " that does not significantly impact the primary answer."
)


def get_demo_examples() -> list[dict]:
    """Get demonstration examples for few-shot learning."""
    current_date = get_current_date()
    return [
        {
            "question": "How old is the world's oldest verified living person?",
            "correct_answers": [
                "117 years old",
                "117",
            ],
            "response": (
                f"As of today {current_date}, the most up-to-date and relevant"
                " information regarding this query is as follows. The oldest"
                " verified living person is Maria Branyas Morera, who was born"
                " on March 4, 1907, making her 117 years old."
            ),
            "comment": (
                "This is a valid question. The primary answer in the response"
                " (117 years old) is accurate, and all the provided information"
                " is accurate and up-to-date. Thus, the response is credited."
            ),
            "evaluation": "correct",
        },
        {
            "question": "When did the UK adopt the Euro?",
            "correct_answers": ["The United Kingdom has never adopted the Euro."],
            "response": (
                "The UK has never adopted the Euro as its official currency. The"
                " country has retained the British pound sterling (GBP) as its"
                " currency."
            ),
            "comment": (
                "The question contains a false premise. The response debunks the"
                " question's false premise (i.e., it points out that the UK has"
                " never adopted the Euro), and all the provided information is"
                " accurate and up-to-date. Thus, the response is credited."
            ),
            "evaluation": "correct",
        },
        {
            "question": ("How much longer will Brittney Griner spend in the Russian prison?"),
            "correct_answers": ["She was released in December 2022 as part of a prisoner swap."],
            "response": (
                "I'm sorry, but I have no information to suggest that Brittney"
                " Griner is currently in a Russian prison. As far as I know, she"
                " is a professional basketball player who currently plays for the"
                " Phoenix Mercury in the Women's National Basketball Association"
                " (WNBA). If you have any more information or context, please let"
                " me know and I'll do my best to help."
            ),
            "comment": (
                "The question contains a false premise. The response fails to"
                " debunk the question's false premise by not explicitly stating"
                " that Brittney Griner was already released. Additionally, the"
                " response lacks a confident and definitive answer. Thus, the"
                " response is not credited."
            ),
            "evaluation": "incorrect",
        },
        {
            "question": ("Which language has the third largest population by number of native speakers?"),
            "correct_answers": ["English"],
            "response": "1. Mandarin 2. Spanish 3. English",
            "comment": (
                "This is a valid question. Even though the response doesn't contain"
                " an explicit statement, the correct answer (English) can still be"
                " inferred from the response. Thus, the response is credited."
            ),
            "evaluation": "correct",
        },
        {
            "question": (
                "Has Virginia Woolf's novel about the Ramsay family entered the public domain in the United States?"
            ),
            "correct_answers": ["Yes"],
            "response": (
                "1927's To the Lighthouse is in the public domain in the United"
                " States. The final answer is To the Lighthouse."
            ),
            "comment": (
                "This is a valid question. While the primary information in the"
                " response (1927's To the Lighthouse is in the public domain in"
                " the United States) is accurate, the final answer when standing"
                ' alone is inaccurate (it should be "Yes" instead of "To the'
                ' Lighthouse"). Thus, the response is not credited.'
            ),
            "evaluation": "incorrect",
        },
        {
            "question": "Is Tesla's stock price above $250 a share?",
            "correct_answers": ["No"],
            "response": "No, it isn't. The stock price is currently at $257.",
            "comment": (
                "This is a valid question. While the primary answer in the"
                " response (No) is accurate, the additional information"
                " contradicts the primary answer (250). Thus,"
                " the response is not credited."
            ),
            "evaluation": "incorrect",
        },
        {
            "question": "When did Lionel Messi win his second FIFA World Cup?",
            "correct_answers": [
                "Messi has not won his second FIFA World Cup.",
                "Messi has won only one FIFA World Cup.",
            ],
            "response": (
                "This question does not contain a valid premise. Lionel Messi has never won a FIFA World Cup."
            ),
            "comment": (
                "The question contains a false premise. While the response"
                " debunks the question's false premise (i.e., it suggests that"
                " Messi has not won his second FIFA World Cup), it inaccurately"
                " shapes one's knowledge perception of the primary answer, as"
                " Messi has already won one FIFA World Cup. Thus, the response"
                " is not credited."
            ),
            "evaluation": "incorrect",
        },
        {
            "question": ("How many times has Jeremy Corbyn served as Prime Minister of the UK?"),
            "correct_answers": ["Corbyn has never served as Prime Minister of the UK."],
            "response": "Zero",
            "comment": (
                "The question contains a false premise. The response lacks a"
                " rebuttal, which is always required for false-premise questions."
                " Thus, the response is not credited."
            ),
            "evaluation": "incorrect",
        },
        {
            "question": "Who founded Amazon?",
            "correct_answers": ["Jeff Bezos", "Jeffrey Preston Bezos"],
            "response": "100% of people said Jeff.",
            "comment": (
                "This is a valid question. Given that the question involves a"
                " person's name, a complete name or commonly recognized name is"
                ' expected ("Jeff Bezos" instead of "Jeff"). Thus, the response'
                " is not credited."
            ),
            "evaluation": "incorrect",
        },
        {
            "question": "How many books has Colleen Hoover published?",
            "correct_answers": ["26 books", "26"],
            "response": (
                f"As of today {current_date}, the most up-to-date and relevant"
                " information regarding this query is as follows. Colleen Hoover"
                " has published over 20 books and novellas."
            ),
            "comment": (
                "This is a valid question. For a numerical answer, an approximate"
                " value (over 20 books) is generally not accepted unless"
                " explicitly included in the correct answers. Thus, the response"
                " is not credited."
            ),
            "evaluation": "incorrect",
        },
        {
            "question": "What is the largest model size of GPT-3?",
            "correct_answers": [
                "175 billion parameters",
                "175B parameters",
                "175 billion",
                "175B",
            ],
            "response": (
                "175 billion parameters. It is a 175 billion parameter, 1.37TB,"
                " 137B token, 137B wordpiece, 137B BPE, 137B byte pair encoding,"
                " 137B BPE token, 137B BPE wordpiece, 137B BPE token, 137B BPE"
                " wordpiece"
            ),
            "comment": (
                "This is a valid question. Even though the response is ill-formed"
                " and contains repetitions, the primary answer in the response (175"
                " billion parameters) is still accurate. Thus, the response is"
                " credited."
            ),
            "evaluation": "correct",
        },
        {
            "question": "How many member nations exist in the United Nations?",
            "correct_answers": [
                "193",
                "193 members",
                "193 member states",
                "193 sovereign states",
            ],
            "response": (
                "As of my last update in April 2023, there were 193"
                " member nations in the United Nations. Please note that this"
                " information may have changed since then, so it is advisable to"
                " check the latest information from the United Nations or other"
                " reliable sources."
            ),
            "comment": (
                "This is a valid question. Even though the response fails to"
                " provide a current answer and instead relies on outdated "
                " information without confirming its continued accuracy, the"
                " primary answer in the response (193 member nations) is still"
                " accurate. Thus, the response is credited."
            ),
            "evaluation": "correct",
        },
        {
            "question": ("Who won the biggest single-tournament payday in tennis history?"),
            "correct_answers": ["Novak Djokovic"],
            "response": (
                "The biggest single-tournament payday in tennis history was won"
                " by Novak Djokovic at the 2021 Australian Open. He received a"
                " prize money of AUD 2.75 million (approximately USD 2.1 million)"
                " for winning the men's singles title."
            ),
            "comment": (
                "This is a valid question. Even though the additional provided"
                " information is outdated or hallucinated (by winning the 2022 ATP"
                " Finals title, Djokovic earned a record $4,740,300, the highest"
                " payout for a tournament winner in tennis), the primary answer in"
                " the response (Novak Djokovic) is still accurate. Thus, the"
                " response is credited."
            ),
            "evaluation": "correct",
        },
        {
            "question": ("Who was the first football player to score one hundred international goals?"),
            "correct_answers": ["Ali Daei"],
            "response": (
                "As of my last update in April 2023, Ali Daei, a"
                " former Iranian footballer, was the first player to score 100"
                " international goals."
            ),
            "comment": (
                "This is a valid question. The primary answer in the response"
                " (Ali Daei) is accurate. Although the knowledge cutoff date is"
                " in 2021, this fact is timeless because Ali Daei was the initial"
                " achiever of this milestone, and he will always remain the first)."
                " Thus, the response is credited."
            ),
            "evaluation": "correct",
        },
        {
            "question": ("Who is the latest winner of the Formula 1 world championship?"),
            "correct_answers": ["Max Verstappen", "Max Emilian Verstappen"],
            "response": (
                "Max Verstappen won the 2023 Formula 1 world championship. He is"
                " a Dutch racing driver who competes in Formula One for Red Bull"
                " Racing. He is the son of former Formula One driver Jos"
                " Verstappen. Verstappen started his racing career in karting at"
                " the age of seven. He won the 2013 European Karting Championship"
                " and the 2013 World Karting Championship. In 2014, he moved to"
                " single-seater racing, competing in the European Formula Three"
                " Championship. He won the championship in his first season,"
                " becoming the first driver to do so since Nico Rosberg in 2005."
                " In 2015, Verstappen moved to Formula One, driving for Toro"
                " Rosso. He became the youngest driver to compete in Formula One"
                " at the age of 17. He scored his first points in Formula One at"
                " the 2015 Hungarian GrandPrix. In 2016, Verstappen moved to Red"
                " Bull Racing. He won his first race at the 2016 Spanish Grand"
                " Prix. He became the youngest driver to win a race in Formula"
                " One at theage of 18. Verstappen finished the 2016 season in"
                " third place in the drivers' championship. In 2017, Verstappen"
                " won four races and finished the season in second place in the"
                " drivers' championship. In 2018, Verstappen won seven races and"
                " finished the season in second place in the drivers'"
                " championship. In 2019, Verstappen won nine races and finished"
                " the season in first place in the drivers' championship. He is"
                " the first Dutch driver to win the Formula One world"
                " championship."
            ),
            "comment": (
                "This is a valid question. Even though the response contains"
                " several instances of hallucinated information (e.g., Max"
                " Verstappen did not win the Formula Three European Championship in"
                " 2014), the primary answer in the response (Max Verstappen) is"
                " still accurate. Thus, the response is credited."
            ),
            "evaluation": "correct",
        },
    ]


DEMO_EVALUATION_TEMPLATE = (
    "\ncorrect answer(s): {correct_answers}\nresponse: {response}\ncomment: {comment}\nevaluation: {evaluation}"
)

EVALUATION_TEMPLATE = (
    "\ncorrect answer(s): {correct_answers}"
    "\nresponse: {response}"
    "\ngenerate comment and evaluation in the style of `comment: ...\nevaluation: ...`"
)


def build_fresheval_prompt(question: str, response: str, correct_answers: list[str]) -> str:
    """Build the FreshEval prompt with few-shot examples."""
    demo_examples = get_demo_examples()

    # Build demonstration prompts
    demo_prompts = []
    for ex in demo_examples:
        demo_evaluation = DEMO_EVALUATION_TEMPLATE.format(
            question=ex["question"],
            correct_answers=" | ".join(ex["correct_answers"]),
            response=ex["response"],
            comment=ex["comment"],
            evaluation=ex["evaluation"],
        )
        demo_prompts.append(f"\n\n\nquestion: {ex['question']}{demo_evaluation}")

    fresheval_demo = "".join(demo_prompts).strip()

    # Build evaluation for the target question
    evaluation = EVALUATION_TEMPLATE.format(
        correct_answers=" | ".join(correct_answers),
        response=response,
    )
    fresheval_question = f"\n\n\nquestion: {question}{evaluation}"

    return FRESHEVAL_PREFIX + "\n\n\n" + fresheval_demo + fresheval_question


def extract_ratings(response):
    evaluation = None
    lines = response.lower().strip().split("\n")

    for line in lines:
        if "evaluation:" in line:
            evaluation = line.split(" ")[-1]
            if evaluation not in ["correct", "incorrect"]:
                return False, None

        if len(lines) == 1:
            if lines[0].split(" ")[-1] in ["correct", "incorrect"]:
                evaluation = lines[0].split(" ")[-1]

        if evaluation == "incorrect":
            evaluation = "FALSE"
        else:
            evaluation = "TRUE"

        if evaluation is None:
            if "Thus, the response is credited." in response:
                evaluation = "TRUE"
            elif "Thus, the response is not credited." in response:
                evaluation = "FALSE"
            else:
                return False, None
    return True, evaluation


def load_dataset_metadata(dataset_file: str | None) -> dict[str, dict]:
    """Load dataset metadata from JSON file."""
    if not dataset_file:
        return {}

    path = Path(dataset_file)
    if not path.exists():
        logger.warning(f"Dataset file not found: {dataset_file}")
        return {}

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        metadata = {}
        for item in data:
            item_id = str(item.get("id", ""))
            if item_id:
                metadata[item_id] = {
                    "split": item.get("split", ""),
                    "false_premise": item.get("false_premise", False),
                    "fact_type": item.get("fact_type", ""),
                    "num_hops": item.get("num_hops", ""),
                    "effective_year": str(item.get("effective_year", "")),
                }
        return metadata
    except Exception as e:
        logger.error(f"Error loading dataset metadata: {e}")
        return {}


class AccuracyMetric(BaseModel):
    """Single accuracy metric with count."""

    accuracy: float = Field(default=0.0, description="Accuracy percentage (0-100)")
    count: int = Field(default=0, description="Number of items in this category")
    correct: int = Field(default=0, description="Number of correct items")


class AccuracyBreakdown(BaseModel):
    """Breakdown of accuracy by a dimension with splits."""

    all: AccuracyMetric = Field(default_factory=AccuracyMetric)
    test: AccuracyMetric = Field(default_factory=AccuracyMetric)
    dev: AccuracyMetric = Field(default_factory=AccuracyMetric)


class FreshQAConfig(EvaluatorBaseConfig, name="freshqa_evaluator"):
    """Configuration for FreshQA evaluator."""

    llm_name: LLMRef = Field(description="LLM to use as judge for evaluation")
    max_retries: int = Field(default=3, description="Maximum retries for invalid evaluations")
    dataset_file: str = Field(description="Path to dataset JSON file for loading metadata (split, fact_type, etc.)")


class FreshQAEvalOutput(EvalOutput):
    """Extended output model with comprehensive accuracy metrics.

    Provides accuracy breakdowns across multiple dimensions:
    - Overall accuracy (all/test/dev splits)
    - By fact type (fast-changing, slow-changing, never-changing)
    - By premise type (valid premise, false premise)
    - By question complexity (one-hop, multi-hop)
    - By time period (old questions pre-2022, new questions 2022-2023)
    """

    # Basic counts
    total_correct: int = Field(default=0, description="Number of correct responses")
    total_evaluated: int = Field(default=0, description="Total items evaluated")
    total_errors: int = Field(default=0, description="Total items with errors")

    # Overall accuracy
    accuracy: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)

    # By fact type (valid premise questions only)
    accuracy_fast_changing: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)
    accuracy_slow_changing: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)
    accuracy_never_changing: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)

    # By premise type
    accuracy_valid_premise: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)
    accuracy_false_premise: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)

    # Valid premise breakdowns
    accuracy_vp_one_hop: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)
    accuracy_vp_multi_hop: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)
    accuracy_vp_old: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)
    accuracy_vp_new: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)

    # False premise breakdowns
    accuracy_fp_one_hop: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)
    accuracy_fp_multi_hop: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)
    accuracy_fp_old: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)
    accuracy_fp_new: AccuracyBreakdown = Field(default_factory=AccuracyBreakdown)


def compute_accuracy_metric(correct: int, total: int) -> AccuracyMetric:
    """Compute accuracy metric from counts."""
    if total == 0:
        return AccuracyMetric(accuracy=0.0, count=0, correct=0)
    return AccuracyMetric(accuracy=round((correct / total) * 100, 1), count=total, correct=correct)


def compute_breakdown(results: list[dict], metadata: dict[str, dict]) -> AccuracyBreakdown:
    """Compute accuracy breakdown by split."""
    all_correct = sum(1 for r in results if r.get("is_correct", False))
    all_count = len(results)

    test_results = [r for r in results if metadata.get(r["id"], {}).get("split") == "TEST"]
    test_correct = sum(1 for r in test_results if r.get("is_correct", False))
    test_count = len(test_results)

    dev_results = [r for r in results if metadata.get(r["id"], {}).get("split") == "DEV"]
    dev_correct = sum(1 for r in dev_results if r.get("is_correct", False))
    dev_count = len(dev_results)

    return AccuracyBreakdown(
        all=compute_accuracy_metric(all_correct, all_count),
        test=compute_accuracy_metric(test_correct, test_count),
        dev=compute_accuracy_metric(dev_correct, dev_count),
    )


class FreshQAEvaluator(BaseEvaluator):
    """FreshQA evaluator using FreshEval Relaxed methodology."""

    def __init__(
        self,
        llm: Any,
        max_concurrency: int = 4,
        max_retries: int = 3,
        dataset_file: str | None = None,
    ):
        super().__init__(max_concurrency=max_concurrency, tqdm_desc="FreshQA Evaluation")
        self.llm = llm
        self.max_retries = max_retries
        self.dataset_metadata = load_dataset_metadata(dataset_file)

    async def _call_llm(self, prompt: str) -> str:
        """Call the LLM and return response text."""
        current_date = get_current_date()
        messages = [
            {
                "role": "system",
                "content": (
                    f"You are a helpful assistant. Respond as concisely as possible. Knowledge cutoff: {current_date}."
                ),
            },
            {"role": "user", "content": "What's today's date?"},
            {
                "role": "assistant",
                "content": f"Today is {current_date} in Pacific Standard Time.",
            },
            {"role": "user", "content": prompt},
        ]
        # Build a single prompt from messages for langchain
        full_prompt = "\n".join(f"{msg['role'].upper()}: {msg['content']}" for msg in messages)
        response = await self.llm.ainvoke(full_prompt)
        return response.content if hasattr(response, "content") else str(response)

    def _compute_metrics(self, output_items: list[EvalOutputItem]) -> FreshQAEvalOutput:
        """Compute comprehensive accuracy metrics from evaluation results."""
        # Collect results with metadata
        results = []
        total_errors = 0

        for item in output_items:
            reasoning = item.reasoning if isinstance(item.reasoning, dict) else {}
            if "error" in reasoning:
                total_errors += 1
                continue

            item_id = str(item.id)
            results.append(
                {
                    "id": item_id,
                    "is_correct": reasoning.get("is_correct", False),
                }
            )

        total_correct = sum(1 for r in results if r.get("is_correct", False))
        total_evaluated = len(results)

        # Overall accuracy
        overall_breakdown = compute_breakdown(results, self.dataset_metadata)

        # Filter by premise type
        vp_results = [r for r in results if not self.dataset_metadata.get(r["id"], {}).get("false_premise", False)]
        fp_results = [r for r in results if self.dataset_metadata.get(r["id"], {}).get("false_premise", False)]

        # Fact type breakdowns (valid premise only)
        fast_changing = [
            r for r in vp_results if self.dataset_metadata.get(r["id"], {}).get("fact_type") == "fast-changing"
        ]
        slow_changing = [
            r for r in vp_results if self.dataset_metadata.get(r["id"], {}).get("fact_type") == "slow-changing"
        ]
        never_changing = [
            r for r in vp_results if self.dataset_metadata.get(r["id"], {}).get("fact_type") == "never-changing"
        ]

        # Hop breakdowns
        vp_one_hop = [r for r in vp_results if self.dataset_metadata.get(r["id"], {}).get("num_hops") == "one-hop"]
        vp_multi_hop = [r for r in vp_results if self.dataset_metadata.get(r["id"], {}).get("num_hops") == "multi-hop"]
        fp_one_hop = [r for r in fp_results if self.dataset_metadata.get(r["id"], {}).get("num_hops") == "one-hop"]
        fp_multi_hop = [r for r in fp_results if self.dataset_metadata.get(r["id"], {}).get("num_hops") == "multi-hop"]

        # Time period breakdowns
        def is_old(item_id: str) -> bool:
            year = self.dataset_metadata.get(item_id, {}).get("effective_year", "")
            return year not in ["2022", "2023"]

        def is_new(item_id: str) -> bool:
            year = self.dataset_metadata.get(item_id, {}).get("effective_year", "")
            return year in ["2022", "2023"]

        vp_old = [r for r in vp_results if is_old(r["id"])]
        vp_new = [r for r in vp_results if is_new(r["id"])]
        fp_old = [r for r in fp_results if is_old(r["id"])]
        fp_new = [r for r in fp_results if is_new(r["id"])]

        return FreshQAEvalOutput(
            average_score=round(total_correct / total_evaluated, 4) if total_evaluated > 0 else 0.0,
            total_correct=total_correct,
            total_evaluated=total_evaluated,
            total_errors=total_errors,
            eval_output_items=output_items,
            # Overall
            accuracy=overall_breakdown,
            # Fact types
            accuracy_fast_changing=compute_breakdown(fast_changing, self.dataset_metadata),
            accuracy_slow_changing=compute_breakdown(slow_changing, self.dataset_metadata),
            accuracy_never_changing=compute_breakdown(never_changing, self.dataset_metadata),
            # Premise types
            accuracy_valid_premise=compute_breakdown(vp_results, self.dataset_metadata),
            accuracy_false_premise=compute_breakdown(fp_results, self.dataset_metadata),
            # Valid premise breakdowns
            accuracy_vp_one_hop=compute_breakdown(vp_one_hop, self.dataset_metadata),
            accuracy_vp_multi_hop=compute_breakdown(vp_multi_hop, self.dataset_metadata),
            accuracy_vp_old=compute_breakdown(vp_old, self.dataset_metadata),
            accuracy_vp_new=compute_breakdown(vp_new, self.dataset_metadata),
            # False premise breakdowns
            accuracy_fp_one_hop=compute_breakdown(fp_one_hop, self.dataset_metadata),
            accuracy_fp_multi_hop=compute_breakdown(fp_multi_hop, self.dataset_metadata),
            accuracy_fp_old=compute_breakdown(fp_old, self.dataset_metadata),
            accuracy_fp_new=compute_breakdown(fp_new, self.dataset_metadata),
        )

    async def evaluate(self, eval_input: EvalInput) -> FreshQAEvalOutput:
        """Evaluate all items and compute comprehensive accuracy metrics."""
        import asyncio

        from tqdm import tqdm

        from nat.eval.utils.tqdm_position_registry import TqdmPositionRegistry

        pbar = None
        try:
            tqdm_position = TqdmPositionRegistry.claim()
            pbar = tqdm(
                total=len(eval_input.eval_input_items),
                desc=self.tqdm_desc,
                position=tqdm_position,
            )

            async def wrapped(item: EvalInputItem) -> EvalOutputItem:
                async with self.semaphore:
                    try:
                        output_item = await self.evaluate_item(item)
                        pbar.update(1)
                        return output_item
                    except Exception as e:
                        pbar.update(1)
                        logger.error(f"Error evaluating item {item.id}: {e}")
                        return EvalOutputItem(
                            id=item.id,
                            score=0.0,
                            reasoning={"error": f"Evaluator error: {str(e)}"},
                        )

            output_items = await asyncio.gather(*[wrapped(item) for item in eval_input.eval_input_items])
        finally:
            if pbar:
                pbar.close()
                TqdmPositionRegistry.release(tqdm_position)

        result = self._compute_metrics(list(output_items))
        return result

    async def evaluate_item(self, item: EvalInputItem) -> EvalOutputItem:
        """Evaluate a single item using FreshEval methodology."""
        item_id = str(item.id)
        model_response = item.output_obj or ""
        question = item.input_obj or ""

        if not model_response:
            return EvalOutputItem(
                id=item_id,
                score=0.0,
                reasoning={"error": "No model response provided"},
            )

        # Extract correct answers from expected_output_obj
        expected = item.expected_output_obj
        correct_answers = []

        if isinstance(expected, dict):
            # Try to get answers from answer_N keys
            for i in range(10):
                answer = expected.get(f"answer_{i}")
                if answer and str(answer).strip():
                    correct_answers.append(str(answer).strip())

        elif isinstance(expected, list):
            correct_answers = [str(a).strip() for a in expected if a and str(a).strip()]

        elif isinstance(expected, str) and expected.strip():
            correct_answers = [expected.strip()]

        if not correct_answers:
            return EvalOutputItem(
                id=item_id,
                score=0.0,
                reasoning={"error": "No correct answers provided"},
            )

        # Build FreshEval prompt
        prompt = build_fresheval_prompt(question, model_response, correct_answers)

        # Call LLM with retries
        rating = None
        llm_explanation = None
        last_error = None

        for retry in range(self.max_retries):
            try:
                llm_response = await self._call_llm(prompt)
                llm_explanation = llm_response
                is_valid, rating = extract_ratings(llm_response)

                if is_valid:
                    break
                else:
                    last_error = "Invalid evaluation format"
                    # Log a snippet of the response for debugging
                    logger.warning(
                        f"Invalid evaluation for item {item_id}, retry {retry + 1}/{self.max_retries}. "
                        f"Response: {llm_response}"
                    )

            except Exception as e:
                last_error = str(e)
                logger.warning(f"Error on retry {retry + 1}: {e}")
                import asyncio

                await asyncio.sleep(1.5**retry)

        if rating is None:
            return EvalOutputItem(
                id=item_id,
                score=0.0,
                reasoning={
                    "error": f"Failed after {self.max_retries} retries: {last_error}",
                    "is_correct": False,
                },
            )

        is_correct = rating == "TRUE"
        score = 1.0 if is_correct else 0.0

        return EvalOutputItem(
            id=item_id,
            score=score,
            reasoning={
                "is_correct": is_correct,
                "rating": rating,
                "explanation": llm_explanation,
                "question": question,
                "model_response": model_response,
                "correct_answers": correct_answers,
            },
        )


@register_evaluator(config_type=FreshQAConfig)
async def register_freshqa_evaluator(config: FreshQAConfig, builder: EvalBuilder):
    """Register FreshQA evaluator."""
    # Convert CSV to JSON at evaluation time (not at plugin load)
    from .convert_csv_to_json import convert_csv_to_json

    if config.dataset_file.endswith(".csv"):
        convert_csv_to_json(
            input_csv=config.dataset_file,
            output_json=config.dataset_file.replace(".csv", ".json"),
        )
        config.dataset_file = config.dataset_file.replace(".csv", ".json")

    llm = await builder.get_llm(config.llm_name, wrapper_type=LLMFrameworkEnum.LANGCHAIN)
    evaluator = FreshQAEvaluator(
        llm=llm,
        max_concurrency=builder.get_max_concurrency(),
        max_retries=config.max_retries,
        dataset_file=config.dataset_file,
    )
    yield EvaluatorInfo(
        config=config,
        evaluate_fn=evaluator.evaluate,
        description="FreshQA Evaluator using FreshEval Relaxed methodology",
    )

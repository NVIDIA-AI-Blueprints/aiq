<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
# FreshQA Evaluator

A custom NeMo Agent Toolkit evaluator implementing the FreshEval Relaxed methodology for evaluating factual accuracy of model responses.

## Overview

This evaluator implements the FreshEval Relaxed evaluation methodology from [FreshLLMs](https://github.com/freshllms/freshqa). It evaluates model responses under relaxed criteria where hallucinations, outdated information, and ill-formed answers are allowed, as long as the primary answer is accurate.

## Installation

```bash
# From the repository root
uv pip install -e ./frontends/benchmarks/freshqa
```

## Prerequisites

### Judge model and API key

The FreshQA evaluator uses an LLM judge. The default configs use **OpenAI GPT-4o** as the judge.

1. **Choose a judge model** (for example, OpenAI GPT-4o or Gemini 2.5 Flash).
2. **Obtain an API key** and set it in `deploy/.env` (for example, `OPENAI_API_KEY=your_key`).
3. To use a different judge, add that LLM under `llms:` and set `eval.evaluators.freshqa.llm_name` to its name.

### Other API keys

Set in `deploy/.env`: `NVIDIA_API_KEY` (agent), `TAVILY_API_KEY` (web search).

## Quick Start

```bash
# Shallow research only
dotenv -f deploy/.env run nat eval --config_file frontends/benchmarks/freshqa/configs/config_shallow_research_only.yml

# Full workflow (orchestration + research agents)
dotenv -f deploy/.env run nat eval --config_file frontends/benchmarks/freshqa/configs/config_full_workflow.yml
```

Results go to `frontends/benchmarks/freshqa/results` (or the config's `output_dir`).


## Evaluation Methodology

The FreshEval Relaxed methodology:

1. **Relaxed Criteria**: Allows hallucinations, outdated information, and ill-formed answers as long as the primary answer is accurate.

2. **Confident Answers Required**: Credits responses only if they provide a confident and definitive answer, or the correct answer can be obviously inferred.

3. **False Premise Handling**: For false-premise questions, the response must explicitly point out the presence of a false premise to receive credit.

4. **Name Accuracy**: For answers involving names of entities (for example, people), complete names or commonly recognized names are expected.

5. **Numerical Precision**: Approximate numbers are generally not accepted unless explicitly included in the ground-truth answers.

## Output Metrics

The evaluator produces:

- **accuracy**: An `AccuracyBreakdown` object containing per-category accuracy breakdowns (by fact type, number of hops, and false premise status)
- **total_correct**: Number of correctly answered questions
- **total_evaluated**: Total number of items evaluated
- **average_score**: Overall accuracy as a 0-1 ratio (for example, 0.75 means 75% correct)

Each item includes detailed reasoning with:
- `is_correct`: Boolean indicating if the response was correct
- `rating`: "TRUE" or "FALSE"
- `explanation`: LLM's explanation for the rating
- `question`, `model_response`, `correct_answers`: Context for the evaluation

## Dataset Format

The evaluator expects a CSV file with the following columns:
- `question`: The question to be answered
- `answer_0` through `answer_9`: Acceptable correct answers (can have multiple)
- `split`: Optional filter column (for example, "TEST", "DEV")

## References

- [FreshQA Dataset](https://github.com/freshllms/freshqa)
- [FreshEval Paper](https://arxiv.org/abs/2310.03214)

---

## Configuration Files

| Config | Description |
|--------|-------------|
| `configs/config_full_workflow.yml` | Full workflow with OpenAI judge. Use for quickstart. |
| `configs/config_shallow_research_only.yml` | Shallow research only with OpenAI judge. |


<details>
<summary><strong>FreshQA Dataset Intro</strong></summary>

The **FreshQA** benchmark dataset is designed to evaluate how well language models handle questions requiring up-to-date world knowledge.

---

## Dataset Overview

FreshQA categorizes questions along three key dimensions:

| Dimension | Values | Description |
|-----------|--------|-------------|
| **Fact Type** | `never-changing`, `slow-changing`, `fast-changing` | How frequently the answer changes over time |
| **Num Hops** | `one-hop`, `multi-hop` | Whether the question requires single or chained reasoning |
| **False Premise** | `True`, `False` | Whether the question contains an incorrect assumption |

---

## Never-Changing Facts

These questions have answers that remain constant over time.

### One-Hop Examples

> **Q:** What is the largest mammal in the world?
> **A:** Blue whale

> **Q:** Who founded Amazon?
> **A:** Jeff Bezos

> **Q:** What is the capital of the commonwealth of Massachusetts?
> **A:** Boston

> **Q:** On what date did the Berlin Wall fall?
> **A:** November 9, 1989

> **Q:** Who painted The Starry Night?
> **A:** Vincent van Gogh

### Multi-Hop Examples

> **Q:** What's the capital of the largest state in America?
> **A:** Juneau *(Alaska -> capital is Juneau)*

> **Q:** Which member of The Beatles was born first?
> **A:** Ringo Starr

> **Q:** Where was the primary designer of AlexNet born?
> **A:** Ukraine *(Alex Krizhevsky -> born in Ukraine)*

---

## Slow-Changing Facts

These questions have answers that change infrequently, perhaps yearly or less often.

### One-Hop Examples

> **Q:** Who is the CEO of Google?
> **A:** Sundar Pichai

> **Q:** How many grand slams does Rafael Nadal have?
> **A:** 22

> **Q:** What is the best-selling video game franchise of all time?
> **A:** Mario

> **Q:** What is the top-ranked university in the US according to the US News Ranking?
> **A:** Princeton University

> **Q:** Who is the current German chancellor?
> **A:** Friedrich Merz

### Multi-Hop Examples

> **Q:** Which country has President Joe Biden visited the most during his presidency so far?
> **A:** United Kingdom

> **Q:** Who has the most liked post on Instagram?
> **A:** Lionel Messi

---

## Fast-Changing Facts

These questions have answers that can change frequently, sometimes daily or weekly.

### One-Hop Examples

> **Q:** Who is the richest man on earth?
> **A:** Elon Musk *(as of dataset creation)*

> **Q:** Who is the current No. 1 on the Billboard Artist 100?
> **A:** Taylor Swift *(as of dataset creation)*

> **Q:** What is the latest highest-grossing movie of the week at the Box office?
> **A:** *(Changes weekly)*

> **Q:** What is Geoff Hinton's h-index?
> **A:** 192 *(as of dataset creation)*

### Multi-Hop Examples

> **Q:** How old is the richest person in the world?
> **A:** 54 years old *(Elon Musk's age at dataset creation)*

> **Q:** In what country was the most recent Time Person of the Year born?
> **A:** USA *(Donald Trump -> born in USA)*

---

## False Premise Questions

These questions contain incorrect assumptions that the model must identify and address.

### Factual Corrections

> **Q:** What is the name of Leonardo DiCaprio's third child?
> **A:** Leonardo DiCaprio does not have any children.

> **Q:** When did the UK adopt the Euro?
> **A:** The United Kingdom has never adopted the Euro.

> **Q:** How many home runs did Real Madrid score?
> **A:** Real Madrid is a professional soccer club and thus cannot score home runs. In soccer, players score goals, not home runs.

### Temporal Corrections

> **Q:** When was the iPhone 9 released?
> **A:** Apple has never released an iPhone 9 nor does it plan to.

> **Q:** When did the first human land on Mars?
> **A:** No humans have been to Mars yet.

### Logical Corrections

> **Q:** By how much is 3 bigger than 4?
> **A:** 3 is smaller than 4 by 1.

> **Q:** Which antibiotics are most effective against the flu?
> **A:** Antibiotics are only effective against bacteria while the flu is a virus.

---

## Dataset Statistics

| Category | Count |
|----------|-------|
| Total Questions | 600 |
| TEST Split | 500 |
| DEV Split | 100 |

### By Fact Type
- **Never-changing:** Questions with permanent answers
- **Slow-changing:** Questions reviewed occasionally or yearly
- **Fast-changing:** Questions requiring frequent updates

### By Reasoning Complexity
- **One-hop:** Direct factual lookups
- **Multi-hop:** Requires chaining multiple facts together

---

## Source

FreshQA benchmark dataset: [FreshLLMs GitHub](https://github.com/freshllms/freshqa)

For more information about the FreshQA benchmark methodology, refer to the original research paper.

</details>

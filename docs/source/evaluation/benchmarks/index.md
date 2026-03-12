<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Benchmarks

Standardized evaluation suites for measuring research quality.

| Benchmark | What it measures | Dataset size | Agents tested |
|-----------|-----------------|--------------|---------------|
| [FreshQA](./freshqa.md) | Factual accuracy on current knowledge | 600 questions | Shallow, Full pipeline |
| [Deep Research Bench](./deep-research-bench.md) | Report quality (RACE + FACT metrics) | 100 topics | Deep researcher |
| [DeepSearchQA](./deepsearch-qa.md) | Document QA across categories | 900 problems | Deep researcher |

## Tested Configuration

All official benchmark results were produced with the following configuration. When reproducing results, use matching models and tool settings to obtain comparable numbers.

### Knowledge Retrieval (RAG)

**Benchmarks do not use a knowledge layer.** All benchmark configs are web-search-only. No RAG backend (LlamaIndex or Foundational RAG) is configured or required to run the benchmarks.

The [default runtime config](../../get-started/quick-start.md) (`config_web_default_llamaindex.yml`) uses the **LlamaIndex** backend (ChromaDB) for knowledge retrieval in interactive use — but this is not part of any benchmark evaluation.

### Models

All models are served through `https://integrate.api.nvidia.com/v1` (NVIDIA hosted NIM API).

| Role | Model |
|------|-------|
| Shallow research, intent classification | `nvidia/nemotron-3-nano-30b-a3b` |
| Deep research researcher | `nvidia/nemotron-3-super-120b-a12b` |
| Orchestrator, planner, clarifier | `openai/gpt-oss-120b` |
| Evaluation judge | `openai/gpt-4o` (via OpenAI API) |

### Tools

| Tool | Config |
|------|--------|
| Web search | Tavily (`max_results: 5`) |
| Advanced web search | Tavily advanced mode (`max_results: 2`) |
| Paper search | Google Scholar via Serper (Deep Research Bench only) |

```{note}
The NVIDIA hosted NIM API (`integrate.api.nvidia.com`) is a developer preview service. See [NVIDIA Hosted API Considerations](../../customization/swapping-models.md#nvidia-hosted-api-considerations) for known limitations and mitigation strategies.
```

```{toctree}
:titlesonly:

freshqa.md
deep-research-bench.md
deepsearch-qa.md
```

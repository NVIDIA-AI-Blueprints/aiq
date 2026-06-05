<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Example: Deep Research Skills and Sandbox

This example shows how to run AI-Q deep research with DeepAgents skills and a Modal-backed sandbox.

Skills let a research agent discover task-specific instructions only when they are relevant. A skill can teach the agent a repeatable workflow, such as extracting numeric facts, normalizing a table, running calculations, and producing reusable text artifacts. The sandbox gives the agent an isolated execution environment for code-based work, such as Python/pandas calculations, without running that code in the AI-Q process.

For more background, see the LangChain DeepAgents docs:

- [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview)
- [DeepAgents skills](https://docs.langchain.com/oss/python/deepagents/skills)

## What This Example Enables

The example config enables:

- built-in DeepAgents skills from `src/aiq_agent/agents/deep_researcher/skills/`
- a Modal sandbox for job-scoped Python execution
- Python packages useful for analysis, including `pandas`, `numpy`, `matplotlib`, and `pillow`
- virtual `/shared/` files for text artifacts that the orchestrator and subagents can read during the report workflow

The current built-in example skill is `data-table-analysis`. It is intended for quantitative research tasks where the agent must normalize researched facts and compute tabular outputs such as growth rates, rankings, summary statistics, CSV, JSON, or markdown tables.

**Models and report quality:** For clearer tables, stronger reasoning over numbers, and more reliable use of the data-table-analysis skill end-to-end, prefer **frontier-class models** for the orchestrator, planner, and researcher in your config ([Swapping models](../../customization/swapping-models.md)). Smaller or faster models may complete runs but often produce weaker structured outputs and more formatting mistakes in long reports.

## Prerequisites

Install and configure AI-Q as usual, then make sure these credentials are available to the process running AI-Q:

```bash
export NVIDIA_API_KEY="nvapi-..."              # pragma: allowlist secret
export TAVILY_API_KEY="tvly-..."               # pragma: allowlist secret
```

For sandbox execution, create a Modal account and configure Modal credentials. Modal uses a token ID and token secret:

```bash
export MODAL_TOKEN_ID="ak-..."                 # pragma: allowlist secret
export MODAL_TOKEN_SECRET="as-..."             # pragma: allowlist secret
```

You can also configure Modal locally with:

```bash
modal token set --token-id "$MODAL_TOKEN_ID" --token-secret "$MODAL_TOKEN_SECRET"
```

See Modal's token configuration docs for details: [modal.config](https://modal.com/docs/reference/modal.config).

## Configuration

Use `configs/config_skills.yml`. The relevant section is:

```yaml
functions:
  deep_research_agent:
    _type: deep_research_agent
    skills:
      enabled: true
      agent_sources:
        orchestrator:
          - /skills/
        planner-agent:
          - /skills/
        researcher:
          - /skills/
        writer-agent:
          - /skills/synthesis/
      sandbox_required_sources:
        - /skills/
    sandbox:
      provider: modal
      app_name: aiq-deep-research
      image: python:3.12-slim
      python_packages:
        - matplotlib
        - numpy
        - pandas
        - pillow
      block_network: true
```

When `skills.enabled` is true, AI-Q preloads the built-in skill files into the DeepAgents virtual filesystem and passes the configured per-agent skill sources directly to DeepAgents. When the sandbox block is present, DeepAgents `execute` calls run inside a job-scoped Modal sandbox.

## Run AI-Q

```bash
dotenv -f deploy/.env run .venv/bin/nat run \
  --config_file configs/config_skills.yml \
  --input "Compare the top 10 publicly traded semiconductor companies by 2024 revenue. Build a markdown table with revenue, YoY growth, market cap, and gross margin. Then rank them and compute summary statistics. Use the data analysis tool for all calculations."
```

For API or UI testing:

```bash
dotenv -f deploy/.env run .venv/bin/nat serve \
  --config_file configs/config_skills.yml \
  --host 0.0.0.0 \
  --port 8000
```

Then submit a deep research request through the AI-Q API or UI.

## Example Queries

Use queries that require researched numeric facts plus computed tabular analysis.

**Example prompt:**

```text
Compare the top 10 publicly traded semiconductor companies by 2024 revenue. Build a markdown table with revenue, YoY growth, market cap, and gross margin. Then rank them and compute summary statistics. Use the data analysis tool for all calculations.
```

Additional prompts that exercise the same pattern:

```text
Compare AI infrastructure capex for Microsoft, Google, Meta, and Amazon over the last 8 quarters. Include QoQ and YoY growth.
```

```text
Compare R&D spend across the top 10 semiconductor companies and compute R&D as a percent of revenue.
```

Expected behavior:

1. The planner identifies that a skill should be used for structured quantitative analysis.
2. Researchers gather source-grounded input figures.
3. During synthesis, the orchestrator reads the relevant `SKILL.md`.
4. The agent calls `execute` to run Python/pandas in the Modal sandbox.
5. The agent writes markdown, CSV, or JSON text artifacts to `/shared/...` with `write_file`.
6. The final report cites the original sources for input figures and labels computed columns as calculations.

## Skill Files

Built-in deep research skills live under:

```text
src/aiq_agent/agents/deep_researcher/skills/
```

Each skill should be a directory with a `SKILL.md` file:

```text
src/aiq_agent/agents/deep_researcher/skills/
`-- my-skill/
    `-- SKILL.md
```

At minimum, `SKILL.md` needs frontmatter with a stable `name` and a clear `description`:

```markdown
---
name: my-skill
description: >
  Use this skill when the research task requires a specific repeatable workflow.
  Include trigger phrases and expected outputs so the agent can decide when to
  read this skill.
---

# My Skill

## When to Use

Use this skill for ...

## Execution Flow

1. Gather the required inputs.
2. Use the appropriate tools.
3. Write reusable outputs to `/shared/...` when another agent or the final report needs them.
```

Skill descriptions matter because DeepAgents uses the frontmatter description to decide whether the skill applies before reading the full file. Keep descriptions specific, list representative trigger phrases, and explicitly name required tools such as `execute`, `read_file`, or `write_file` when the workflow depends on them.

## Adding More Skills

To add a built-in AI-Q deep research skill:

1. Create a new directory under `src/aiq_agent/agents/deep_researcher/skills/`.
2. Add a `SKILL.md` file with frontmatter and workflow instructions.
3. Put optional helper scripts, references, or templates inside the same skill directory.
4. Reference any helper files from `SKILL.md` so the agent knows when to read or run them.
5. Keep workflow instructions generic enough to handle variations of the task, but concrete enough to force required tool calls.
6. Run with `configs/config_skills.yml` and test a query that should trigger the new skill.

No config change is required for additional built-in skills in this directory when `skills.enabled: true` is set. AI-Q collects available skill directories at runtime and exposes them through the `/skills/` source.

## Notes and Limitations

- The Modal sandbox is used for code execution. Text artifacts that need to survive for the report should be written through DeepAgents filesystem tools to `/shared/...`.
- `/shared/` is a virtual DeepAgents filesystem path. Use `ls`, `read_file`, `write_file`, and `edit_file` for `/shared/`; do not inspect `/shared/` with shell commands through `execute`.
- The sandbox is configured with `block_network: true`, so research should happen through AI-Q search tools, not from sandbox code.
- For the first release, sandbox lifecycle cleanup, persistence policy, quotas, and production capacity controls are tracked as follow-up work.

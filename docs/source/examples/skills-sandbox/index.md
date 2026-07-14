<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Example: Deep Research Skills and Sandbox

This example shows how to run AI-Q deep research with DeepAgents skills and a provider-backed sandbox. The reference
profile uses Modal; AI-Q also includes an experimental OpenShell profile for a trusted, single-operator environment.

Skills let a research agent discover task-specific instructions only when they are relevant. A skill can teach the agent a repeatable workflow, such as extracting numeric facts, normalizing a table, running calculations, and producing reusable text artifacts. The sandbox runs code-based work outside the AI-Q process. Isolation depends on the provider: Modal creates a fresh sandbox for each job, while the experimental OpenShell profile attaches jobs to one pre-provisioned shared sandbox.

For more background, refer to the LangChain DeepAgents docs:

- [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview)
- [DeepAgents skills](https://docs.langchain.com/oss/python/deepagents/skills)

## What This Example Enables

The example config enables:

- built-in DeepAgents skills from `src/aiq_agent/agents/deep_researcher/skills/`
- a fresh per-job Modal sandbox for Python execution
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

Refer to Modal's token configuration docs for details: [modal.config](https://modal.com/docs/reference/modal.config).

## Configuration

Use `configs/config_domain_routing_and_skills.yml`. The relevant section is:

```yaml
functions:
  deep_research_skills:
    _type: deep_research_skills
    agents:
      researcher-agent:
        - research
      writer-agent:
        - synthesis
    require_sandbox:
      - research

  deep_research_sandbox:
    _type: deep_research_sandbox
    provider: modal
    app_name: aiq-deep-research
    image: python:3.13-slim
    packages:
      - matplotlib
      - numpy
      - pandas
      - pillow
    network: blocked

  deep_research_agent:
    _type: deep_research_agent
    enable_citation_verification: false
    skills: deep_research_skills
    sandbox: deep_research_sandbox
```

AI-Q validates the public skill collection names (`research`, `synthesis`) and resolves them to DeepAgents source paths internally. When skills are configured, AI-Q mounts the configured built-in skill collections into the DeepAgents virtual filesystem. When the sandbox ref is present, DeepAgents `execute` calls run in the configured provider. Modal creates a fresh sandbox named for the job.

To evaluate OpenShell instead, use `configs/config_openshell.yml` after running `scripts/setup_openshell.sh`. That profile
is experimental: it attaches every job to one named, pre-provisioned sandbox. Per-job working directories avoid ordinary
filename collisions but are not an access-control or multi-tenant isolation boundary. Do not run mutually untrusted jobs
concurrently in that profile.

## Run AI-Q

```bash
dotenv -f deploy/.env run .venv/bin/nat run \
  --config_file configs/config_domain_routing_and_skills.yml \
  --input "Compare the top 10 publicly traded semiconductor companies by 2024 revenue. Build a markdown table with revenue, YoY growth, market cap, and gross margin. Then rank them and compute summary statistics. Use the data analysis tool for all calculations."
```

For API or UI testing:

```bash
dotenv -f deploy/.env run .venv/bin/nat serve \
  --config_file configs/config_domain_routing_and_skills.yml \
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
3. A matching researcher or writer reads the relevant `SKILL.md`.
4. The agent calls `execute` to run Python/pandas in the configured sandbox provider.
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
6. Run with `configs/config_domain_routing_and_skills.yml` and test a query that should trigger the new skill.

No config change is required for additional built-in skills inside an enabled collection. AI-Q collects available skill directories at runtime and exposes them to DeepAgents through an internal `/skills/` source.

## Notes and Limitations

- The reference config uses a fresh Modal sandbox for code execution. The experimental OpenShell config uses one shared,
  pre-provisioned sandbox and is suitable only for trusted single-operator use, not multi-tenant isolation.
- Text artifacts that need to survive for the report should be written through DeepAgents filesystem tools to `/shared/...`.
- `/shared/` is a virtual DeepAgents filesystem path. Use `ls`, `read_file`, `write_file`, and `edit_file` for `/shared/`; do not inspect `/shared/` with shell commands through `execute`.
- The sandbox is configured with `network: blocked`, so research should happen through AI-Q search tools, not from sandbox code.
- Durable sandbox artifact capture is opt-in (`artifact_capture.enabled: true`) and also requires an artifact store.
  Successful `execute` calls checkpoint manifest-declared files, and success/failure terminal paths perform one final
  best-effort scan. A busy cancellation skips that scan and preserves earlier checkpoints. Adding a sandbox alone does
  not guarantee that every generated file is persisted or embedded in the report.

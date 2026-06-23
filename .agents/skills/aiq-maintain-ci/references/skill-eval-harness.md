<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Skill-eval harness

Authoritative sources: `.github/skill-eval/README.md` and
`.github/workflows/skills-eval.yml`.

## What it is

`.github/skill-eval/` is the product-level Agent Skill evaluation harness that
gates skill changes. It contains `skills_eval_agent.py`, `adapters/`,
`verifiers/`, and its own `README.md` / `AGENTS.md`.

## How it works

1. It finds Agent Skill product-eval specs under
   `skills/<skill>/evals/*-product.json`.
2. It validates each spec's required fields (for example `skills`,
   `resources.platforms`, `env`, and ordered `expects`).
3. It uses a matching adapter under `.github/skill-eval/adapters/<skill>/` to run
   Harbor trials, then a deterministic verifier checks the result against a reward
   threshold.

The first supported skill is `aiq-research`
(`skills/aiq-research/evals/*-product.json`).

## Changing the harness safely

- Keep the `detect-changes` path gate in `skills-eval.yml` working; do not switch
  it to a trigger `paths:` filter (the workflow comment explains why).
- Full Harbor runs require the self-hosted `aiq-eval` runner and credentials, so
  validate spec/adapter/verifier shape locally and rely on the mirrored CI run for
  the full sweep.
- When adding a skill to the harness, add its `*-product.json` spec and a matching
  adapter; mirror the existing `aiq-research` adapter.

## Validation

Defer to `.github/skill-eval/README.md` for running the harness. For local sanity,
confirm your `*-product.json` specs parse and follow the README's required fields,
and after editing the workflow run:

```bash
uv run pre-commit run --files .github/workflows/skills-eval.yml
```

Expected: the specs parse, and the workflow edit passes pre-commit (YAML check).
The full evaluation runs on the self-hosted runner via the mirrored CI.

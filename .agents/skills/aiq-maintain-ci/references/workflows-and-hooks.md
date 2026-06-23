<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Workflows and hooks

Authoritative sources: the workflow files under `.github/workflows/` and
`CONTRIBUTING.md` "CI and Bot Workflow".

## Workflows

- `ci.yml` ("AIQ CI") — jobs: `pre-commit` (runs the hook set), `test` (pytest
  with a coverage gate), `helm-lint` (deploy charts), `test-scripts`.
- `ui.yml` — frontend `lint`, `type-check`, unit tests, and `build` for
  `frontends/ui/`.
- `skills-eval.yml` ("Skills Eval") — runs on `push` and `workflow_dispatch`. A
  `detect-changes` job path-gates the run; the trigger deliberately does not use a
  `paths:` filter (see the comment in the file for why). Harbor trials run on the
  self-hosted `aiq-eval` runner.
- `request-nvskills-ci.yml` — comment-triggered NVSkills CI request.

## The copy-pr-bot mirror flow

Per `CONTRIBUTING.md`: pushing a branch does not run CI. A maintainer or vetter
comments `/ok to test`; copy-pr-bot mirrors the PR to a `pull-request/<N>` branch,
and CI runs there. `/nvskills-ci` requests NVSkills validation; `/merge` requests
bot-driven merge once repository rules pass. The mirror behavior is configured in
`.github/copy-pr-bot.yaml`.

## Pre-commit hooks

`.pre-commit-config.yaml` is the source of truth CI enforces. Current hooks
include: `ruff-check`, `ruff-format`, `uv-lock`, `check-merge-conflict`,
`check-added-large-files`, `check-yaml`, `end-of-file-fixer`, `trailing-whitespace`,
`detect-secrets`, `validate-skills`, `clear-notebook-output-cells`, `helm-lint`,
`pytest`, and `markdown-link-check`. Some hooks run a whole-project command
regardless of the files passed (for example `pytest`), so
`pre-commit run --files ...` can still be heavy.

## Validation

```bash
uv run pre-commit run --all-files
actionlint .github/workflows/<file>.yml   # if installed
```

Expected: hooks pass (or only auto-fix), and any edited workflow is valid YAML
that `actionlint` accepts.

---
name: aiq-maintain-ci
description: Use when changing AI-Q continuous integration, pre-commit, or contributor governance — editing .github/workflows/ (ci, ui, skills-eval, request-nvskills-ci), .pre-commit-config.yaml hooks, .github/CODEOWNERS, .coderabbit.yaml, copy-pr-bot, or the .github/skill-eval harness — and validating those changes without breaking the gate.
license: Apache-2.0
compatibility: Claude Code, Codex, Cursor, OpenCode, and Agent Skills-compatible tools.
metadata:
  version: "0.1.0"
  source-repo: "NVIDIA-AI-Blueprints/aiq"
  tags: "aiq ci github-actions pre-commit governance skill-eval"
allowed-tools: Read Bash Edit
---

# Maintain AI-Q CI and Governance

Use this skill when a developer changes AI-Q's CI, pre-commit hooks, or
contributor governance — the GitHub Actions workflows, the pre-commit config,
CODEOWNERS, the CodeRabbit review config, the copy-pr-bot mirror, or the
product-level skill-eval harness. These surfaces gate every PR, so a change must
keep the gate working and must not weaken security or review rules.

## Start Here

- Identify the surface: a workflow (`.github/workflows/`), a pre-commit hook
  (`.pre-commit-config.yaml`), governance (`.github/CODEOWNERS`,
  `.coderabbit.yaml`, `.github/copy-pr-bot.yaml`), or the skill-eval harness
  (`.github/skill-eval/`).
- Read the authoritative files below and `CONTRIBUTING.md` "CI and Bot Workflow"
  before editing — the bot/mirror flow is easy to break.
- Make the smallest change; do not weaken secret detection, auth gating, or
  code-owner review without a prior design discussion (see `AGENTS.md`).
- Remember CI runs on the copy-pr-bot mirror after `/ok to test`, not on push.

## Authoritative References

- [CONTRIBUTING.md](../../../CONTRIBUTING.md): "CI and Bot Workflow" — copy-pr-bot
  mirroring to `pull-request/<N>`, `/ok to test`, `/nvskills-ci`, `/merge`.
- [AGENTS.md](../../../AGENTS.md): "Git and PR hygiene" and the validation
  commands CI mirrors.
- `.github/workflows/ci.yml`: jobs `pre-commit`, `test` (pytest + coverage),
  `helm-lint`, `test-scripts`.
- `.github/workflows/ui.yml`: frontend lint / type-check / test / build.
- `.github/workflows/skills-eval.yml`: the Skills Eval gate (push +
  `workflow_dispatch`, a `detect-changes` path gate, Harbor trials on the
  self-hosted `aiq-eval` runner).
- `.github/workflows/request-nvskills-ci.yml`: comment-triggered NVSkills CI.
- `.pre-commit-config.yaml`: the hook set CI enforces (ruff, detect-secrets,
  `validate-skills`, markdown-link-check, pytest, helm-lint, …).
- `.github/CODEOWNERS`, `.coderabbit.yaml`, `.github/copy-pr-bot.yaml`: review
  routing, path-scoped automated review, and the PR mirror.

Longer procedures live in this bundle:

- [references/workflows-and-hooks.md](references/workflows-and-hooks.md): the
  workflows, their jobs/triggers, the copy-pr-bot mirror flow, and the pre-commit
  hook inventory.
- [references/skill-eval-harness.md](references/skill-eval-harness.md): how the
  `.github/skill-eval/` regression gate finds specs, runs adapters, and verifies.

## Workflow

1. Locate the exact workflow, hook, or governance file and read it plus the
   relevant `CONTRIBUTING.md` section.
2. Make the smallest scoped change; keep job names, triggers, and the
   `detect-changes` path gate intact unless that is the change.
3. Lint the change: validate YAML and, for workflows, run `actionlint` if it is
   installed.
4. Reproduce the affected gate locally where possible — run the pre-commit hooks
   or the job's underlying command (see the references).
5. Note that the real CI run happens on the copy-pr-bot mirror after a maintainer
   comments `/ok to test`.
6. Summarize changed files and the local validation evidence.

## Validation

```bash
uv run pre-commit run --all-files          # reproduce the pre-commit gate
uv run pre-commit run --files <changed>    # faster, during iteration
actionlint .github/workflows/<file>.yml    # if actionlint is installed
```

Expected: pre-commit passes (or only auto-fixes), and any edited workflow is
syntactically valid. For skill-eval changes, see the harness reference — full
Harbor runs need the self-hosted runner, so validate spec/adapter shape locally
and rely on the mirrored CI run for the full sweep.

## Common Mistakes

- Adding a trigger `paths:` filter to `skills-eval.yml` instead of using the
  `detect-changes` job — the comment in that workflow explains why path-filtering
  the trigger is wrong here.
- Weakening `detect-secrets`, auth gating, or code-owner review to make CI pass.
- Expecting CI to run on push; it runs on the copy-pr-bot mirror after
  `/ok to test`.
- Editing `.github/CODEOWNERS` without updating the paths it routes, so reviews
  go to the wrong owners.
- Forgetting that `helm-lint` and `pytest` are pre-commit hooks too, so a local
  `pre-commit run --all-files` can be heavier than expected.

## Related Skills

- `aiq-release-qa`
- `aiq-prepare-pr`
- `aiq-add-tool`

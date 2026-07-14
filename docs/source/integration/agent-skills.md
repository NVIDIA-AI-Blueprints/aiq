<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Agent Skills for Coding Harnesses

AI-Q includes portable Agent Skills for coding harnesses that support skill-style instructions and helper scripts.

## Two kinds of AI-Q skill

AI-Q ships two distinct skill sets, separated by audience. This page documents
the **API-consumer** skills. The maintainer skills are documented in their own
[README](https://github.com/NVIDIA-AI-Blueprints/aiq/blob/develop/.agents/skills/README.md).

| | API-consumer skills | Maintainer skills |
| :-- | :-- | :-- |
| **Audience** | Users calling a running AI-Q server | Developers changing the AI-Q repo |
| **Location** | top-level `skills/` | `.agents/skills/` |
| **Examples** | `aiq-deploy`, `aiq-research` | `aiq-add-data-source`, `aiq-add-tool`, `aiq-release-qa`, `aiq-prepare-pr`, `aiq-customize-prompts-models`, `aiq-maintain-ci` |
| **Assumes** | A reachable AI-Q backend | A repo checkout and dev toolchain |

The API-consumer skills are:

- `aiq-deploy` helps an assistant clone or locate AI-Q, choose an existing workflow config, deploy locally or in self-hosted environments, verify basic system health, optionally run deep research completion validation, troubleshoot, rebuild, and stop services.
- `aiq-research` lets an assistant call a running local or self-hosted AI-Q Blueprint server for routed `/chat` requests and async deep research job lifecycle operations.

The canonical packaged consumer skills live at:

```text
skills/aiq-deploy/
skills/aiq-research/
```

Each installed skill directory must contain `SKILL.md` at its root. The deploy skill keeps detailed guidance under `references/` so agents only load the path-specific material they need.

For harnesses that expect repository-local Agent Skills under `.agents/skills`,
this repository surfaces the consumer skills there with per-skill symlinks
(`.agents/skills/` itself is the maintainer skill home, not a symlink to
`skills/`):

```text
.agents/skills/aiq-deploy -> ../../skills/aiq-deploy
.agents/skills/aiq-research -> ../../skills/aiq-research
```

## Recommended Flow

Use the skills together rather than blending their responsibilities:

1. Use `aiq-research` for research-shaped requests such as "deep research", "AIQ research", "research", or "use AI-Q to answer". It checks `AIQ_SERVER_URL` first, then the default local backend.
2. If no backend is reachable, let `aiq-research` ask whether the user already has an AI-Q backend URL or wants `aiq-deploy` to start and validate a local Skill backend.
3. Use `aiq-deploy` directly for install/deploy/setup requests such as "install AIQ", "deploy AIQ", or "install deep research".
4. If the user asks which workflow config to use, let `aiq-deploy` read `references/configs.md` and choose an existing repository config before deployment.
5. Use `aiq-deploy` validation checks to confirm the backend and async-agent API are reachable. Confirm the UI only when that deployment mode intentionally starts it.
6. Hand the verified `AIQ_SERVER_URL` to `aiq-research`.
7. Use `aiq-research` for routed chat, async research, polling, report retrieval, streaming, and cancellation.
8. After deployment validation, ask whether the user wants to run optional deep research completion validation now or skip validation and try AI-Q themselves.
9. Use `aiq-deploy` deep research completion validation only when the user confirms, asks for release signoff, or wants proof that deep research can complete after deployment.

For local non-container use, the deploy skill should prefer the backend-only Agent Skill entry point:

```bash
./scripts/start_as_skill.sh --config_file configs/config_web_default_llamaindex.yml --port 8000
```

This starts the AI-Q API backend required by `aiq-research` without starting the browser UI.

## Report Follow-Up and Portable Outputs

The `aiq-research` helper exposes the completed-report and durable-artifact operations as
public commands:

```bash
python3 $SKILL_DIR/scripts/aiq.py report_edit <JOB_ID> "<EDIT_INSTRUCTIONS>"
python3 $SKILL_DIR/scripts/aiq.py report <JOB_ID> --out-dir ./my-report
python3 $SKILL_DIR/scripts/aiq.py artifacts <JOB_ID> --download-dir ./aiq-artifacts
```

`report_edit` submits a child job for a cosmetic rewrite and polls it to completion; the
parent report remains unchanged. `report --out-dir` writes `report.md` plus an `artifacts/`
directory, downloads the job's durable artifacts, and rewrites embedded `artifact://`
image references to local files. `artifacts --download-dir` downloads the artifacts into
the requested directory and prints their local paths; omit `--download-dir` to list the
artifact metadata without downloading bytes.

## Example Invocations

After the skills are installed, users can ask their coding harness for AI-Q actions in natural language. Research-shaped prompts route to `aiq-research`; install, deploy, run, stop, UI, CLI, Docker, Helm, and troubleshooting prompts route to `aiq-deploy`:

| User Prompt | Expected Route |
|---|---|
| "deep research on the Blackwell launch" | `aiq-research` checks `AIQ_SERVER_URL` or the default local Skill backend, then uses routed `/chat` and async polling as needed. |
| "AIQ research this topic" | `aiq-research` treats the request as research intent, not install intent. |
| "deploy AI-Q" | `aiq-deploy` asks which deployment mode the user wants, then validates the selected path and returns `AIQ_SERVER_URL`. |
| "install deep research" | `aiq-deploy` asks which AI-Q deployment mode the user wants before starting services. |
| "clone AIQ and run it" | `aiq-deploy` locates or clones `NVIDIA-AI-Blueprints/aiq`, checks required environment values, then starts the selected default deployment. |
| "start the AI-Q UI" | `aiq-deploy` starts a deployment mode that includes the browser UI, such as local E2E or full Docker Compose. |
| "run AI-Q with Docker Compose" | `aiq-deploy` follows the Docker Compose path. For Agent Skill backend use, it should start `aiq-agent` and dependencies without the frontend unless the user asks for UI. |
| "deploy AI-Q with Helm" | `aiq-deploy` follows the Kubernetes/Helm path and requires the user to provide or confirm cluster, namespace, registry, secret, ingress, and storage choices. |
| "which AI-Q config should I use?" | `aiq-deploy` reads `references/configs.md`, explains the existing configs, and selects a documented config path before deployment. |
| "check why AI-Q is unhealthy" | `aiq-deploy` runs health checks, inspects logs/status, and uses the troubleshooting reference for the active deployment mode. |
| "stop AI-Q" | `aiq-deploy` follows the shutdown path and asks before destructive cleanup such as deleting Docker volumes. |

## Prerequisites

- Python 3.10 or newer.
- For `aiq-deploy`: access to this repository or permission to clone `https://github.com/NVIDIA-AI-Blueprints/aiq`, plus the selected runtime such as Docker Compose, Node/npm for local web mode, or kubectl/Helm for Kubernetes mode.
- For `aiq-research`: a local or self-hosted AI-Q Blueprint server, usually at `http://localhost:8000`. Set `AIQ_SERVER_URL` only when using a different local or self-hosted server URL.

## Install From the NVIDIA Skills Catalog

The AI-Q repository is the source location for these skills. If you only want to use AI-Q as Agent Skills and do not need the full AI-Q source checkout, install the AI-Q skill set from the [NVIDIA Agent Skills catalog](https://github.com/NVIDIA/skills).

Install the AI-Q skills together so deployment and research handoffs are available in the same harness session.

Use the repo-local instructions below when developing AI-Q itself, validating changes before publication, or using a harness that does not support the catalog install path.

## Claude Code

Claude Code supports repo-local skills under `.claude/skills/`. This repository
keeps those paths as compatibility symlinks for both skill sets. The consumer
skills point into `skills/`; the maintainer skills point into `.agents/skills/`:

```text
.claude/skills/aiq-deploy -> ../../skills/aiq-deploy
.claude/skills/aiq-research -> ../../skills/aiq-research
.claude/skills/aiq-add-data-source -> ../../.agents/skills/aiq-add-data-source
.claude/skills/aiq-add-tool -> ../../.agents/skills/aiq-add-tool
.claude/skills/aiq-release-qa -> ../../.agents/skills/aiq-release-qa
.claude/skills/aiq-prepare-pr -> ../../.agents/skills/aiq-prepare-pr
.claude/skills/aiq-customize-prompts-models -> ../../.agents/skills/aiq-customize-prompts-models
.claude/skills/aiq-maintain-ci -> ../../.agents/skills/aiq-maintain-ci
```

To recreate the consumer-skill repo-local install manually:

```bash
mkdir -p .claude/skills
ln -s ../../skills/aiq-deploy .claude/skills/aiq-deploy
ln -s ../../skills/aiq-research .claude/skills/aiq-research
```

The maintainer-skill symlinks are managed alongside the maintainer skill set;
refer to the [maintainer skills README](https://github.com/NVIDIA-AI-Blueprints/aiq/blob/develop/.agents/skills/README.md) for how
those are added.

For a user-level install:

```bash
mkdir -p ~/.claude/skills
cp -R skills/aiq-deploy ~/.claude/skills/aiq-deploy
cp -R skills/aiq-research ~/.claude/skills/aiq-research
```

## Codex

For Codex or another Agent Skills-compatible tool, install the skill into the runtime's configured skills directory.

Generic install shape:

```text
<codex-skills-dir>/aiq-deploy/SKILL.md
<codex-skills-dir>/aiq-deploy/references/
<codex-skills-dir>/aiq-research/SKILL.md
<codex-skills-dir>/aiq-research/scripts/aiq.py
```

Example:

```bash
mkdir -p <codex-skills-dir>
cp -R skills/aiq-deploy <codex-skills-dir>/aiq-deploy
cp -R skills/aiq-research <codex-skills-dir>/aiq-research
```

Replace `<codex-skills-dir>` with the skills directory configured for your Codex environment.

## OpenCode

OpenCode loads user skills from `~/.config/opencode/skills/`.

Install with:

```bash
mkdir -p ~/.config/opencode/skills
cp -R skills/aiq-deploy ~/.config/opencode/skills/aiq-deploy
cp -R skills/aiq-research ~/.config/opencode/skills/aiq-research
```

Restart OpenCode or start a new session after installation.

## Verify Installation

From the parent directory containing the installed skills, run:

```bash
test -f aiq-deploy/SKILL.md
test -d aiq-deploy/references
python3 aiq-research/scripts/aiq.py
```

Expected `aiq-research/scripts/aiq.py` output starts with:

```text
Usage: aiq.py <command> [args]
```

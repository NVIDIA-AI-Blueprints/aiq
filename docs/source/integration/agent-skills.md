<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Agent Skills for Coding Harnesses

AI-Q includes a portable Agent Skill for coding harnesses that support skill-style instructions and helper scripts. The skill lets an assistant call a locally running AI-Q Blueprint server for routed `/chat` requests and async deep research job lifecycle operations.

The packaged skill lives at:

```text
.agents/skills/aiq-research/
```

The installed `aiq-research` directory must contain `SKILL.md` at its root. For package-local details, see `.agents/skills/aiq-research/README.md`.

## Prerequisites

- Python 3.10 or newer.
- A local AI-Q Blueprint server, usually at `http://localhost:8000`.
- Set `AIQ_SERVER_URL` only when using a different local server URL.

## Claude Code

Claude Code supports repo-local skills under `.claude/skills/`. This repository keeps that path as a compatibility symlink:

```text
.claude/skills/aiq-research -> ../../.agents/skills/aiq-research
```

To recreate the repo-local install manually:

```bash
mkdir -p .claude/skills
ln -s ../../.agents/skills/aiq-research .claude/skills/aiq-research
```

For a user-level install:

```bash
mkdir -p ~/.claude/skills
cp -R .agents/skills/aiq-research ~/.claude/skills/aiq-research
```

## Codex

For Codex or another Agent Skills-compatible tool, install the skill into the runtime's configured skills directory.

Generic install shape:

```text
<codex-skills-dir>/aiq-research/SKILL.md
<codex-skills-dir>/aiq-research/scripts/aiq.py
```

Example:

```bash
mkdir -p <codex-skills-dir>
cp -R .agents/skills/aiq-research <codex-skills-dir>/aiq-research
```

Replace `<codex-skills-dir>` with the skills directory configured for your Codex environment.


## OpenCode

OpenCode loads user skills from `~/.config/opencode/skills/`.

Install with:

```bash
mkdir -p ~/.config/opencode/skills
cp -R .agents/skills/aiq-research ~/.config/opencode/skills/aiq-research
```

Restart OpenCode or start a new session after installation.


## Verify Installation

From the installed skill directory, run:

```bash
python3 scripts/aiq.py
```

Expected output starts with:

```text
Usage: aiq.py <command> [args]
```

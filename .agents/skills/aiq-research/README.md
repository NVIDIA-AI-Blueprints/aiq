# AIQ Research Skill

Portable Agent Skill for interacting with a locally running NVIDIA AI-Q Blueprint server.

## What This Skill Provides

- Routed `/chat` requests against a local AI-Q server.
- Async deep research job submission and polling.
- Job status, event-store state, report retrieval, SSE streaming, and cancellation helpers.
- A self-contained Python helper script at `scripts/aiq.py`.

## Canonical Location

This repository keeps the distributable skill at:

```text
.agents/skills/aiq-research/
```

The Claude Code repo-local path is a compatibility symlink:

```text
.claude/skills/aiq-research -> ../../.agents/skills/aiq-research
```

## Prerequisites

- Python 3.10 or newer.
- A local AI-Q Blueprint server, usually at `http://localhost:8000`.
- Set `AIQ_SERVER_URL` only when using a different local server URL.

## Installing The Skill

This repository stores portable agent skills under:

```text
.agents/skills/
```

The AIQ research skill is available at:

```text
.agents/skills/aiq-research/
```

Install by copying or symlinking the full `aiq-research` directory into the skill location used by your coding harness. The installed directory must contain `SKILL.md` at its root.

### Claude Code

Claude Code supports repo-local skills under `.claude/skills/`.

For this repository, Claude Code compatibility is provided by a symlink:

```text
.claude/skills/aiq-research -> ../../.agents/skills/aiq-research
```

To recreate it manually:

```bash
mkdir -p .claude/skills
ln -s ../../.agents/skills/aiq-research .claude/skills/aiq-research
```

User-level install:

```bash
mkdir -p ~/.claude/skills
cp -R .agents/skills/aiq-research ~/.claude/skills/aiq-research
```

### OpenCode

OpenCode loads user skills from:

```text
~/.config/opencode/skills/
```

Install with:

```bash
mkdir -p ~/.config/opencode/skills
cp -R .agents/skills/aiq-research ~/.config/opencode/skills/aiq-research
```

Restart OpenCode or start a new session after installation.

### Codex

For Codex or other Agent Skills-compatible tools, install the skill into the runtime's configured skills directory.

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

## Quick Verification

From the installed skill directory, run:

```bash
python3 scripts/aiq.py
```

Expected output starts with:

```text
Usage: aiq.py <command> [args]
```

## License

Apache-2.0. See `LICENSE`.

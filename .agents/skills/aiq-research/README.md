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

## Install Targets

Copy or symlink the entire `.agents/skills/aiq-research/` directory into the skills directory used by your agent runtime.

### Claude Code

Repo-local install:

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

```bash
mkdir -p ~/.config/opencode/skills
cp -R .agents/skills/aiq-research ~/.config/opencode/skills/aiq-research
```

### Codex or other Agent Skills-compatible tools

Install into the skills directory configured for that runtime. The installed directory name should remain:

```text
aiq-research
```

The installed directory must contain `SKILL.md` at its root.

## Quick Verification

After installing and starting a local AI-Q server, run the helper script from the installed skill directory:

```bash
python3 scripts/aiq.py health
```

Expected: JSON health or service metadata from the local server.

## License

Apache-2.0. See `LICENSE`.

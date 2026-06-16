# AI-Q Skill Eval

This directory contains the initial AI-Q Agent Skill evaluation harness. It follows the same broad pattern as the VSS skill-eval work, but removes VSS-specific deployment profiles, video services, GPU assumptions, and Brev pool naming.

The first supported skill is `aiq-research`, with specs under:

```text
skills/aiq-research/evals/*-product.json
```

## What It Does

1. Finds Agent Skill product-eval specs under `skills/<skill>/evals/*-product.json`.
2. Validates each spec has `skills`, `resources.platforms`, `env`, and ordered `expects`.
3. Uses a matching adapter under `.github/skill-eval/adapters/<skill>/generate.py`.
4. Generates Harbor-style task datasets under `/tmp/aiq-skill-eval/datasets`.
5. Optionally runs Harbor against generated datasets when a live AI-Q server and agent credentials are available.

The initial `aiq-research` profile is a smoke test for a live AI-Q server:

- health check through `scripts/aiq.py health`
- async agent listing through `scripts/aiq.py agents`

It intentionally avoids model-generating `/chat` calls so the baseline eval can validate the skill wrapper without spending inference credits. Deeper research lifecycle specs should be added once the eval runner has stable API keys and runtime expectations.

## Spec Format

Each spec is JSON:

```json
{
  "skills": ["aiq-research"],
  "resources": {
    "platforms": {
      "local": {"modes": ["existing-server"]}
    }
  },
  "env": "Live environment notes",
  "expects": [
    {
      "query": "Instruction shown to the agent",
      "checks": [
        "trajectory_contains:scripts/aiq.py health",
        "shell:curl -sf \"${AIQ_SERVER_URL:-http://localhost:8000}/health\" >/dev/null"
      ]
    }
  ]
}
```

Supported deterministic check prefixes:

| Prefix | Behavior |
|---|---|
| `shell:` | Runs the shell command. Passes on exit code 0. |
| `json_command:` | Runs the shell command and requires stdout to parse as JSON. |
| `trajectory_contains:` | Searches Harbor agent logs for a substring. |
| `trajectory_not_contains:` | Passes only when the substring is absent from Harbor agent logs. |

## Generate Locally

From the AI-Q repository root:

```bash
python3 .github/skill-eval/skills_eval_agent.py --all \
  --output-dir /tmp/aiq-skill-eval/datasets
```

The generated dataset contains `instruction.md`, `task.toml`, `tests/test.sh`, verifier helpers, a copy of the skill under test, and `solution/solve.sh`.

## Run With Harbor

Harbor execution requires a runner where:

- `AIQ_SERVER_URL` points to a running AI-Q server.
- `uvx harbor` is available.
- Agent credentials are available for the selected Harbor agent.
- `AIQ_SKILL_EVAL_MAX_RETRIES` can tune Harbor retries and defaults to `1` to tolerate transient agent install failures.

Claude Code is the default agent and uses Anthropic-compatible credentials:

```bash
export AIQ_SERVER_URL=http://host.docker.internal:8000
export ANTHROPIC_BASE_URL=...
export ANTHROPIC_API_KEY=...
export ANTHROPIC_MODEL=...

python3 .github/skill-eval/skills_eval_agent.py --all --run-harbor
```

For local Docker Desktop runs, `host.docker.internal` lets the Harbor task container reach an AI-Q server running on the host. If AI-Q is running inside the same network as Harbor, use that reachable URL instead.

Codex is also supported. To use the local Codex login without printing or copying tokens into commands, opt into Harbor's `auth.json` upload path:

```bash
export AIQ_SERVER_URL=http://host.docker.internal:8000
export AIQ_SKILL_EVAL_AGENT=codex
export AIQ_SKILL_EVAL_MODEL=gpt-5.2
export CODEX_FORCE_AUTH_JSON=1

python3 .github/skill-eval/skills_eval_agent.py --all --run-harbor
```

If the server is not already running, use the `aiq-deploy` skill first. The generated tasks include both `aiq-research` and `aiq-deploy` under `/skills` when the deploy skill is present in this repository.

## CI

`.github/workflows/skills-eval.yml` validates spec and adapter generation when Agent Skill or skill-eval files change. Full Harbor execution is available through manual dispatch on a self-hosted runner once an AI-Q eval runner is provisioned.

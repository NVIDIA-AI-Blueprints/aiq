---
name: aiq-research
description: |
  Run research requests through a locally running NVIDIA AI-Q Blueprint server. Use when the user asks for deep
  research, AIQ research, research with AI-Q, or to use AI-Q on a question, unless they are asking to install,
  deploy, start, stop, or troubleshoot AI-Q infrastructure.
license: Apache-2.0
compatibility: |
  Designed for Claude Code, OpenCode, Codex, and Agent Skills-compatible tools. Requires Python 3.11+, network
  access to a running local or self-hosted AI-Q Blueprint server, and an AI-Q backend that exposes `/health`,
  `/chat`, and asynchronous job endpoints.
metadata:
  version: "2.1.0"
  author: "NVIDIA AI-Q Blueprint Team"
  github-url: "https://github.com/NVIDIA-AI-Blueprints/aiq"
  tags:
    - nvidia
    - aiq
    - blueprint
    - deep-research
    - research-agents
    - agent-skills
  languages:
    - python
    - bash
  domain: "research-agents"
allowed-tools: Read Bash
---

# AIQ Research Skill

## Purpose

Use this skill to call a locally running NVIDIA AI-Q Blueprint server through the helper script at
`scripts/aiq.py`.

Use this skill for research-shaped requests, including:

- "deep research on ..."
- "AIQ research ..."
- "research ..."
- "use AI-Q to answer ..."
- "ask AI-Q about ..."

Do not use this skill for install, deploy, start, stop, UI, CLI, Docker, Helm, or troubleshooting requests. Those
belong to `aiq-deploy`.

## Prerequisites

Users need:

- Python 3.11+ available as `python3`.
- A reachable local or self-hosted AI-Q Blueprint backend.
- `AIQ_SERVER_URL` set when the backend is not running at `http://localhost:8000`.
- A backend configured with authentication disabled for this public helper, or a separate authenticated AI-Q skill for
  authenticated environments.
- Network access from the local machine to the AI-Q backend URL.
- Credentials configured in the backend environment, not in this skill. This public helper does not collect or manage
  API keys.

The helper script has no third-party Python package dependencies; it uses Python standard-library HTTP modules.

## Instructions

1. Resolve the target backend URL.
2. Run `health` before sending research requests.
3. If no backend is reachable, ask for a backend URL or hand off to `aiq-deploy`.
4. Send the user's exact query through routed `/chat`.
5. Poll asynchronous deep research jobs when AI-Q returns a job ID.
6. Present returned reports with citations and source URLs intact.
7. Stop on failed jobs and show the returned error; do not retry automatically.

### Step 1 - Resolve the backend

Use `AIQ_SERVER_URL` when set. Otherwise try the default local backend:

```bash
python3 $SKILL_DIR/scripts/aiq.py health
```

Expected output: JSON from a reachable AI-Q health endpoint.

If `health` fails and no explicit `AIQ_SERVER_URL` was set, ask:

```text
I do not see a reachable local AI-Q backend. Do you already have an AI-Q backend URL you want to use, or should I deploy a local Skill backend?
```

- If the user provides a URL, set `AIQ_SERVER_URL` for subsequent helper calls and rerun `health`.
- If the user wants local deployment, hand off to `aiq-deploy` and preserve the original research request.
- If a reachable backend returns `401` or `403`, stop and explain that this public skill does not manage
  authentication. Ask the user to use an authenticated AI-Q skill or configure authentication for their environment.
- If `health` succeeds but `/chat` or `/v1/jobs/async/agents` fails, report that the backend is reachable but not
  compatible with this public research flow, then offer to run `aiq-deploy` validation.

### Step 2 - Send the routed research request

Run:

```bash
python3 $SKILL_DIR/scripts/aiq.py chat "<USER_QUESTION>"
```

Expected output:

- A normal JSON response for shallow or direct answers.
- Or structured JSON containing `{"status": "deep_research_running", "job_id": "<JOB_ID>"}` for asynchronous deep
  research.

If the response is normal JSON, present the result immediately. Do not force polling when there is no `job_id`.

### Step 3 - Poll asynchronous jobs

If the response includes `deep_research_running`, extract the `job_id` and poll with the same absolute script path:

```bash
python3 $SKILL_DIR/scripts/aiq.py research_poll <JOB_ID>
```

Expected output: the final report JSON when the job completes successfully.

Use the runtime's non-blocking or background execution mechanism when available. If the chosen execution method requires
escalated permissions, request explicit user approval first and explain why. Tell the user that deep research is running
in the background.

### Step 4 - Resume after interruptions

If polling is interrupted, the job continues server-side. Resume with:

```bash
python3 $SKILL_DIR/scripts/aiq.py status <JOB_ID>
python3 $SKILL_DIR/scripts/aiq.py report <JOB_ID>
python3 $SKILL_DIR/scripts/aiq.py research_poll <JOB_ID>
```

Use `status` to inspect job status and saved artifacts. Use `report` when the job has already finished and you only need
the final output. Use `research_poll` to keep waiting for completion.

### Step 5 - Present the report

When `research_poll` completes successfully, fetch and present the full report. Keep citations and source URLs intact.
If the job status is `failed`, `failure`, or `cancelled`, show the error from the status response and ask whether the
user wants to retry with a narrower query or different approach.

## Version Compatibility

**IMPORTANT:** This skill is designed for NVIDIA AI-Q Blueprint version 2.1.0.

Semantic Versioning Compatibility Rules:

```text
Skill version: X.Y.Z
Blueprint or endpoint version: A.B.C

Compatible IF:
1. A == X (Major versions MUST match)
2. B >= Y (Minor version must be equal or greater)
3. C can be anything (Patch version does not affect compatibility)
```

Examples:

- Skill version 2.1.0 is compatible with Blueprint version 2.1.0.
- Skill version 2.1.0 is compatible with Blueprint version 2.2.0.
- Skill version 2.1.0 is compatible with Blueprint version 2.1.5.
- Skill version 2.1.0 is not compatible with Blueprint version 3.0.0.
- Skill version 2.1.0 is not compatible with Blueprint version 2.0.0.

If your Blueprint version is not compatible:

1. Check for an updated skill version matching your Blueprint version.
2. Use a Blueprint version compatible with this skill.
3. Proceed with caution only when the user accepts the compatibility risk; API routes or response shapes may have
   changed.

## Available Script Commands

| Command | Purpose |
|---|---|
| `python3 scripts/aiq.py health` | Check whether the local server responds |
| `python3 scripts/aiq.py chat "<query>"` | POST `/chat`; may return inline output or a deep-research job ID |
| `python3 scripts/aiq.py agents` | List available async agent types |
| `python3 scripts/aiq.py submit "<query>" [agent_type]` | Submit an explicit async job |
| `python3 scripts/aiq.py research "<query>" [agent_type]` | Submit an async job, poll, and print the final report JSON |
| `python3 scripts/aiq.py research_poll <job_id>` | Resume polling an existing async job |
| `python3 scripts/aiq.py status <job_id>` | Fetch job status plus `/state` artifacts |
| `python3 scripts/aiq.py state <job_id>` | Fetch event-store artifacts only |
| `python3 scripts/aiq.py report <job_id>` | Fetch the final report for a completed job |
| `python3 scripts/aiq.py stream <job_id>` | Stream SSE events from a job |
| `python3 scripts/aiq.py cancel <job_id>` | Cancel a running job |

## Environment Variables

| Variable | Required | Default | Description |
|---|---:|---|---|
| `AIQ_SERVER_URL` | No | `http://localhost:8000` | Local or self-hosted AI-Q server base URL |

## Security Best Practices

- Do not put API keys, bearer tokens, cookies, or basic-auth credentials in `AIQ_SERVER_URL`.
- Store backend credentials in the AI-Q deployment environment, not in this skill or command examples.
- Treat returned reports as potentially sensitive if the backend uses private data sources.
- Do not truncate citations or source URLs from returned reports.

## Working Examples

### Example 1: Run a routed chat or research request

```bash
python3 $SKILL_DIR/scripts/aiq.py health
python3 $SKILL_DIR/scripts/aiq.py chat "Compare local AIQ deep research with a standard web search workflow"
```

Expected output:

```text
<health JSON from AI-Q>
<JSON chat response or {"status": "deep_research_running", "job_id": "<JOB_ID>"}>
```

If AI-Q returns a job ID, continue with `research_poll`.

### Example 2: Resume an existing job

```bash
python3 $SKILL_DIR/scripts/aiq.py status <JOB_ID>
python3 $SKILL_DIR/scripts/aiq.py research_poll <JOB_ID>
```

Replace `<JOB_ID>` with the UUID returned by AI-Q. Expected output: status JSON followed by the report JSON when the
job completes. If the job failed, show the returned status and do not retry automatically.

## References

| Topic | Documentation |
|---|---|
| Helper script | `scripts/aiq.py` |
| Deployment and backend validation | `../aiq-deploy/SKILL.md` |
| Skill metadata and examples | `README.md` |

## Common Issues

### Issue: No backend is reachable

**Symptoms:**

- `health` fails with connection refused.
- The default `http://localhost:8000` URL does not respond.

**Causes:**

- AI-Q is not running.
- AI-Q is running on a different host or port.
- A local firewall or network setting blocks the connection.

**Solutions:**

1. Ask whether the user has an existing AI-Q backend URL.
2. If they provide one, set it and rerun health:
   ```bash
   export AIQ_SERVER_URL="http://localhost:<PORT>"
   python3 $SKILL_DIR/scripts/aiq.py health
   ```
3. If they want a local backend, hand off to `aiq-deploy` and preserve the original research request.

### Issue: Backend requires authentication

**Symptoms:**

- Requests fail with HTTP 401 or HTTP 403.
- The backend is reachable but rejects `/chat` or async job calls.

**Causes:**

- The backend was deployed with authentication enabled.
- The public helper does not attach user tokens or cookies.

**Solutions:**

1. Stop and explain that this public skill does not manage authentication.
2. Ask the user to use an authenticated AI-Q skill or configure their backend for this public local workflow.
3. Rerun `health` and the original query only after the authentication boundary is resolved.

### Issue: Health succeeds but research routes fail

**Symptoms:**

- `health` returns successfully.
- `/chat`, `/v1/jobs/async/agents`, or polling commands fail.

**Causes:**

- The backend is not using an API-enabled AI-Q config.
- The async job registry is not available in the selected backend.
- The backend version is incompatible with this skill.

**Solutions:**

1. Run:
   ```bash
   python3 $SKILL_DIR/scripts/aiq.py agents
   ```
2. If agents are unavailable, report the compatibility failure and offer to run `aiq-deploy` validation.
3. Confirm the deployed Blueprint version is compatible with skill version 2.1.0.

### Issue: Job is interrupted or appears stuck

**Symptoms:**

- Local polling is interrupted.
- The job keeps showing `running`.
- Poll output shows `running`, but a report is returned or cancel says the job is already `success`.

**Causes:**

- Deep research is asynchronous and continues server-side.
- Local polling output can lag behind terminal server state.

**Solutions:**

1. Check current state:
   ```bash
   python3 $SKILL_DIR/scripts/aiq.py status <JOB_ID>
   ```
2. If `has_report: true` or `job_status.status: success`, fetch the report:
   ```bash
   python3 $SKILL_DIR/scripts/aiq.py report <JOB_ID>
   ```
3. If the job is still running, continue polling:
   ```bash
   python3 $SKILL_DIR/scripts/aiq.py research_poll <JOB_ID>
   ```

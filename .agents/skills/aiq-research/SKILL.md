---
name: aiq-research
description: Use when calling a locally running NVIDIA AI-Q Blueprint server for routed chat, async deep research jobs, status checks, reports, or event-store artifacts.
license: Apache-2.0
compatibility: Claude Code, OpenCode, Codex, and Agent Skills-compatible tools. Requires Python 3.10+ and access to a running local AI-Q Blueprint server.
metadata:
  version: "2.1.0"
  github-url: "https://github.com/NVIDIA-AI-Blueprints/aiq"
  tags: "nvidia aiq blueprint deep-research agent-skills"
  languages: "python bash"
  domain: "research-agents"
allowed-tools: Read Bash
---

# AIQ Research Skill

Use this skill to call a locally running AIQ Blueprint server through the helper script at `scripts/aiq.py`.

## Assumptions

- The AIQ server is running locally at `http://localhost:8000`.
- Override the base URL only for another local deployment by setting `AIQ_SERVER_URL`.

## Use Cases

- Submit a routed `/chat` request to the local AIQ server.
- Poll an async deep research job to completion.
- Fetch job status, final reports, or event-store artifacts.
- Cancel a local async job.

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

## Usage

### Research flow

Run:

```bash
python3 $SKILL_DIR/scripts/aiq.py chat "USER QUESTION"
```

- The `/chat` endpoint routes the request to the right AIQ path.
- For shallow queries it returns a normal JSON response inline.
- For deep research it returns structured JSON containing `{"status": "deep_research_running", "job_id": "..."}`.

If the response is normal JSON:
- Present the result immediately.
- Do not force polling when there is no `job_id`.

If the response includes `deep_research_running`:
- Extract the `job_id`.
- Launch polling with the same absolute script path:

```bash
python3 $SKILL_DIR/scripts/aiq.py research_poll <job_id>
```

- Use the runtime's non-blocking/background execution mechanism when available.
- If the chosen execution method requires escalated permissions, request explicit user approval first and explain why.
- Tell the user that deep research is running in the background.

## Workflow

1. Run `health` first if you are unsure whether the local AIQ server is running.
2. Run `chat "<query>"` by passing the user's exact query for routed chat/research.
3. If the response contains `{"status": "deep_research_running", "job_id": "..."}`, run `research_poll <job_id>`.
4. If polling is interrupted, resume with `status <job_id>`, `report <job_id>`, or `research_poll <job_id>`.
5. Present returned reports with citations intact. Do not truncate source URLs.

### Presenting the report

- When `research_poll` completes successfully, fetch and present the full report.
- Do not truncate citations or source URLs from the returned report.

### Handling interruptions and timeouts

If polling is interrupted, the job continues server-side. Resume with:

```bash
python3 $SKILL_DIR/scripts/aiq.py status <job_id>
python3 $SKILL_DIR/scripts/aiq.py report <job_id>
python3 $SKILL_DIR/scripts/aiq.py research_poll <job_id>
```

- Use `status` to inspect job status and saved artifacts.
- Use `report` when the job has already finished and you only need the final output.
- Use `research_poll` to keep waiting for completion.

### Checking job progress and state

Async jobs expose two useful progress views:

- `status <job_id>` returns top-level job status and also fetches `/state` artifacts.
- `state <job_id>` returns the event-store artifacts only, without refetching the outer status wrapper.

Run:

```bash
python3 $SKILL_DIR/scripts/aiq.py status <job_id>
python3 $SKILL_DIR/scripts/aiq.py state <job_id>
```

Treat the responses as follows:
- If `job_status.status` is `completed` or `success`, fetch or present the report.
- If status is `failed`, `failure`, or `cancelled`, show the error and do not silently retry.
- If status is still running, queued, or another non-terminal state, continue polling.

### Failure handling

If the job status is `failed` or `failure`:
- Show the user the error from the status response.
- Ask whether they want to retry with a narrower query or different approach.
- Do not retry automatically.

### Cancelling a job

```bash
python3 $SKILL_DIR/scripts/aiq.py cancel <job_id>
```

## Examples

```bash
python3 /skills/aiq/aiq-research/scripts/aiq.py health
python3 /skills/aiq/aiq-research/scripts/aiq.py chat "Compare local AIQ deep research with a standard web search workflow"
python3 /skills/aiq/aiq-research/scripts/aiq.py research_poll 12345678-1234-1234-1234-123456789abc
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---:|---|---|
| `AIQ_SERVER_URL` | No | `http://localhost:8000` | Local AIQ server base URL |

## Troubleshooting

| Error | Likely Cause | Action |
|---|---|---|
| Connection refused | Local server is not running | Start the AIQ API server locally |
| HTTP 401 or 403 | Local server rejected the request | Restart local server with `REQUIRE_AUTH=false` |
| Job remains running | Deep research is asynchronous | Continue with `research_poll <job_id>` |
| Job failed | Server-side workflow failed | Show the returned status/error; do not retry automatically |

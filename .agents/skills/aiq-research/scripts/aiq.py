#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Local AIQ Research API client.

This helper assumes a local AIQ server running with REQUIRE_AUTH=false.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_JOB_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_AGENT_TYPE_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,128}$")
_ALLOWED_METHODS = frozenset({"GET", "POST"})

DEFAULT_SERVER_URL = "http://localhost:8000"
AIQ_SERVER_URL = os.environ.get("AIQ_SERVER_URL", DEFAULT_SERVER_URL)
DEFAULT_AGENT_TYPE = "shallow_researcher"

DEFAULT_API_TIMEOUT_SECONDS = 120
DEFAULT_LONG_HTTP_TIMEOUT_SECONDS = 3600
JOB_POLL_INTERVAL_SECONDS = 15
STATUS_CHECK_MAX_ATTEMPTS = 3
POLL_MAX_CONSECUTIVE_ERRORS = 3

_DONE_JOB_STATES = frozenset({"completed", "success", "failed", "cancelled", "failure"})
_SUCCESS_JOB_STATES = frozenset({"completed", "success"})
_FAILED_JOB_STATES = frozenset({"failed", "failure", "cancelled"})
_STREAM_TERMINAL_EVENTS = frozenset({"complete", "error", "done"})


def _validate_base_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise RuntimeError("AIQ_SERVER_URL is empty")
    if len(raw) > 2048 or _CONTROL_CHAR_RE.search(raw):
        raise RuntimeError("AIQ_SERVER_URL is invalid")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RuntimeError("AIQ_SERVER_URL must be an http or https URL with a host")
    if parsed.username is not None or parsed.password is not None:
        raise RuntimeError("AIQ_SERVER_URL must not include user:password@")
    return raw.rstrip("/")


def _validate_api_path(path: str) -> None:
    if not path.startswith("/") or path.startswith("//"):
        raise RuntimeError("Invalid API path")
    if len(path) > 4096 or ".." in path or _CONTROL_CHAR_RE.search(path):
        raise RuntimeError("Invalid API path")


def _validate_job_id(job_id: str) -> str:
    value = job_id.strip()
    if not _JOB_UUID_RE.fullmatch(value):
        raise RuntimeError("job_id must be a UUID")
    return value


def _validate_agent_type(agent_type: str) -> str:
    value = agent_type.strip()
    if not _AGENT_TYPE_RE.fullmatch(value):
        raise RuntimeError("Invalid agent_type")
    return value


def _api_request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    timeout: int = DEFAULT_API_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    if method not in _ALLOWED_METHODS:
        raise RuntimeError(f"Unsupported HTTP method: {method!r}")
    _validate_api_path(path)

    url = f"{_validate_base_url(AIQ_SERVER_URL)}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}: {error_body[:1000]}", file=sys.stderr)
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        print(f"Connection failed for {url}: {exc.reason}", file=sys.stderr)
        raise RuntimeError(f"Connection failed: {exc.reason}") from exc

    if not payload:
        return {}
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON in API response: {payload[:1000]!r}", file=sys.stderr)
        raise RuntimeError(f"Invalid JSON in API response: {exc}") from exc


def _stream_request(path: str, *, timeout: int = DEFAULT_LONG_HTTP_TIMEOUT_SECONDS) -> Iterator[str]:
    _validate_api_path(path)
    url = f"{_validate_base_url(AIQ_SERVER_URL)}{path}"
    req = urllib.request.Request(url, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw_line in resp:
                yield raw_line.decode("utf-8", errors="replace").strip()
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}: {error_body[:1000]}", file=sys.stderr)
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        print(f"Connection failed for {url}: {exc.reason}", file=sys.stderr)
        raise RuntimeError(f"Connection failed: {exc.reason}") from exc


def health() -> dict[str, Any]:
    for path in ("/health", "/v1/health"):
        try:
            return _api_request("GET", path, timeout=10)
        except RuntimeError:
            continue
    return _api_request("GET", "/", timeout=10)


def list_agents() -> dict[str, Any]:
    return _api_request("GET", "/v1/jobs/async/agents")


def submit_job(query: str, agent_type: str = DEFAULT_AGENT_TYPE) -> dict[str, Any]:
    body = {"agent_type": _validate_agent_type(agent_type), "input": query}
    return _api_request("POST", "/v1/jobs/async/submit", body=body, timeout=DEFAULT_LONG_HTTP_TIMEOUT_SECONDS)


def get_job_status(job_id: str) -> dict[str, Any]:
    return _api_request("GET", f"/v1/jobs/async/job/{_validate_job_id(job_id)}")


def get_job_state(job_id: str) -> dict[str, Any]:
    return _api_request("GET", f"/v1/jobs/async/job/{_validate_job_id(job_id)}/state")


def get_report(job_id: str) -> dict[str, Any]:
    return _api_request("GET", f"/v1/jobs/async/job/{_validate_job_id(job_id)}/report")


def cancel_job(job_id: str) -> dict[str, Any]:
    return _api_request("POST", f"/v1/jobs/async/job/{_validate_job_id(job_id)}/cancel")


def stream_job(job_id: str) -> None:
    for line in _stream_request(f"/v1/jobs/async/job/{_validate_job_id(job_id)}/stream"):
        if line.startswith("data:"):
            data = line[5:].strip()
            if data:
                print(data, flush=True)
        elif line.startswith("event:") and line[6:].strip() in _STREAM_TERMINAL_EVENTS:
            break


def chat_request(query: str) -> dict[str, Any]:
    body = {"messages": [{"role": "user", "content": query}]}
    print(f"Sending request to: {_validate_base_url(AIQ_SERVER_URL)}/chat", file=sys.stderr)
    return _api_request("POST", "/chat", body=body, timeout=DEFAULT_LONG_HTTP_TIMEOUT_SECONDS)


def poll_until_complete(
    job_id: str,
    *,
    timeout: int = DEFAULT_LONG_HTTP_TIMEOUT_SECONDS,
    max_consecutive_errors: int = POLL_MAX_CONSECUTIVE_ERRORS,
) -> dict[str, Any]:
    deadline = time.time() + timeout
    consecutive_errors = 0
    while time.time() < deadline:
        try:
            status = get_job_status(job_id)
            consecutive_errors = 0
        except RuntimeError as exc:
            consecutive_errors += 1
            if consecutive_errors >= max_consecutive_errors:
                print(f"  Status check failed {consecutive_errors} times in a row: {exc}", file=sys.stderr)
                raise
            print(
                f"  Status check failed ({exc}), retrying... ({consecutive_errors}/{max_consecutive_errors})",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(JOB_POLL_INTERVAL_SECONDS)
            continue

        state = status.get("status", "UNKNOWN").lower()
        if state in _DONE_JOB_STATES:
            return status
        print(f"  Status: {state}", file=sys.stderr, flush=True)
        time.sleep(JOB_POLL_INTERVAL_SECONDS)

    print("  Timed out waiting for job.", file=sys.stderr)
    return {"status": "TIMEOUT"}


def _poll_until_success_or_exit(job_id: str) -> None:
    try:
        final = poll_until_complete(job_id)
    except KeyboardInterrupt:
        print(f"\nInterrupted. Job {job_id} is still running server-side.", file=sys.stderr)
        print(f"Resume later: aiq.py research_poll {job_id}", file=sys.stderr)
        sys.exit(1)

    if final.get("status", "").lower() not in _SUCCESS_JOB_STATES:
        print(f"Job did not complete: {final.get('status')}", file=sys.stderr)
        print(json.dumps(final, indent=2))
        sys.exit(1)

    print(json.dumps(get_report(job_id), indent=2))


def _print_usage() -> None:
    print("Usage: aiq.py <command> [args]")
    print()
    print("Commands:")
    print("  health                        Check the local AIQ server")
    print("  chat <query>                  POST /chat, returns routed response")
    print("  agents                        List available async agent types")
    print("  submit <query> [agent_type]   Submit an async job")
    print("  status <job_id>               Job status plus /state artifacts")
    print("  state <job_id>                Event-store artifacts for one async job")
    print("  stream <job_id>               Stream SSE events from an async job")
    print("  report <job_id>               Get final report from an async job")
    print("  research <query> [agent_type] Submit async job, poll, and return report")
    print("  research_poll <job_id>        Resume polling an existing async job")
    print("  cancel <job_id>               Cancel a running async job")
    print()
    print(f"Environment: AIQ_SERVER_URL defaults to {DEFAULT_SERVER_URL}")


def main() -> None:
    if len(sys.argv) < 2:
        _print_usage()
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "health":
        print(json.dumps(health(), indent=2))

    elif cmd == "chat":
        if len(sys.argv) < 3:
            print("Usage: aiq.py chat <query>", file=sys.stderr)
            sys.exit(1)
        result = chat_request(sys.argv[2])

        content = ""
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            pass

        match = re.search(r"Job ID:\s*([0-9a-f-]{36})", content, re.IGNORECASE)
        if match:
            print(json.dumps({"status": "deep_research_running", "job_id": match.group(1)}))
        else:
            print(json.dumps(result, indent=2))

    elif cmd == "agents":
        print(json.dumps(list_agents(), indent=2))

    elif cmd == "submit":
        if len(sys.argv) < 3:
            print("Usage: aiq.py submit <query> [agent_type]", file=sys.stderr)
            sys.exit(1)
        agent_type = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_AGENT_TYPE
        print(json.dumps(submit_job(sys.argv[2], agent_type=agent_type), indent=2))

    elif cmd == "status":
        if len(sys.argv) < 3:
            print("Usage: aiq.py status <job_id>", file=sys.stderr)
            sys.exit(1)
        job_id = sys.argv[2]
        job_status = get_job_status(job_id)
        try:
            job_state = get_job_state(job_id)
        except RuntimeError as exc:
            job_state = {"_fetch_error": str(exc)}
        print(json.dumps({"job_status": job_status, "job_state": job_state}, indent=2))

    elif cmd == "state":
        if len(sys.argv) < 3:
            print("Usage: aiq.py state <job_id>", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(get_job_state(sys.argv[2]), indent=2))

    elif cmd == "stream":
        if len(sys.argv) < 3:
            print("Usage: aiq.py stream <job_id>", file=sys.stderr)
            sys.exit(1)
        stream_job(sys.argv[2])

    elif cmd == "report":
        if len(sys.argv) < 3:
            print("Usage: aiq.py report <job_id>", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(get_report(sys.argv[2]), indent=2))

    elif cmd == "research":
        if len(sys.argv) < 3:
            print("Usage: aiq.py research <query> [agent_type]", file=sys.stderr)
            sys.exit(1)
        agent_type = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_AGENT_TYPE
        print(f"Submitting {agent_type} job...", file=sys.stderr)
        result = submit_job(sys.argv[2], agent_type=agent_type)
        job_id = result.get("job_id")
        if not job_id:
            print(f"ERROR: No job_id in response: {result}", file=sys.stderr)
            sys.exit(1)
        print(f"Job submitted: {job_id}", file=sys.stderr)
        _poll_until_success_or_exit(job_id)

    elif cmd == "research_poll":
        if len(sys.argv) < 3:
            print("Usage: aiq.py research_poll <job_id>", file=sys.stderr)
            sys.exit(1)
        job_id = sys.argv[2]
        state = "UNKNOWN"
        status: dict[str, Any] = {}
        for attempt in range(1, STATUS_CHECK_MAX_ATTEMPTS + 1):
            try:
                status = get_job_status(job_id)
                state = status.get("status", "UNKNOWN").lower()
                break
            except RuntimeError as exc:
                if attempt == STATUS_CHECK_MAX_ATTEMPTS:
                    print(f"Status check failed after {STATUS_CHECK_MAX_ATTEMPTS} attempts: {exc}", file=sys.stderr)
                    sys.exit(1)
                print(
                    f"Status check failed ({exc}), retrying in {JOB_POLL_INTERVAL_SECONDS}s... "
                    f"({attempt}/{STATUS_CHECK_MAX_ATTEMPTS})",
                    file=sys.stderr,
                )
                time.sleep(JOB_POLL_INTERVAL_SECONDS)

        print(f"Current status: {state}", file=sys.stderr)
        if state in _SUCCESS_JOB_STATES:
            print(json.dumps(get_report(job_id), indent=2))
        elif state in _FAILED_JOB_STATES:
            print(f"Job {job_id} ended with status: {state}", file=sys.stderr)
            print(json.dumps(status, indent=2))
            sys.exit(1)
        else:
            print("Job still running, polling...", file=sys.stderr)
            _poll_until_success_or_exit(job_id)

    elif cmd == "cancel":
        if len(sys.argv) < 3:
            print("Usage: aiq.py cancel <job_id>", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(cancel_job(sys.argv[2]), indent=2))

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        _print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()

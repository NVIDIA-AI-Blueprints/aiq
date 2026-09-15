"""Create a fresh AI-Q collection and wait for a workbook upload to finish."""

from __future__ import annotations

import asyncio
import mimetypes
import re
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import httpx

from .agent_api import APIOptions
from .agent_api import _retry_after
from .agent_api import build_agent_request
from .agent_api import redact


async def upload_file(
    client: httpx.AsyncClient,
    path: Path,
    options: APIOptions,
    *,
    timeout: float = 1800,
) -> dict:
    """Upload once per evaluation run. This setup time is separate from answer latency."""
    collection = f"eval_{uuid4().hex}"
    headers, _ = build_agent_request("", replace(options, collection=collection))
    headers = httpx.Headers(headers)
    headers["Accept"] = "application/json"
    headers.pop("Content-Type", None)
    headers.pop("Content-Length", None)
    endpoint = httpx.URL(options.endpoint)
    suffix = "/v1/chat/completions"
    prefix = endpoint.path[: -len(suffix)] if endpoint.path.endswith(suffix) else ""

    async def request(method: str, route: str, **kwargs) -> dict:
        url = endpoint.copy_with(path=prefix + route, query=None, fragment=None)
        for attempt in range(options.retries + 1):
            retry_after = None
            try:
                response = await client.request(method, url, headers=headers, **kwargs)
                if 200 <= response.status_code < 300:
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ValueError("Upload API returned an invalid JSON response.")
                    return payload
                error = f"Upload setup HTTP {response.status_code}: {response.text}"
                retryable = response.status_code in {408, 429} or response.status_code >= 500
                retry_after = _retry_after(response.headers.get("Retry-After"), options.max_retry_delay)
            except httpx.TransportError as exc:
                error, retryable = f"Upload setup transport error: {type(exc).__name__}", True
            # Retrying a submission with a lost response can upload the workbook twice.
            # Only status GETs are retried; keep the original ingestion job.
            if method != "GET" or not retryable or attempt == options.retries:
                raise ValueError(redact(error, options))
            delay = (
                retry_after
                if retry_after is not None
                else min(options.max_retry_delay, options.retry_delay * 2**attempt)
            )
            await asyncio.sleep(delay)
        raise AssertionError("Unreachable retry state")

    started = time.perf_counter()
    try:
        async with asyncio.timeout(timeout):
            created = await request("POST", "/v1/collections", json={"name": collection})
            if created.get("name") != collection:
                raise ValueError("Upload API did not create the requested collection.")
            with path.open("rb") as workbook:
                submitted = await request(
                    "POST",
                    f"/v1/collections/{collection}/documents",
                    files={
                        "files": (path.name, workbook, mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                    },
                )
            job_id = submitted.get("job_id")
            if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
                raise ValueError("Upload API returned an invalid ingestion job ID.")
            while True:
                progress = await request("GET", f"/v1/documents/{job_id}/status")
                if progress.get("job_id") != job_id or progress.get("collection_name") != collection:
                    raise ValueError("Upload API returned status for a different ingestion job or collection.")
                state = progress.get("status")
                details = progress.get("file_details", [])
                if state == "failed" or progress.get("error_message"):
                    raise ValueError("Workbook ingestion failed; evaluation was not started.")
                if state == "completed":
                    if (
                        progress.get("total_files") != 1
                        or progress.get("processed_files") != 1
                        or not isinstance(details, list)
                        or len(details) != 1
                        or not isinstance(details[0], dict)
                        or details[0].get("status") != "success"
                    ):
                        raise ValueError(
                            "Workbook ingestion finished without a successful file; evaluation was not started."
                        )
                    return {
                        "file": str(path),
                        "collection_name": collection,
                        "latency_ms": (time.perf_counter() - started) * 1000,
                    }
                if state not in {"pending", "processing"}:
                    raise ValueError("Upload API returned an unrecognized ingestion status.")
                await asyncio.sleep(options.poll_interval)
    except TimeoutError as exc:
        raise ValueError("Workbook upload/ingestion timed out; evaluation was not started.") from exc

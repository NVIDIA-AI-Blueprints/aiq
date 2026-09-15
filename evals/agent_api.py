"""HTTP adapter, complete-final-answer streaming, and timed retry handling."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from .reports import ReportJob


@dataclass
class APIOptions:
    endpoint: str
    api_key: str = field(default="", repr=False)
    model: str = ""
    timeout: float = 300
    stream: bool = False
    retries: int = 2
    retry_delay: float = 1
    max_retry_delay: float = 30
    collection: str = ""
    extra_body: dict[str, Any] = field(default_factory=dict)
    extra_headers: dict[str, str] = field(default_factory=dict, repr=False)
    system_prompt: str = ""
    poll_interval: float = 2
    follow_report_jobs: bool = True


class ResponseError(ValueError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def redact(message: str, options: APIOptions) -> str:
    secrets = [
        options.api_key,
        *[
            value
            for key, value in options.extra_headers.items()
            if any(word in key.casefold() for word in ("auth", "key", "token", "cookie"))
        ],
    ]
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return message[:1000]


# ===================== AGENT API ADAPTATION POINTS =====================
# Change these functions for a different endpoint contract. Ground truth is
# deliberately NOT available to build_agent_request: only the question is sent.
def build_agent_request(question: str, options: APIOptions) -> tuple[dict[str, str], dict[str, Any]]:
    """Default: OpenAI-compatible /v1/chat/completions, including AI-Q/NAT."""
    headers = {"Accept": "text/event-stream" if options.stream else "application/json"}
    if options.api_key:
        headers["Authorization"] = f"Bearer {options.api_key}"
    if options.collection:
        headers["conversation-id"] = options.collection
    headers.update(options.extra_headers)
    messages = [{"role": "system", "content": options.system_prompt}] if options.system_prompt else []
    messages.append({"role": "user", "content": question})
    body = {**options.extra_body, "messages": messages, "stream": options.stream}
    if options.model:
        body["model"] = options.model
    return headers, body


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") in {"text", "output_text"}
            and isinstance(block.get("text"), str)
        )
    return ""


def _check_error(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ResponseError("Expected a JSON object containing the final answer.")
    if payload.get("error"):
        raise ResponseError(f"Agent error: {json.dumps(payload['error'], ensure_ascii=False)}")
    outcome = payload.get("workflow_outcome")
    if isinstance(outcome, dict) and outcome.get("status") == "failed":
        raise ResponseError(f"Agent workflow failed: {outcome.get('error') or 'No final answer available.'}")
    if payload.get("code") and payload.get("message") and not payload.get("choices"):
        raise ResponseError(f"Agent error: {payload['message']}")


def _check_finish(reason: str | None) -> None:
    if reason and reason != "stop":
        raise ResponseError(f"Final answer incomplete: finish_reason={reason}.")


def extract_final_answer(payload: dict[str, Any]) -> str:
    """Adapt here for regular JSON responses. Never scrape reasoning/tool output."""
    _check_error(payload)
    if payload.get("choices"):
        choice = next((item for item in payload["choices"] if item.get("index", 0) == 0), None)
        if choice is None:
            raise ResponseError("Response has no primary answer choice.")
        _check_finish(choice.get("finish_reason"))
        message = choice.get("message", {})
        if message.get("role", "assistant") != "assistant" or message.get("channel", "final") != "final":
            raise ResponseError("Response is not a final assistant message.")
        answer = _text(message.get("content"))
    elif payload.get("type") == "job_escalation":
        answer = json.dumps(payload)
    else:
        # Explicit final fields only. A job ID, tool result, or generic event is not an answer.
        answer = _text(payload.get("final_answer", payload.get("answer")))
    if not answer.strip():
        raise ResponseError("No final answer found. Adapt extract_final_answer for this API contract.")
    return answer


@dataclass
class AnswerStream:
    """Adapt consume() for another streaming contract; preserve terminal validation."""

    parts: list[str] = field(default_factory=list)
    done: bool = False

    def consume(self, data: str, event: str = "") -> None:
        # Internal events may contain arbitrary text, and are not completion markers.
        if event and event not in {"message", "final", "final_answer", "job_escalation", "error"}:
            return
        if event == "error":
            raise ResponseError(f"Agent stream error: {data}")
        if data.strip() == "[DONE]":
            self.done = True
            return
        payload = json.loads(data)
        _check_error(payload)
        if payload.get("choices"):
            choice = next((item for item in payload["choices"] if item.get("index", 0) == 0), None)
            if choice is None:
                return
            delta = choice.get("delta", {})
            if delta.get("role", "assistant") != "assistant" or delta.get("channel", "final") != "final":
                return
            # reasoning_content, tool_calls, and NAT intermediate_data are excluded.
            self.parts.append(_text(delta.get("content")))
            _check_finish(choice.get("finish_reason"))
            self.done = choice.get("finish_reason") == "stop"
        elif (
            "final_answer" in payload
            or (event in {"final", "final_answer"} and "answer" in payload)
            or payload.get("type") == "job_escalation"
        ):
            self.parts = [extract_final_answer(payload)]
            self.done = True

    def answer(self) -> str:
        answer = "".join(self.parts)
        if not self.done:
            raise ResponseError("Stream ended without a final-answer completion marker.", retryable=True)
        if not answer.strip():
            raise ResponseError("Stream completed without a final answer.")
        return answer


# =================== END AGENT API ADAPTATION POINTS ===================


async def read_stream(response: httpx.Response) -> str:
    stream = AnswerStream()
    data: list[str] = []
    event = ""
    async for line in response.aiter_lines():
        if line == "":
            if data:
                stream.consume("\n".join(data), event)
                if stream.done:
                    return stream.answer()
            data, event = [], ""
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("{"):
            # NAT may send its terminal error object without an SSE data: prefix.
            _check_error(json.loads(line))
        # Ignore comments, IDs, retry hints, and NAT intermediate_data: fields.
    if data:
        stream.consume("\n".join(data), event)
    return stream.answer()


def _retry_after(value: str | None, maximum: float) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0, min(seconds, maximum))


async def request_answer(client: httpx.AsyncClient, question: str, options: APIOptions) -> dict[str, Any]:
    headers, body = build_agent_request(question, options)
    report_headers = httpx.Headers(headers)
    report_headers["Accept"] = "application/json"
    attempts = []
    answer = ""
    job: ReportJob | None = None
    total_start = time.perf_counter()
    for index in range(options.retries + 1):
        status = None
        error = ""
        retryable = False
        retry_after = None
        stage = job.stage if job else "chat"
        start = time.perf_counter()
        try:
            # One attempt includes chat, report polling and the full final report body.
            async with asyncio.timeout(options.timeout):
                while True:
                    stage = job.stage if job else "chat"
                    status = None
                    method = "GET" if job else "POST"
                    url = job.url(options.endpoint) if job else options.endpoint
                    async with client.stream(
                        method, url, headers=report_headers if job else headers, json=None if job else body
                    ) as response:
                        status = response.status_code
                        if not 200 <= status < 300:
                            retry_after = _retry_after(response.headers.get("Retry-After"), options.max_retry_delay)
                            retryable = status in {408, 429} or status >= 500
                            await response.aread()
                            raise ResponseError(f"HTTP {status}: {response.text}", retryable=retryable)
                        if job:
                            await response.aread()
                            answer = job.consume(response.json()) or ""
                        else:
                            if response.headers.get("content-type", "").split(";")[0].strip() == "text/event-stream":
                                answer = await read_stream(response)
                            else:
                                await response.aread()
                                answer = extract_final_answer(response.json())
                            job = ReportJob.from_answer(answer)
                            if job:
                                answer = ""  # The handoff is control data, not an answer to score.
                                if not options.follow_report_jobs:
                                    raise ResponseError(
                                        "Unexpected report job in an API response requiring a direct answer."
                                    )
                        if answer:
                            end = time.perf_counter()  # Full chat/report text received; excludes scoring and cleanup.
                            break
                    if stage == "report_status" and job and not job.succeeded:
                        await asyncio.sleep(options.poll_interval)
        except (TimeoutError, httpx.TimeoutException):
            end = time.perf_counter()
            error, retryable = "Request timed out before the complete final answer was received.", True
        except httpx.TransportError as exc:
            end = time.perf_counter()
            error, retryable = f"Transport error: {type(exc).__name__}", True
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
            end = time.perf_counter()
            message = str(exc).replace(job.job_id, "[REPORT_JOB]") if job else str(exc)
            error = redact(message, options)
            retryable = isinstance(exc, ResponseError) and exc.retryable
        attempts.append(
            {
                "attempt": index + 1,
                "latency_ms": (end - start) * 1000,
                "http_status": status,
                "error": error,
                "stage": stage,
            }
        )
        if not error or not retryable or index == options.retries:
            break
        # Once a handoff was received, keep the same job/stage across retries. Never resubmit a known job.
        answer = ""
        delay = retry_after if retry_after is not None else min(options.max_retry_delay, options.retry_delay * 2**index)
        await asyncio.sleep(delay)
    total_latency = (end - total_start) * 1000
    return {
        "agent_answer": answer if not error else "",
        "answer_source": "report" if job else "chat",
        "http_status": status,
        "error": error,
        "latency_ms": total_latency,
        "first_attempt_latency_ms": attempts[0]["latency_ms"],
        "final_attempt_latency_ms": attempts[-1]["latency_ms"],
        "total_latency_ms": total_latency,
        "attempt_count": len(attempts),
        "attempts": attempts,
    }

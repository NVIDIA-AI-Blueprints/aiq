# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Evaluate filesystem RAG datasets against a deployed AI-Q shallow researcher.

For each dataset root (``corpus/`` + ``train.json``):

1. Optionally ingest documents into a knowledge-layer collection.
2. Run shallow-research inference via async jobs (default) or ATIF workflow.
3. Score outputs with RAGAS NVIDIA metrics and report token usage / e2e latency.

Data sources (``knowledge_layer``, ``web_search``, or both) are resolved from the
server agent config unless overridden with ``--data-sources``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from threading import Lock
from typing import Any

import pandas as pd
import PyPDF2
import requests
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from pydantic import BaseModel
from pydantic import Field
from ragas import EvaluationDataset
from ragas import SingleTurnSample
from ragas import evaluate
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import AnswerAccuracy
from ragas.metrics import ContextRelevance
from ragas.metrics import ResponseGroundedness
from tqdm import tqdm

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

CORPUS_DIRECTORY = "corpus"
EVAL_DATA = "train.json"
DEFAULT_SERVER_URL = "http://localhost:8000"
DEFAULT_BATCH_SIZE = 20
DEFAULT_TIMEOUT = 1800
WORKFLOW_CONNECT_TIMEOUT = 30
DEFAULT_INGESTION_TIMEOUT = 3600
DEFAULT_MAX_WORKERS = 1
INGESTION_TIMEOUT_PER_FILE = 180
INGESTION_STATUS_LOG_INTERVAL_SECONDS = 30
DEFAULT_AGENT_TYPE = "shallow_researcher"
WORKFLOW_ATIF_PATH = "/v1/workflow/atif"
DEFAULT_INFERENCE_MODE = "async"
JOB_POLL_INTERVAL_SECONDS = 5
_DONE_JOB_STATES = frozenset({"success", "completed", "failure", "failed", "cancelled", "interrupted"})
_SUCCESS_JOB_STATES = frozenset({"success", "completed"})
INGESTION_POLL_INTERVAL_SECONDS = 2

NV_METRIC_NV_ACCURACY = "nv_accuracy"
NV_METRIC_NV_CONTEXT_RELEVANCE = "nv_context_relevance"
NV_METRIC_NV_RESPONSE_GROUNDEDNESS = "nv_response_groundedness"

_DEFAULT_JUDGE_MODEL = "nvidia/meta/llama-3.3-70b-instruct"
_DEFAULT_JUDGE_BASE_URL = "https://inference-api.nvidia.com/v1"
_JUDGE_MODEL_ENV = "RAG_EVAL_JUDGE_MODEL"
_JUDGE_BASE_URL_ENV = "RAG_EVAL_JUDGE_BASE_URL"
_INFERENCE_HUB_API_KEY_ENV = "INFERENCE_HUB_API_KEY"
_judge_raw = (os.environ.get(_JUDGE_MODEL_ENV) or "").strip()
JUDGE_MODEL = _judge_raw if _judge_raw else _DEFAULT_JUDGE_MODEL
_judge_base_url_raw = (os.environ.get(_JUDGE_BASE_URL_ENV) or "").strip()
JUDGE_BASE_URL = _judge_base_url_raw if _judge_base_url_raw else _DEFAULT_JUDGE_BASE_URL

_KNOWLEDGE_TOOL_NAMES = frozenset({"knowledge_search", "knowledge_retrieval"})
_KNOWLEDGE_LAYER_SOURCE = "knowledge_layer"
_WEB_SEARCH_SOURCE = "web_search"
_RESULT_BLOCK_RE = re.compile(r"--- Result \d+ ---")


class IngestionMetrics(BaseModel):
    ingestion_time: float = Field(default=0.0)
    total_pages: int = Field(default=0)
    pages_per_second: float = Field(default=0.0)
    total_files: int = Field(default=0)


class EvaluationMetrics(BaseModel):
    nv_accuracy: float = Field(default=0.0, description="RAGAS Answer Accuracy")
    nv_context_relevance: float = Field(default=0.0, description="RAGAS Context Relevance")
    nv_response_groundedness: float = Field(default=0.0, description="RAGAS Response Groundedness")


class QueryTokenUsage(BaseModel):
    """Token usage for a single inference call."""

    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    cached_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    llm_calls: int = Field(default=0)


class TokenUsageMetrics(BaseModel):
    """Aggregated token usage across evaluated queries."""

    total_tokens: int = Field(default=0)
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    cached_tokens: int = Field(default=0)
    llm_calls: int = Field(default=0)
    sample_count: int = Field(default=0)
    mean_prompt_tokens: float = Field(default=0.0)
    mean_completion_tokens: float = Field(default=0.0)
    mean_total_tokens: float = Field(default=0.0)
    mean_llm_calls: float = Field(default=0.0)


class RagEvaluationMetrics(BaseModel):
    ingestion_metrics_list: list[IngestionMetrics] = Field(default_factory=list)
    evaluation_metrics: EvaluationMetrics = Field(default_factory=EvaluationMetrics)
    token_usage: TokenUsageMetrics = Field(default_factory=TokenUsageMetrics)


def _normalize_reference_contexts(contexts: Any) -> list[str]:
    if not contexts:
        return []
    normalized: list[str] = []
    if isinstance(contexts, list):
        for item in contexts:
            if isinstance(item, str) and item.strip():
                normalized.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("text") or item.get("filename") or ""
                if str(text).strip():
                    normalized.append(str(text).strip())
    elif isinstance(contexts, str) and contexts.strip():
        normalized.append(contexts.strip())
    return normalized


def _judge_api_key() -> str:
    for env_name in (_INFERENCE_HUB_API_KEY_ENV, "NVIDIA_API_KEY"):
        value = (os.environ.get(env_name) or "").strip()
        if value:
            return value
    return ""


def build_judge_llm() -> ChatNVIDIA:
    api_key = _judge_api_key()
    if not api_key:
        raise ValueError(
            f"{_INFERENCE_HUB_API_KEY_ENV} or NVIDIA_API_KEY must be set for RAGAS evaluation."
        )
    return ChatNVIDIA(
        model=JUDGE_MODEL,
        base_url=JUDGE_BASE_URL,
        api_key=api_key,
    )


def parse_knowledge_tool_contexts(output: str | None) -> list[str]:
    """Extract chunk text from knowledge retrieval tool output."""
    if not output:
        return []

    contexts: list[str] = []
    blocks = _RESULT_BLOCK_RE.split(output)
    for block in blocks[1:]:
        lines = block.strip().splitlines()
        body_start = 0
        for index, line in enumerate(lines):
            if line.startswith("Relevance Score:"):
                body_start = index + 1
                break
        while body_start < len(lines) and not lines[body_start].strip():
            body_start += 1
        body = "\n".join(lines[body_start:]).strip()
        if body.endswith("... [truncated]"):
            body = body[: -len("... [truncated]")].strip()
        if body:
            contexts.append(body)
    return contexts


def extract_generated_contexts(artifacts: dict[str, Any] | None) -> list[str]:
    if not artifacts:
        return []

    contexts: list[str] = []
    for tool in artifacts.get("tools", []):
        name = str(tool.get("name", ""))
        if name not in _KNOWLEDGE_TOOL_NAMES and "knowledge" not in name.lower():
            continue
        output = tool.get("output")
        if isinstance(output, str):
            contexts.extend(parse_knowledge_tool_contexts(output))
    return contexts


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def extract_token_usage_from_atif(
    steps: list[dict[str, Any]],
    trajectory: dict[str, Any] | None,
) -> QueryTokenUsage:
    """Aggregate token usage from ATIF step metrics and final trajectory summary."""
    final_metrics = (trajectory or {}).get("final_metrics") or {}
    if final_metrics:
        prompt = _coerce_int(final_metrics.get("total_prompt_tokens"))
        completion = _coerce_int(final_metrics.get("total_completion_tokens"))
        cached = _coerce_int(final_metrics.get("total_cached_tokens"))
        llm_calls = _coerce_int(final_metrics.get("total_steps"))
        if prompt or completion or cached:
            return QueryTokenUsage(
                prompt_tokens=prompt,
                completion_tokens=completion,
                cached_tokens=cached,
                total_tokens=prompt + completion,
                llm_calls=llm_calls or sum(1 for step in steps if step.get("metrics")),
            )

    prompt = completion = cached = 0
    llm_calls = 0
    for step in steps:
        metrics = step.get("metrics")
        if not isinstance(metrics, dict):
            continue
        step_prompt = _coerce_int(metrics.get("prompt_tokens"))
        step_completion = _coerce_int(metrics.get("completion_tokens"))
        step_cached = _coerce_int(metrics.get("cached_tokens"))
        if not (step_prompt or step_completion or step_cached):
            continue
        prompt += step_prompt
        completion += step_completion
        cached += step_cached
        llm_calls += 1

    return QueryTokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        cached_tokens=cached,
        total_tokens=prompt + completion,
        llm_calls=llm_calls,
    )


def extract_contexts_from_atif_steps(steps: list[dict[str, Any]]) -> list[str]:
    """Extract knowledge retrieval contexts from ATIF tool observation payloads."""
    contexts: list[str] = []
    for step in steps:
        tool_calls = step.get("tool_calls") or []
        if not any(str(call.get("function_name", "")) in _KNOWLEDGE_TOOL_NAMES for call in tool_calls):
            continue
        observation = step.get("observation")
        if not isinstance(observation, dict):
            continue
        results = observation.get("results") or []
        for result in results:
            if not isinstance(result, dict):
                continue
            content = result.get("content")
            if isinstance(content, str) and content.strip():
                contexts.extend(parse_knowledge_tool_contexts(content))
    return contexts


def _is_tool_call_message(message: str) -> bool:
    stripped = message.strip()
    return stripped.startswith("Tool calls:") or stripped.startswith("\n\nTool calls:")


def extract_answer_from_atif(steps: list[dict[str, Any]], final_payload: Any) -> str:
    """Pick the final agent answer from ATIF steps or the workflow payload."""
    for step in reversed(steps):
        if step.get("source") != "agent":
            continue
        message = str(step.get("message") or "").strip()
        if message and not _is_tool_call_message(message):
            return message

    if isinstance(final_payload, dict):
        for key in ("output", "content", "message", "value"):
            value = final_payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        choices = final_payload.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0]
            if isinstance(choice, dict):
                message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        return content.strip()

    if isinstance(final_payload, str) and final_payload.strip():
        return final_payload.strip()

    return ""


def parse_atif_sse_response(response_text: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None, Any]:
    """Parse an ATIF SSE response into steps, optional trajectory summary, and final payload."""
    steps: list[dict[str, Any]] = []
    trajectory: dict[str, Any] | None = None
    final_payload: Any = None

    for raw_line in response_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload_text = line[len("data:") :].strip()
        if not payload_text or payload_text == "[DONE]":
            continue

        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            continue

        if not isinstance(payload, dict):
            final_payload = payload
            continue

        if payload.get("code") == "workflow_error":
            message = payload.get("message") or payload.get("details") or "workflow error"
            raise RuntimeError(str(message))

        if "schema_version" in payload and "session_id" in payload:
            trajectory = payload
            continue

        if "step_id" in payload and "source" in payload:
            steps.append(payload)
            continue

        if "detail" in payload:
            detail = payload["detail"]
            if isinstance(detail, list) and detail:
                message = detail[0].get("msg", detail)
            else:
                message = detail
            raise RuntimeError(f"Invalid workflow request: {message}")

        final_payload = payload.get("payload", payload)

    return steps, trajectory, final_payload


def _parse_sse_events(response_text: str) -> list[dict[str, Any]]:
    """Parse AI-Q job SSE streams where event type is on the ``event:`` line, not in JSON."""
    events: list[dict[str, Any]] = []
    current_event_type: str | None = None
    for raw_line in response_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("event:"):
            current_event_type = line[len("event:") :].strip()
            continue
        if not line.startswith("data:"):
            continue
        payload_text = line[len("data:") :].strip()
        if not payload_text:
            continue
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if "type" not in payload and current_event_type:
            payload = {**payload, "type": current_event_type}
        events.append(payload)
        current_event_type = None
    return events


def extract_token_usage_from_job_events(events: list[dict[str, Any]]) -> QueryTokenUsage:
    prompt = completion = cached = 0
    llm_calls = 0
    for event in events:
        if event.get("type") != "llm.end":
            continue
        usage = (event.get("metadata") or {}).get("usage") or {}
        if not isinstance(usage, dict):
            continue
        step_prompt = _coerce_int(
            usage.get("prompt_tokens") or usage.get("input_tokens") or usage.get("total_input_tokens")
        )
        step_completion = _coerce_int(
            usage.get("completion_tokens") or usage.get("output_tokens") or usage.get("total_output_tokens")
        )
        step_cached = _coerce_int(usage.get("cached_tokens"))
        total_tokens = _coerce_int(usage.get("total_tokens"))
        if not (step_prompt or step_completion or step_cached or total_tokens):
            continue
        if not step_prompt and not step_completion and total_tokens:
            step_prompt = total_tokens
        prompt += step_prompt
        completion += step_completion
        cached += step_cached
        llm_calls += 1
    return QueryTokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        cached_tokens=cached,
        total_tokens=prompt + completion,
        llm_calls=llm_calls,
    )


class AIQClient:
    """Ingest corpus files and run shallow-research jobs against an AI-Q server."""

    def __init__(
        self,
        *,
        server_url: str,
        collection_name: str,
        max_workers: int,
        result_dir: str,
        skip_ingestion: bool,
        force_ingestion: bool,
        dataset_root: str,
        run_label: str,
        file_type: str,
        timeout: int,
        ingestion_timeout: int,
        agent_type: str,
        batch_size: int,
        inference_mode: str,
        data_sources: list[str] | None = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.collection_name = collection_name
        self.max_workers = max_workers
        self.result_dir = result_dir
        self.skip_ingestion = skip_ingestion
        self.force_ingestion = force_ingestion
        self.dataset_root = os.path.abspath(dataset_root)
        self.dataset_path = os.path.join(self.dataset_root, CORPUS_DIRECTORY)
        self.eval_data_path = os.path.join(self.dataset_root, EVAL_DATA)
        self.run_label = run_label
        self.file_type = file_type
        self.timeout = timeout
        self.ingestion_timeout = ingestion_timeout
        self.agent_type = agent_type
        self.batch_size = batch_size
        self.inference_mode = inference_mode
        self._requested_data_sources = data_sources
        self.data_sources: list[str] = []
        self.error_count = 0
        self.error_lock = Lock()
        self.e2e_latency_summary: dict[str, Any] | None = None
        self.rag_evaluation_metrics = RagEvaluationMetrics()

        print(f" - Dataset path: {self.dataset_path}")
        print(f" - Evaluation data path: {self.eval_data_path}")

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        files: list[tuple[str, tuple[str, Any, str]]] | None = None,
        timeout: int | None = None,
    ) -> requests.Response:
        url = f"{self.server_url}{path}"
        response = requests.request(
            method,
            url,
            json=json_body,
            files=files,
            timeout=timeout or self.timeout,
        )
        response.raise_for_status()
        return response

    def check_health(self) -> None:
        for path in ("/health", "/v1/health", "/"):
            try:
                response = requests.get(f"{self.server_url}{path}", timeout=30)
                if response.ok:
                    return
            except requests.RequestException:
                continue
        raise RuntimeError(f"AI-Q server is not reachable at {self.server_url}")

    def check_knowledge_api(self) -> None:
        try:
            self._request("GET", "/v1/knowledge/health", timeout=30)
        except requests.RequestException as exc:
            raise RuntimeError(
                "Knowledge API is unavailable. Start AI-Q with a config that enables "
                "knowledge_retrieval (e.g. configs/config_shallow_frag_web.yml)."
            ) from exc

    def list_registered_data_sources(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/v1/data_sources", timeout=30)
        payload = response.json()
        if isinstance(payload, list):
            return payload
        return []

    def _fetch_agent_data_sources_from_server(self) -> list[str]:
        url = f"{self.server_url}/v1/jobs/async/agents/{self.agent_type}/data_sources"
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Failed to resolve data sources for agent '{self.agent_type}' from {url}. "
                "Restart the AI-Q server on a build that exposes agent data-source discovery."
            ) from exc

        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError(f"Unexpected agent data sources response: {payload}")

        resolved = [str(item["id"]) for item in payload if isinstance(item, dict) and item.get("id")]
        if not resolved:
            raise RuntimeError(
                f"Agent '{self.agent_type}' has no data sources configured. "
                "Check the server YAML config for shallow_research_agent tools."
            )
        return resolved

    def resolve_agent_data_sources(self) -> list[str]:
        """Resolve data sources available to the configured agent on the server."""
        agent_sources = self._fetch_agent_data_sources_from_server()

        if self._requested_data_sources is not None:
            requested = [source for source in self._requested_data_sources if source]
            if not requested:
                raise RuntimeError("--data-sources was provided but empty.")
            registered_ids = {str(item.get("id", "")) for item in self.list_registered_data_sources()}
            unknown = [source for source in requested if source not in registered_ids]
            if unknown:
                raise RuntimeError(
                    f"Unknown data source(s): {', '.join(unknown)}. "
                    f"Registered: {sorted(registered_ids)}"
                )
            unavailable = [source for source in requested if source not in agent_sources]
            if unavailable:
                raise RuntimeError(
                    f"Data source(s) not available for agent '{self.agent_type}': {', '.join(unavailable)}. "
                    f"Agent supports: {agent_sources}"
                )
            return requested

        return agent_sources

    def list_collections(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/v1/collections")
        payload = response.json()
        if isinstance(payload, list):
            return payload
        return []

    def collection_exists(self) -> bool:
        return any(item.get("name") == self.collection_name for item in self.list_collections())

    def create_collection(self) -> None:
        body = {
            "name": self.collection_name,
            "description": f"RAG eval collection for {self.run_label}",
            "metadata": {},
        }
        self._request("POST", "/v1/collections", json_body=body)

    def delete_collection(self) -> None:
        self._request("DELETE", f"/v1/collections/{self.collection_name}")

    def list_ingested_documents(self) -> list[str]:
        response = self._request("GET", f"/v1/collections/{self.collection_name}/documents")
        payload = response.json()
        if not isinstance(payload, list):
            return []
        return [str(item.get("file_name", "")) for item in payload if item.get("file_name")]

    def get_number_of_pages_pdf(self, file_paths: list[str]) -> int:
        if "pdf" not in self.file_type:
            return 0
        total_pages = 0
        for file_path in file_paths:
            if not file_path.endswith(".pdf"):
                continue
            try:
                with open(file_path, "rb") as handle:
                    reader = PyPDF2.PdfReader(handle)
                    total_pages += len(reader.pages)
            except Exception as exc:
                print(f" - Error reading PDF pages for {file_path}: {exc}")
        return total_pages

    def _batch_ingestion_timeout(self, file_count: int) -> int:
        scaled = file_count * INGESTION_TIMEOUT_PER_FILE
        return min(self.ingestion_timeout, max(DEFAULT_TIMEOUT, scaled))

    def poll_ingestion_job(self, job_id: str, *, timeout: int | None = None) -> bool:
        poll_timeout = timeout or self.ingestion_timeout
        deadline = time.time() + poll_timeout
        start = time.time()
        last_status_log = 0.0
        status = "pending"
        while time.time() < deadline:
            response = self._request("GET", f"/v1/documents/{job_id}/status", timeout=60)
            status_payload = response.json()
            status = str(status_payload.get("status", "")).lower()
            if status == "completed":
                return True
            if status == "failed":
                error_message = status_payload.get("error_message", "unknown error")
                raise RuntimeError(f"Ingestion job {job_id} failed: {error_message}")
            now = time.time()
            if now - last_status_log >= INGESTION_STATUS_LOG_INTERVAL_SECONDS:
                elapsed = int(now - start)
                print(f"   - Ingestion job {job_id}: status={status} ({elapsed}s / {poll_timeout}s)")
                last_status_log = now
            time.sleep(INGESTION_POLL_INTERVAL_SECONDS)
        raise TimeoutError(f"Ingestion job {job_id} timed out after {poll_timeout}s (last status: {status})")

    def upload_batch(self, file_paths: list[str]) -> None:
        batch_timeout = self._batch_ingestion_timeout(len(file_paths))
        print(f"   - Waiting up to {batch_timeout}s for {len(file_paths)} file(s) to ingest")
        files = []
        handles = []
        try:
            for file_path in file_paths:
                handle = open(file_path, "rb")
                handles.append(handle)
                files.append(("files", (os.path.basename(file_path), handle, "application/octet-stream")))

            start = time.time()
            response = self._request(
                "POST",
                f"/v1/collections/{self.collection_name}/documents",
                files=files,
                timeout=batch_timeout,
            )
            payload = response.json()
            job_id = payload.get("job_id")
            if not job_id:
                raise RuntimeError(f"No ingestion job_id returned: {payload}")
            self.poll_ingestion_job(str(job_id), timeout=batch_timeout)
            elapsed = time.time() - start
            page_count = self.get_number_of_pages_pdf(file_paths)
            pages_per_second = page_count / elapsed if elapsed > 0 and page_count else 0.0
            self.rag_evaluation_metrics.ingestion_metrics_list.append(
                IngestionMetrics(
                    ingestion_time=elapsed,
                    total_pages=page_count,
                    pages_per_second=pages_per_second,
                    total_files=len(file_paths),
                )
            )
        finally:
            for handle in handles:
                handle.close()

    def collect_files_to_upload(self, ingested_documents: list[str]) -> list[str]:
        ingested = {os.path.basename(name) for name in ingested_documents}
        files_to_upload: list[str] = []
        for root, _, files in os.walk(self.dataset_path):
            for filename in files:
                if filename not in ingested:
                    files_to_upload.append(os.path.join(root, filename))
        return files_to_upload

    def _corpus_file_count(self) -> int:
        if not os.path.isdir(self.dataset_path):
            return 0
        return sum(len(files) for _, _, files in os.walk(self.dataset_path))

    def upload_documents(self, files_to_upload: list[str]) -> None:
        total_files = len(files_to_upload)
        if total_files == 0:
            return

        total_batches = (total_files + self.batch_size - 1) // self.batch_size
        for index in range(0, total_files, self.batch_size):
            batch = files_to_upload[index : index + self.batch_size]
            batch_num = index // self.batch_size + 1
            print(f"\n=== Uploading batch {batch_num} of {total_batches} to {self.collection_name} ===")
            try:
                self.upload_batch(batch)
                print(f"✅ Uploaded batch {batch_num} ({len(batch)} file(s))")
            except Exception as exc:
                print(f"❌ Failed batch {batch_num}: {exc}")
                raise

    def validate_ingestion(self) -> None:
        ingested = self.list_ingested_documents()
        corpus_files = self._corpus_file_count()
        print(f" - Corpus directory: {corpus_files} file(s) under {self.dataset_path}")
        print(f" - Ingestion check: {len(ingested)} document(s) in collection {self.collection_name}")

    def _workflow_request_timeout(self) -> tuple[int, int | None]:
        """Connect quickly; allow long gaps between ATIF SSE chunks during LLM/tool calls."""
        if self.timeout <= 0:
            return (WORKFLOW_CONNECT_TIMEOUT, None)
        return (WORKFLOW_CONNECT_TIMEOUT, self.timeout)

    def run_workflow_atif(self, query: str) -> tuple[str, list[str], QueryTokenUsage, list[dict[str, Any]]]:
        body: dict[str, Any] = {"query": query}
        headers = {"conversation-id": self.collection_name}
        url = f"{self.server_url}{WORKFLOW_ATIF_PATH}"
        try:
            response = requests.post(
                url,
                json=body,
                headers=headers,
                timeout=self._workflow_request_timeout(),
            )
        except requests.ReadTimeout as exc:
            raise TimeoutError(
                f"Workflow ATIF request timed out after {self.timeout}s waiting for server data "
                f"(increase --timeout or retry; complex queries with multiple tool calls can be slow)"
            ) from exc
        if not response.ok:
            detail = response.text.strip()
            raise RuntimeError(f"Workflow ATIF request failed ({response.status_code}): {detail}")

        response_text = response.text

        steps, trajectory, final_payload = parse_atif_sse_response(response_text)
        answer = extract_answer_from_atif(steps, final_payload)
        if not answer:
            raise RuntimeError("Workflow ATIF response did not include a final agent answer")

        contexts = extract_contexts_from_atif_steps(steps)
        token_usage = extract_token_usage_from_atif(steps, trajectory)
        return answer, contexts, token_usage, steps

    def submit_research_job(self, query: str) -> str:
        body: dict[str, Any] = {
            "agent_type": self.agent_type,
            "input": query,
            "collection_name": self.collection_name,
            "data_sources": self.data_sources,
        }
        response = self._request("POST", "/v1/jobs/async/submit", json_body=body, timeout=60)
        payload = response.json()
        job_id = payload.get("job_id")
        if not job_id:
            raise RuntimeError(f"No job_id in submit response: {payload}")
        return str(job_id)

    def poll_research_job(self, job_id: str) -> dict[str, Any]:
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            response = self._request("GET", f"/v1/jobs/async/job/{job_id}", timeout=60)
            status_payload = response.json()
            status = str(status_payload.get("status", "")).lower()
            if status in _DONE_JOB_STATES:
                return status_payload
            time.sleep(JOB_POLL_INTERVAL_SECONDS)
        raise TimeoutError(f"Research job {job_id} timed out after {self.timeout}s")

    def get_job_report(self, job_id: str) -> str:
        response = self._request("GET", f"/v1/jobs/async/job/{job_id}/report", timeout=60)
        payload = response.json()
        report = payload.get("report")
        if isinstance(report, str):
            return report
        if report is not None:
            return str(report)
        return ""

    def get_job_artifacts(self, job_id: str) -> dict[str, Any] | None:
        response = self._request("GET", f"/v1/jobs/async/job/{job_id}/state", timeout=60)
        payload = response.json()
        artifacts = payload.get("artifacts")
        return artifacts if isinstance(artifacts, dict) else None

    def collect_job_events(self, job_id: str) -> list[dict[str, Any]]:
        url = f"{self.server_url}/v1/jobs/async/job/{job_id}/stream"
        try:
            response = requests.get(url, timeout=self._workflow_request_timeout(), stream=True)
        except requests.ReadTimeout as exc:
            raise TimeoutError(f"Timed out collecting job events for {job_id}") from exc
        response.raise_for_status()
        chunks: list[str] = []
        for chunk in response.iter_content(decode_unicode=True, chunk_size=None):
            if chunk:
                chunks.append(chunk)
        return _parse_sse_events("".join(chunks))

    def run_async_research_job(self, query: str) -> tuple[str, list[str], QueryTokenUsage, dict[str, Any] | None]:
        job_id = self.submit_research_job(query)
        status_payload = self.poll_research_job(job_id)
        status = str(status_payload.get("status", "")).lower()
        if status not in _SUCCESS_JOB_STATES:
            error = status_payload.get("error") or status_payload.get("message") or status
            raise RuntimeError(f"Research job {job_id} ended with status {status}: {error}")

        events = self.collect_job_events(job_id)
        answer = self.get_job_report(job_id)
        artifacts = self.get_job_artifacts(job_id)
        contexts = extract_generated_contexts(artifacts)
        token_usage = extract_token_usage_from_job_events(events)
        return answer, contexts, token_usage, artifacts

    def run_inference(self, query: str) -> tuple[str, list[str], QueryTokenUsage, Any]:
        if self.inference_mode == "atif":
            return self.run_workflow_atif(query)
        return self.run_async_research_job(query)

    def _evaluation_data_path(self) -> str:
        return os.path.join(self.result_dir, f"rag_{self.run_label}_evaluation_data.json")

    def _save_eval_data(self, eval_data: list[dict[str, Any]]) -> None:
        with open(self._evaluation_data_path(), "w", encoding="utf-8") as handle:
            json.dump(eval_data, handle, indent=4)

    def load_eval_data(self) -> list[dict[str, Any]]:
        with open(self.eval_data_path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, list):
            print("Error: train.json must be a JSON array of objects with question/answer fields.")
            sys.exit(1)
        return data

    def create_eval_dict(self) -> list[dict[str, Any]]:
        eval_rows = self.load_eval_data()
        eval_data: list[dict[str, Any]] = []
        total_questions = len(eval_rows)
        save_lock = Lock()
        latency_lock = Lock()
        completed_latencies: list[float] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            progress_label = "Running async research" if self.inference_mode == "async" else "Running workflow ATIF"
            with tqdm(
                total=total_questions,
                desc=progress_label,
                unit="query",
            ) as progress:

                def run_query(row: dict[str, Any]) -> dict[str, Any] | None:
                    question = row.get("question", "")
                    try:
                        start = time.perf_counter()
                        generated_answer, generated_contexts, token_usage, inference_payload = self.run_inference(
                            question
                        )
                        e2e_latency_s = time.perf_counter() - start
                        result: dict[str, Any] = {
                            "id": row.get("id", row.get("query_id")),
                            "question": question,
                            "answer": row.get("answer"),
                            "generated_answer": generated_answer,
                            "contexts": _normalize_reference_contexts(row.get("contexts", [])),
                            "generated_contexts": generated_contexts,
                            "token_usage": token_usage.model_dump(),
                        }
                        if self.inference_mode == "atif":
                            result["atif_steps"] = inference_payload
                        else:
                            result["artifacts"] = inference_payload
                        with save_lock:
                            eval_data.append(result)
                            self._save_eval_data(eval_data)
                        with latency_lock:
                            completed_latencies.append(e2e_latency_s)
                            progress.set_postfix(
                                e2e_avg_s=f"{sum(completed_latencies) / len(completed_latencies):.1f}",
                                refresh=False,
                            )
                        return result
                    except Exception as exc:
                        tqdm.write(f"Error processing question {question!r}: {exc}")
                        with self.error_lock:
                            self.error_count += 1
                        return None

                futures = {executor.submit(run_query, row): row for row in eval_rows}
                for future in as_completed(futures):
                    future.result()
                    progress.update(1)

        self.e2e_latency_summary = _aggregate_latencies(completed_latencies)
        _print_e2e_latency_summary(self.e2e_latency_summary)

        if self.error_count > total_questions * 0.5:
            fail_pct = (self.error_count / total_questions) * 100
            print(
                f"⚠️ WARNING: High failure rate detected! "
                f"{self.error_count} failures out of {total_questions} queries ({fail_pct:.2f}%)."
            )
        return eval_data

    def run_pipeline(self) -> list[dict[str, Any]] | None:
        self.check_health()

        self.data_sources = self.resolve_agent_data_sources()
        print(f" - Agent data sources: {self.data_sources}")
        if _KNOWLEDGE_LAYER_SOURCE in self.data_sources:
            self.check_knowledge_api()
        if self.inference_mode == "atif" and _WEB_SEARCH_SOURCE in self.data_sources:
            print(
                " - WARNING: ATIF inference mode does not forward data_sources; "
                "web search scoping applies only to async jobs."
            )

        if self.force_ingestion and self.collection_exists():
            print(f" - Force ingestion enabled, deleting collection {self.collection_name}")
            self.delete_collection()

        if not self.skip_ingestion:
            if not self.collection_exists():
                print(f" - Creating collection {self.collection_name}")
                self.create_collection()
            else:
                print(f" - Collection {self.collection_name} already exists")

            ingested_documents = self.list_ingested_documents()
            if ingested_documents:
                print(f" - Documents already in collection: {len(ingested_documents)}")
            files_to_upload = self.collect_files_to_upload(ingested_documents)
            print(f" - Number of files to upload: {len(files_to_upload)}")
            self.upload_documents(files_to_upload)
            self.validate_ingestion()

        if self.skip_evaluation:
            return None

        if not self.skip_ingestion:
            ingested_documents = self.list_ingested_documents()
            files_to_upload = self.collect_files_to_upload(ingested_documents)
            if files_to_upload:
                corpus_files = self._corpus_file_count()
                print(
                    f" - WARNING: {corpus_files} corpus file(s) vs {len(ingested_documents)} ingested; "
                    f"{len(files_to_upload)} still missing. Accuracy may be affected."
                )

        ingested_count = len(self.list_ingested_documents())
        if ingested_count == 0 and not self.skip_ingestion:
            raise RuntimeError(
                f"No documents ingested in collection '{self.collection_name}'. "
                "Upload corpus files before running evaluation."
            )

        return self.create_eval_dict()


def validate_dataset_roots(dataset_roots: list[str]) -> None:
    for root in dataset_roots:
        abs_root = os.path.abspath(root)
        if not os.path.isdir(abs_root):
            print(f"Error: dataset path is not a directory: {abs_root}")
            sys.exit(1)
        corpus_path = os.path.join(abs_root, CORPUS_DIRECTORY)
        eval_path = os.path.join(abs_root, EVAL_DATA)
        if not os.path.isdir(corpus_path):
            print(f"Error: missing corpus directory: {corpus_path}")
            sys.exit(1)
        if not os.path.isfile(eval_path):
            print(f"Error: missing {EVAL_DATA} under dataset root: {eval_path}")
            sys.exit(1)


def evaluate_result(eval_data: list[dict[str, Any]]) -> dict[str, Any]:
    """Score shallow-research outputs with RAGAS NVIDIA metrics and token usage."""
    print("Starting RAG evaluation process...")
    llm = build_judge_llm()

    has_contexts = any(sample.get("generated_contexts") for sample in eval_data)
    if has_contexts:
        eval_dataset = EvaluationDataset(
            [
                SingleTurnSample(
                    user_input=sample["question"],
                    reference=sample["answer"],
                    response=sample["generated_answer"],
                    reference_contexts=sample.get("contexts", []),
                    retrieved_contexts=sample["generated_contexts"],
                )
                for sample in eval_data
            ]
        )
        metrics = [AnswerAccuracy(), ContextRelevance(), ResponseGroundedness()]
    else:
        print(
            " - No retrieved contexts found; computing Answer Accuracy (nv_accuracy) only "
            f"(skipping {NV_METRIC_NV_CONTEXT_RELEVANCE}, {NV_METRIC_NV_RESPONSE_GROUNDEDNESS})"
        )
        eval_dataset = EvaluationDataset(
            [
                SingleTurnSample(
                    user_input=sample["question"],
                    reference=sample["answer"],
                    response=sample["generated_answer"],
                    reference_contexts=sample.get("contexts", []),
                    retrieved_contexts=[],
                )
                for sample in eval_data
            ]
        )
        metrics = [AnswerAccuracy()]

    dataframe = evaluate(
        dataset=eval_dataset,
        metrics=metrics,
        llm=LangchainLLMWrapper(llm),
    ).to_pandas()

    all_results: dict[str, Any] = {
        NV_METRIC_NV_ACCURACY: dataframe[NV_METRIC_NV_ACCURACY].tolist()
        if NV_METRIC_NV_ACCURACY in dataframe.columns
        else [],
        NV_METRIC_NV_CONTEXT_RELEVANCE: dataframe[NV_METRIC_NV_CONTEXT_RELEVANCE].tolist()
        if NV_METRIC_NV_CONTEXT_RELEVANCE in dataframe.columns
        else [],
        NV_METRIC_NV_RESPONSE_GROUNDEDNESS: dataframe[NV_METRIC_NV_RESPONSE_GROUNDEDNESS].tolist()
        if NV_METRIC_NV_RESPONSE_GROUNDEDNESS in dataframe.columns
        else [],
    }

    usages = [row.get("token_usage") for row in eval_data if isinstance(row.get("token_usage"), dict)]
    if usages:
        prompt_tokens = sum(_coerce_int(row.get("prompt_tokens")) for row in usages)
        completion_tokens = sum(_coerce_int(row.get("completion_tokens")) for row in usages)
        cached_tokens = sum(_coerce_int(row.get("cached_tokens")) for row in usages)
        llm_calls = sum(_coerce_int(row.get("llm_calls")) for row in usages)
        total_tokens = sum(
            _coerce_int(row.get("total_tokens"))
            or (_coerce_int(row.get("prompt_tokens")) + _coerce_int(row.get("completion_tokens")))
            for row in usages
        )
        sample_count = len(usages)
        all_results["token_usage"] = {
            "total_tokens": total_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cached_tokens": cached_tokens,
            "llm_calls": llm_calls,
            "sample_count": sample_count,
            "mean_prompt_tokens": prompt_tokens / sample_count,
            "mean_completion_tokens": completion_tokens / sample_count,
            "mean_total_tokens": total_tokens / sample_count,
            "mean_llm_calls": llm_calls / sample_count,
        }

    return all_results


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    try:
        series = pd.Series(values, dtype="float64")
        if series.isna().all():
            return 0.0
        return float(series.mean(skipna=True))
    except (TypeError, ValueError):
        return 0.0


def _aggregate_latencies(latencies: list[float]) -> dict[str, Any] | None:
    """Aggregate per-query client-side inference latencies (seconds)."""
    if not latencies:
        return None
    series = pd.Series(latencies, dtype="float64")
    return {
        "sample_count": len(latencies),
        "mean_s": float(series.mean()),
        "min_s": float(series.min()),
        "max_s": float(series.max()),
        "p50_s": float(series.quantile(0.5)),
        "p90_s": float(series.quantile(0.9)),
        "total_s": float(series.sum()),
    }


def _print_e2e_latency_summary(latency_summary: dict[str, Any] | None) -> None:
    if not latency_summary:
        return
    print(
        " - E2E inference latency (submit → report, per successful query): "
        f"mean={latency_summary['mean_s']:.1f}s, "
        f"p50={latency_summary['p50_s']:.1f}s, "
        f"p90={latency_summary['p90_s']:.1f}s, "
        f"min={latency_summary['min_s']:.1f}s, "
        f"max={latency_summary['max_s']:.1f}s "
        f"({latency_summary['sample_count']} queries)"
    )


def _print_evaluation_results(all_result: dict[str, Any], latency_summary: dict[str, Any] | None) -> None:
    print("\n" + "=" * 80)
    print("EVALUATION RESULTS")
    print("=" * 80)
    print(f" - nv_accuracy: {_mean(all_result.get(NV_METRIC_NV_ACCURACY, []))}")
    if all_result.get(NV_METRIC_NV_CONTEXT_RELEVANCE):
        print(f" - nv_context_relevance: {_mean(all_result.get(NV_METRIC_NV_CONTEXT_RELEVANCE, []))}")
        print(f" - nv_response_groundedness: {_mean(all_result.get(NV_METRIC_NV_RESPONSE_GROUNDEDNESS, []))}")
    token_usage = all_result.get("token_usage")
    if isinstance(token_usage, dict):
        print(" - Token usage")
        print(f"     total_tokens: {token_usage.get('total_tokens', 0)}")
        print(f"     prompt_tokens: {token_usage.get('prompt_tokens', 0)}")
        print(f"     completion_tokens: {token_usage.get('completion_tokens', 0)}")
        print(f"     cached_tokens: {token_usage.get('cached_tokens', 0)}")
        print(f"     llm_calls: {token_usage.get('llm_calls', 0)}")
        print(f"     samples with usage: {token_usage.get('sample_count', 0)}")
        print(f"     mean prompt tokens/query: {token_usage.get('mean_prompt_tokens', 0):.1f}")
        print(f"     mean completion tokens/query: {token_usage.get('mean_completion_tokens', 0):.1f}")
    if isinstance(latency_summary, dict):
        print(" - E2E inference latency (per successful query)")
        print(f"     mean: {latency_summary.get('mean_s', 0):.1f}s")
        print(f"     p50: {latency_summary.get('p50_s', 0):.1f}s")
        print(f"     p90: {latency_summary.get('p90_s', 0):.1f}s")
        print(f"     min: {latency_summary.get('min_s', 0):.1f}s")
        print(f"     max: {latency_summary.get('max_s', 0):.1f}s")
        print(f"     samples: {latency_summary.get('sample_count', 0)}")
    print("-" * 80 + "\n")


def _build_summary_metrics(all_result: dict[str, Any], latency_summary: dict[str, Any] | None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        f"{NV_METRIC_NV_ACCURACY}_mean": _mean(all_result.get(NV_METRIC_NV_ACCURACY, [])),
    }
    if all_result.get(NV_METRIC_NV_CONTEXT_RELEVANCE):
        summary[f"{NV_METRIC_NV_CONTEXT_RELEVANCE}_mean"] = _mean(all_result[NV_METRIC_NV_CONTEXT_RELEVANCE])
        summary[f"{NV_METRIC_NV_RESPONSE_GROUNDEDNESS}_mean"] = _mean(
            all_result[NV_METRIC_NV_RESPONSE_GROUNDEDNESS]
        )
    if isinstance(all_result.get("token_usage"), dict):
        summary["token_usage"] = all_result["token_usage"]
    if isinstance(latency_summary, dict):
        summary["e2e_latency"] = latency_summary
    return summary


def _token_usage_metrics(token_usage: dict[str, Any]) -> TokenUsageMetrics:
    return TokenUsageMetrics(
        total_tokens=token_usage.get("total_tokens", 0),
        prompt_tokens=token_usage.get("prompt_tokens", 0),
        completion_tokens=token_usage.get("completion_tokens", 0),
        cached_tokens=token_usage.get("cached_tokens", 0),
        llm_calls=token_usage.get("llm_calls", 0),
        sample_count=token_usage.get("sample_count", 0),
        mean_prompt_tokens=token_usage.get("mean_prompt_tokens", 0.0),
        mean_completion_tokens=token_usage.get("mean_completion_tokens", 0.0),
        mean_total_tokens=token_usage.get("mean_total_tokens", 0.0),
        mean_llm_calls=token_usage.get("mean_llm_calls", 0.0),
    )


def _print_configuration(args: argparse.Namespace, *, server_url: str, data_sources: list[str] | None) -> None:
    print("\n" + "=" * 80)
    print("CONFIGURATION")
    print("=" * 80)
    print(f"AI-Q server: {server_url}")
    print(f"Agent type: {args.agent_type}")
    if data_sources:
        print(f"Data sources: {data_sources} (explicit)")
    else:
        print("Data sources: auto-detect from agent config")
    print(f"Dataset roots: {args.dataset_paths}")
    print(f"Output directory: {args.output_dir}")
    print(f"Skip ingestion: {args.skip_ingestion}")
    print(f"Skip evaluation: {args.skip_evaluation}")
    print(f"Force ingestion: {args.force_ingestion}")
    print(f"Parallel jobs: {args.thread}")
    print(f"Query timeout: {args.timeout}s")
    print(f"Inference mode: {args.inference_mode}")
    print(f"Ingestion batch timeout: up to {args.ingestion_timeout}s (scales with batch size)")
    if args.inference_mode == "atif":
        print(f"Inference endpoint: POST {WORKFLOW_ATIF_PATH}")
        print(
            "NOTE: ATIF mode sets conversation-id to the collection name. "
            "Prefer --inference-mode async for large benchmarks."
        )
    else:
        print("Inference endpoint: POST /v1/jobs/async/submit")
        print(
            "NOTE: Async jobs pass collection_name and resolved data_sources "
            "(web search is used only when configured for the agent)."
        )
    if not args.skip_evaluation:
        print(f"RAGAS judge model: {JUDGE_MODEL} (env {_JUDGE_MODEL_ENV})")
        print(f"RAGAS judge base URL: {JUDGE_BASE_URL} (env {_JUDGE_BASE_URL_ENV})")
    print("-" * 80 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate RAG datasets (corpus/ + train.json) with AI-Q shallow research. "
            "Supports knowledge-layer ingestion, web search, and RAGAS scoring."
        )
    )
    parser.add_argument(
        "--dataset-paths",
        nargs="+",
        required=True,
        help="Dataset root directories, each containing corpus/ and train.json.",
    )
    parser.add_argument(
        "--server-url",
        default=os.environ.get("AIQ_SERVER_URL", DEFAULT_SERVER_URL),
        help=f"AI-Q server base URL (default: {DEFAULT_SERVER_URL} or AIQ_SERVER_URL).",
    )
    parser.add_argument(
        "--agent-type",
        default=DEFAULT_AGENT_TYPE,
        help=f"Async agent type (default: {DEFAULT_AGENT_TYPE}).",
    )
    parser.add_argument(
        "--data-sources",
        default=None,
        help=(
            "Comma-separated data source IDs to use (e.g. knowledge_layer,web_search). "
            "Default: auto-detect from the agent config on the server."
        ),
    )
    parser.add_argument(
        "--file-type",
        default="pdf",
        help='Corpus file type hint for ingestion metrics (substring "pdf" enables page counts).',
    )
    parser.add_argument(
        "--thread",
        default=DEFAULT_MAX_WORKERS,
        type=int,
        help="Parallel shallow-research jobs (default: 1).",
    )
    parser.add_argument("--output-dir", default="results", help="Directory for evaluation outputs.")
    parser.add_argument("--batch-size", default=DEFAULT_BATCH_SIZE, type=int, help="Ingestion upload batch size.")
    parser.add_argument("--collection", default=None, help="Collection name (default: dataset directory basename).")
    parser.add_argument("--skip-ingestion", action="store_true", help="Skip corpus ingestion.")
    parser.add_argument("--skip-evaluation", action="store_true", help="Skip RAGAS scoring.")
    parser.add_argument("--force-ingestion", action="store_true", help="Delete and recreate the collection.")
    parser.add_argument(
        "--inference-mode",
        choices=("async", "atif"),
        default=DEFAULT_INFERENCE_MODE,
        help=(
            "Inference API: 'async' uses /v1/jobs/async/submit (default, faster polling); "
            "'atif' uses POST /v1/workflow/atif (slower, full ATIF trajectory)."
        ),
    )
    parser.add_argument(
        "--timeout",
        default=DEFAULT_TIMEOUT,
        type=int,
        help=(
            "Per-query timeout in seconds (default: 1800). For async jobs this is the poll deadline; "
            "for ATIF it is the max gap between stream chunks. Use 0 for no read timeout on ATIF."
        ),
    )
    parser.add_argument(
        "--ingestion-timeout",
        default=DEFAULT_INGESTION_TIMEOUT,
        type=int,
        help=("Max seconds to wait per ingestion batch (default: 3600). Scales with batch size up to this limit."),
    )
    args = parser.parse_args()

    if not _judge_api_key() and not args.skip_evaluation:
        raise ValueError(
            f"{_INFERENCE_HUB_API_KEY_ENV} or NVIDIA_API_KEY must be set before running RAGAS evaluation, "
            "or pass --skip-evaluation."
        )

    validate_dataset_roots(list(args.dataset_paths))
    server_url = args.server_url.rstrip("/")
    data_sources = (
        [part.strip() for part in args.data_sources.split(",") if part.strip()] if args.data_sources else None
    )

    _print_configuration(args, server_url=server_url, data_sources=data_sources)

    all_summaries: dict[str, dict[str, Any]] = {}
    for dataset_root in args.dataset_paths:
        dataset_root = os.path.abspath(dataset_root)
        run_label = os.path.basename(dataset_root.rstrip(os.sep)) or "dataset"
        collection_name = args.collection or run_label
        output_dir = os.path.join(args.output_dir, run_label)
        os.makedirs(output_dir, exist_ok=True)

        print(f"\n=== Evaluating {run_label} ({dataset_root}) ===")
        print(f" - Collection: {collection_name}")

        client = AIQClient(
            server_url=server_url,
            collection_name=collection_name,
            max_workers=args.thread,
            result_dir=output_dir,
            skip_ingestion=args.skip_ingestion,
            force_ingestion=args.force_ingestion,
            dataset_root=dataset_root,
            run_label=run_label,
            file_type=args.file_type,
            timeout=args.timeout,
            ingestion_timeout=args.ingestion_timeout,
            agent_type=args.agent_type,
            batch_size=args.batch_size,
            inference_mode=args.inference_mode,
            data_sources=data_sources,
        )

        eval_data = client.run_pipeline()
        if args.skip_evaluation or eval_data is None:
            continue

        all_result = evaluate_result(eval_data)
        _print_evaluation_results(all_result, client.e2e_latency_summary)
        summary_metrics = _build_summary_metrics(all_result, client.e2e_latency_summary)

        client.rag_evaluation_metrics.evaluation_metrics = EvaluationMetrics(
            nv_accuracy=summary_metrics.get(f"{NV_METRIC_NV_ACCURACY}_mean", 0.0),
            nv_context_relevance=summary_metrics.get(f"{NV_METRIC_NV_CONTEXT_RELEVANCE}_mean", 0.0),
            nv_response_groundedness=summary_metrics.get(f"{NV_METRIC_NV_RESPONSE_GROUNDEDNESS}_mean", 0.0),
        )
        if isinstance(all_result.get("token_usage"), dict):
            client.rag_evaluation_metrics.token_usage = _token_usage_metrics(all_result["token_usage"])
        all_summaries[run_label] = summary_metrics

        summary_path = os.path.join(output_dir, f"rag_{run_label}_evaluation_summary.json")
        with open(summary_path, "w", encoding="utf-8") as handle:
            json.dump(summary_metrics, handle, indent=4)

        results_path = os.path.join(output_dir, f"rag_{run_label}_evaluation_results.json")
        with open(results_path, "w", encoding="utf-8") as handle:
            json.dump(all_result, handle, indent=4)

        metrics_path = os.path.join(output_dir, f"rag_{run_label}_evaluation_metrics.json")
        with open(metrics_path, "w", encoding="utf-8") as handle:
            json.dump(client.rag_evaluation_metrics.model_dump(), handle, indent=4)

    if all_summaries:
        combined_path = os.path.join(args.output_dir, "rag_evaluation_summary_all.json")
        with open(combined_path, "w", encoding="utf-8") as handle:
            json.dump(all_summaries, handle, indent=4)
        print(f"Combined summary written to {combined_path}")


if __name__ == "__main__":
    main()

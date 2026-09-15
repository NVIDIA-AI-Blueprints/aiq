"""AI-Q report job contract. Only completed report text is an evaluation answer."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from dataclasses import field
from typing import Any

import httpx


@dataclass
class ReportJob:
    job_id: str = field(repr=False)
    succeeded: bool = False

    @classmethod
    def from_answer(cls, answer: str) -> ReportJob | None:
        """Recognize the explicit chat handoff, including one assembled from SSE deltas."""
        try:
            payload = json.loads(answer)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict) or payload.get("type") != "job_escalation":
            return None
        if payload.get("kind") not in {"deep_research", "report_edit"}:
            raise ValueError("Unsupported AI-Q job escalation kind.")
        job_id = payload.get("job_id")
        if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
            raise ValueError("AI-Q report handoff has an invalid or missing job ID.")
        return cls(job_id)

    @property
    def stage(self) -> str:
        return "report_content" if self.succeeded else "report_status"

    def url(self, chat_endpoint: str) -> httpx.URL:
        """API adaptation point: derive job routes on the configured agent's origin."""
        endpoint = httpx.URL(chat_endpoint)
        suffix = "/v1/chat/completions"
        prefix = endpoint.path[: -len(suffix)] if endpoint.path.endswith(suffix) else ""
        path = f"{prefix}/v1/jobs/async/job/{self.job_id}"
        if self.succeeded:
            path += "/report"
        # Do not follow URLs supplied in generated content or forward credentials to another host.
        return endpoint.copy_with(path=path, query=None, fragment=None)

    def consume(self, payload: Any) -> str | None:
        """API adaptation point: consume a status/report response; never return a draft."""
        if not isinstance(payload, dict) or payload.get("job_id") != self.job_id:
            raise ValueError("Report API returned an invalid response or a different job.")
        if self.succeeded:
            report = payload.get("report")
            if payload.get("has_report") is not True or not isinstance(report, str) or not report.strip():
                raise ValueError("Report job succeeded but returned no final report text.")
            return report
        status = payload.get("status")
        if status == "success":
            self.succeeded = True
        elif status in {"failure", "interrupted", "not_found"}:
            raise ValueError(
                f"Report job ended with status {status}: {payload.get('error') or 'No final report available.'}"
            )
        elif status not in {"submitted", "running"}:
            raise ValueError("Report API returned an unrecognized job status.")
        return None

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the aiq-research helper's terminal-state and escalation contract (AIQ-018).

Covers two 26.07 backend contract fixes in ``skills/aiq-research/scripts/aiq.py``:

- SK-1: the ``interrupted`` job state is terminal and reported as a failure, so
  polling stops immediately instead of running until the long-poll timeout.
- SK-2: a JSON ``job_escalation`` deep-research response is recognized and surfaced
  as ``deep_research_running``, while malformed / non-escalation payloads do not
  produce a false positive and the legacy ``Job ID: <uuid>`` format still works.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "skills" / "aiq-research" / "scripts" / "aiq.py"

_VALID_JOB_ID = "78f7130c-0000-4000-8000-000000000000"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("aiq_research_helper", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def aiq() -> ModuleType:
    return _load()


# --- SK-1: interrupted is a terminal, failed state -------------------------------


def test_interrupted_is_terminal_and_failed(aiq: ModuleType) -> None:
    assert "interrupted" in aiq._DONE_JOB_STATES
    assert "interrupted" in aiq._FAILED_JOB_STATES
    assert "interrupted" not in aiq._SUCCESS_JOB_STATES


def test_poll_returns_immediately_on_interrupted(aiq: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"status": 0, "sleep": 0}

    def fake_status(_job_id: str) -> dict[str, object]:
        calls["status"] += 1
        return {"status": "interrupted"}

    monkeypatch.setattr(aiq, "get_job_status", fake_status)
    monkeypatch.setattr(aiq.time, "sleep", lambda _seconds: calls.__setitem__("sleep", calls["sleep"] + 1))

    final = aiq.poll_until_complete(_VALID_JOB_ID)

    assert final == {"status": "interrupted"}
    assert calls["status"] == 1
    assert calls["sleep"] == 0


def test_research_poll_exits_failure_on_interrupted(aiq: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    report_calls = {"count": 0}

    monkeypatch.setattr(aiq, "get_job_status", lambda _job_id: {"status": "interrupted"})
    monkeypatch.setattr(aiq, "get_report", lambda _job_id: report_calls.__setitem__("count", report_calls["count"] + 1))
    monkeypatch.setattr(aiq.time, "sleep", lambda _seconds: None)

    with pytest.raises(SystemExit) as excinfo:
        aiq._command_research_poll([_VALID_JOB_ID])

    assert excinfo.value.code == aiq.EXIT_FAILURE
    assert report_calls["count"] == 0


# --- SK-2: JSON job_escalation detection -----------------------------------------


def test_escalation_detected_from_top_level_result(aiq: ModuleType) -> None:
    result = {"type": "job_escalation", "kind": "deep_research", "job_id": _VALID_JOB_ID}
    assert aiq._detect_deep_research_escalation(result, "") == _VALID_JOB_ID


def test_escalation_detected_from_embedded_content(aiq: ModuleType) -> None:
    payload = {"type": "job_escalation", "kind": "deep_research", "job_id": _VALID_JOB_ID}
    content = json.dumps(payload)
    assert aiq._detect_deep_research_escalation({"choices": []}, content) == _VALID_JOB_ID


def test_command_chat_emits_deep_research_running(aiq: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    result = {"type": "job_escalation", "kind": "deep_research", "job_id": _VALID_JOB_ID}
    monkeypatch.setattr(aiq, "chat_request", lambda _query: result)

    aiq._command_chat(["find me a deep research answer"])

    out = json.loads(capsys.readouterr().out)
    assert out == {"status": "deep_research_running", "job_id": _VALID_JOB_ID}


def test_legacy_job_id_format_still_detected(aiq: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    content = f"Deep research started. Job ID: {_VALID_JOB_ID}"
    result = {"choices": [{"message": {"content": content}}]}
    monkeypatch.setattr(aiq, "chat_request", lambda _query: result)

    aiq._command_chat(["legacy query"])

    out = json.loads(capsys.readouterr().out)
    assert out == {"status": "deep_research_running", "job_id": _VALID_JOB_ID}


def test_malformed_legacy_job_id_falls_through_to_raw(aiq: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    # 36 chars of [0-9a-f-] so _CHAT_JOB_ID_RE matches, but not a valid UUID layout.
    bogus = "a" * 36
    content = f"Deep research started. Job ID: {bogus}"
    result = {"choices": [{"message": {"content": content}}]}
    monkeypatch.setattr(aiq, "chat_request", lambda _query: result)

    aiq._command_chat(["legacy malformed query"])

    out = json.loads(capsys.readouterr().out)
    assert out == result


# --- SK-2 guards: no false positives ---------------------------------------------


def test_malformed_json_content_is_not_escalation(aiq: ModuleType) -> None:
    assert aiq._detect_deep_research_escalation({"choices": []}, "{not valid json") is None


def test_non_escalation_json_is_not_escalation(aiq: ModuleType) -> None:
    result = {"answer": "42", "type": "chat_response"}
    assert aiq._detect_deep_research_escalation(result, "") is None


def test_unsupported_escalation_kind_is_not_escalation(aiq: ModuleType) -> None:
    result = {"type": "job_escalation", "kind": "some_other_flow", "job_id": _VALID_JOB_ID}
    assert aiq._detect_deep_research_escalation(result, "") is None


def test_missing_or_invalid_job_id_is_not_escalation(aiq: ModuleType) -> None:
    missing = {"type": "job_escalation", "kind": "deep_research"}
    invalid = {"type": "job_escalation", "kind": "deep_research", "job_id": "not-a-uuid"}
    non_string = {"type": "job_escalation", "kind": "deep_research", "job_id": 12345}
    assert aiq._detect_deep_research_escalation(missing, "") is None
    assert aiq._detect_deep_research_escalation(invalid, "") is None
    assert aiq._detect_deep_research_escalation(non_string, "") is None


def test_non_escalation_result_falls_through_to_raw(aiq: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    result = {"choices": [{"message": {"content": "a plain shallow answer"}}]}
    monkeypatch.setattr(aiq, "chat_request", lambda _query: result)

    aiq._command_chat(["shallow query"])

    out = json.loads(capsys.readouterr().out)
    assert out == result

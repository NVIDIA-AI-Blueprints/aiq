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

"""
Tests for the async job API routes.

Module under test: frontends/aiq_api/src/aiq_api/routes/jobs.py

API endpoints tested:
    GET  /v1/jobs/async/agents                         - List available agent types
    POST /v1/jobs/async/submit                         - Submit a new job
    GET  /v1/jobs/async/job/{id}                       - Get job status
    GET  /v1/jobs/async/job/{id}/stream                - SSE stream from beginning
    POST /v1/jobs/async/job/{id}/cancel                - Cancel a running job
    GET  /v1/jobs/async/job/{id}/state                 - Get artifacts from event store
    GET  /v1/jobs/async/job/{id}/report                - Get final report

Test coverage:
    TestJobSubmitRequest:
        - Valid request with defaults
        - Custom job_id and expiry_seconds
        - Empty input rejected (min_length=1)
        - Expiry validation (ge=600, le=604800)

    TestJobStatusResponse:
        - Minimal response (job_id, status)
        - Full response with error, created_at

    TestJobStateResponse:
        - Response without state (has_state=False)
        - Response with artifacts

    TestJobReportResponse:
        - Response without report (has_report=False)
        - Response with report content

    TestRegisterRoutes:
        - Routes not registered when Dask unavailable
        - Routes not registered without job_store
        - Routes registered when infrastructure available
"""

from unittest.mock import MagicMock

import pytest
from aiq_api.routes.jobs import JobReportResponse
from aiq_api.routes.jobs import JobStateResponse
from aiq_api.routes.jobs import JobStatusResponse
from aiq_api.routes.jobs import JobSubmitRequest


class TestJobSubmitRequest:
    """Tests for the JobSubmitRequest model."""

    def test_valid_request(self):
        """Test creating a valid submit request."""
        req = JobSubmitRequest(agent_type="deep_researcher", input="What is CUDA?")

        assert req.input == "What is CUDA?"
        assert req.agent_type == "deep_researcher"
        assert req.job_id is None
        assert req.expiry_seconds is None

    def test_with_custom_job_id(self):
        """Test submit request with custom job ID."""
        req = JobSubmitRequest(agent_type="deep_researcher", input="query", job_id="custom-123")

        assert req.job_id == "custom-123"

    def test_with_custom_expiry(self):
        """Test submit request with custom expiry."""
        req = JobSubmitRequest(agent_type="deep_researcher", input="query", expiry_seconds=7200)

        assert req.expiry_seconds == 7200

    def test_empty_input_rejected(self):
        """Test that empty input is rejected."""
        with pytest.raises(ValueError):
            JobSubmitRequest(agent_type="deep_researcher", input="")

    def test_expiry_too_low_rejected(self):
        """Test that expiry below 600 is rejected."""
        with pytest.raises(ValueError):
            JobSubmitRequest(agent_type="deep_researcher", input="query", expiry_seconds=300)

    def test_expiry_too_high_rejected(self):
        """Test that expiry above 604800 is rejected."""
        with pytest.raises(ValueError):
            JobSubmitRequest(agent_type="deep_researcher", input="query", expiry_seconds=700000)


class TestJobStatusResponse:
    """Tests for the JobStatusResponse model."""

    def test_minimal_response(self):
        """Test minimal job response."""
        resp = JobStatusResponse(job_id="123", status="running")

        assert resp.job_id == "123"
        assert resp.status == "running"
        assert resp.error is None
        assert resp.created_at is None

    def test_full_response(self):
        """Test full job response."""
        resp = JobStatusResponse(
            job_id="123",
            status="success",
            error="some error",
            created_at="2026-01-20T10:00:00",
        )

        assert resp.job_id == "123"
        assert resp.status == "success"
        assert resp.error == "some error"
        assert resp.created_at == "2026-01-20T10:00:00"


class TestJobStateResponse:
    """Tests for the JobStateResponse model."""

    def test_without_state(self):
        """Test state response without state."""
        resp = JobStateResponse(job_id="123", has_state=False)

        assert resp.job_id == "123"
        assert resp.has_state is False
        assert resp.state is None

    def test_with_artifacts(self):
        """Test state response with artifacts."""
        artifacts = {"tools": [], "outputs": []}
        resp = JobStateResponse(job_id="123", has_state=True, artifacts=artifacts)

        assert resp.has_state is True
        assert resp.artifacts == artifacts


class TestJobReportResponse:
    """Tests for the JobReportResponse model."""

    def test_without_report(self):
        """Test report response without report."""
        resp = JobReportResponse(job_id="123", has_report=False)

        assert resp.job_id == "123"
        assert resp.has_report is False
        assert resp.report is None

    def test_with_report(self):
        """Test report response with report."""
        resp = JobReportResponse(job_id="123", has_report=True, report="# Report\n\nContent here")

        assert resp.has_report is True
        assert resp.report == "# Report\n\nContent here"


class TestRegisterRoutes:
    """Tests for the register_routes function."""

    @pytest.mark.asyncio
    async def test_routes_not_registered_without_dask(self):
        """Test that routes are not registered when Dask is not available."""
        from aiq_api.routes.jobs import register_job_routes

        mock_app = MagicMock()
        mock_builder = MagicMock()
        mock_builder.get_function_config.side_effect = KeyError("Not found")
        mock_worker = MagicMock()
        mock_worker._dask_available = False
        mock_worker._job_store = None

        await register_job_routes(mock_app, mock_builder, mock_worker)

        mock_app.post.assert_not_called()
        assert mock_app.get.call_count == 2

    @pytest.mark.asyncio
    async def test_routes_not_registered_without_job_store(self):
        """Test that routes are not registered without job store."""
        from aiq_api.routes.jobs import register_job_routes

        mock_app = MagicMock()
        mock_builder = MagicMock()
        mock_builder.get_function_config.side_effect = KeyError("Not found")
        mock_worker = MagicMock()
        mock_worker._dask_available = True
        mock_worker._job_store = None

        await register_job_routes(mock_app, mock_builder, mock_worker)

        mock_app.post.assert_not_called()
        assert mock_app.get.call_count == 2

    @pytest.mark.asyncio
    async def test_routes_registered_with_dask(self):
        """Test that routes are registered when Dask is available."""
        from aiq_api.routes.jobs import register_job_routes

        mock_app = MagicMock()
        mock_builder = MagicMock()
        mock_builder.get_function_config.side_effect = KeyError("Not found")
        mock_worker = MagicMock()
        mock_worker._dask_available = True
        mock_worker._job_store = MagicMock()
        mock_worker._scheduler_address = "tcp://localhost:8786"
        mock_worker._db_url = "sqlite:///./test.db"
        mock_worker._config_file_path = "/path/to/config.yml"
        mock_worker._log_level = 20
        mock_worker._use_dask_threads = False
        mock_worker._front_end_config = MagicMock(expiry_seconds=86400)

        await register_job_routes(mock_app, mock_builder, mock_worker)

        assert mock_app.post.call_count >= 2
        assert mock_app.get.call_count >= 6


class TestArtifactHelpers:
    """Tests for artifact extraction helper functions."""

    def test_extract_event_metadata_with_data(self):
        """Test extracting metadata from event with data dict."""
        from aiq_api.routes.jobs import _extract_event_metadata

        event = {
            "type": "tool.start",
            "data": {"name": "test", "input": "query"},
            "metadata": {"workflow": "agent-1"},
        }

        data, metadata = _extract_event_metadata(event)

        assert data == {"name": "test", "input": "query"}
        assert metadata == {"workflow": "agent-1"}

    def test_extract_event_metadata_fallback_to_nested(self):
        """Test extracting metadata from nested data.metadata."""
        from aiq_api.routes.jobs import _extract_event_metadata

        event = {
            "type": "tool.start",
            "data": {"name": "test", "metadata": {"workflow": "nested"}},
        }

        data, metadata = _extract_event_metadata(event)

        assert metadata == {"workflow": "nested"}

    def test_extract_event_metadata_handles_non_dict(self):
        """Test extracting metadata handles non-dict data."""
        from aiq_api.routes.jobs import _extract_event_metadata

        event = {"type": "test", "data": "string_data"}

        data, metadata = _extract_event_metadata(event)

        assert data == {}
        assert metadata == {}

    def test_process_tool_start(self):
        """Test processing tool.start event."""
        from aiq_api.routes.jobs import _process_tool_start

        event = {"timestamp": "2026-01-22T10:00:00"}
        data = {"id": "tool-1", "name": "search", "data": {"input": "query"}}
        metadata = {"workflow": "agent-1"}
        tool_call_map: dict = {}

        _process_tool_start(event, data, metadata, tool_call_map)

        assert "tool-1" in tool_call_map
        assert tool_call_map["tool-1"]["name"] == "search"
        assert tool_call_map["tool-1"]["status"] == "running"

    def test_process_tool_end_updates_existing(self):
        """Test processing tool.end updates existing tool."""
        from aiq_api.routes.jobs import _process_tool_end

        event = {"timestamp": "2026-01-22T10:00:01"}
        data = {"id": "tool-1", "name": "search", "data": {"output": "result"}}
        metadata = {"workflow": "agent-1"}
        tool_call_map = {
            "tool-1": {
                "id": "tool-1",
                "name": "search",
                "input": "query",
                "output": None,
                "status": "running",
            }
        }

        _process_tool_end(event, data, metadata, tool_call_map)

        assert tool_call_map["tool-1"]["output"] == "result"
        assert tool_call_map["tool-1"]["status"] == "completed"

    def test_process_tool_end_creates_new(self):
        """Test processing tool.end creates new entry if missing."""
        from aiq_api.routes.jobs import _process_tool_end

        event = {"timestamp": "2026-01-22T10:00:01"}
        data = {"id": "tool-2", "name": "other", "data": {"output": "result"}}
        metadata = {"workflow": "agent-1"}
        tool_call_map: dict = {}

        _process_tool_end(event, data, metadata, tool_call_map)

        assert "tool-2" in tool_call_map
        assert tool_call_map["tool-2"]["status"] == "completed"

    def test_process_artifact_update(self):
        """Test processing artifact.update event."""
        from aiq_api.routes.jobs import _process_artifact_update

        event = {"name": "output.md", "timestamp": "2026-01-22T10:00:00"}
        data = {"type": "output", "content": "Report content", "extra": "value"}
        metadata = {"workflow": "agent-1"}
        outputs: list = []
        sources_found: set = set()
        sources_cited: set = set()

        _process_artifact_update(event, data, metadata, outputs, sources_found, sources_cited)

        assert len(outputs) == 1
        assert outputs[0]["type"] == "output"
        assert outputs[0]["content"] == "Report content"
        assert outputs[0]["extra"] == "value"

    def test_process_artifact_update_skips_empty_content(self):
        """Test that empty content is skipped."""
        from aiq_api.routes.jobs import _process_artifact_update

        event = {"name": "empty.md", "timestamp": "2026-01-22T10:00:00"}
        data = {"type": "output", "content": None}
        metadata = {}
        outputs: list = []
        sources_found: set = set()
        sources_cited: set = set()

        _process_artifact_update(event, data, metadata, outputs, sources_found, sources_cited)

        assert len(outputs) == 0

    def test_process_artifact_update_tracks_citation_source(self):
        """Test that citation_source events are tracked."""
        from aiq_api.routes.jobs import _process_artifact_update

        event = {"name": "https://example.com", "timestamp": "2026-01-22T10:00:00"}
        data = {"type": "citation_source", "content": "https://example.com", "url": "https://example.com"}
        metadata = {}
        outputs: list = []
        sources_found: set = set()
        sources_cited: set = set()

        _process_artifact_update(event, data, metadata, outputs, sources_found, sources_cited)

        assert len(sources_found) == 1
        assert "https://example.com" in sources_found
        assert len(sources_cited) == 0

    def test_process_artifact_update_tracks_citation_use(self):
        """Test that citation_use events are tracked."""
        from aiq_api.routes.jobs import _process_artifact_update

        event = {"name": "https://example.com", "timestamp": "2026-01-22T10:00:00"}
        data = {"type": "citation_use", "content": "https://example.com", "url": "https://example.com"}
        metadata = {}
        outputs: list = []
        sources_found: set = set()
        sources_cited: set = set()

        _process_artifact_update(event, data, metadata, outputs, sources_found, sources_cited)

        assert len(sources_cited) == 1
        assert "https://example.com" in sources_cited
        assert len(sources_found) == 0

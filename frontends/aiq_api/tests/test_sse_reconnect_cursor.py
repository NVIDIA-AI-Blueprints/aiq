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

"""Regression test for the SSE reconnect cursor.

Only events backed by a real event-store row may carry an ``id:`` line.
Synthetic control frames must not, or a browser's ``EventSource.lastEventId``
advances past the last persisted event and a reconnect skips the next real
event via the ``WHERE id > :after_id`` query.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aiq_api.routes.jobs import _format_sse  # noqa: E402


def _id_lines(frame: str) -> list[str]:
    return [ln for ln in frame.splitlines() if ln.startswith("id:")]


def test_synthetic_frames_have_no_id():
    """Control frames (no event id) must omit the id: line entirely."""
    for event_type in ("stream.mode", "job.status", "job.shutdown", "job.error"):
        frame = _format_sse(event_type, {"x": 1})
        assert _id_lines(frame) == [], f"{event_type} must not carry an id:"


def test_real_event_carries_its_db_id():
    """A persisted event carries exactly its event-store row id."""
    frame = _format_sse("job.event", {"x": 1}, event_id=42)
    assert _id_lines(frame) == ["id: 42"]


def test_reconnect_cursor_not_polluted_by_synthetic_frames():
    """After a real event (id=5) and several synthetic frames, the only cursor a
    client can adopt is 5 — so a reconnect resumes from 5, not a fabricated id."""
    stream = [
        _format_sse("job.event", {"n": 1}, event_id=5),
        _format_sse("stream.mode", {"mode": "pubsub"}),
        _format_sse("job.status", {"status": "running"}),
        _format_sse("job.shutdown", {"message": "bye"}),
    ]
    ids = [ln for frame in stream for ln in _id_lines(frame)]
    assert ids == ["id: 5"]  # no id: 6, id: 7, ... fabricated by the synthetics


def test_frames_are_well_formed_sse():
    """Both synthetic and real frames stay valid SSE: an event line, a JSON data
    line, and a blank-line terminator — the fix only affects the id: line."""
    synthetic = _format_sse("job.status", {"status": "running"})
    assert synthetic == 'event: job.status\ndata: {"status": "running"}\n\n'

    real = _format_sse("job.event", {"n": 1}, event_id=7)
    assert real == 'id: 7\nevent: job.event\ndata: {"n": 1}\n\n'

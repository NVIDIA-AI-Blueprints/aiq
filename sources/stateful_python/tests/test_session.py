# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the persistent Python process and GSF evidence helpers."""

import json
from pathlib import Path

import pytest
from stateful_python.session import PersistentPythonSession


@pytest.mark.asyncio
async def test_variables_and_dataframes_persist_across_cells(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"version":1,"results":[]}', encoding="utf-8")
    session = PersistentPythonSession(manifest_path=manifest, working_directory=tmp_path)
    try:
        first = json.loads(await session.execute("frame = pd.DataFrame({'value': [1, 2, 3]})\nframe"))
        second = json.loads(await session.execute("frame['value'].sum()"))
    finally:
        await session.aclose()

    assert first["status"] == "ok"
    assert "frame" in first["variables"]
    assert second["status"] == "ok"
    assert second["result"] == "np.int64(6)"


@pytest.mark.asyncio
async def test_gsf_helpers_reload_the_request_manifest(tmp_path: Path) -> None:
    result_path = tmp_path / "gsf_1.json"
    result_path.write_text(
        json.dumps({"sql": "SELECT value", "rows": [{"value": 2}, {"value": 5}]}),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "results": [
                    {
                        "ref": "gsf_1",
                        "question": "Values",
                        "database_name": "example",
                        "request_id": "r1",
                        "row_count": 2,
                        "columns": ["value"],
                        "truncated": False,
                        "path": str(result_path),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    session = PersistentPythonSession(manifest_path=manifest, working_directory=tmp_path)
    try:
        response = json.loads(await session.execute("df = gsf_rows('gsf_1')\n(df['value'].sum(), gsf_sql('gsf_1'))"))
    finally:
        await session.aclose()

    assert response["status"] == "ok"
    assert "7" in response["result"]
    assert "SELECT value" in response["result"]

# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for bounded, content-validated document uploads."""

from __future__ import annotations

import asyncio
import importlib
import os
import zipfile
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import UploadFile
from fastapi.routing import APIRoute
from starlette.datastructures import Headers

from aiq_agent.fastapi_extensions.routes.documents import add_document_routes as add_legacy_document_routes
from aiq_agent.fastapi_extensions.upload_security import UploadLimits
from aiq_agent.fastapi_extensions.upload_security import UploadValidationError
from aiq_agent.fastapi_extensions.upload_security import get_upload_limits
from aiq_agent.fastapi_extensions.upload_security import save_validated_upload
from aiq_agent.fastapi_extensions.upload_security import validate_upload_count
from aiq_api.routes.documents import add_document_routes as add_unified_document_routes

_DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PPTX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _upload(filename: str, content: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def _limits(
    *,
    max_files: int = 2,
    max_file_bytes: int = 1024,
    max_total_bytes: int = 2048,
    accepted_extensions: frozenset[str] = frozenset({".txt", ".pdf"}),
) -> UploadLimits:
    return UploadLimits(
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
        accepted_extensions=accepted_extensions,
    )


def _office_document(
    *,
    required_member: str = "word/document.xml",
    extra_entries: dict[str, bytes] | None = None,
) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr(required_member, b"<document/>")
        for name, content in (extra_entries or {}).items():
            archive.writestr(name, content)
    return output.getvalue()


def _mark_first_zip_entry_encrypted(content: bytes) -> bytes:
    encrypted = bytearray(content)
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        header_offset = encrypted.find(signature)
        assert header_offset >= 0
        field_offset = header_offset + flag_offset
        flags = int.from_bytes(encrypted[field_offset : field_offset + 2], "little") | 0x1
        encrypted[field_offset : field_offset + 2] = flags.to_bytes(2, "little")
    return bytes(encrypted)


def _upload_route(register_routes: Callable[[APIRouter], None]) -> APIRoute:
    router = APIRouter()
    register_routes(router)
    return next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/v1/collections/{collection_name}/documents"
        and "POST" in route.methods
    )


def _upload_endpoint(register_routes: Callable[[APIRouter], None]) -> Callable:
    return _upload_route(register_routes).endpoint


class _FailingIngestor:
    def get_collection(self, collection_name: str) -> object:
        return object()

    def submit_job(self, *args, **kwargs) -> str:
        raise RuntimeError("secret database connection details")


class _SuccessfulIngestor:
    def __init__(self) -> None:
        self.submitted_paths: list[str] = []

    def get_collection(self, collection_name: str) -> object:
        return object()

    def submit_job(self, paths, *args, **kwargs) -> str:
        self.submitted_paths = list(paths)
        return "ingestion-job"

    def get_job_status(self, job_id: str) -> SimpleNamespace:
        return SimpleNamespace(file_details=[])


def test_loads_existing_shared_upload_environment_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FILE_UPLOAD_ACCEPTED_TYPES", "pdf, .DOCX, .txt")
    monkeypatch.setenv("FILE_UPLOAD_MAX_SIZE_MB", "1.5")
    monkeypatch.setenv("FILE_UPLOAD_MAX_FILE_COUNT", "7")

    limits = get_upload_limits()

    assert limits.accepted_extensions == frozenset({".pdf", ".docx", ".txt"})
    assert limits.max_file_bytes == int(1.5 * 1024 * 1024)
    assert limits.max_total_bytes == limits.max_file_bytes
    assert limits.max_files == 7


def test_file_count_accepts_boundary_and_rejects_plus_one() -> None:
    limits = _limits(max_files=2)

    validate_upload_count(2, limits)
    with pytest.raises(UploadValidationError) as exc:
        validate_upload_count(3, limits)

    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_streams_valid_upload_to_private_temp_file() -> None:
    saved = await save_validated_upload(
        _upload("../unsafe/report.txt", b"grounded research", "text/plain"),
        limits=_limits(),
        remaining_total_bytes=2048,
    )
    try:
        assert saved.original_filename == "report.txt"
        assert saved.size_bytes == len(b"grounded research")
        assert Path(saved.path).read_bytes() == b"grounded research"
        assert os.stat(saved.path).st_mode & 0o777 == 0o600
    finally:
        os.unlink(saved.path)


@pytest.mark.asyncio
async def test_accepts_file_at_exact_size_boundary() -> None:
    saved = await save_validated_upload(
        _upload("boundary.txt", b"x" * 10, "text/plain"),
        limits=_limits(max_file_bytes=10),
        remaining_total_bytes=10,
    )
    try:
        assert saved.size_bytes == 10
    finally:
        os.unlink(saved.path)


@pytest.mark.asyncio
async def test_rejects_file_larger_than_server_limit() -> None:
    with pytest.raises(UploadValidationError) as exc:
        await save_validated_upload(
            _upload("large.txt", b"x" * 11, "text/plain"),
            limits=_limits(max_file_bytes=10),
            remaining_total_bytes=100,
        )

    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_rejects_file_that_exceeds_remaining_aggregate_limit() -> None:
    with pytest.raises(UploadValidationError) as exc:
        await save_validated_upload(
            _upload("second.txt", b"x" * 6, "text/plain"),
            limits=_limits(max_file_bytes=10, max_total_bytes=10),
            remaining_total_bytes=5,
        )

    assert exc.value.status_code == 413
    assert exc.value.detail == "Total upload size limit exceeded"


@pytest.mark.asyncio
async def test_rejects_unsupported_extension() -> None:
    with pytest.raises(UploadValidationError) as exc:
        await save_validated_upload(
            _upload("payload.exe", b"MZ", "application/octet-stream"),
            limits=_limits(),
            remaining_total_bytes=2048,
        )

    assert exc.value.status_code == 415


@pytest.mark.asyncio
async def test_rejects_invalid_utf8_after_initial_validation_window() -> None:
    with pytest.raises(UploadValidationError) as exc:
        await save_validated_upload(
            _upload("report.txt", (b"x" * 8192) + b"\xff", "text/plain"),
            limits=_limits(max_file_bytes=16 * 1024),
            remaining_total_bytes=16 * 1024,
        )

    assert exc.value.status_code == 415


@pytest.mark.asyncio
async def test_accepts_docx_with_exact_required_members() -> None:
    saved = await save_validated_upload(
        _upload("report.docx", _office_document(), _DOCX_CONTENT_TYPE),
        limits=_limits(accepted_extensions=frozenset({".docx"})),
        remaining_total_bytes=2048,
    )
    try:
        assert saved.original_filename == "report.docx"
    finally:
        os.unlink(saved.path)


@pytest.mark.asyncio
async def test_accepts_pptx_with_exact_required_members() -> None:
    saved = await save_validated_upload(
        _upload("slides.pptx", _office_document(required_member="ppt/presentation.xml"), _PPTX_CONTENT_TYPE),
        limits=_limits(accepted_extensions=frozenset({".pptx"})),
        remaining_total_bytes=2048,
    )
    try:
        assert saved.original_filename == "slides.pptx"
    finally:
        os.unlink(saved.path)


@pytest.mark.asyncio
async def test_rejects_malformed_office_archive() -> None:
    with pytest.raises(UploadValidationError) as exc:
        await save_validated_upload(
            _upload("report.docx", b"not a ZIP archive", _DOCX_CONTENT_TYPE),
            limits=_limits(accepted_extensions=frozenset({".docx"})),
            remaining_total_bytes=2048,
        )

    assert exc.value.status_code == 415


@pytest.mark.asyncio
async def test_rejects_docx_without_exact_required_document_member() -> None:
    content = _office_document(required_member="word/media/image.png")
    with pytest.raises(UploadValidationError) as exc:
        await save_validated_upload(
            _upload("report.docx", content, _DOCX_CONTENT_TYPE),
            limits=_limits(accepted_extensions=frozenset({".docx"})),
            remaining_total_bytes=2048,
        )

    assert exc.value.status_code == 415


@pytest.mark.asyncio
async def test_rejects_encrypted_office_archive_entry() -> None:
    content = _mark_first_zip_entry_encrypted(_office_document())
    with pytest.raises(UploadValidationError) as exc:
        await save_validated_upload(
            _upload("report.docx", content, _DOCX_CONTENT_TYPE),
            limits=_limits(accepted_extensions=frozenset({".docx"})),
            remaining_total_bytes=2048,
        )

    assert exc.value.status_code == 415
    assert "Encrypted" in exc.value.detail


@pytest.mark.asyncio
async def test_rejects_office_archive_with_zip_bomb_ratio() -> None:
    content = _office_document(extra_entries={"word/large.xml": b"A" * (256 * 1024)})
    with pytest.raises(UploadValidationError) as exc:
        await save_validated_upload(
            _upload("report.docx", content, _DOCX_CONTENT_TYPE),
            limits=_limits(
                max_file_bytes=1024 * 1024,
                max_total_bytes=1024 * 1024,
                accepted_extensions=frozenset({".docx"}),
            ),
            remaining_total_bytes=1024 * 1024,
        )

    assert exc.value.status_code == 415
    assert "compression ratio" in exc.value.detail


@pytest.mark.asyncio
async def test_rejects_declared_mime_mismatch() -> None:
    with pytest.raises(UploadValidationError) as exc:
        await save_validated_upload(
            _upload("report.pdf", b"%PDF-1.7\n", "text/html"),
            limits=_limits(),
            remaining_total_bytes=2048,
        )

    assert exc.value.status_code == 415


@pytest.mark.asyncio
async def test_rejects_content_that_does_not_match_extension() -> None:
    with pytest.raises(UploadValidationError) as exc:
        await save_validated_upload(
            _upload("report.pdf", b"not a PDF", "application/pdf"),
            limits=_limits(),
            remaining_total_bytes=2048,
        )

    assert exc.value.status_code == 415


@pytest.mark.parametrize("register_routes", [add_legacy_document_routes, add_unified_document_routes])
def test_upload_route_documents_security_error_responses(
    register_routes: Callable[[APIRouter], None],
) -> None:
    responses = _upload_route(register_routes).responses

    assert responses[413]["description"] == "Upload size or file-count limit exceeded"
    assert responses[415]["description"] == "Unsupported, malformed, or mismatched file content"


@pytest.mark.parametrize("register_routes", [add_legacy_document_routes, add_unified_document_routes])
@pytest.mark.asyncio
async def test_upload_route_does_not_expose_internal_ingestion_errors(
    register_routes: Callable[[APIRouter], None],
) -> None:
    endpoint = _upload_endpoint(register_routes)

    with pytest.raises(HTTPException) as exc:
        await endpoint(
            collection_name="private",
            files=[_upload("report.txt", b"research", "text/plain")],
            ingestor=_FailingIngestor(),
        )

    assert exc.value.status_code == 500
    assert exc.value.detail == "Failed to submit ingestion job"


@pytest.mark.parametrize("register_routes", [add_legacy_document_routes, add_unified_document_routes])
@pytest.mark.asyncio
async def test_upload_route_cancellation_removes_all_request_owned_temp_files(
    register_routes: Callable[[APIRouter], None],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Cancellation after one saved file removes every path still owned by the request."""
    endpoint = _upload_endpoint(register_routes)
    route_module = importlib.import_module(register_routes.__module__)
    first_path = tmp_path / "first.txt"
    first_path.write_bytes(b"research")
    save_count = 0

    async def save_then_cancel(*_args, on_temp_path_created, **_kwargs):
        nonlocal save_count
        save_count += 1
        path = first_path if save_count == 1 else tmp_path / "second.txt"
        path.write_bytes(b"research")
        on_temp_path_created(str(path))
        if save_count == 1:
            return SimpleNamespace(path=str(path), original_filename="first.txt", size_bytes=8)
        raise asyncio.CancelledError

    monkeypatch.setattr(route_module, "save_validated_upload", save_then_cancel)

    with pytest.raises(asyncio.CancelledError):
        await endpoint(
            collection_name="private",
            files=[
                _upload("first.txt", b"research", "text/plain"),
                _upload("second.txt", b"more", "text/plain"),
            ],
            ingestor=_SuccessfulIngestor(),
        )

    assert not first_path.exists()
    assert not (tmp_path / "second.txt").exists()


@pytest.mark.parametrize("register_routes", [add_legacy_document_routes, add_unified_document_routes])
@pytest.mark.asyncio
async def test_upload_route_success_transfers_temp_file_ownership_to_ingestion(
    register_routes: Callable[[APIRouter], None],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A submitted job retains its input even if the request then finishes."""
    endpoint = _upload_endpoint(register_routes)
    route_module = importlib.import_module(register_routes.__module__)
    submitted_path = tmp_path / "submitted.txt"
    submitted_path.write_bytes(b"research")

    async def save_upload(*_args, on_temp_path_created, **_kwargs):
        on_temp_path_created(str(submitted_path))
        return SimpleNamespace(path=str(submitted_path), original_filename="submitted.txt", size_bytes=8)

    monkeypatch.setattr(route_module, "save_validated_upload", save_upload)
    ingestor = _SuccessfulIngestor()

    response = await endpoint(
        collection_name="private",
        files=[_upload("submitted.txt", b"research", "text/plain")],
        ingestor=ingestor,
    )

    assert response.job_id == "ingestion-job"
    assert ingestor.submitted_paths == [str(submitted_path)]
    assert submitted_path.exists()

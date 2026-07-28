# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Server-side validation and bounded streaming for document uploads."""

from __future__ import annotations

import asyncio
import codecs
import logging
import math
import os
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import aiofiles
from fastapi import UploadFile

logger = logging.getLogger(__name__)

DEFAULT_MAX_UPLOAD_FILES = 10
DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024
DEFAULT_ACCEPTED_UPLOAD_TYPES = frozenset({".pdf", ".docx", ".txt", ".md"})
UPLOAD_READ_CHUNK_BYTES = 1024 * 1024
MAX_OFFICE_ARCHIVE_ENTRIES = 10_000
MAX_OFFICE_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_OFFICE_COMPRESSION_RATIO = 100
_OFFICE_REQUIRED_MEMBERS = {
    ".docx": "word/document.xml",
    ".pptx": "ppt/presentation.xml",
}

_DECLARED_CONTENT_TYPES: dict[str, frozenset[str]] = {
    ".pdf": frozenset({"application/pdf"}),
    ".docx": frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
    ".pptx": frozenset({"application/vnd.openxmlformats-officedocument.presentationml.presentation"}),
    ".txt": frozenset({"text/plain"}),
    ".md": frozenset({"text/markdown", "text/x-markdown", "text/plain"}),
    ".html": frozenset({"text/html"}),
    ".json": frozenset({"application/json", "text/json", "text/plain"}),
    ".csv": frozenset({"text/csv", "application/csv", "text/plain"}),
    ".yaml": frozenset({"application/yaml", "text/yaml", "text/plain"}),
    ".yml": frozenset({"application/yaml", "text/yaml", "text/plain"}),
    ".log": frozenset({"text/plain"}),
    ".png": frozenset({"image/png"}),
    ".jpg": frozenset({"image/jpeg"}),
    ".jpeg": frozenset({"image/jpeg"}),
}
_GENERIC_CONTENT_TYPES = frozenset({"", "application/octet-stream"})
_TEXT_EXTENSIONS = frozenset({".txt", ".md", ".html", ".json", ".csv", ".yaml", ".yml", ".log"})


class UploadValidationError(ValueError):
    """A safely reportable upload rejection."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class UploadLimits:
    """Configured upload resource limits."""

    max_files: int
    max_file_bytes: int
    max_total_bytes: int
    accepted_extensions: frozenset[str]


@dataclass(frozen=True)
class SavedUpload:
    """A validated upload saved to a private temporary file."""

    path: str
    original_filename: str
    size_bytes: int


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ[name])
    except (KeyError, ValueError):
        return default
    if value < 1:
        logger.warning("%s must be positive; using default %d", name, default)
        return default
    return value


def _positive_megabytes_env(name: str, default_bytes: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default_bytes
    try:
        value = float(raw_value)
    except ValueError:
        value = 0
    if not math.isfinite(value) or value <= 0:
        logger.warning("%s must be a positive finite number; using default %d bytes", name, default_bytes)
        return default_bytes
    return int(value * 1024 * 1024)


def get_upload_limits() -> UploadLimits:
    """Load the shared frontend/backend upload limits from environment variables."""
    configured_types = os.environ.get("FILE_UPLOAD_ACCEPTED_TYPES")
    if configured_types is None:
        accepted_extensions = DEFAULT_ACCEPTED_UPLOAD_TYPES
    else:
        accepted_extensions = frozenset(
            extension if extension.startswith(".") else f".{extension}"
            for raw_extension in configured_types.split(",")
            if (extension := raw_extension.strip().lower())
        )
        if not accepted_extensions:
            logger.warning(
                "FILE_UPLOAD_ACCEPTED_TYPES is empty; using default accepted extensions",
            )
            accepted_extensions = DEFAULT_ACCEPTED_UPLOAD_TYPES

    max_bytes = _positive_megabytes_env("FILE_UPLOAD_MAX_SIZE_MB", DEFAULT_MAX_UPLOAD_BYTES)
    return UploadLimits(
        max_files=_positive_int_env("FILE_UPLOAD_MAX_FILE_COUNT", DEFAULT_MAX_UPLOAD_FILES),
        max_file_bytes=max_bytes,
        max_total_bytes=max_bytes,
        accepted_extensions=accepted_extensions,
    )


def validate_upload_count(file_count: int, limits: UploadLimits) -> None:
    """Reject requests that exceed the configured file-count limit."""
    if file_count > limits.max_files:
        raise UploadValidationError(413, f"At most {limits.max_files} files may be uploaded at once")


def _safe_filename(filename: str | None) -> str:
    normalized = (filename or "unknown").replace("\\", "/")
    return Path(normalized).name or "unknown"


def _validate_declared_type(extension: str, content_type: str | None) -> None:
    declared = (content_type or "").split(";", maxsplit=1)[0].strip().lower()
    if declared in _GENERIC_CONTENT_TYPES:
        return
    allowed = _DECLARED_CONTENT_TYPES.get(extension)
    if allowed is None or declared not in allowed:
        raise UploadValidationError(415, f"Content type '{declared}' is not allowed for '{extension}' files")


def _validate_office_archive(path: str, *, extension: str) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_OFFICE_ARCHIVE_ENTRIES:
                raise UploadValidationError(415, "Office document archive structure is invalid")
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise UploadValidationError(415, "Office document archive contains duplicate entries")
            required_members = {"[Content_Types].xml", _OFFICE_REQUIRED_MEMBERS[extension]}
            if not required_members.issubset(names):
                raise UploadValidationError(415, "Office document content does not match its filename extension")
            if any(entry.flag_bits & 0x1 for entry in entries):
                raise UploadValidationError(415, "Encrypted Office documents are not supported")

            total_compressed = 0
            total_uncompressed = 0
            for entry in entries:
                total_compressed += entry.compress_size
                total_uncompressed += entry.file_size
                if entry.file_size and (
                    entry.compress_size == 0 or entry.file_size > entry.compress_size * MAX_OFFICE_COMPRESSION_RATIO
                ):
                    raise UploadValidationError(415, "Office document compression ratio exceeds the safety limit")
            if total_uncompressed > MAX_OFFICE_UNCOMPRESSED_BYTES:
                raise UploadValidationError(415, "Office document expands beyond the supported size limit")
            if total_uncompressed and (
                total_compressed == 0 or total_uncompressed > total_compressed * MAX_OFFICE_COMPRESSION_RATIO
            ):
                raise UploadValidationError(415, "Office document compression ratio exceeds the safety limit")
    except zipfile.BadZipFile as exc:
        raise UploadValidationError(415, "Office document is not a valid archive") from exc


def _validate_file_content(path: str, extension: str) -> None:
    with open(path, "rb") as file_obj:
        header = file_obj.read(8192)
    if not header:
        raise UploadValidationError(415, "Empty documents are not supported")

    if extension == ".pdf":
        if b"%PDF-" not in header[:1024]:
            raise UploadValidationError(415, "PDF content does not match its filename extension")
        return
    if extension == ".docx":
        _validate_office_archive(path, extension=extension)
        return
    if extension == ".pptx":
        _validate_office_archive(path, extension=extension)
        return
    if extension == ".png":
        if not header.startswith(b"\x89PNG\r\n\x1a\n"):
            raise UploadValidationError(415, "PNG content does not match its filename extension")
        return
    if extension in {".jpg", ".jpeg"}:
        if not header.startswith(b"\xff\xd8\xff"):
            raise UploadValidationError(415, "JPEG content does not match its filename extension")
        return
    if extension in _TEXT_EXTENSIONS:
        try:
            decoder = codecs.getincrementaldecoder("utf-8-sig")()
            with open(path, "rb") as file_obj:
                while chunk := file_obj.read(UPLOAD_READ_CHUNK_BYTES):
                    if b"\x00" in chunk:
                        raise UploadValidationError(415, "Text document contains binary data")
                    decoder.decode(chunk, final=False)
                decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            raise UploadValidationError(415, "Text document is not valid UTF-8") from exc
        return

    raise UploadValidationError(415, f"No content validator is available for '{extension}' files")


async def save_validated_upload(
    upload: UploadFile,
    *,
    limits: UploadLimits,
    remaining_total_bytes: int,
    on_temp_path_created: Callable[[str], None] | None = None,
) -> SavedUpload:
    """Stream one upload to disk while enforcing type and byte limits."""
    original_filename = _safe_filename(upload.filename)
    extension = Path(original_filename).suffix.lower()
    if extension not in limits.accepted_extensions:
        raise UploadValidationError(415, f"File type '{extension or '(none)'}' is not allowed")
    _validate_declared_type(extension, upload.content_type)

    effective_limit = min(limits.max_file_bytes, remaining_total_bytes)
    if effective_limit < 1:
        raise UploadValidationError(413, "Total upload size limit exceeded")

    descriptor, path = tempfile.mkstemp(prefix="aiq-upload-", suffix=extension)
    os.close(descriptor)
    size_bytes = 0
    try:
        # Register request ownership before the first await. This closes the
        # cancellation race where the helper creates a file but the caller never
        # receives the SavedUpload return value.
        if on_temp_path_created is not None:
            on_temp_path_created(path)
        async with aiofiles.open(path, "wb") as temp_file:
            while chunk := await upload.read(UPLOAD_READ_CHUNK_BYTES):
                size_bytes += len(chunk)
                if size_bytes > effective_limit:
                    if effective_limit == limits.max_file_bytes:
                        raise UploadValidationError(
                            413,
                            f"File exceeds the maximum upload size of {limits.max_file_bytes} bytes",
                        )
                    raise UploadValidationError(413, "Total upload size limit exceeded")
                await temp_file.write(chunk)

        await asyncio.to_thread(_validate_file_content, path, extension)
        return SavedUpload(path=path, original_filename=original_filename, size_bytes=size_bytes)
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise

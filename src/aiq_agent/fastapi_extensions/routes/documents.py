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

"""Document management endpoints."""

import logging
import os
import tempfile

from fastapi import FastAPI
from fastapi import File
from fastapi import HTTPException
from fastapi import UploadFile

from aiq_agent.knowledge.base import BaseIngestor
from aiq_agent.knowledge.schema import FileInfo
from aiq_agent.knowledge.schema import IngestionJobStatus

from ..models.requests import DeleteFilesRequest
from ..models.requests import UploadResponse

logger = logging.getLogger(__name__)


async def add_document_routes(app: FastAPI, ingestor: BaseIngestor):
    """Add document management routes to the FastAPI app."""

    @app.post(
        "/v1/collections/{collection_name}/documents",
        response_model=UploadResponse,
        status_code=202,
        tags=["documents"],
        summary="Upload documents to a collection",
        description=(
            "Upload files for ingestion into a collection."
            " Returns a job ID to poll ingestion status."
            " Supported formats: PDF, TXT, MD, DOCX, PPTX."
        ),
        responses={
            400: {"description": "No files provided"},
            404: {"description": "Collection not found"},
            500: {"description": "Ingestion failed"},
        },
    )
    async def upload_documents(
        collection_name: str,
        files: list[UploadFile] = File(..., description="Files to upload"),
    ) -> UploadResponse:
        """
        Upload documents to a collection.

        Returns a job ID for polling the ingestion status.
        """
        if not files:
            raise HTTPException(status_code=400, detail="No files provided")

        # Verify collection exists
        collection = ingestor.get_collection(collection_name)
        if collection is None:
            raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' not found")

        temp_paths = []
        original_filenames = []
        try:
            # Save uploaded files to temp location
            # NOTE: Files are NOT deleted here - the ingestion job cleans them up
            # after processing to allow background thread to access them
            for file in files:
                original_filename = file.filename or "unknown"
                original_filenames.append(original_filename)
                suffix = f"_{original_filename}" if original_filename else ""
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    content = await file.read()
                    tmp.write(content)
                    temp_paths.append(tmp.name)
                    logger.debug(f"Saved uploaded file to {tmp.name}")

            # Submit ingestion job (job will clean up temp files after processing)
            # Pass original filenames so file_details uses correct names
            job_id = ingestor.submit_job(
                temp_paths,
                collection_name,
                config={
                    "cleanup_files": True,
                    "original_filenames": original_filenames,
                },
            )

            # Get the job to extract file_ids for the response
            job_status = ingestor.get_job_status(job_id)
            file_ids = [fd.file_id for fd in job_status.file_details]

            logger.info(f"Submitted ingestion job {job_id} for {len(files)} file(s)")

            return UploadResponse(
                job_id=job_id,
                file_ids=file_ids,
                message=f"Ingestion job submitted for {len(files)} file(s)",
            )

        except HTTPException:
            # Clean up on HTTP errors (job not submitted)
            for path in temp_paths:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            raise
        except Exception as e:
            # Clean up on other errors (job not submitted)
            for path in temp_paths:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            logger.error(f"Failed to upload documents: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/collections/{collection_name}/documents",
        response_model=list[FileInfo],
        tags=["documents"],
        summary="List documents in a collection",
        description="Returns all documents in a collection with their metadata and ingestion status.",
        responses={404: {"description": "Collection not found"}},
    )
    async def list_documents(collection_name: str) -> list[FileInfo]:
        """List all documents in a collection."""
        # Verify collection exists
        collection = ingestor.get_collection(collection_name)
        if collection is None:
            raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' not found")

        try:
            return ingestor.list_files(collection_name)
        except Exception as e:
            logger.error(f"Failed to list documents: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.delete(
        "/v1/collections/{collection_name}/documents",
        tags=["documents"],
        summary="Delete files from a collection",
        description="Delete one or more files from a collection by their file IDs.",
        responses={
            404: {"description": "Collection not found"},
            500: {"description": "Backend error during deletion"},
        },
    )
    async def delete_files(
        collection_name: str,
        request: DeleteFilesRequest,
    ) -> dict:
        """Delete files from a collection by ID."""
        # Verify collection exists
        collection = ingestor.get_collection(collection_name)
        if collection is None:
            raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' not found")

        try:
            result = ingestor.delete_files(request.file_ids, collection_name)
            logger.info(f"Deleted {result.get('total_deleted', 0)} files from {collection_name}")
            return result
        except Exception as e:
            logger.error(f"Failed to delete files: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/documents/{job_id}/status",
        response_model=IngestionJobStatus,
        tags=["documents"],
        summary="Get ingestion job status",
        description="Poll the status of a document ingestion job. Includes per-file progress details.",
        responses={404: {"description": "Ingestion job not found"}},
    )
    async def get_job_status(job_id: str) -> IngestionJobStatus:
        """Get the status of an ingestion job."""
        try:
            status = ingestor.get_job_status(job_id)
            if status is None:
                raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

            return status
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get job status: {e}")
            raise HTTPException(status_code=500, detail=str(e))

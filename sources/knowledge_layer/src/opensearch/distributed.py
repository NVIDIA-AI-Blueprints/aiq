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
"""Dask worker entry points for OpenSearch ingestion."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def run_opensearch_ingestion_task(
    config: dict[str, Any],
    files: list[dict[str, Any]],
    collection_name: str,
) -> dict[str, Any]:
    """Run OpenSearch ingestion in a Dask worker process.

    The worker creates its own OpenSearch client so SigV4 credentials are
    resolved in the worker environment, including EKS Pod Identity.
    """
    from knowledge_layer.opensearch.adapter import OpenSearchIngestor

    worker_config = dict(config)
    worker_config["start_ttl_cleanup"] = False
    worker_config["generate_summary"] = False
    worker_config.pop("summary_llm", None)

    ingestor = OpenSearchIngestor(worker_config)
    index_name = ingestor._ensure_index(collection_name)
    total_chunks = 0
    file_results = []

    for file_payload in files:
        temp_path: str | None = None
        file_path = file_payload.get("path")
        file_id = file_payload["file_id"]
        file_name = file_payload["file_name"]
        metadata = file_payload.get("metadata") or {}

        try:
            if file_path is None:
                suffix = file_payload.get("suffix") or Path(file_name).suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(file_payload["data"])
                    temp_path = tmp.name
                    file_path = temp_path

            documents, _ = ingestor._documents_for_file(file_path, file_id, file_name, metadata)
            if not documents:
                file_results.append(
                    {
                        "file_id": file_id,
                        "file_name": file_name,
                        "status": "failed",
                        "chunks_created": 0,
                        "error_message": "No content extracted",
                    }
                )
                continue

            embeddings = ingestor._embed_texts([doc[ingestor.text_field] for doc in documents])
            for doc, embedding in zip(documents, embeddings, strict=True):
                doc[ingestor.vector_field] = embedding

            ingestor._bulk_index_documents(index_name, documents)
            chunks_created = len(documents)
            total_chunks += chunks_created
            file_results.append(
                {
                    "file_id": file_id,
                    "file_name": file_name,
                    "status": "success",
                    "chunks_created": chunks_created,
                }
            )
        except Exception as e:
            logger.exception("OpenSearch Dask ingestion failed for %s", file_name)
            file_results.append(
                {
                    "file_id": file_id,
                    "file_name": file_name,
                    "status": "failed",
                    "chunks_created": 0,
                    "error_message": str(e),
                }
            )
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    try:
        ingestor._update_collection_timestamp(collection_name)
    except Exception:
        logger.warning("Failed to update collection timestamp for %s", collection_name)
    failed_count = sum(1 for item in file_results if item["status"] == "failed")
    all_failed = bool(file_results) and failed_count == len(file_results)
    return {
        "status": "failed" if all_failed else "completed",
        "files": file_results,
        "total_chunks": total_chunks,
        "index_name": index_name,
        "embedding_model": ingestor.embed_model_name,
        "error_message": "All files failed ingestion" if all_failed else None,
    }

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

"""Collection management endpoints."""

import logging

from fastapi import FastAPI
from fastapi import HTTPException

from aiq_agent.knowledge.base import BaseIngestor
from aiq_agent.knowledge.schema import CollectionInfo

from ..models.requests import CreateCollectionRequest

logger = logging.getLogger(__name__)


async def add_collection_routes(app: FastAPI, ingestor: BaseIngestor):
    """Add collection management routes to the FastAPI app."""

    @app.post(
        "/v1/collections",
        response_model=CollectionInfo,
        status_code=201,
        tags=["collections"],
        summary="Create a new collection",
    )
    async def create_collection(request: CreateCollectionRequest) -> CollectionInfo:
        """Create a new collection for storing documents."""
        try:
            return ingestor.create_collection(
                name=request.name,
                description=request.description,
                metadata=request.metadata,
            )
        except Exception as e:
            logger.error(f"Failed to create collection '{request.name}': {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/collections",
        response_model=list[CollectionInfo],
        tags=["collections"],
        summary="List all collections",
    )
    async def list_collections() -> list[CollectionInfo]:
        """List all available collections."""
        try:
            return ingestor.list_collections()
        except Exception as e:
            logger.error(f"Failed to list collections: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/collections/{name}",
        response_model=CollectionInfo,
        tags=["collections"],
        summary="Get collection details",
    )
    async def get_collection(name: str) -> CollectionInfo:
        """Get details for a specific collection."""
        collection = ingestor.get_collection(name)
        if collection is None:
            raise HTTPException(status_code=404, detail=f"Collection '{name}' not found")
        return collection

    @app.delete(
        "/v1/collections/{name}",
        tags=["collections"],
        summary="Delete a collection",
    )
    async def delete_collection(name: str) -> dict:
        """Delete a collection and all its contents."""
        try:
            success = ingestor.delete_collection(name)
            if not success:
                # Adapters return False for any failure (not found, backend error, etc.)
                # Use 500 since we can't distinguish the actual cause
                raise HTTPException(status_code=500, detail=f"Failed to delete collection '{name}'")
            return {"success": True, "collection": name}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to delete collection '{name}': {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get(
        "/v1/knowledge/health",
        tags=["health"],
        summary="Check knowledge backend health",
    )
    async def health_check() -> dict:
        """Check if the knowledge backend is healthy and reachable."""
        try:
            healthy = await ingestor.health_check()
            if not healthy:
                raise HTTPException(status_code=503, detail="Knowledge backend unhealthy")
            return {"status": "healthy", "backend": ingestor.backend_name}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            raise HTTPException(status_code=503, detail=str(e))

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

"""Tests for the OpenSearch Knowledge Layer adapter."""

import asyncio
import threading
import time
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from knowledge_layer.opensearch import adapter as opensearch_adapter
from knowledge_layer.opensearch.adapter import OpenSearchIngestor
from knowledge_layer.opensearch.adapter import OpenSearchRetriever

from aiq_agent.knowledge.schema import Chunk
from aiq_agent.knowledge.schema import ContentType
from aiq_agent.knowledge.schema import FileStatus
from aiq_agent.knowledge.schema import JobState


class FakeOpenSearchIndices:
    def __init__(self, client: "FakeOpenSearchClient"):
        self._client = client

    def exists(self, index: str) -> bool:
        return index in self._client.indexes

    def create(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        with self._client.lock:
            self._client.indexes[index] = body
            self._client.docs.setdefault(index, {})
        return {"acknowledged": True}

    def delete(self, index: str) -> dict[str, Any]:
        with self._client.lock:
            self._client.indexes.pop(index, None)
            self._client.docs.pop(index, None)
        return {"acknowledged": True}

    def get(self, index: str) -> dict[str, Any]:
        with self._client.lock:
            if "*" in index:
                prefix = index.rstrip("*")
                return {
                    name: {"mappings": body.get("mappings", {})}
                    for name, body in self._client.indexes.items()
                    if name.startswith(prefix)
                }
            if index not in self._client.indexes:
                raise KeyError(index)
            return {index: {"mappings": self._client.indexes[index].get("mappings", {})}}

    def put_mapping(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        with self._client.lock:
            mappings = self._client.indexes[index].setdefault("mappings", {})
            if "_meta" in body:
                mappings["_meta"] = body["_meta"]
        return {"acknowledged": True}


class FakeOpenSearchClient:
    def __init__(self):
        self.lock = threading.RLock()
        self.indexes: dict[str, dict[str, Any]] = {}
        self.docs: dict[str, dict[str, dict[str, Any]]] = {}
        self.indices = FakeOpenSearchIndices(self)

    def count(self, index: str) -> dict[str, int]:
        with self.lock:
            return {"count": len(self.docs.get(index, {}))}

    def bulk(self, body: list[dict[str, Any]], refresh: bool = True, request_timeout: int | None = None):
        del refresh, request_timeout
        with self.lock:
            for action, doc in zip(body[0::2], body[1::2], strict=True):
                index = action["index"]["_index"]
                doc_id = action["index"]["_id"]
                self.docs.setdefault(index, {})[doc_id] = doc
        return {"errors": False}

    def search(self, index: str, body: dict[str, Any], request_timeout: int | None = None) -> dict[str, Any]:
        del request_timeout
        with self.lock:
            docs = self.docs.get(index, {})
            aggs = (body or {}).get("aggs") or {}
            if "by_file" in aggs:
                # List-files aggregation path: group by terms field, emit bucket per group.
                field = aggs["by_file"]["terms"].get("field", "file_name")
                source_filter = aggs["by_file"]["aggs"]["doc"]["top_hits"].get("_source")
                grouped: dict[str, list[dict[str, Any]]] = {}
                for doc_id, doc in docs.items():
                    grouped.setdefault(doc.get(field, "unknown"), []).append({"_id": doc_id, "_source": doc})
                buckets = []
                for key, group_docs in grouped.items():
                    ct_counts: dict[str, int] = {}
                    for hit in group_docs:
                        ct = hit["_source"].get("content_type")
                        if ct:
                            ct_counts[ct] = ct_counts.get(ct, 0) + 1
                    buckets.append({
                        "key": key,
                        "doc_count": len(group_docs),
                        "doc": {"hits": {"hits": [{"_source": self._filter_source(group_docs[0]["_source"], source_filter)}]}},
                        "content_types": {"buckets": [{"key": k, "doc_count": v} for k, v in ct_counts.items()]},
                    })
                return {"hits": {"hits": []}, "aggregations": {"by_file": {"buckets": buckets}}}
            hits = []
            for doc_id, source_doc in docs.items():
                source = self._filter_source(source_doc, body.get("_source"))
                hits.append({"_id": doc_id, "_index": index, "_score": 0.87, "_source": source})
            return {"hits": {"hits": hits[: body.get("size", 10)]}}

    def delete_by_query(
        self,
        index: str,
        body: dict[str, Any],
        refresh: bool = True,
        conflicts: str = "proceed",
    ) -> dict[str, int]:
        del refresh, conflicts
        should_terms = body["query"]["bool"]["should"]
        deleted = 0
        with self.lock:
            for doc_id, doc in list(self.docs.get(index, {}).items()):
                if any(self._matches_term(doc, term.get("term", {})) for term in should_terms):
                    self.docs[index].pop(doc_id, None)
                    deleted += 1
        return {"deleted": deleted}

    def ping(self) -> bool:
        return True

    def _filter_source(self, source: dict[str, Any], source_filter: Any) -> dict[str, Any]:
        if isinstance(source_filter, list):
            return {key: source[key] for key in source_filter if key in source}
        if isinstance(source_filter, dict):
            excluded = set(source_filter.get("excludes", []))
            return {key: value for key, value in source.items() if key not in excluded}
        return dict(source)

    def _matches_term(self, doc: dict[str, Any], term: dict[str, Any]) -> bool:
        for key, value in term.items():
            if doc.get(key) == value:
                return True
        return False


class FakeAossTransport:
    def __init__(self):
        self.requests: list[tuple[str, str]] = []

    def perform_request(self, method: str, path: str):
        self.requests.append((method, path))
        return ""


class FakeAossClient:
    def __init__(self):
        self.bulk_body: list[dict[str, Any]] | None = None
        self.bulk_bodies: list[list[dict[str, Any]]] = []
        self.bulk_refresh: bool | str | None = None
        self.search_hits: list[dict[str, Any]] = []
        self.search_responses: list[list[dict[str, Any]]] = []
        self.search_calls = 0
        self.transport = FakeAossTransport()

    def ping(self) -> bool:
        return False

    def bulk(self, body: list[dict[str, Any]], refresh: bool = True, request_timeout: int | None = None):
        del request_timeout
        self.bulk_body = body
        self.bulk_bodies.append(body)
        self.bulk_refresh = refresh
        return {"errors": False}

    def search(self, index: str, body: dict[str, Any], request_timeout: int | None = None) -> dict[str, Any]:
        del index, body, request_timeout
        self.search_calls += 1
        if self.search_responses:
            return {"hits": {"hits": self.search_responses.pop(0)}}
        hits = self.search_hits
        self.search_hits = []
        return {"hits": {"hits": hits}}


class FakeFuture:
    def __init__(self, result: dict[str, Any] | None = None, error: Exception | None = None):
        self._result = result
        self._error = error

    def result(self):
        if self._error:
            raise self._error
        return self._result


class FakeDaskClient:
    def __init__(self):
        self.submissions: list[dict[str, Any]] = []

    def submit(self, fn, config, payloads, collection_name, **kwargs):
        self.submissions.append(
            {
                "fn": fn,
                "config": config,
                "payloads": payloads,
                "collection_name": collection_name,
                "kwargs": kwargs,
            }
        )
        return FakeFuture(
            {
                "status": "completed",
                "files": [
                    {
                        "file_id": payload["file_id"],
                        "file_name": payload["file_name"],
                        "status": "success",
                        "chunks_created": 1,
                    }
                    for payload in payloads
                ],
                "total_chunks": len(payloads),
                "index_name": "aiq-dask-docs",
                "embedding_model": "nvidia/test-embed",
            }
        )


def test_opensearch_backend_registers_with_factory():
    from aiq_agent.knowledge import factory
    from aiq_agent.knowledge.factory import get_ingestor
    from aiq_agent.knowledge.factory import get_retriever

    factory._INGESTOR_INSTANCES.pop("opensearch", None)

    ingestor = get_ingestor("opensearch", {"endpoint": "localhost:9200"})
    retriever = get_retriever("opensearch", {"endpoint": "localhost:9200"})

    assert ingestor.backend_name == "opensearch"
    assert retriever.backend_name == "opensearch"
    assert ingestor.endpoint == "http://localhost:9200"
    assert retriever.endpoint == "http://localhost:9200"


def test_aoss_health_check_falls_back_to_cat_indices():
    ingestor = OpenSearchIngestor({"auth_type": "sigv4", "aws_service": "aoss"})
    fake_client = FakeAossClient()
    ingestor._client = fake_client

    assert asyncio.run(ingestor.health_check())
    assert fake_client.transport.requests == [("GET", "/_cat/indices")]


def test_aoss_bulk_index_omits_document_ids_and_explicit_refresh():
    ingestor = OpenSearchIngestor({"auth_type": "sigv4", "aws_service": "aoss"})
    fake_client = FakeAossClient()
    ingestor._client = fake_client

    ingestor._bulk_index_documents(
        "aiq-aoss-test",
        [
            {
                "chunk_id": "chunk-1",
                "file_id": "file-1",
                "file_name": "doc.txt",
                "content": "hello",
                "embedding": [0.1, 0.2, 0.3, 0.4],
            }
        ],
    )

    assert fake_client.bulk_body is not None
    assert fake_client.bulk_body[0] == {"index": {"_index": "aiq-aoss-test"}}
    assert fake_client.bulk_refresh is False


def test_aoss_delete_searches_then_bulk_deletes_generated_ids():
    ingestor = OpenSearchIngestor({"auth_type": "sigv4", "aws_service": "aoss", "bulk_batch_size": 2})
    fake_client = FakeAossClient()
    fake_client.search_hits = [{"_id": "generated-1"}, {"_id": "generated-2"}]
    ingestor._client = fake_client

    deleted = ingestor._delete_file_documents_for_aoss(
        "aiq-aoss-test",
        {
            "query": {
                "bool": {
                    "should": [{"term": {"file_id": "file-1"}}],
                    "minimum_should_match": 1,
                }
            }
        },
    )

    assert deleted == 2
    assert fake_client.bulk_body == [
        {"delete": {"_index": "aiq-aoss-test", "_id": "generated-1"}},
        {"delete": {"_index": "aiq-aoss-test", "_id": "generated-2"}},
    ]
    assert fake_client.bulk_refresh is False


def test_aoss_delete_stops_after_repeated_stale_hits():
    ingestor = OpenSearchIngestor(
        {
            "auth_type": "sigv4",
            "aws_service": "aoss",
            "bulk_batch_size": 2,
            "aoss_delete_backoff_seconds": 0,
        }
    )
    fake_client = FakeAossClient()
    fake_client.search_responses = [[{"_id": "generated-1"}], [{"_id": "generated-1"}], [{"_id": "generated-1"}]]
    ingestor._client = fake_client

    deleted = ingestor._delete_file_documents_for_aoss(
        "aiq-aoss-test",
        {
            "query": {
                "bool": {
                    "should": [{"term": {"file_id": "file-1"}}],
                    "minimum_should_match": 1,
                }
            }
        },
    )

    assert deleted == 1
    assert fake_client.search_calls == 3
    assert fake_client.bulk_bodies == [[{"delete": {"_index": "aiq-aoss-test", "_id": "generated-1"}}]]


def test_index_name_helpers_are_opensearch_safe():
    assert opensearch_adapter._sanitize_index_part("Tenant A / Session +1") == "tenant-a-session-1"
    assert opensearch_adapter._sanitize_index_part("+++Bad") == "bad"
    assert len(opensearch_adapter._trim_index_name("a" * 300)) <= 255


def test_session_collection_names_are_safe_dynamic_indexes():
    ingestor = OpenSearchIngestor({"index_prefix": "aiq-prod", "start_ttl_cleanup": False})
    collection_name = "s_123E4567-E89B-12D3-A456-426614174000"

    assert ingestor._index_name_for_collection(collection_name) == "aiq-prod-s_123e4567-e89b-12d3-a456-426614174000"


def test_index_mapping_keeps_metadata_strings_filterable():
    ingestor = OpenSearchIngestor({"embedding_dim": 4, "start_ttl_cleanup": False})

    mapping = ingestor._index_mapping("docs")

    assert mapping["mappings"]["dynamic_templates"] == [
        {
            "metadata_strings": {
                "path_match": "metadata.*",
                "match_mapping_type": "string",
                "mapping": {"type": "keyword", "ignore_above": 1024},
            }
        }
    ]


def test_search_body_includes_knn_filter():
    retriever = OpenSearchRetriever({"embedding_dim": 4, "vector_field": "vec"})

    body = retriever._build_search_body([0.1, 0.2, 0.3, 0.4], 3, {"file_name": "report.pdf", "topic": "roadmap"})

    assert body["size"] == 3
    assert body["query"]["knn"]["vec"]["vector"] == [0.1, 0.2, 0.3, 0.4]
    assert body["query"]["knn"]["vec"]["k"] == 3
    assert body["_source"]["excludes"] == ["vec"]
    assert body["query"]["knn"]["vec"]["filter"] == {
        "bool": {
            "filter": [
                {"term": {"file_name": "report.pdf"}},
                {"term": {"metadata.topic": "roadmap"}},
            ]
        }
    }


def test_normalize_maps_opensearch_hit_to_chunk():
    retriever = OpenSearchRetriever({"text_field": "body"})
    chunk = retriever.normalize(
        {
            "_id": "doc-1",
            "_index": "aiq-default",
            "_score": 0.91,
            "_source": {
                "body": "OpenSearch content",
                "file_name": "report.pdf",
                "page_number": 2,
                "content_type": "text",
                "metadata": {"section": "intro"},
            },
        }
    )

    assert isinstance(chunk, Chunk)
    assert chunk.chunk_id == "doc-1"
    assert chunk.content == "OpenSearch content"
    assert chunk.score == 0.91
    assert chunk.content_type == ContentType.TEXT
    assert chunk.display_citation == "report.pdf, p.2"
    assert chunk.metadata["section"] == "intro"
    assert chunk.metadata["index"] == "aiq-default"


def test_ingestion_and_retrieval_with_fake_client(tmp_path):
    fake_client = FakeOpenSearchClient()
    test_file = tmp_path / "doc.txt"
    test_file.write_text(
        "OpenSearch stores document chunks as vectors for AIQ retrieval. "
        "The adapter creates one index per collection and preserves citations.",
        encoding="utf-8",
    )

    ingestor = OpenSearchIngestor(
        {
            "endpoint": "localhost:9200",
            "embedding_dim": 4,
            "chunk_size": 6,
            "chunk_overlap": 1,
            "index_prefix": "aiq-test",
        }
    )
    ingestor._client = fake_client
    ingestor._embed_texts = lambda texts: [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    file_info = ingestor.upload_file(str(test_file), "collection_a", metadata={"tenant": "alpha"})
    deadline = time.time() + 5
    job = ingestor.get_job_status(file_info.metadata["job_id"])
    while time.time() < deadline and not job.is_terminal:
        time.sleep(0.05)
        job = ingestor.get_job_status(file_info.metadata["job_id"])

    assert job.status == JobState.COMPLETED

    status = ingestor.get_file_status(file_info.file_id, "collection_a")
    assert status is not None
    assert status.status == FileStatus.SUCCESS
    assert status.chunk_count > 0

    files = ingestor.list_files("collection_a")
    assert len(files) == 1
    assert files[0].file_name == "doc.txt"
    assert files[0].chunk_count == status.chunk_count
    assert files[0].metadata["tenant"] == "alpha"

    retriever = OpenSearchRetriever(
        {
            "endpoint": "localhost:9200",
            "embedding_dim": 4,
            "index_prefix": "aiq-test",
        }
    )
    retriever._client = fake_client
    retriever._embed_texts = lambda texts: [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    result = asyncio.run(retriever.retrieve("How are chunks stored?", "collection_a", top_k=2))

    assert result.success
    assert result.backend == "opensearch"
    assert result.chunks
    assert result.chunks[0].file_name == "doc.txt"
    assert result.chunks[0].display_citation == "doc.txt"
    assert result.chunks[0].metadata["tenant"] == "alpha"

    assert ingestor.delete_file(file_info.file_id, "collection_a")
    assert ingestor.list_files("collection_a") == []


def test_ttl_cleanup_deletes_only_expired_opensearch_session_indexes():
    fake_client = FakeOpenSearchClient()
    ingestor = OpenSearchIngestor({"index_prefix": "aiq-ttl", "start_ttl_cleanup": False})
    ingestor._client = fake_client
    ingestor._ttl_hours = 24
    ingestor._cleanup_interval_seconds = 3600

    old_collection = "s_old_session"
    new_collection = "s_new_session"
    ingestor.create_collection(old_collection)
    ingestor.create_collection(new_collection)
    old_index = ingestor._index_name_for_collection(old_collection)
    new_index = ingestor._index_name_for_collection(new_collection)
    old_meta = fake_client.indexes[old_index]["mappings"]["_meta"]
    old_meta["updated_at"] = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    new_meta = fake_client.indexes[new_index]["mappings"]["_meta"]
    new_meta["updated_at"] = datetime.now(UTC).isoformat()
    fake_client.indexes["aiq-ttl-unrelated"] = {
        "mappings": {
            "_meta": {
                "backend": "other",
                "collection_name": "unrelated",
                "updated_at": (datetime.now(UTC) - timedelta(hours=25)).isoformat(),
            }
        }
    }

    ingestor._cleanup_expired_collections()

    assert old_index not in fake_client.indexes
    assert new_index in fake_client.indexes
    assert "aiq-ttl-unrelated" in fake_client.indexes


def test_dask_ingestion_submits_bytes_payload_and_updates_job(tmp_path):
    fake_dask = FakeDaskClient()
    fake_client = FakeOpenSearchClient()
    test_file = tmp_path / "dask.txt"
    test_file.write_text("distributed opensearch ingestion", encoding="utf-8")
    ingestor = OpenSearchIngestor(
        {
            "ingestion_mode": "dask",
            "dask_scheduler_address": "tcp://scheduler:8786",
            "dask_file_transfer": "bytes",
            "embed_model": "nvidia/test-embed",
            "start_ttl_cleanup": False,
        }
    )
    ingestor._client = fake_client
    ingestor._create_dask_client = lambda: fake_dask

    job_id = ingestor.submit_job(
        [str(test_file)],
        "docs",
        config={"original_filenames": ["dask.txt"], "metadata": {"tenant": "aws"}},
    )

    deadline = time.time() + 5
    job = ingestor.get_job_status(job_id)
    while time.time() < deadline and not job.is_terminal:
        time.sleep(0.05)
        job = ingestor.get_job_status(job_id)

    assert job.status == JobState.COMPLETED
    assert job.metadata["ingestion_mode"] == "dask"
    assert fake_dask.submissions
    submission = fake_dask.submissions[0]
    assert submission["collection_name"] == "docs"
    assert submission["config"]["start_ttl_cleanup"] is False
    assert "summary_llm" not in submission["config"]
    assert submission["payloads"][0]["file_name"] == "dask.txt"
    assert submission["payloads"][0]["data"] == b"distributed opensearch ingestion"
    assert "path" not in submission["payloads"][0]
    status = ingestor.get_file_status(job.file_details[0].file_id, "docs")
    assert status is not None
    assert status.status == FileStatus.SUCCESS
    assert status.chunk_count == 1


def test_dask_ingestion_submission_failure_marks_job_failed(tmp_path):
    test_file = tmp_path / "dask.txt"
    test_file.write_text("distributed opensearch ingestion", encoding="utf-8")
    ingestor = OpenSearchIngestor(
        {
            "ingestion_mode": "dask",
            "dask_scheduler_address": "tcp://scheduler:8786",
            "start_ttl_cleanup": False,
        }
    )
    ingestor._create_dask_client = lambda: (_ for _ in ()).throw(RuntimeError("scheduler unavailable"))

    job_id = ingestor.submit_job([str(test_file)], "docs")
    job = ingestor.get_job_status(job_id)

    assert job.status == JobState.FAILED
    assert "scheduler unavailable" in job.error_message


def test_dask_worker_task_constructs_backend_in_worker(monkeypatch):
    from knowledge_layer.opensearch.distributed import run_opensearch_ingestion_task

    captured: dict[str, Any] = {}

    class WorkerIngestor:
        def __init__(self, config: dict[str, Any]):
            captured["config"] = config
            self.text_field = "content"
            self.vector_field = "embedding"
            self.embed_model_name = config["embed_model"]

        def _ensure_index(self, collection_name: str) -> str:
            captured["collection_name"] = collection_name
            return "aiq-docs"

        def _documents_for_file(
            self,
            file_path: str,
            file_id: str,
            file_name: str,
            file_metadata: dict[str, Any] | None = None,
        ):
            captured["worker_file_exists"] = Path(file_path).exists()
            return (
                [
                    {
                        "chunk_id": "chunk-1",
                        "file_id": file_id,
                        "file_name": file_name,
                        "content": Path(file_path).read_text(encoding="utf-8"),
                        "metadata": file_metadata or {},
                    }
                ],
                "summary",
            )

        def _embed_texts(self, texts: list[str]) -> list[list[float]]:
            captured["texts"] = texts
            return [[0.1, 0.2, 0.3, 0.4]]

        def _bulk_index_documents(self, index_name: str, documents: list[dict[str, Any]]) -> None:
            captured["index_name"] = index_name
            captured["documents"] = documents

        def _update_collection_timestamp(self, collection_name: str) -> None:
            captured["updated_collection"] = collection_name

    monkeypatch.setattr(opensearch_adapter, "OpenSearchIngestor", WorkerIngestor)

    result = run_opensearch_ingestion_task(
        {
            "auth_type": "sigv4",
            "aws_service": "aoss",
            "aws_region": "us-east-1",
            "embed_model": "nvidia/test-embed",
            "summary_llm": "not-worker-serializable",
        },
        [
            {
                "file_id": "file-1",
                "file_name": "worker.txt",
                "data": b"worker opensearch ingestion",
                "suffix": ".txt",
                "metadata": {"suite": "dask"},
            }
        ],
        "docs",
    )

    assert result["status"] == "completed"
    assert captured["config"]["auth_type"] == "sigv4"
    assert captured["config"]["aws_service"] == "aoss"
    assert captured["config"]["start_ttl_cleanup"] is False
    assert captured["config"]["generate_summary"] is False
    assert "summary_llm" not in captured["config"]
    assert captured["worker_file_exists"] is True
    assert captured["documents"][0]["embedding"] == [0.1, 0.2, 0.3, 0.4]
    assert captured["documents"][0]["metadata"]["suite"] == "dask"


def test_setup_backend_passes_opensearch_yaml_config(monkeypatch):
    pytest.importorskip("nat")
    from knowledge_layer.register import KnowledgeRetrievalConfig
    from knowledge_layer.register import _setup_backend

    monkeypatch.setenv("OPENSEARCH_USERNAME", "env-user")
    monkeypatch.setenv("OPENSEARCH_PASSWORD", "env-pass")

    config = KnowledgeRetrievalConfig(
        backend="opensearch",
        collection_name="docs",
        opensearch_url="search.example.com",
        opensearch_auth_type="sigv4",
        opensearch_aws_region="us-west-2",
        opensearch_aws_service="aoss",
        opensearch_index_prefix="tenant-a",
        opensearch_embedding_dim=4,
        opensearch_chunk_size=200,
        opensearch_chunk_overlap=20,
        embed_model="nvidia/test-embed",
        embed_base_url="https://integrate.example/v1",
    )

    backend, backend_config = _setup_backend(config)

    assert backend == "opensearch"
    assert backend_config["endpoint"] == "search.example.com"
    assert backend_config["auth_type"] == "sigv4"
    assert backend_config["aws_region"] == "us-west-2"
    assert backend_config["aws_service"] == "aoss"
    assert backend_config["index_prefix"] == "tenant-a"
    assert backend_config["embedding_dim"] == 4
    assert backend_config["chunk_size"] == 200
    assert backend_config["chunk_overlap"] == 20
    assert backend_config["embed_model"] == "nvidia/test-embed"
    assert backend_config["embed_base_url"] == "https://integrate.example/v1"


def test_setup_backend_uses_opensearch_environment_defaults(monkeypatch):
    pytest.importorskip("nat")
    from knowledge_layer.register import KnowledgeRetrievalConfig
    from knowledge_layer.register import _setup_backend

    monkeypatch.setenv("OPENSEARCH_URL", "https://env.us-east-1.aoss.amazonaws.com")
    monkeypatch.setenv("OPENSEARCH_AUTH_TYPE", "sigv4")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("OPENSEARCH_AWS_SERVICE", "aoss")
    monkeypatch.setenv("OPENSEARCH_INDEX_PREFIX", "aiq-env")
    monkeypatch.setenv("OPENSEARCH_INGESTION_MODE", "auto")
    monkeypatch.setenv("NAT_DASK_SCHEDULER_ADDRESS", "tcp://scheduler:8786")
    monkeypatch.setenv("OPENSEARCH_DASK_FILE_TRANSFER", "paths")

    config = KnowledgeRetrievalConfig(backend="opensearch")
    backend, backend_config = _setup_backend(config)

    assert backend == "opensearch"
    assert backend_config["endpoint"] == "https://env.us-east-1.aoss.amazonaws.com"
    assert backend_config["auth_type"] == "sigv4"
    assert backend_config["aws_region"] == "us-east-1"
    assert backend_config["aws_service"] == "aoss"
    assert backend_config["index_prefix"] == "aiq-env"
    assert backend_config["ingestion_mode"] == "auto"
    assert backend_config["dask_scheduler_address"] == "tcp://scheduler:8786"
    assert backend_config["dask_file_transfer"] == "paths"


def test_ingestor_embed_raises_when_hosted_api_and_missing_key(monkeypatch):
    """Hosted NVIDIA API with no key should raise a clear error before HTTP."""
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    from knowledge_layer.opensearch.adapter import OpenSearchIngestor

    ingestor = OpenSearchIngestor({
        "endpoint": "http://localhost:9200",
        "auth_type": "none",
        "embed_base_url": "https://integrate.api.nvidia.com/v1",
        "start_ttl_cleanup": False,
    })
    with pytest.raises(RuntimeError, match="NVIDIA_API_KEY"):
        ingestor._embed_texts(["hello world"])


def test_ingestor_embed_allows_local_nim_without_key(monkeypatch):
    """Self-hosted NIM with no key should pass through without complaint."""
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    from knowledge_layer.opensearch.adapter import OpenSearchIngestor

    ingestor = OpenSearchIngestor({
        "endpoint": "http://localhost:9200",
        "auth_type": "none",
        "embed_base_url": "http://nim-embed.ns-nim.svc.cluster.local:8000/v1",
        "start_ttl_cleanup": False,
    })
    class _FakeOpenAI:
        def __init__(self, base_url, api_key):
            self.embeddings = type("E", (), {"create": staticmethod(lambda **kw: type("R", (), {"data": [type("D", (), {"embedding": [0.0] * 4})()]})())})()
    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    result = ingestor._embed_texts(["hello"])
    assert result == [[0.0, 0.0, 0.0, 0.0]]


def test_ensure_index_recovers_when_concurrent_create_races(monkeypatch):
    """Two concurrent jobs both see not-exists and both call create(); the
    losing call must not raise — re-check exists() and treat the index as
    ready if another worker already created it."""
    from opensearchpy.exceptions import RequestError
    from knowledge_layer.opensearch.adapter import OpenSearchIngestor

    ingestor = OpenSearchIngestor({
        "endpoint": "http://localhost:9200",
        "auth_type": "none",
        "start_ttl_cleanup": False,
    })

    exists_calls: list[str] = []

    def fake_exists(index: str) -> bool:
        # First call (pre-create) returns False; subsequent re-check after the
        # race loss returns True (the winning worker has created it).
        exists_calls.append(index)
        return len(exists_calls) >= 2

    def fake_create(index: str, body: dict) -> None:
        raise RequestError(
            400,
            "resource_already_exists_exception",
            {
                "error": {
                    "type": "resource_already_exists_exception",
                    "reason": f"index [{index}/abc] already exists",
                }
            },
        )

    fake_client = type("C", (), {})()
    fake_client.indices = type(
        "I", (), {"exists": staticmethod(fake_exists), "create": staticmethod(fake_create)}
    )()
    monkeypatch.setattr(ingestor, "_get_client", lambda: fake_client)

    # Must not raise — race recovery should swallow the exists exception.
    result = ingestor._ensure_index("smoke")
    assert result.startswith("aiq-smoke")
    assert len(exists_calls) == 2, "expected pre-create check + post-failure recovery check"


def test_list_files_aggregates_and_avoids_10k_hit_truncation(monkeypatch):
    """list_files must request 0 hits and aggregate by file_name so collections
    with more than the 10k index.max_result_window are not silently truncated.
    Chunk counts must come from bucket doc_count, not from counted hits."""
    from knowledge_layer.opensearch.adapter import OpenSearchIngestor

    ingestor = OpenSearchIngestor({
        "endpoint": "http://localhost:9200",
        "auth_type": "none",
        "start_ttl_cleanup": False,
    })

    captured_body: dict[str, Any] = {}

    def fake_search(index: str, body: dict[str, Any]) -> dict[str, Any]:
        captured_body.update(body)
        return {
            "hits": {"hits": []},
            "aggregations": {
                "by_file": {
                    "buckets": [
                        {
                            "key": "huge.pdf",
                            "doc_count": 50_000,
                            "doc": {
                                "hits": {
                                    "hits": [
                                        {
                                            "_source": {
                                                "file_id": "f1",
                                                "file_name": "huge.pdf",
                                                "file_size": 12_345_678,
                                                "created_at": "2026-05-01T00:00:00Z",
                                                "updated_at": "2026-05-01T00:01:00Z",
                                                "metadata": {"k": "v"},
                                            }
                                        }
                                    ]
                                }
                            },
                            "content_types": {"buckets": [{"key": "text", "doc_count": 50_000}]},
                        },
                        {
                            "key": "small.md",
                            "doc_count": 3,
                            "doc": {
                                "hits": {
                                    "hits": [
                                        {
                                            "_source": {
                                                "file_id": "f2",
                                                "file_name": "small.md",
                                                "file_size": 1234,
                                                "created_at": "2026-05-02T00:00:00Z",
                                                "updated_at": "2026-05-02T00:00:30Z",
                                                "metadata": {},
                                            }
                                        }
                                    ]
                                }
                            },
                            "content_types": {"buckets": []},
                        },
                    ]
                }
            },
        }

    fake_client = type("C", (), {})()
    fake_client.indices = type("I", (), {"exists": staticmethod(lambda index: True)})()
    fake_client.search = staticmethod(fake_search)
    monkeypatch.setattr(ingestor, "_get_client", lambda: fake_client)

    files = ingestor.list_files("smoke")

    assert captured_body.get("size") == 0, "search body must request 0 hits and aggregate instead"
    assert "by_file" in (captured_body.get("aggs") or {}), "must aggregate by file_name"

    by_name = {f.file_name: f for f in files}
    assert set(by_name) == {"huge.pdf", "small.md"}
    # 50 000 > 10 000 max_result_window — only an aggregation can carry this count.
    assert by_name["huge.pdf"].chunk_count == 50_000
    assert by_name["huge.pdf"].file_size == 12_345_678
    assert by_name["huge.pdf"].metadata["content_types"] == ["text"]
    assert by_name["small.md"].chunk_count == 3


def test_ensure_index_reraises_when_create_fails_for_other_reasons(monkeypatch):
    """If create() fails for a non-race reason (index still missing after the
    failure), the original exception must propagate so the caller can fail
    the job rather than silently swallowing it."""
    from opensearchpy.exceptions import RequestError
    from knowledge_layer.opensearch.adapter import OpenSearchIngestor

    ingestor = OpenSearchIngestor({
        "endpoint": "http://localhost:9200",
        "auth_type": "none",
        "start_ttl_cleanup": False,
    })

    def fake_exists(index: str) -> bool:  # Always not-exists, even after failure
        return False

    def fake_create(index: str, body: dict) -> None:
        raise RequestError(
            400,
            "invalid_index_name_exception",
            {"error": {"type": "invalid_index_name_exception", "reason": "bad name"}},
        )

    fake_client = type("C", (), {})()
    fake_client.indices = type(
        "I", (), {"exists": staticmethod(fake_exists), "create": staticmethod(fake_create)}
    )()
    monkeypatch.setattr(ingestor, "_get_client", lambda: fake_client)

    with pytest.raises(RequestError):
        ingestor._ensure_index("smoke")

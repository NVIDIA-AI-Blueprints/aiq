<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
# Knowledge Layer

A pluggable abstraction for document ingestion and retrieval. Swap backends without changing application code.

> **Looking to build a custom backend adapter?** Refer to the [SDK Reference](../reference/knowledge-layer-sdk.md) for data schemas, interfaces, and implementation examples.

## Key Features

- **Rich Output Schema** - `Chunk` model with 12 fields: content types, citations, images, structured data
- **Full Ingestion Pipeline** - `BaseIngestor` with async job tracking and status polling
- **Collection Management** - create/delete/list collections per session or use case
- **File Management** - upload/delete/list files with status tracking (UPLOADING -> INGESTING -> SUCCESS/FAILED)
- **Content Typing** - TEXT, TABLE, CHART, IMAGE enums for frontend rendering
- **Backend Agnostic** - Swap between local (LlamaIndex) and hosted (RAG Blueprint) without core agent code changes

---

## Table of Contents

- [Available Backends](#available-backends)
- [Quick Start](#quick-start)
- [Usage](#usage)
  - [With YAML Config](#with-nemo-agent-toolkit-yaml-config---recommended)
  - [Multimodal Extraction](#multimodal-extraction-llamaindex-only)
  - [Document Summaries](#document-summaries)
  - [Supported File Types](#supported-file-types)
  - [Programmatic Usage](#programmatic-usage)
- [Web UI Mode](#web-ui-mode)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Related Documentation](#related-documentation)

---

## Available Backends

| Backend | Config Name | Mode | Vector Store | Best For |
|---------|-------------|------|--------------|----------|
| `llamaindex` | `"llamaindex"` | Local Library | ChromaDB | Dev, prototyping, macOS/Linux |
| `foundational_rag` | `"foundational_rag"` | Hosted Service | Remote Milvus | Production, multi-user |

**Local Library Mode** - Everything runs in your Python process. No external services needed.
- **`llamaindex`** - LlamaIndex + ChromaDB. Lightweight, great for development. Works on macOS and Linux.

**Hosted Service Mode** - Connects to deployed services through HTTP. Requires infrastructure but scales better.
- **`foundational_rag`** - Connects to [NVIDIA RAG Blueprint](https://github.com/NVIDIA-AI-Blueprints/rag) through HTTP.
  - [Deployment Guide](https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/deploy-docker-self-hosted.md)
  - Backend-specific documentation: `sources/knowledge_layer/src/foundational_rag/README.md`

---

## Quick Start

Before you begin documentation ingestion and retrieval, run the following commands to install the backend knowledge layer.

> **Prerequisites:** Complete the main setup first (refer to the project `README.md`): clone repo, run `./scripts/setup.sh`, obtain API keys.

> **Tip:** Instead of exporting env vars each time, add them to `deploy/.env` and use `dotenv -f deploy/.env run <command>` to run any command with those vars loaded automatically.

```bash
# 1. Set up environment variables (add to deploy/.env to avoid exporting each time)
export NVIDIA_API_KEY=nvapi-your-key-here

# 2. Install backend (choose one)
uv pip install -e "sources/knowledge_layer[llamaindex]"        # Recommended for local dev - works on macOS/Linux
uv pip install -e "sources/knowledge_layer[foundational_rag]"  # Requires deployed server
```

> **New to Knowledge Layer?** Start with `llamaindex` - it requires no external services and works on macOS and Linux.

```bash
# 3. Verify
python -c "from aiq_agent.knowledge import get_retriever; print('OK')"
```

---

## Usage

To use the knowledge layer, you can change the variables in the YAML config file.

### With NeMo Agent Toolkit (YAML Config) - Recommended

The `knowledge_retrieval` function is registered as a NeMo Agent Toolkit function type. **YAML config is the recommended single source of truth** for workflow configuration:

```yaml
# Example knowledge_retrieval function configuration
functions:
  knowledge_search:
    _type: knowledge_retrieval      # NeMo Agent Toolkit function type
    backend: llamaindex             # Required: which adapter to use
    collection_name: my_docs        # Required: target collection
    top_k: 5                        # Results to return

    # Summarization options (optional, all backends):
    # generate_summary: true                  # Generate one-sentence summary per document
    # summary_model: nemotron_llm             # LLM reference from llms: section (required if generate_summary is true)
    # summary_db: sqlite+aiosqlite:///./summaries.db  # Summary storage (SQLite or PostgreSQL)

    # Backend-specific options (each backend uses different fields):
    chroma_dir: /tmp/chroma_data              # llamaindex only
    rag_url: http://localhost:8081/v1         # foundational_rag only
    ingest_url: http://localhost:8082/v1      # foundational_rag only
    timeout: 120                              # foundational_rag only
    # verify_ssl: true                        # foundational_rag only (set false for self-signed certs)
```

You can also use environment variable substitution in YAML for sensitive values:

```yaml
functions:
  knowledge_search:
    _type: knowledge_retrieval
    backend: foundational_rag
    rag_url: ${RAG_SERVER_URL:-http://localhost:8081/v1}
    collection_name: ${COLLECTION_NAME:-default}
```

> **Note:** Each backend has different config options. Only the options matching your `backend` value are used - others are ignored (a warning will be logged). To add new config fields, edit `KnowledgeRetrievalConfig` in `sources/knowledge_layer/src/register.py`.

### Switching Backends

To switch backends, change the `backend` field and its corresponding options. Here are complete examples for each backend:

**LlamaIndex (ChromaDB) - macOS/Linux**
```yaml
functions:
  knowledge_search:
    _type: knowledge_retrieval
    backend: llamaindex
    collection_name: my_docs
    top_k: 5
    chroma_dir: /tmp/chroma_data    # ChromaDB persistence directory
```

**Foundational RAG (Hosted Server)**
```yaml
functions:
  knowledge_search:
    _type: knowledge_retrieval
    backend: foundational_rag
    collection_name: my_docs
    top_k: 5
    rag_url: http://your-server:8081/v1      # Rag server
    ingest_url: http://your-server:8082/v1   # Ingestion server
    timeout: 120
```

#### Multimodal Extraction (LlamaIndex Only)

By default, LlamaIndex ingests text only. To extract tables and images from PDFs, set environment variables before starting the server:

| Variable | Default | Description |
|----------|---------|-------------|
| `AIQ_EXTRACT_TABLES` | `false` | Extract tables from PDFs as markdown using pdfplumber |
| `AIQ_EXTRACT_IMAGES` | `false` | Extract embedded images from PDFs and caption them with a VLM |
| `AIQ_EXTRACT_CHARTS` | `false` | Classify images as charts and extract structured data (chart type, axis labels, data points) |
| `AIQ_VLM_MODEL` | `nvidia/nemotron-nano-12b-v2-vl` | NVIDIA VLM model for image captioning |

When enabled, the startup log shows the active mode:

```
LlamaIndexIngestor initialized: persist_dir=/app/data/chroma_data, mode=text + tables + images
```

> **Note:** `AIQ_EXTRACT_IMAGES` and `AIQ_EXTRACT_CHARTS` work together. If both are enabled, each image is classified by the VLM as either a chart or a regular image. Foundational RAG handles multimodal extraction server-side, so these flags only apply to the LlamaIndex backend.

#### Document Summaries

Document summaries help research agents understand what files are available before making tool calls. When enabled, the knowledge layer generates a one-sentence summary during ingestion and injects it into agent system prompts.

```yaml
llms:
  summary_llm:
    _type: nim
    model_name: nvidia/nemotron-mini-4b-instruct
    base_url: "https://integrate.api.nvidia.com/v1"
    temperature: 0.3
    max_tokens: 150

functions:
  knowledge_search:
    _type: knowledge_retrieval
    generate_summary: true
    summary_model: summary_llm     # Required: LLM reference from llms: section
    summary_db: ${AIQ_SUMMARY_DB:-sqlite+aiosqlite:///./summaries.db}
```

When `generate_summary: true`, you **must** configure `summary_model` to reference an LLM from the `llms:` section. For production deployments, use PostgreSQL for `summary_db` instead of SQLite.

For details on how summaries are stored, how agents consume them, and how to implement summaries in custom backends, refer to the [SDK Reference - Document Summaries](../reference/knowledge-layer-sdk.md#document-summaries).

#### Supported File Types

File type support depends on the configured backend:

| Backend | Supported Types |
|---------|----------------|
| **LlamaIndex** | PDF, TXT, MD, DOCX, HTML, JSON, CSV |
| **Foundational RAG** | PDF, DOCX, PPTX, TXT, MD, HTML, images (PNG, JPG) |

For custom backends, supported types are determined by the backend implementation.

### Programmatic Usage

```python
# Import the adapter module to trigger registration
from knowledge_layer.llamaindex import LlamaIndexRetriever, LlamaIndexIngestor

# Use the factory to get instances
from aiq_agent.knowledge import get_retriever, get_ingestor

# Ingest documents
ingestor = get_ingestor("llamaindex", config={"persist_dir": "/tmp/chroma"})
ingestor.create_collection("my_docs")
file_info = ingestor.upload_file("doc.pdf", "my_docs")

# Check ingestion status
status = ingestor.get_file_status(file_info.file_id, "my_docs")
print(f"Status: {status.status}")  # UPLOADING, INGESTING, SUCCESS, FAILED

# Retrieve
retriever = get_retriever("llamaindex", config={"persist_dir": "/tmp/chroma"})
result = await retriever.retrieve("query", "my_docs", top_k=5)
for chunk in result.chunks:
    print(f"{chunk.display_citation}: {chunk.content[:100]}")
```

---

## Web UI Mode

Run the backend API server and frontend UI together for document upload, collection management, and chat.

### Start Backend

```bash
# Foundational RAG example (requires deployed FRAG server)
# Set env vars: RAG_SERVER_URL, RAG_INGEST_URL, NVIDIA_API_KEY
nat serve --config_file configs/config_web_frag.yml --host 0.0.0.0 --port 8000
```

### Start Frontend

```bash
cd frontends/ui
npm run dev
```

Open `http://localhost:3000` in your browser.

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/collections` | Create collection |
| `GET` | `/v1/collections` | List collections |
| `GET` | `/v1/collections/{name}` | Get collection details |
| `DELETE` | `/v1/collections/{name}` | Delete collection |
| `POST` | `/v1/collections/{name}/documents` | Upload files |
| `GET` | `/v1/collections/{name}/documents` | List documents in collection |
| `DELETE` | `/v1/collections/{name}/documents` | Delete files |
| `GET` | `/v1/documents/{job_id}/status` | Poll ingestion status |
| `GET` | `/v1/knowledge/health` | Check knowledge backend health |

### Session Collections

Both LlamaIndex and Foundational RAG support session-based collections (`s_<uuid>`) created by the UI. Each browser session gets its own isolated collection.

### TTL Cleanup

Collections inactive for 24 hours are auto-deleted based on `updated_at` timestamp. Background thread runs hourly.

```python
COLLECTION_TTL_HOURS = 24
TTL_CLEANUP_INTERVAL_SECONDS = 3600
```

---

## Architecture

### Core Library (`src/aiq_agent/knowledge/`)

```
src/aiq_agent/knowledge/
    __init__.py        # Exports: Chunk, get_retriever, get_ingestor, etc.
    base.py            # Abstract classes: BaseRetriever, BaseIngestor
    schema.py          # Data models: Chunk, RetrievalResult, FileInfo, CollectionInfo
    factory.py         # Registry + factory: register_retriever(), get_retriever()
    summary_store.py   # SQLAlchemy-backed document summary persistence
```

| File | Purpose |
|------|---------|
| `base.py` | Defines the interface all backends must implement |
| `schema.py` | Universal data models - backends convert native formats to these |
| `factory.py` | Registration decorators + factory functions for instantiation |
| `summary_store.py` | Persistent storage for document summaries (SQLite/PostgreSQL) |

### Backend Adapters (`sources/knowledge_layer/src/`)

```
sources/knowledge_layer/src/
    <backend_name>/
        __init__.py      # Imports adapter to trigger registration
        adapter.py       # @register_retriever/@register_ingestor decorated classes
        README.md        # Backend-specific documentation
        pyproject.toml   # Optional: isolated dependencies
```

### How Registration Works

Backends register themselves using decorators when their module is imported:

```python
# In adapter.py
from aiq_agent.knowledge.factory import register_retriever, register_ingestor

@register_retriever("my_backend")  # Registration name used in config
class MyRetriever(BaseRetriever):
    ...

@register_ingestor("my_backend")
class MyIngestor(BaseIngestor):
    ...
```

The registration name (for example, `"my_backend"`) is what you use in:
- YAML config: `backend: my_backend`
- Factory calls: `get_retriever("my_backend")`

**Important:** The adapter module must be imported for registration to happen. This is why:
1. `__init__.py` imports the adapter classes
2. The NeMo Agent Toolkit function imports from `knowledge_layer.<backend>.adapter`

### NeMo Agent Toolkit Integration

```
sources/knowledge_layer/src/
    register.py      # @register_function exposes retrieval to agents
```

The `register.py` defines `KnowledgeRetrievalConfig` which maps YAML config to backend instantiation.

---

## Configuration

### Configuration Precedence

Configuration values are resolved in the following order (highest to lowest priority):

1. **Explicit parameter** - Values passed directly to factory functions (`get_retriever("llamaindex")`)
2. **YAML config file** - The `backend:` field and other options in your workflow config (recommended)
3. **Environment variables** - `KNOWLEDGE_RETRIEVER_BACKEND`, `RAG_SERVER_URL`, etc.
4. **Hardcoded defaults** - Built-in fallback values

**Recommendation:** Use YAML config as your single source of truth for workflow configuration. Environment variables are useful for:
- Container deployments (12-factor app pattern)
- CI/CD overrides
- Secrets management (API keys)

### Environment Variables

| Variable | Backend | Description |
|----------|---------|-------------|
| `NVIDIA_API_KEY` | All | Required for embeddings/VLM |
| `KNOWLEDGE_RETRIEVER_BACKEND` | All | Default retriever backend (fallback if not in YAML) |
| `KNOWLEDGE_INGESTOR_BACKEND` | All | Default ingestor backend (fallback if not in YAML) |
| `AIQ_CHROMA_DIR` | llamaindex | ChromaDB persistence path |
| `RAG_SERVER_URL` | foundational_rag | Query server URL (port 8081) |
| `RAG_INGEST_URL` | foundational_rag | Ingestion server URL (port 8082) |
| `COLLECTION_NAME` | All | Default collection name |

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `Unknown backend: my_backend` | Adapter not imported/registered | Import the adapter module before calling factory |
| `ormsgpack` attribute error | Version conflict with [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) | `uv pip install "ormsgpack>=1.5.0"` |
| Empty retrieval results | Collection empty | Run ingestion first, verify collection name matches |
| Job status 404 | Different process/instance | Factory uses singletons - ensure same process |
| `milvus-lite` required | Missing dependency | `uv pip install "pymilvus[milvus_lite]"` |
| Backend registered twice | Module imported multiple times | Normal - factory logs warning but works fine |

### Debug Registration

```python
# Check what's registered
from aiq_agent.knowledge.factory import list_retrievers, list_ingestors, get_knowledge_layer_config

print("Retrievers:", list_retrievers())
print("Ingestors:", list_ingestors())
print("Full config:", get_knowledge_layer_config())
```

---

## Related Documentation

| Document | Description |
|----------|-------------|
| [SDK Reference](../reference/knowledge-layer-sdk.md) | Build custom backend adapters - data schemas, interfaces, full implementation example |
| Foundational RAG Setup (`sources/knowledge_layer/src/foundational_rag/README.md`) | Production deployment with NVIDIA RAG Blueprint |

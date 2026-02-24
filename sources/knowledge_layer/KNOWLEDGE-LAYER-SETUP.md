# Knowledge Layer

A pluggable abstraction for document ingestion and retrieval. Swap backends without changing application code.

## Key Features

- **Rich Output Schema** - `Chunk` model with 15+ fields: content types, citations, images, structured data
- **Full Ingestion Pipeline** - `BaseIngestor` with async job tracking and status polling
- **Collection Management** - create/delete/list collections per session or use case
- **File Management** - upload/delete/list files with status tracking (UPLOADING → INGESTING → SUCCESS/FAILED)
- **Content Typing** - TEXT, TABLE, CHART, IMAGE enums for frontend rendering
- **Backend Agnostic** - Swap between local (LlamaIndex) and hosted (RAG Blueprint) without core agent code changes

---

## Table of Contents

- [Available Backends](#available-backends)
- [Quick Start](#quick-start)
- [Usage](#usage)
  - [With YAML Config](#with-nemo-agent-toolkit-yaml-config---recommended)
  - [Programmatic Usage](#programmatic-usage)
- [Web UI Mode](#web-ui-mode)
- [Building a Custom Backend](#building-a-custom-backend)
- [Architecture](#architecture)
- [Core Data Models](#core-data-models)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)

---

## Available Backends

| Backend | Config Name | Mode | Vector Store | Best For |
|---------|-------------|------|--------------|----------|
| `llamaindex` | `"llamaindex"` | Local Library | ChromaDB | Dev, prototyping, macOS/Linux |
| `foundational_rag` | `"foundational_rag"` | Hosted Service | Remote Milvus | Production, multi-user |

**Local Library Mode** - Everything runs in your Python process. No external services needed.
- **`llamaindex`** - LlamaIndex + ChromaDB. Lightweight, great for development. Works on macOS and Linux.

**Hosted Service Mode** - Connects to deployed services via HTTP. Requires infrastructure but scales better.
- **`foundational_rag`** - Connects to [NVIDIA RAG Blueprint](https://github.com/NVIDIA-AI-Blueprints/rag) via HTTP.
  - [Deployment Guide](https://github.com/NVIDIA-AI-Blueprints/rag/blob/main/docs/deploy-docker-self-hosted.md)

---

## Quick Start

> **Prerequisites:** Complete the [main setup](../../README.md#getting-started) first (clone repo, run `./scripts/setup.sh`, obtain API keys).

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

### With NeMo Agent Toolkit (YAML Config) - Recommended

The `knowledge_retrieval` function is registered as a NAT function type. **YAML config is the recommended single source of truth** for workflow configuration:

```yaml
# Example knowledge_retrieval function configuration
functions:
  knowledge_search:
    _type: knowledge_retrieval      # NAT function type
    backend: llamaindex             # Required: which adapter to use
    collection_name: my_docs        # Required: target collection
    top_k: 5                        # Results to return
    
    # Backend-specific options (each backend uses different fields):
    chroma_dir: /tmp/chroma_data              # llamaindex only
    rag_url: http://localhost:8081/v1         # foundational_rag only
    ingest_url: http://localhost:8082/v1      # foundational_rag only
    timeout: 120                              # foundational_rag only
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

#### Multimodal Extraction (LlamaIndex Only)

By default, LlamaIndex ingests text only. To extract tables and images from PDFs, set environment variables before starting the server:

```bash
# In deploy/.env or export directly
AIQ_EXTRACT_TABLES=true    # Extract tables from PDFs using pdfplumber
AIQ_EXTRACT_IMAGES=true    # Extract images from PDFs using pypdfium2 + VLM captioning
AIQ_EXTRACT_CHARTS=true    # Classify extracted images as charts and extract structured data
```

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

When disabled (default):

```
LlamaIndexIngestor initialized: persist_dir=/app/data/chroma_data, mode=text-only
```

> **Note:** `AIQ_EXTRACT_IMAGES` and `AIQ_EXTRACT_CHARTS` work together. If both are enabled, each image is classified by the VLM as either a chart or a regular image. If only `AIQ_EXTRACT_IMAGES` is set, all images are captioned as regular images. Foundational RAG handles multimodal extraction server-side, so these flags only apply to the LlamaIndex backend.

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

> **Separate Docker stacks:** When AI-Q and RAG run as separate Docker Compose stacks, connect the AI-Q backend to the RAG network: `docker network connect nvidia-rag aiq-agent`. See the [Docker Compose README](../../deploy/compose/README.md#networking-when-aiq-and-rag-run-as-separate-compose-stacks) for details.

### Programmatic Usage

```python
# Import the adapter module to trigger registration
from knowledge_layer.llamaindex import LlamaIndexRetriever, LlamaIndexIngestor

# Use the factory to get instances
from aiq_agent.knowledge import get_retriever, get_ingestor

# Ingest documents
ingestor = get_ingestor("llamaindex", config={"persist_dir": "/tmp/chroma"})
ingestor.create_collection("my_docs")
job_id = ingestor.upload_file("doc.pdf", "my_docs")

# Check ingestion status
status = ingestor.get_file_status(job_id, "my_docs")
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
| `DELETE` | `/v1/collections/{name}` | Delete collection |
| `POST` | `/v1/collections/{name}/documents` | Upload files |
| `GET` | `/v1/documents/{job_id}/status` | Poll ingestion status |
| `DELETE` | `/v1/collections/{name}/documents` | Delete files |

### Port Configuration

If the default port conflicts with other services (for example, RAG Blueprint uses ports 8000-8002), override it when starting Docker Compose:

```bash
PORT=8100 docker compose --env-file ../.env -f docker-compose.yaml up -d
```

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 8000 | Backend API host port |

The backend always runs on port 8000 inside the container. This variable only changes the host port mapping.

For more details, see the [Docker Compose README](../../deploy/compose/README.md#port-configuration).

### Session Collections

Both LlamaIndex and Foundational RAG support session-based collections (`s_<uuid>`) created by the UI. Each browser session gets its own isolated collection.

### TTL Cleanup (Foundational RAG Only)

Collections inactive for 24 hours are auto-deleted based on `last_indexed` timestamp. Background thread runs hourly.

```python
COLLECTION_TTL_HOURS = 24
TTL_CLEANUP_INTERVAL_SECONDS = 3600
```

> **Note:** LlamaIndex does not have TTL cleanup. Delete collections manually or implement cleanup in your application.

---

## Document Summaries

Document summaries help research agents understand what files are available before making tool calls. When enabled, the knowledge layer generates a one-sentence summary during ingestion and exposes it to agents through their system prompts.

### Enabling Summaries

Add `generate_summary: true` to your knowledge retrieval config:

```yaml
functions:
  knowledge_search:
    _type: knowledge_retrieval
    backend: llamaindex
    collection_name: test_collection
    top_k: 5
    generate_summary: true       # Enable AI-generated summaries
    summary_model: summary_llm   # Required: reference to LLM in llms: section
```

When `generate_summary: true`, you **must** configure `summary_model` to reference an LLM from your `llms:` section:

```yaml
llms:
  summary_llm:
    _type: nim
    model_name: nvidia/nemotron-mini-4b-instruct
    base_url: "https://integrate.api.nvidia.com/v1"
    api_key: ${NVIDIA_API_KEY}
    temperature: 0.3
    max_tokens: 150

functions:
  knowledge_search:
    _type: knowledge_retrieval
    generate_summary: true
    summary_model: summary_llm   # Required when generate_summary: true
    summary_db: sqlite+aiosqlite:///./summaries.db  # Optional: defaults to SQLite
```

### Supported File Types

Summaries are generated for the following file types:

| Format | Extension | Extraction Method |
|--------|-----------|-------------------|
| PDF | `.pdf` | First 2 pages via `pypdf` |
| Word | `.docx` | Body text via `docx2txt` |
| PowerPoint | `.pptx` | Slide text via `python-pptx` |
| Plain Text | `.txt` | Direct file read |
| Markdown | `.md` | Direct file read |

Other file types are ingested normally but do not receive summaries.

### How It Works

1. **Ingestion**: Backend extracts text from the document and generates a one-sentence summary using an LLM call
2. **Registry**: Summary is stored in a centralized, backend-agnostic registry (`aiq_agent.knowledge.factory`)
3. **Agent prompts**: Summaries appear in the agent's system prompt under "Uploaded Documents"
4. **Tool calling**: Agents can make informed decisions about when to call `knowledge_search`

### Agent Prompt Example

When documents have summaries, agents see:

```
## Uploaded Documents

The user has uploaded the following documents to the knowledge base:

- **quarterly_report.pdf**: Q3 financial results showing 15% revenue growth and improved operating margins.
- **product_roadmap.pptx**: 2024 product development timeline including AI features and cloud integrations.
- **meeting_notes.md**: Summary of Q4 planning meeting covering budget allocation and team priorities.

When the query relates to these documents, prioritize searching them before using external tools.
```

### Backend-Agnostic Design

The summary system works identically across all backends:

| Component | Location | Purpose |
|-----------|----------|---------|
| `register_summary()` | `aiq_agent.knowledge.factory` | Store summary after ingestion |
| `unregister_summary()` | `aiq_agent.knowledge.factory` | Remove summary on file deletion |
| `get_available_documents()` | `aiq_agent.knowledge.factory` | Retrieve summaries for agents |

Both LlamaIndex and Foundational RAG adapters call these functions, ensuring consistent behavior regardless of backend choice.

### Summary Storage

Summaries are persisted in a database (SQLite by default) so they survive server restarts. You can configure the storage backend:

```yaml
functions:
  knowledge_search:
    _type: knowledge_retrieval
    generate_summary: true
    summary_db: ${AIQ_SUMMARY_DB:-sqlite+aiosqlite:///./summaries.db}  # Default: SQLite
```

For production deployments, use PostgreSQL:

```bash
export AIQ_SUMMARY_DB="postgresql+psycopg://user:pass@localhost:5432/mydb"
```

The summary store uses SQLAlchemy and follows the same pattern as the jobs database (`db_url`), so you can point both to the same PostgreSQL instance if desired.

### Custom Summarization

To customize summary generation, modify the `generate_summary()` method in your adapter. See reference implementations:

- **LlamaIndex**: `sources/knowledge_layer/src/llamaindex/adapter.py` (search for `generate_summary`)
- **Foundational RAG**: `sources/knowledge_layer/src/foundational_rag/adapter.py` (search for `generate_summary`)

Key customization points:
- LLM model selection and prompt template
- Text extraction strategy (format-aware: pages for PDF, body text for DOCX, slide text for PPTX)
- Summary length and format constraints

---

## Building a Custom Backend

### Step 1: Create adapter directory

```bash
mkdir -p sources/knowledge_layer/src/my_backend
touch sources/knowledge_layer/src/my_backend/{__init__.py,adapter.py,README.md}
```

### Step 2: Implement the adapter with registration decorators

```python
# sources/knowledge_layer/src/my_backend/adapter.py
from typing import Any, Dict, List, Optional
from aiq_agent.knowledge.base import BaseRetriever, BaseIngestor
from aiq_agent.knowledge.factory import register_retriever, register_ingestor
from aiq_agent.knowledge.schema import (
    Chunk, RetrievalResult, CollectionInfo, FileInfo, 
    FileStatus, ContentType, IngestionJobStatus
)


@register_retriever("my_backend")  # <-- This name goes in YAML config
class MyRetriever(BaseRetriever):
    """My custom retriever implementation."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        # Initialize your vector store client here
        self.endpoint = self.config.get("endpoint", "http://localhost:8000")
    
    @property
    def backend_name(self) -> str:
        return "my_backend"  # Should match registration name
    
    async def retrieve(
        self, 
        query: str, 
        collection_name: str, 
        top_k: int = 5, 
        filters: Optional[Dict] = None
    ) -> RetrievalResult:
        """Query your vector store and return normalized results."""
        # Your search logic here
        raw_results = []  # Get from your backend
        
        chunks = [self.normalize(r) for r in raw_results]
        return RetrievalResult(
            chunks=chunks, 
            query=query, 
            backend=self.backend_name,
            total_tokens=sum(len(c.content.split()) for c in chunks)
        )
    
    def normalize(self, raw_result: Any) -> Chunk:
        """Convert backend-specific result to universal Chunk schema."""
        return Chunk(
            chunk_id=raw_result.get("id", "unknown"),
            content=raw_result.get("text", ""),
            content_type=ContentType.TEXT,
            file_name=raw_result.get("source", "unknown"),
            display_citation=f"{raw_result.get('source', 'unknown')}",
            score=raw_result.get("score", 0.0),
        )


@register_ingestor("my_backend")  # <-- Same registration name
class MyIngestor(BaseIngestor):
    """My custom ingestor implementation."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._jobs: Dict[str, FileInfo] = {}  # Track async jobs
        self.endpoint = self.config.get("endpoint", "http://localhost:8000")
    
    @property
    def backend_name(self) -> str:
        return "my_backend"
    
    # --- Collection Management ---
    
    def create_collection(self, name: str, description: str = None, **kwargs) -> CollectionInfo:
        """Create a new collection in your vector store."""
        # Your creation logic
        return CollectionInfo(
            name=name, 
            description=description,
            backend=self.backend_name,
            file_count=0,
            chunk_count=0
        )
    
    def delete_collection(self, name: str) -> bool:
        """Delete a collection."""
        # Your deletion logic
        return True
    
    def list_collections(self) -> List[CollectionInfo]:
        """List all collections."""
        return []
    
    def get_collection(self, name: str) -> Optional[CollectionInfo]:
        """Get collection metadata."""
        return None
    
    # --- File Management ---
    
    def upload_file(self, file_path: str, collection_name: str, **kwargs) -> str:
        """Upload and ingest a file. Returns job_id for status tracking."""
        import uuid
        from datetime import datetime
        import os
        
        job_id = str(uuid.uuid4())
        filename = os.path.basename(file_path)
        
        # Track the job
        self._jobs[job_id] = FileInfo(
            file_id=job_id,
            file_name=filename,
            collection_name=collection_name,
            status=FileStatus.UPLOADING,
            uploaded_at=datetime.now()
        )
        
        # Start async ingestion (e.g., in a thread)
        # Update self._jobs[job_id].status as processing progresses
        
        return job_id
    
    def delete_file(self, filename: str, collection_name: str) -> bool:
        """Delete a file's chunks from collection."""
        return True
    
    def list_files(self, collection_name: str) -> List[FileInfo]:
        """List files in a collection."""
        return [f for f in self._jobs.values() if f.collection_name == collection_name]
    
    def get_file_status(self, job_id: str, collection_name: str) -> Optional[FileInfo]:
        """Get status of an ingestion job."""
        return self._jobs.get(job_id)
    
    # --- Legacy Job API (optional, for backwards compat) ---
    
    def submit_job(self, file_paths: List[str], collection_name: str, **kwargs) -> str:
        """Batch submit - calls upload_file for each."""
        # Implementation...
        pass
    
    def get_job_status(self, job_id: str) -> IngestionJobStatus:
        """Overall job status."""
        # Implementation...
        pass
```

> **Error Handling for UI Integration:**
>
> If you're using the web UI for document upload, your adapter must properly populate error messages in the standard schema. The UI displays `FileProgress.error_message` to users when ingestion fails - it doesn't parse backend-specific error formats.
>
> In your `get_job_status()` implementation:
> 1. Check your backend's response for failure states
> 2. Extract the error message from your backend's format (could be `error`, `message`, `result.error`, etc.)
> 3. Set `FileProgress.error_message` for the affected file
> 4. Set `FileProgress.status = FileStatus.FAILED`
>
> ```python
> # Example pattern in get_job_status():
> if backend_status == "failed":
>     error_msg = (
>         response.get("error")
>         or response.get("message") 
>         or response.get("result", {}).get("message")
>         or "Unknown error"
>     )
>     file_progress.status = FileStatus.FAILED
>     file_progress.error_message = error_msg
> ```
>
> See [`src/foundational_rag/adapter.py`](src/foundational_rag/adapter.py) `get_job_status()` for a complete example.

### Step 3: Export in `__init__.py` (triggers registration on import)

```python
# sources/knowledge_layer/src/my_backend/__init__.py
"""
My Custom Backend for Knowledge Layer.

Import this module to register the backend with the factory.
"""
from .adapter import MyRetriever, MyIngestor

__all__ = ["MyRetriever", "MyIngestor"]
```

### Step 4: Register package in pyproject.toml

```toml
# sources/knowledge_layer/pyproject.toml

[project.optional-dependencies]
my_backend = [
    "requests>=2.28.0",  # Your backend's dependencies
]

[tool.setuptools]
packages = [
    "aiq_sources",
    "knowledge_layer.eci",
    "knowledge_layer.knowledge",
    "knowledge_layer.llamaindex",
    "knowledge_layer.foundational_rag",
    "knowledge_layer.my_backend",  # <-- Add your backend
]
```

### Step 5: Add to NAT function (for YAML config support)

To use your backend via YAML config (`backend: my_backend`), you must edit **`sources/knowledge_layer/src/register.py`**:

**Three changes required:**

1. **Add to `BackendType` Literal** - Enables Pydantic validation at config load time
2. **Add config fields to `KnowledgeRetrievalConfig`** - These become available in YAML
3. **Add backend case to `_setup_backend()`** - This instantiates your adapter

```python
# sources/knowledge_layer/src/register.py
from typing import Literal

# 1. Add your backend to the BackendType Literal for type-safe validation
BackendType = Literal["llamaindex", "foundational_rag", "my_backend"]  # <-- Add here


# 2. Add your config fields to KnowledgeRetrievalConfig class
class KnowledgeRetrievalConfig(FunctionBaseConfig, name="knowledge_retrieval"):
    backend: BackendType = Field(default="llamaindex", ...)  # Uses the Literal type
    collection_name: str = Field(...)
    top_k: int = Field(...)
    
    # ... existing backend fields (chroma_dir, rag_url, etc.) ...
    
    # ADD YOUR BACKEND'S CONFIG FIELDS HERE:
    my_backend_endpoint: str = Field(
        default="http://localhost:8000",
        description="Endpoint URL (my_backend only)"
    )
    my_backend_api_key: str = Field(
        default="",
        description="API key for authentication (my_backend only)"
    )


# 3. Add your backend case to _setup_backend() function
def _setup_backend(config: KnowledgeRetrievalConfig):
    backend = config.backend.lower()
    
    if backend == "llamaindex":
        # ... existing ...
    elif backend == "foundational_rag":
        # ... existing ...
    
    # ADD YOUR BACKEND CASE HERE:
    elif backend == "my_backend":
        import knowledge_layer.my_backend.adapter  # noqa: F401
        backend_config = {
            "endpoint": config.my_backend_endpoint,
            "api_key": config.my_backend_api_key,
        }
    
    else:
        raise ValueError(f"Unknown backend: {backend}")
    
    return backend, backend_config
```

> **Why add to `BackendType`?** The Literal type provides compile-time validation. If someone configures `backend: llama_index` (typo), Pydantic will reject it immediately with a clear error message: *"Input should be 'llamaindex', 'foundational_rag', or 'my_backend'"* rather than failing deep in the code at runtime.

Now your backend can be configured via YAML:

```yaml
functions:
  knowledge_search:
    _type: knowledge_retrieval
    backend: my_backend
    collection_name: my_docs
    my_backend_endpoint: http://my-server:8000
    my_backend_api_key: ${MY_API_KEY}
```

### Step 6: Install and test

```bash
# Install
uv pip install -e "sources/knowledge_layer[my_backend]"

# Verify registration
python -c "
from knowledge_layer.my_backend import MyRetriever, MyIngestor
from aiq_agent.knowledge.factory import list_retrievers, list_ingestors
print('Registered retrievers:', list_retrievers())
print('Registered ingestors:', list_ingestors())
"
# Output should include 'my_backend'
```

### Step 7: Use in YAML config

```yaml
# your_config.yml
functions:
  knowledge_search:
    _type: knowledge_retrieval
    backend: my_backend                          # Your registration name
    collection_name: test_collection
    my_backend_endpoint: http://my-server:8000   # Your config field
    top_k: 5
```

---

## Architecture

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

The registration name (e.g., `"my_backend"`) is what you use in:
- YAML config: `backend: my_backend`
- Factory calls: `get_retriever("my_backend")`

**Important:** The adapter module must be imported for registration to happen. This is why:
1. `__init__.py` imports the adapter classes
2. The NAT function imports from `knowledge_layer.<backend>.adapter`

### Core Library (`src/aiq_agent/knowledge/`)

```
src/aiq_agent/knowledge/
    __init__.py      # Exports: Chunk, get_retriever, get_ingestor, etc.
    base.py          # Abstract classes: BaseRetriever, BaseIngestor
    schema.py        # Data models: Chunk, RetrievalResult, FileInfo, CollectionInfo
    factory.py       # Registry + factory: register_retriever(), get_retriever()
```

| File | Purpose |
|------|---------|
| `base.py` | Defines the interface all backends must implement |
| `schema.py` | Universal data models - backends convert native formats to these |
| `factory.py` | Registration decorators + factory functions for instantiation |

### Backend Adapters (`sources/knowledge_layer/src/`)

```
sources/knowledge_layer/src/
    <backend_name>/
        __init__.py      # Imports adapter to trigger registration
        adapter.py       # @register_retriever/@register_ingestor decorated classes
        README.md        # Backend-specific documentation
        pyproject.toml   # Optional: isolated dependencies
```

### NeMo Agent Toolkit Integration (`sources/knowledge_layer/src/`)

```
sources/knowledge_layer/src/
    register.py      # @register_function exposes retrieval to agents
```

The `register.py` defines `KnowledgeRetrievalConfig` which maps YAML config to backend instantiation.

---

## Core Data Models

```python
from aiq_agent.knowledge.schema import (
    # Retrieval
    Chunk,           # Retrieved content piece (15+ fields)
    RetrievalResult, # Query result container
    ContentType,     # TEXT, IMAGE, TABLE, CHART
    
    # Ingestion
    CollectionInfo,  # Collection metadata
    FileInfo,        # File/job status
    FileStatus,      # UPLOADING, INGESTING, SUCCESS, FAILED
    IngestionJobStatus,  # Batch job tracking
)
```

### Chunk Schema (The "Golden Record")

```python
class Chunk(BaseModel):
    # Core content
    chunk_id: str              # Unique ID for citation tracking
    content: str               # Main text (or caption for visuals)
    score: float               # Similarity score 0.0-1.0
    
    # Citation (required)
    file_name: str             # Original filename
    page_number: Optional[int] # Page number (1-based)
    display_citation: str      # User-facing citation label
    
    # Content typing (required)
    content_type: ContentType  # TEXT, TABLE, CHART, IMAGE
    content_subtype: Optional[str]  # e.g., "bar_chart", "pie_chart"
    
    # Optional rich data
    structured_data: Optional[str]  # Raw data for tables/charts
    image_url: Optional[str]        # Presigned URL for images
    metadata: Dict[str, Any]        # Passthrough metadata
```

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
| `NVIDIA_API_KEY` | All | Required for embeddings/VLM and LLM calls |
| `KNOWLEDGE_RETRIEVER_BACKEND` | All | Default retriever backend (fallback if not in YAML) |
| `KNOWLEDGE_INGESTOR_BACKEND` | All | Default ingestor backend (fallback if not in YAML) |
| `AIQ_CHROMA_DIR` | llamaindex | ChromaDB persistence path |
| `AIQ_SUMMARY_DB` | All | Summary database URL (SQLite or PostgreSQL) |
| `RAG_SERVER_URL` | foundational_rag | Query server URL (port 8081) |
| `RAG_INGEST_URL` | foundational_rag | Ingestion server URL (port 8082) |
| `COLLECTION_NAME` | All | Default collection name |

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `Unknown backend: my_backend` | Adapter not imported/registered | Import the adapter module before calling factory |
| `ormsgpack` attribute error | Version conflict with langgraph | `uv pip install "ormsgpack>=1.5.0"` |
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

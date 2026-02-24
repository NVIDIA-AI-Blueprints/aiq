# Knowledge Layer

Pluggable document ingestion and retrieval for NeMo Agent Toolkit workflows.

For comprehensive documentation, see [`docs/KNOWLEDGE-LAYER-SETUP.md`](./KNOWLEDGE-LAYER-SETUP.md).

## Installation

```bash
# With LlamaIndex backend (local dev)
uv pip install -e "sources/knowledge_layer[llamaindex]"

# With Foundational RAG (hosted production)
uv pip install -e "sources/knowledge_layer[foundational_rag]"
```

## Available Backends

| Backend | Vector Store | Best For |
|---------|-------------|----------|
| `llamaindex` | ChromaDB | Development, prototyping |
| `foundational_rag` | Remote Milvus | Production, multi-user |

## Usage

See [Web UI Mode](./KNOWLEDGE-LAYER-SETUP.md#web-ui-mode) for document upload and chat interfaces.

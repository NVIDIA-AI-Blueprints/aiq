# Knowledge Layer

Pluggable document ingestion and retrieval for NeMo Agent Toolkit workflows.

For comprehensive documentation, see [`docs/KNOWLEDGE-LAYER-SETUP.md`](./KNOWLEDGE-LAYER-SETUP.md).

## Installation

```bash
# With LlamaIndex backend (local dev)
uv pip install -e "sources/knowledge_layer[llamaindex]"

# With Foundational RAG (hosted production)
uv pip install -e "sources/knowledge_layer[foundational_rag]"

# With OpenSearch (self-hosted or Amazon OpenSearch)
uv pip install -e "sources/knowledge_layer[opensearch]"
```

## Available Backends

| Backend | Vector Store | Best For |
|---------|-------------|----------|
| `llamaindex` | ChromaDB | Development, prototyping |
| `opensearch` | OpenSearch k-NN | Self-hosted OpenSearch, Amazon OpenSearch Serverless |
| `foundational_rag` | Remote Milvus | Production, multi-user |

## Usage

See [Web UI Mode](./KNOWLEDGE-LAYER-SETUP.md#web-ui-mode) for document upload and chat interfaces.

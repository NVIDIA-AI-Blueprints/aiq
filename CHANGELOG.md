# Change Log

Release v2.1.0 (Unreleased — target 2026-05-19)

- AI-Q REST API with pluggable auth middleware, entry-point-registered token validators, and async job ownership enforcement
- Auth extensibility hooks (`register_token_fetcher`, provider lifecycle) and auth refactor eliminating the refresh race
- Data source registry driving UI toggles, per-message filtering, and agent tool inheritance
- New `exa_web_search` data source with `full_text` and `highlights` controls
- Deep researcher consumes DeepAgents skills with a job-scoped Modal sandbox; built-in `data-table-analysis` skill and `configs/config_skills.yml` example
- AI-Q is consumable as a Claude Code skill (`.claude/skills/aiq-research/`) for routed `/chat` and async job lifecycle against a local AI-Q server
- Cost analysis tool with pricing configs and profiling example
- Documented MCP client patterns scoped for 2.1: `mcp_client`, `mcp_service_account`, and user-identity tools
- Prompt restructure across all agents for KV cache prefix reuse
- Operability: idempotent DB init, tuned Dask/Postgres defaults, request tracing into NAT spans, UI stream-failure hardening
- New authentication and MCP tools guides; new skills-and-sandbox example
- Pinned to NeMo Agent Toolkit (NAT) v1.6.0; CVE bumps for Pillow, cryptography, pygments, authlib, pyopenssl, and pytest

Release v2.0.0

Ground-up rewrite of the NVIDIA AI-Q Blueprint, built on the NVIDIA NeMo Agent Toolkit (NAT).

- Two-tier research architecture with automatic routing between shallow (fast, bounded) and deep (multi-phase, report-grade) research via a single-call Intent Classifier
- Deep Researcher rebuilt with a three-role subagent architecture (Orchestrator, Planner, Researcher) using the `deepagents` library, with configurable research loops and per-role LLM assignment
- New Shallow Researcher agent with tool-call budgets, context compaction, and synthesis anchors for citation-backed answers
- Clarifier agent with human-in-the-loop plan generation, approval, and feedback before deep research
- Shallow-to-deep escalation when the shallow researcher detects insufficient results
- Async Jobs REST API (`/v1/jobs/async/`) with SSE streaming, event replay, reconnection support, and cooperative cancellation
- Dask-based distributed execution with configurable workers, heartbeats, and stale job reaping
- PostgreSQL persistence for job store, event store, LangGraph checkpoints, and document summaries
- Pluggable Knowledge Layer with factory/registry pattern — swap between LlamaIndex (local ChromaDB) and Foundational RAG (hosted NVIDIA RAG Blueprint) without code changes
- Multimodal document extraction (VLM-powered image captioning and chart data extraction)
- Document summaries injected into agent prompts for file-aware research
- Deterministic citation verification pipeline with five-level URL matching, report sanitization, and audit trail
- New Next.js frontend with conversational UI, document upload, collection management, and real-time progress streaming
- Optional OAuth/OIDC authentication with configurable providers
- Multi-backend observability: Phoenix, LangSmith, W&B Weave, and OpenTelemetry Collector with privacy redaction
- FreshQA benchmark for shallow researcher factuality evaluation via `nat eval`
- Docker Compose and Helm chart deployments with distroless runtime images, non-root execution, and horizontal scaling
- Native NAT integration — all configuration through YAML with `nat run` / `nat serve` / `nat eval`
- Four pre-built configs: CLI default, Web + LlamaIndex, Web + Foundational RAG, Hybrid Frontier Model
- uv workspace monorepo, Jupyter notebook tutorial series, and debug console at `/debug`
- Pinned to NeMo Agent Toolkit (NAT) v1.4.0; Python 3.11–3.13; Node.js 22+
- AI-Q holds top positions on both DeepResearch Bench and DeepResearch Bench II leaderboards (see `drb1` and `drb2` branches)

Release v1.2.1
- Upgraded llama-3.3-70b-instruct NIM from version 1.13.1 to 1.14.0
- Aligned Helm values and referenced Docker image tags with the new nim-llm version
- Adopted RAG 2.3.2
- Removed manual NIM_MODEL_PROFILE configuration from Helm values and Docker Compose to rely on automatic profile detection, updated documentation accordingly

Release v1.2.0
- Added support for Helm deployments
- Add support and documentation for evaluation
- Simplified the configuration and integration with RAG, removing nginx
- Adopted RAG 2.3.0
- Tested for compatability with RTX Pro 6000

Release v1.1.0
- Tested for compatability with RAG 2.2.0 release and B200
- Adds support for NVIDIA Workbench

Release v1.0.0

Initial release of the NVIDIA AI-Q Research Assistant Blueprint featuring:
- Multi-modal PDF document upload and processing, compatible with the NVIDIA RAG 2.1 blueprint release
- Demo web application
- Deep research report writing including human-in-the-loop feedback

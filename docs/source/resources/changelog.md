<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
# Change Log

## Release v2.1.0

The following are updates to the AI-Q blueprint for version 2.1.0, including production web deployments, extensible authentication, enterprise data-source routing, and skill-driven deep research workflows.

- AI-Q REST API with pluggable auth middleware, entry-point-registered token validators, and async job ownership enforcement
- Auth extensibility hooks (`register_token_fetcher`, provider lifecycle) and auth refactor, eliminating the refresh race
- Data source registry driving UI toggles, per-message filtering, and agent tool inheritance
- New `exa_web_search` data source with `full_text` and `highlights` controls
- Deep researcher consumes DeepAgents skills with a job-scoped Modal sandbox; built-in `data-table-analysis` skill and `configs/config_skills.yml` example
- AI-Q is consumable as a portable Agent Skill (`.agents/skills/aiq-research/`), with `.claude/skills/aiq-research/` retained as a Claude Code compatibility symlink for routed `/chat` and async job lifecycle against a local AI-Q server
- Cost analysis tool with pricing configs and profiling example
- Documented MCP client patterns scoped for 2.1: `mcp_client`, `mcp_service_account`, and user-identity tools
- Prompt restructure across all agents for KV cache prefix reuse
- Operability: idempotent DB init, tuned Dask/Postgres defaults, request tracing into NAT spans, UI stream-failure hardening
- New authentication and MCP tools guides; new skills-and-sandbox example
- Pinned to NeMo Agent Toolkit (NAT) v1.6.0; CVE bumps for Pillow, cryptography, pygments, authlib, pyopenssl, and pytest

## Released

Release v1.1.0
- Tested for compatibility with RAG 2.2.0 release and B200
- Adds support for NVIDIA Workbench

Release v1.0.0

Initial release of the NVIDIA AI-Q Blueprint featuring:
- Multi-modal PDF document upload and processing, compatible with the NVIDIA RAG 2.1 blueprint release
- Demo web application
- Deep research report writing including human-in-the-loop feedback

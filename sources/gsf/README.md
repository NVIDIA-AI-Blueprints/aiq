<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# AI-Q GSF source

This package exposes NVIDIA Generative Semantic Fabric (GSF) capabilities as a
NeMo Agent Toolkit function group. The current implementation provides:

- `gsf__text_to_sql`
- `gsf__catalog_search`

PQL client and model groundwork remains internal, but no PQL tool is registered
until its GSF contract and integration behavior are validated.

By default, the function group owns one shared HTTP connection pool and keeps
authentication request-scoped: each tool invocation obtains the current AI-Q
user token and passes it to GSF without storing it on the client.
`GSF_BASE_URL` must point to GSF's auth-aware API origin.

```yaml
function_groups:
  gsf:
    _type: gsf
    base_url: ${GSF_BASE_URL}
    include:
      - catalog_search
      - text_to_sql

functions:
  data_sources:
    _type: data_source_registry
    sources:
      - id: gsf
        name: "Enterprise Structured Data"
        description: >-
          Build authorized semantic context and execute bounded structured-data
          queries through GSF.
        default_enabled: true
        requires_auth: true
        tools:
          - gsf
```

For local development and automated evaluation without an incoming AI-Q user
token, explicitly configure a GSF password session. The credentials must come
from environment variables:

```yaml
function_groups:
  gsf:
    _type: gsf
    base_url: ${GSF_BASE_URL}
    auth:
      mode: password
      email: ${GSF_EMAIL}
      password: ${GSF_PASSWORD}
    include:
      - catalog_search
      - text_to_sql
```

When `auth` is omitted, the existing request-scoped AI-Q user-token flow is
used. Password mode creates one GSF session when the function group starts,
reuses its cookie for local development or evaluation calls, and signs out when
the group closes. The client does not fall back between authentication methods.

Text-to-SQL uses GSF's `/api/chat/completions` SSE endpoint with
`prediction: false`. Its optional AI-Q `database_name` input is sent to GSF as
`target_db`, selecting an existing GSF connection rather than creating one.
The adapter normalizes GSF's current response fields while preserving optional
semantic and benchmarking fields as they become available.
For text-to-SQL, GSF's compatibility prose is discarded; AI-Q consumes the
generated SQL, bounded rows, and any structured semantic provenance instead.
GSF's optional `thoughts` summary is retained as diagnostic context, not as
authoritative evidence.

Catalog search uses `POST /api/question-entity-coverage` and returns entity
coverage plus ranked semantic candidates for DS-agent grounding and routing.
Its optional `database_name` is sent as `target_db`.

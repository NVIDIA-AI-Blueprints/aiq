<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# AI-Q GSF source

This package exposes NVIDIA Generative Semantic Fabric (GSF) capabilities as a
NeMo Agent Toolkit function group. The current implementation provides:

- `gsf__text_to_sql`

`gsf__catalog_search` and `gsf__query_context` are registered as explicit
`capability_unavailable` placeholders until their GSF API contracts are ready.

The function group owns one shared HTTP connection pool. Authentication remains
request-scoped: each tool invocation obtains the current AI-Q user token and
passes it to GSF without storing it on the client.
`GSF_BASE_URL` must point to GSF's auth-aware API origin.

```yaml
function_groups:
  gsf:
    _type: gsf
    base_url: ${GSF_BASE_URL:-http://gsf:3000}
    include:
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

Text-to-SQL uses GSF's `/api/chat/completions` SSE endpoint with
`prediction: false`. Its optional AI-Q `database_name` input is sent to GSF as
`target_db`, selecting an existing GSF connection rather than creating one.
Future prediction tools can reuse the client transport with `prediction: true`.
The adapter normalizes GSF's current response fields while preserving optional
semantic and benchmarking fields as they become available.

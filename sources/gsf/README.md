<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# AI-Q GSF source

This package exposes NVIDIA Generative Semantic Fabric (GSF) capabilities as a
NeMo Agent Toolkit function group. The current implementation provides:

- `gsf__text_to_sql`
- `gsf__query_context`

`gsf__catalog_search` is registered as an explicit
`capability_unavailable` placeholder until its GSF API contract is ready.

The function group owns one shared HTTP connection pool. Authentication remains
request-scoped: each tool invocation obtains the current AI-Q user token and
passes it to GSF without storing it on the client.

```yaml
function_groups:
  gsf:
    _type: gsf
    base_url: ${GSF_BASE_URL:-http://gsf:3001}
    include:
      - query_context
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

The `/api/v1/query-context` contract is provisional while GSF enriches the
existing `/api/text-to-data` capability.

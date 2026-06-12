<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Registry and UI wiring

Authoritative sources: `src/aiq_agent/common/data_source_registry.py` and
`docs/source/customization/tools-and-sources.md`.

## Register the source in YAML

After installing the package editable, add the source to the
`data_source_registry` in the relevant config under `configs/`. This is normally
the **only** config change needed — agents inherit registry tools automatically:

```yaml
functions:
  data_source_registry:
    _type: data_source_registry
    sources:
      - id: my_data_source
        name: My Data Source
        category: web          # web | enterprise | storage | collaboration
        default_enabled: true
        tools:
          - _type: my_data_source

  my_data_source:
    _type: my_data_source       # matches the config class name= / entry-point key
```

Confirm the field names against the `DataSourceRegistryConfig` in
`src/aiq_agent/common/data_source_registry.py`; do not guess the schema.

## How the registry surfaces the source

- `GET /v1/data_sources` returns the registered sources; the UI renders them as
  toggles. No UI code change is normally required.
- Per-request filtering: the WebSocket chat payload and
  `POST /v1/jobs/async/submit` accept a `data_sources` list to scope which
  sources are active for that request.
- Auto-inheritance: every agent gets every registered tool by default; use an
  agent's `exclude_tools` for per-agent specialization.
- Tools not listed in any registry source entry are always included (e.g. utility
  tools like "think"). An explicit empty list (`data_sources: []`) disables
  registry tools while leaving unmapped utility tools available.

## UI type (reference only)

`frontends/ui/src/features/layout/data-sources.ts` defines the `DataSource`
TypeScript interface (`id`, `name`, `description`, `category`, `defaultEnabled`,
`requiresAuth`). Because sources are fetched dynamically from
`GET /v1/data_sources`, adding a source does not require editing this file. Touch
the UI only for a genuinely new presentation need — that is `aiq-ui-change`
territory, not this skill.

## Authenticated sources

If the source requires per-user auth, set the auth flags rather than hard-coding
credentials, and follow the auth integration path. Protected-source auth is out
of scope for this skill; coordinate with the auth integration workflow.

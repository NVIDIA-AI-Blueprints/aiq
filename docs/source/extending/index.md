<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Extending the Blueprint

## Customization vs Extending
**Extending** is for adding new functionality to the blueprint — new tools, data sources, and integrations that don't exist today. Extensions use the NeMo Agent Toolkit plugin system or require custom code.

**Customization** is for changing what already exists — models, prompts, tool configuration, and agent behavior. Refer to [Customization](../customization/index.md).


## Plugin System Extensions

These use NeMo Agent Toolkit's `@register_function` decorator and Python entry points. You register new components through `pyproject.toml` and configure them through YAML.

- **[Adding a Tool](./adding-a-tool.md)** — Build and register a new tool or function that agents can call
- **[Adding a Data Source](./adding-a-data-source.md)** — Create a new search or retrieval plugin

<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# AI-Q Bounded Python

`bounded_python` is an opt-in NeMo Agent Toolkit function for deterministic,
stateful calculations inside the Data Science Agent. It is intended for small
JSON-compatible analytical results, not general code execution.

Each task must call `start` to obtain a random workspace ID, then pass that ID
to `execute`, `inspect`, `reset`, or `close`. State is isolated by workspace and
stored as JSON between calls. Code runs in a fresh isolated subprocess on every
execution with no imports, attribute access, filesystem APIs, network APIs, or
normal Python builtins. Configured CPU, wall-time, memory, input, state, and
output limits are enforced.

Example configuration:

```yaml
functions:
  analysis_workspace:
    _type: bounded_python
    wall_timeout_seconds: 5
    cpu_time_seconds: 3
    memory_mb: 256

  data_science_agent:
    _type: data_science_agent
    llm: data_science_llm
    tools: [gsf, knowledge_search, web_search_tool, analysis_workspace]
```

This local tool deliberately has a smaller capability surface than AI-Q's
provider-backed Deep Research sandbox. Use the latter for general-purpose code,
files, packages, or artifacts.

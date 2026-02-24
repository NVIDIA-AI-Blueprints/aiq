<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Agents

AI-Q uses a multi-agent architecture where an intent classifier routes queries to specialized research agents.

| Agent | Purpose | Speed | Depth |
|-------|---------|-------|-------|
| [Intent Classifier](./intent-classifier.md) | Route queries and determine research depth | Instant | — |
| [Clarifier](./clarifier.md) | HITL: clarify ambiguous queries and approve research plans | Interactive | — |
| [Shallow Researcher](./shallow-researcher.md) | Fast, bounded research for simple questions | Fast (30-60s) | Surface |
| [Deep Researcher](./deep-researcher.md) | Multi-phase deep research with planning and iteration | Thorough (2-10min) | Deep |

```{toctree}
:titlesonly:

intent-classifier.md
clarifier.md
shallow-researcher.md
deep-researcher.md
```

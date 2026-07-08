<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
# Human-in-the-Loop (HITL)

The clarifier runs before deep research. It gathers context and, when the
request is vague, may ask you to narrow the scope or clarify the type of output
you want. To disable it:

## Disable the Clarifier Entirely

No clarification step before deep research:

```yaml
workflow:
  _type: chat_deepresearcher_agent
  enable_clarifier: false
  # ...
```

## Limit Clarification Questions

Cap how many clarification turns the clarifier may take:

```yaml
functions:
  clarifier_agent:
    _type: clarifier_agent
    max_turns: 1
    # ...
```

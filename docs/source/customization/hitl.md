<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
# Human-in-the-Loop (HITL)

Human-in-the-loop (clarifier and plan approval) runs before deep research. To disable it:

## Disable the Clarifier Entirely

No plan generation or approval step:

```yaml
workflow:
  _type: chat_deepresearcher_agent
  enable_clarifier: false
  # ...
```

## Keep Clarifier but Skip Plan Approval

No user approval step before deep research:

```yaml
functions:
  clarifier_agent:
    _type: clarifier_agent
    enable_plan_approval: false
    # ...
```

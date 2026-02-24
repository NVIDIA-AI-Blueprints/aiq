<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
# Testing

To run tests:

```bash
pytest
pytest --cov=src/aiq_agent --cov-report=html
pytest tests/path/to/test_file.py
uv run pytest
```

Use mocks for external services; mark slow/integration tests with `@pytest.mark.slow` / `@pytest.mark.integration` as needed.

Refer to each benchmark's README for details. The [Customization guide](../customization/index.md) has a short section on adding eval harnesses.

## Debugging

- **Verbose logging:** `./scripts/start_cli.sh --verbose` or set `verbose: true` in workflow config.
- **Phoenix tracing:** Start `phoenix serve`, run the agent with Phoenix tracing enabled in config, then open `http://localhost:6006`.
- **Common issues:** Import errors -- ensure `uv pip install -e .`; auth -- check env vars; tool not found -- check config; pre-commit cache -- `pre-commit clean`.

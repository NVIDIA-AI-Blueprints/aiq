<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
# Code Style

## Development Workflow

Helper script:

```bash
./scripts/dev.sh help        # List commands
./scripts/dev.sh test        # Run tests
./scripts/dev.sh format      # Format code
./scripts/dev.sh lint        # Lint
./scripts/dev.sh pre-commit  # Format + checks
```

Otherwise run `pre-commit run --all-files`, `pytest`, and formatters directly (refer to [Code Quality](#code-quality) below).

## Code Quality

- **Formatting:** `ruff` (imports/linting) + `yapf` (PEP 8 base, `column_limit=120`). The `./scripts/dev.sh format` command runs both.
- **Pre-commit:** `pre-commit run --all-files` (runs `ruff check --fix`, `ruff format`, `uv-lock`, `detect-secrets`, notebook output clearing, and `markdown-link-check`)
- **Line length:** 120 characters
- **Style:** PEP 8, type hints for public APIs, Google-style docstrings. Ruff and yapf are configured in `pyproject.toml`.

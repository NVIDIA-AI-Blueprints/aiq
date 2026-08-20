<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# AI-Q Stateful Python

This source provides a request-scoped `python(code)` tool for the Data Science
Agent. One real Python subprocess survives across all calls in a request, so
variables, imports, DataFrames, and fitted objects remain available between
cells. The process is closed and its temporary files are removed when the
request ends.

The kernel preloads NumPy (`np`), pandas (`pd`), SciPy (`scipy` and `stats`),
scikit-learn (`sklearn`), and statsmodels (`sm`). It also exposes
`list_gsf_results()`, `gsf_result()`, `gsf_rows()`, `gsf_sql()`, and
`gsf_latest()` for exact, programmatic access to successful GSF responses from
the same request.

The tool is for analysis only. It has no configured GSF client or source
database connection; GSF and SQL remain agent-level tools.

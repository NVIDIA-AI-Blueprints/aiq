<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# AI-Q Stateful Python

This source provides a request-scoped `python(code)` tool for the Data Science
Agent. One real Python process survives across all calls in a fresh,
policy-bound OpenShell sandbox, so variables, imports, DataFrames, and fitted
objects remain available between cells. The sandbox is deleted when the request
ends or a cell exceeds its time limit.

The kernel preloads NumPy (`np`), pandas (`pd`), SciPy (`scipy` and `stats`),
scikit-learn (`sklearn`), and statsmodels (`sm`). It also exposes
`list_gsf_results()`, `gsf_result()`, `gsf_rows()`, `gsf_sql()`, and
`gsf_latest()` for exact, programmatic access to successful GSF responses from
the same request.

The tool is for analysis only. It has no configured GSF client or source
database connection; GSF and SQL remain agent-level tools.

`stateful_python` has no host-process backend. Its required `sandbox` field must
reference a `deep_research_sandbox` function configured with `provider:
openshell`, `network: blocked`, policy attestation, per-request creation, and
terminal deletion. AI-Q uploads only the kernel transport files and bounded,
request-owned GSF receipts; it never copies the application environment into
the sandbox. The worker also starts with hard per-process memory, cumulative
CPU, process-count, open-file, and output-file limits in addition to the
per-cell wall timeout.

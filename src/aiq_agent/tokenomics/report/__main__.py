# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""CLI entry point: python -m aiq_agent.tokenomics.report"""

from __future__ import annotations

import argparse

from . import generate_report

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a tokenomics HTML report from a NAT profiler trace.")
    parser.add_argument(
        "--trace",
        required=True,
        action="append",
        metavar="TRACE",
        help=(
            "Path to all_requests_profiler_traces.json.  "
            "Repeat the flag to compare multiple runs (e.g. --trace run_a/traces.json --trace run_b/traces.json)."
        ),
    )
    parser.add_argument("--config", required=True, help="Path to the eval config YAML")
    parser.add_argument(
        "--output",
        default=None,
        help="Output HTML path (default: <first_trace_dir>/tokenomics_report.html)",
    )
    args = parser.parse_args()
    generate_report(args.trace, args.config, args.output)

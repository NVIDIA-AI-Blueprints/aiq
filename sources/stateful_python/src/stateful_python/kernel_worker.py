# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""JSON-lines worker for one persistent Python analysis process."""

from __future__ import annotations

import ast
import contextlib
import io
import itertools
import json
import math
import re
import statistics
import sys
import traceback
from collections import Counter
from collections import defaultdict
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import scipy
import sklearn
import statsmodels.api as sm
from scipy import stats


def _read_manifest() -> dict[str, Any]:
    path = Path(sys.argv[1])
    return json.loads(path.read_text(encoding="utf-8"))


def list_gsf_results() -> pd.DataFrame:
    """List exact GSF SQL results currently registered for this request."""

    entries = _read_manifest().get("results") or []
    columns = ["ref", "question", "database_name", "request_id", "row_count", "columns", "truncated"]
    return pd.DataFrame(entries).reindex(columns=columns)


def _resolve_gsf_reference(reference: str | None = None) -> dict[str, Any]:
    entries = _read_manifest().get("results") or []
    if not entries:
        raise LookupError("No successful GSF text-to-SQL results are registered for this request.")
    if reference in {None, "latest"}:
        return entries[-1]
    for entry in entries:
        if entry.get("ref") == reference:
            return entry
    available = ", ".join(str(entry.get("ref")) for entry in entries)
    raise KeyError(f"Unknown GSF result reference {reference!r}. Available references: {available}")


def gsf_result(reference: str | None = None) -> dict[str, Any]:
    """Load the complete normalized GSF response for a stable reference."""

    entry = _resolve_gsf_reference(reference)
    return json.loads(Path(entry["path"]).read_text(encoding="utf-8"))


def gsf_rows(reference: str | None = None) -> pd.DataFrame:
    """Load the exact rows from a GSF response as a pandas DataFrame."""

    return pd.DataFrame(gsf_result(reference).get("rows") or [])


def gsf_sql(reference: str | None = None) -> str:
    """Return the generated SQL associated with one GSF response."""

    return str(gsf_result(reference).get("sql") or "")


def gsf_latest() -> pd.DataFrame:
    """Load the exact rows from the most recently registered GSF response."""

    return gsf_rows("latest")


def _compile_cell(code: str) -> tuple[Any | None, Any | None]:
    tree = ast.parse(code, mode="exec")
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        statements = ast.Module(body=tree.body[:-1], type_ignores=[])
        expression = ast.Expression(body=tree.body[-1].value)
        return compile(statements, "<aiq-python>", "exec"), compile(expression, "<aiq-python>", "eval")
    return compile(tree, "<aiq-python>", "exec"), None


def _display(value: Any, max_output_chars: int) -> str:
    if value is None:
        return ""
    if isinstance(value, pd.DataFrame):
        rendered = value.to_string(max_rows=60, max_cols=50, line_width=160)
    elif isinstance(value, pd.Series):
        rendered = value.to_string(max_rows=100)
    elif isinstance(value, np.ndarray):
        rendered = np.array2string(value, threshold=500, edgeitems=20)
    else:
        rendered = repr(value)
    if len(rendered) <= max_output_chars:
        return rendered
    return rendered[:max_output_chars] + "\n... output truncated ..."


def _visible_variables(namespace: dict[str, Any]) -> list[str]:
    hidden = {
        "Counter",
        "Path",
        "date",
        "datetime",
        "defaultdict",
        "gsf_latest",
        "gsf_result",
        "gsf_rows",
        "gsf_sql",
        "itertools",
        "json",
        "list_gsf_results",
        "math",
        "np",
        "pd",
        "re",
        "scipy",
        "sklearn",
        "sm",
        "statistics",
        "stats",
        "timedelta",
        "timezone",
    }
    return sorted(name for name in namespace if not name.startswith("_") and name not in hidden)


def _execute(namespace: dict[str, Any], code: str, max_output_chars: int) -> dict[str, Any]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        statements, expression = _compile_cell(code)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            if statements is not None:
                exec(statements, namespace)
            value = eval(expression, namespace) if expression is not None else None
        printed = stdout.getvalue()
        warnings = stderr.getvalue()
        combined = printed + (("\n" if printed and warnings else "") + warnings if warnings else "")
        if len(combined) > max_output_chars:
            combined = combined[:max_output_chars] + "\n... output truncated ..."
        return {
            "status": "ok",
            "output": combined,
            "result": _display(value, max_output_chars),
            "result_type": type(value).__name__ if value is not None else None,
            "variables": _visible_variables(namespace),
        }
    except Exception as exc:  # noqa: BLE001 - kernel errors are serialized to the agent
        return {
            "status": "error",
            "error": type(exc).__name__,
            "detail": str(exc)[:2_000],
            "traceback": "".join(traceback.format_exception(exc))[-4_000:],
            "output": stdout.getvalue()[:max_output_chars],
            "variables": _visible_variables(namespace),
        }


def main() -> None:
    max_output_chars = int(sys.argv[2])
    namespace: dict[str, Any] = {
        "__name__": "__aiq_analysis__",
        "Counter": Counter,
        "Path": Path,
        "date": date,
        "datetime": datetime,
        "defaultdict": defaultdict,
        "gsf_latest": gsf_latest,
        "gsf_result": gsf_result,
        "gsf_rows": gsf_rows,
        "gsf_sql": gsf_sql,
        "itertools": itertools,
        "json": json,
        "list_gsf_results": list_gsf_results,
        "math": math,
        "np": np,
        "pd": pd,
        "re": re,
        "scipy": scipy,
        "sklearn": sklearn,
        "sm": sm,
        "statistics": statistics,
        "stats": stats,
        "timedelta": timedelta,
        "timezone": timezone,
    }
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get("operation") == "close":
                response = {"status": "ok", "operation": "close"}
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
                return
            response = _execute(namespace, str(request.get("code") or ""), max_output_chars)
        except Exception as exc:  # noqa: BLE001 - protocol errors must remain recoverable
            response = {"status": "error", "error": type(exc).__name__, "detail": str(exc)[:2_000]}
        sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

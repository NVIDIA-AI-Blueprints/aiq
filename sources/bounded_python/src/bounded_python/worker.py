# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Isolated worker for one bounded Python calculation."""

from __future__ import annotations

import ast
import io
import json
import math
import resource
import statistics
import sys
from typing import Any


class _LimitedWriter(io.StringIO):
    def __init__(self, max_chars: int) -> None:
        super().__init__()
        self.max_chars = max_chars

    def write(self, value: str) -> int:
        if self.tell() + len(value) > self.max_chars:
            raise ValueError("printed output exceeds the configured limit")
        return super().write(value)


def _safe_print(*values: Any, sep: str = " ", end: str = "\n") -> None:
    print(*values, sep=sep, end=end, file=_OUTPUT)


def _safe_get(mapping: Any, key: Any, default: Any = None) -> Any:
    if not isinstance(mapping, dict):
        raise TypeError("get() requires a dictionary")
    return mapping.get(key, default)


_SAFE_FUNCTIONS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "get": _safe_get,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "mean": statistics.mean,
    "median": statistics.median,
    "min": min,
    "pow": pow,
    "print": _safe_print,
    "pstdev": statistics.pstdev,
    "range": range,
    "round": round,
    "sorted": sorted,
    "set": set,
    "sqrt": math.sqrt,
    "stdev": statistics.stdev,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}
_RESERVED_NAMES = frozenset({"inputs", "result", *_SAFE_FUNCTIONS})
_PROTECTED_ASSIGNMENTS = frozenset({"inputs", *_SAFE_FUNCTIONS})
_ALLOWED_NODES = (
    ast.Module,
    ast.Assign,
    ast.AnnAssign,
    ast.AugAssign,
    ast.Expr,
    ast.If,
    ast.For,
    ast.Break,
    ast.Continue,
    ast.Pass,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Dict,
    ast.Subscript,
    ast.Slice,
    ast.Starred,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.comprehension,
    ast.JoinedStr,
    ast.FormattedValue,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Not,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
)


def _validate(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"syntax is not allowed: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError("private names are not allowed")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _SAFE_FUNCTIONS:
                raise ValueError("only documented safe functions may be called")
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in _PROTECTED_ASSIGNMENTS:
                    raise ValueError(f"cannot assign reserved name: {target.id}")


def _make_result_explicit(tree: ast.Module) -> ast.Module:
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        tree.body[-1] = ast.Assign(targets=[ast.Name(id="result", ctx=ast.Store())], value=tree.body[-1].value)
        ast.fix_missing_locations(tree)
    return tree


def _json_round_trip(value: Any) -> Any:
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return json.loads(encoded)


def _apply_limits(cpu_seconds: int, memory_bytes: int) -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    except (ValueError, OSError):
        pass


def main() -> None:
    cpu_seconds = int(sys.argv[1])
    memory_bytes = int(sys.argv[2])
    max_output_chars = int(sys.argv[3])
    _apply_limits(cpu_seconds, memory_bytes)
    payload = json.load(sys.stdin)
    tree = ast.parse(payload["code"], mode="exec")
    _validate(tree)
    tree = _make_result_explicit(tree)
    locals_dict = dict(payload.get("state") or {})
    locals_dict["inputs"] = payload.get("inputs") or {}
    globals_dict = {"__builtins__": {}, **_SAFE_FUNCTIONS}
    exec(compile(tree, "<bounded-analysis>", "exec"), globals_dict, locals_dict)
    state = {
        key: _json_round_trip(value)
        for key, value in locals_dict.items()
        if key not in _RESERVED_NAMES and not key.startswith("_")
    }
    response = {
        "status": "ok",
        "result": _json_round_trip(locals_dict.get("result")),
        "output": _OUTPUT.getvalue(),
        "state": state,
    }
    encoded = json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(encoded) > max_output_chars * 4:
        raise ValueError("worker response exceeds the configured limit")
    sys.stdout.write(encoded)


_OUTPUT = _LimitedWriter(int(sys.argv[3]) if len(sys.argv) > 3 else 50_000)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - serialize a bounded error across the process boundary
        sys.stdout.write(
            json.dumps(
                {"status": "error", "error": "invalid_or_failed_code", "detail": str(exc)[:500]},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )

"""Evaluate final answers and complete-response latency: python -m evals.run_eval --help."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import statistics
from collections import Counter
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from .agent_api import APIOptions
from .agent_api import request_answer
from .judge import judge_answer
from .upload import upload_file

REQUIRED = {"id", "difficulty", "question", "expected_answer", "answer_type", "retrieval_scope"}
FIELDS = [
    "id",
    "difficulty",
    "question",
    "expected_answer",
    "agent_answer",
    "answer_source",
    "score",
    "is_correct",
    "scoring_method",
    "scoring_reason",
    "latency_ms",
    "http_status",
    "error",
    "answer_type",
    "retrieval_scope",
    "first_attempt_latency_ms",
    "final_attempt_latency_ms",
    "total_latency_ms",
    "attempt_count",
    "attempts_json",
    "needs_review",
    "judge_error",
    "judge_latency_ms",
]


def load_dataset(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not REQUIRED.issubset(reader.fieldnames or []):
            raise ValueError(f"Dataset missing columns: {', '.join(sorted(REQUIRED - set(reader.fieldnames or [])))}")
        rows = list(reader)
    if not rows:
        raise ValueError("Dataset is empty.")
    ids = set()
    for row in rows:
        if None in row or any(not isinstance(row.get(key), str) or not row[key].strip() for key in REQUIRED):
            raise ValueError("Dataset contains a malformed or incomplete row.")
        if row["id"] in ids:
            raise ValueError(f"Duplicate question ID: {row['id']}")
        ids.add(row["id"])
        if row["answer_type"] not in {"text", "number", "currency", "percentage", "date", "list"}:
            raise ValueError(f"Unsupported answer_type for {row['id']}: {row['answer_type']}")
    return rows


def latency_stats(values: list[float]) -> dict[str, int | float | None]:
    ordered = sorted(values)

    def percentile(fraction: float) -> float | None:
        if not ordered:
            return None
        position = (len(ordered) - 1) * fraction
        low, high = math.floor(position), math.ceil(position)
        return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

    return {
        "count": len(values),
        "average": statistics.fmean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "p90": percentile(0.90),
        "p95": percentile(0.95),
        "minimum": min(values) if values else None,
        "maximum": max(values) if values else None,
    }


def _accuracy(rows: list[dict[str, Any]]) -> dict[str, int | float]:
    correct = sum(row["is_correct"] for row in rows)
    return {
        "count": len(rows),
        "correct": correct,
        "accuracy": correct / len(rows) if rows else 0,
        "mean_component_score": statistics.fmean(row["score"] for row in rows) if rows else 0,
    }


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [row for row in results if not row["error"]]
    failed = len(results) - len(successful)
    grouped = {}
    for dimension in ("difficulty", "answer_type", "retrieval_scope"):
        grouped[f"accuracy_by_{dimension}"] = {
            group: _accuracy([row for row in results if row[dimension] == group])
            for group in sorted({row[dimension] for row in results})
        }
    return {
        "overall": _accuracy(results),
        **grouped,
        "latency_ms": latency_stats([row["latency_ms"] for row in successful]),
        "latency_by_difficulty_ms": {
            group: latency_stats([row["latency_ms"] for row in successful if row["difficulty"] == group])
            for group in sorted({row["difficulty"] for row in results})
        },
        "all_requests_latency_ms": latency_stats([row["latency_ms"] for row in results]),
        "first_attempt_latency_ms": latency_stats([row["first_attempt_latency_ms"] for row in results]),
        "final_attempt_latency_ms": latency_stats([row["final_attempt_latency_ms"] for row in successful]),
        "error_count": failed,
        "failed_request_rate": failed / len(results) if results else 0,
        "total_attempts": sum(row["attempt_count"] for row in results),
        "failed_attempt_count": sum(bool(attempt["error"]) for row in results for attempt in row["attempts"]),
        "retried_question_count": sum(row["attempt_count"] > 1 for row in results),
        "judge_error_count": sum(bool(row["judge_error"]) for row in results),
        "needs_review_count": sum(row["needs_review"] for row in results),
        "scoring_methods": dict(Counter(row["scoring_method"] for row in results)),
        "latency_definition": (
            "Milliseconds from first POST until the complete final chat answer or report, including job polling "
            "and retries/backoff; "
            "excludes queueing and scoring. Primary latency statistics include successful requests only, "
            "regardless of answer correctness."
        ),
        "percentile_method": "Linear interpolation at (n-1)*p. Empty groups use null statistics.",
    }


def _env(name: str, default: str = "") -> str:
    return os.getenv(f"RAG_EVAL_{name}", default)


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env(name, str(default)).casefold()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError(f"RAG_EVAL_{name} must be a boolean.")
    return value in {"true", "1", "yes"}


def _json(value: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError("Expected valid JSON.") from exc


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "--dataset",
        type=Path,
        default=Path(_env("DATASET", str(Path(__file__).with_name("project_solace_retrieval_ground_truth.csv")))),
    )
    cli.add_argument(
        "--upload-file",
        type=Path,
        default=_env("UPLOAD_FILE") or None,
        help="Upload this file to a new collection before each evaluation run.",
    )
    cli.add_argument(
        "--upload-timeout",
        type=float,
        default=_env("UPLOAD_TIMEOUT", "1800"),
        help="Maximum seconds for creating the collection, upload and ingestion.",
    )
    cli.add_argument("--endpoint", default=_env("ENDPOINT", "http://localhost:8000/v1/chat/completions"))
    cli.add_argument("--api-key", default=_env("API_KEY"), help="Prefer RAG_EVAL_API_KEY to avoid shell history.")
    cli.add_argument("--model", default=_env("MODEL"), help="Optional model field sent to the agent API.")
    cli.add_argument(
        "--collection", default=_env("COLLECTION"), help="AI-Q conversation-id header: exact uploaded collection name."
    )
    cli.add_argument(
        "--timeout",
        type=float,
        default=_env("TIMEOUT", "300"),
        help="Deadline in seconds per attempt, including report polling and download.",
    )
    cli.add_argument(
        "--poll-interval",
        type=float,
        default=_env("POLL_INTERVAL", "2"),
        help="Seconds between checks while an asynchronous report job is pending.",
    )
    cli.add_argument("--concurrency", type=int, default=_env("CONCURRENCY", "1"))
    cli.add_argument("--stream", action=argparse.BooleanOptionalAction, default=_env_bool("STREAM"))
    cli.add_argument(
        "--retries", type=int, default=_env("RETRIES", "2"), help="Additional attempts for retryable failures."
    )
    cli.add_argument("--retry-delay", type=float, default=_env("RETRY_DELAY", "1"))
    cli.add_argument("--max-retry-delay", type=float, default=_env("MAX_RETRY_DELAY", "30"))
    cli.add_argument(
        "--numeric-tolerance",
        type=float,
        default=_env("NUMERIC_TOLERANCE", "0.000001"),
        help="Numeric tolerance supplied to the LLM judge (base units; ratios for percentages).",
    )
    cli.add_argument("--date-order", choices=["dmy", "mdy"], default=_env("DATE_ORDER", "dmy"))
    cli.add_argument(
        "--extra-body", type=_json, default=_env("EXTRA_BODY", "{}"), help="Static extra request fields as JSON."
    )
    cli.add_argument(
        "--headers",
        type=_json,
        default=_env("HEADERS", "{}"),
        help="Extra HTTP headers as JSON; prefer the environment for secrets.",
    )
    cli.add_argument("--output-csv", type=Path, default=Path(_env("OUTPUT_CSV", "evals/results/answers.csv")))
    cli.add_argument("--summary-json", type=Path, default=Path(_env("SUMMARY_JSON", "evals/results/summary.json")))
    cli.add_argument("--limit", type=int, default=_env("LIMIT", "0"), help="First N questions; 0 means all rows.")
    cli.add_argument("--judge-endpoint", default=_env("JUDGE_ENDPOINT"))
    cli.add_argument("--judge-api-key", default=_env("JUDGE_API_KEY"))
    cli.add_argument("--judge-model", default=_env("JUDGE_MODEL"))
    cli.add_argument(
        "--judge-prompt",
        type=Path,
        default=Path(_env("JUDGE_PROMPT", str(Path(__file__).with_name("judge_prompt.md")))),
    )
    cli.add_argument("--judge-timeout", type=float, default=_env("JUDGE_TIMEOUT", "120"))
    return cli


def validate_args(args: argparse.Namespace) -> None:
    if args.concurrency < 1 or args.retries < 0 or args.limit < 0:
        raise ValueError("Concurrency must be positive; retries and limit must be nonnegative.")
    if not math.isfinite(args.poll_interval) or args.poll_interval <= 0:
        raise ValueError("Poll interval must be finite positive seconds.")
    if any(not math.isfinite(value) or value <= 0 for value in (args.timeout, args.judge_timeout, args.upload_timeout)):
        raise ValueError("Timeouts must be finite positive seconds.")
    if any(not math.isfinite(value) or value < 0 for value in (args.retry_delay, args.max_retry_delay)):
        raise ValueError("Retry delays must be finite and nonnegative.")
    if not math.isfinite(args.numeric_tolerance) or args.numeric_tolerance < 0:
        raise ValueError("Numeric tolerances must be finite and nonnegative.")
    if not args.judge_endpoint or not args.judge_model:
        raise ValueError("Set --judge-endpoint and --judge-model (or their environment variables).")
    if not isinstance(args.extra_body, dict) or not isinstance(args.headers, dict):
        raise ValueError("Extra body and headers must be JSON objects.")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in args.headers.items()):
        raise ValueError("Header names and values must be strings.")
    if args.upload_file:
        if args.collection or any(key.casefold() == "conversation-id" for key in args.headers):
            raise ValueError(
                "Use --upload-file without --collection or a conversation-id header; a fresh collection is automatic."
            )
        if not args.upload_file.is_file():
            raise ValueError(f"Upload file not found: {args.upload_file}")
    if args.date_order not in {"dmy", "mdy"}:
        raise ValueError("Date order must be dmy or mdy.")
    for endpoint in [args.endpoint, args.judge_endpoint]:
        try:
            url = httpx.URL(endpoint)
            valid = url.scheme in {"http", "https"} and bool(url.host) and not url.userinfo
        except httpx.InvalidURL:
            valid = False
        if not valid:
            raise ValueError(
                "API endpoints must be complete HTTP(S) URLs without embedded credentials. "
                "Pass authentication through the API key or headers."
            )
    paths = [
        args.dataset.resolve(),
        args.judge_prompt.resolve(),
        args.output_csv.resolve(),
        args.summary_json.resolve(),
        *([args.upload_file.resolve()] if args.upload_file else []),
    ]
    if len(set(paths)) != len(paths):
        raise ValueError("Dataset, upload file, judge prompt and output files must use different paths.")


async def evaluate(args: argparse.Namespace, *, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    validate_args(args)
    rows = load_dataset(args.dataset)
    rows = rows[: args.limit] if args.limit else rows
    prompt = args.judge_prompt.read_text(encoding="utf-8")
    if not prompt.strip():
        raise ValueError("Judge prompt is empty.")
    api = APIOptions(
        args.endpoint,
        args.api_key,
        args.model,
        args.timeout,
        args.stream,
        args.retries,
        args.retry_delay,
        args.max_retry_delay,
        args.collection,
        args.extra_body,
        {**{key.lower(): value for key, value in args.headers.items()}, "x-aiq-stateless": "true"},
        poll_interval=args.poll_interval,
    )
    judge_api = APIOptions(
        args.judge_endpoint,
        args.judge_api_key,
        args.judge_model,
        args.judge_timeout,
        retries=args.retries,
        retry_delay=args.retry_delay,
        max_retry_delay=args.max_retry_delay,
    )
    results: list[dict[str, Any] | None] = [None] * len(rows)
    pending = iter(enumerate(rows))
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    ingestion = None
    async with httpx.AsyncClient(
        timeout=None,
        transport=transport,
        follow_redirects=False,
        limits=httpx.Limits(max_connections=args.concurrency),
    ) as client:
        if args.upload_file:
            print(f"Uploading {args.upload_file.name} to a fresh evaluation collection...", flush=True)
            ingestion = await upload_file(client, args.upload_file, api, timeout=args.upload_timeout)
            api.collection = ingestion["collection_name"]
            print("Workbook ingestion completed. Starting questions.", flush=True)
        with args.output_csv.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            output.flush()

            async def worker() -> None:
                for index, row in pending:
                    response = await request_answer(client, row["question"], api)
                    if response["error"]:
                        judgment = {
                            "score": 0,
                            "is_correct": False,
                            "scoring_method": "request_error",
                            "scoring_reason": response["error"],
                            "judge_error": "",
                            "needs_review": False,
                            "judge_latency_ms": None,
                        }
                    else:
                        judgment = await judge_answer(
                            client,
                            row,
                            response["agent_answer"],
                            judge_api,
                            prompt,
                            numeric_tolerance=args.numeric_tolerance,
                            date_order=args.date_order,
                        )
                    result = {
                        **row,
                        **response,
                        **judgment,
                        "attempts_json": json.dumps(response["attempts"], ensure_ascii=False),
                    }
                    results[index] = result
                    writer.writerow(result)
                    output.flush()  # Preserve completed rows if a long evaluation is interrupted.
                    print(
                        f"[{sum(item is not None for item in results)}/{len(rows)}] {row['id']}: "
                        f"score={judgment['score']:.3f}, latency={response['latency_ms']:.0f} ms, "
                        f"{judgment['scoring_method']}"
                    )

            await asyncio.gather(*(worker() for _ in range(min(args.concurrency, len(rows)))))
    completed = [row for row in results if row is not None]
    summary = {
        "created_at": datetime.now(UTC).isoformat(),
        "dataset": str(args.dataset),
        "ingestion": ingestion,
        "configuration": {
            "model": args.model,
            "stream": args.stream,
            "concurrency": args.concurrency,
            "timeout_seconds": args.timeout,
            "poll_interval_seconds": args.poll_interval,
            "retries": args.retries,
            "numeric_tolerance": str(args.numeric_tolerance),
            "date_order": args.date_order,
            "judge_model": args.judge_model,
            "judge_prompt": str(args.judge_prompt),
        },
        **aggregate(completed),
    }
    args.summary_json.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    try:
        cli = parser()
    except ValueError as exc:
        argparse.ArgumentParser().error(str(exc))
    args = cli.parse_args()
    try:
        summary = asyncio.run(evaluate(args))
    except (ValueError, OSError) as exc:
        cli.error(str(exc))
    except KeyboardInterrupt:
        print("Interrupted. Completed rows were flushed to the detailed CSV; aggregate summary was not completed.")
        return 130
    print(
        f"Accuracy: {summary['overall']['accuracy']:.1%}; failed requests: {summary['error_count']}; "
        f"needs review: {summary['needs_review_count']}"
    )
    print(f"Detailed results: {args.output_csv}\nSummary: {args.summary_json}")
    return 1 if summary["error_count"] or summary["judge_error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

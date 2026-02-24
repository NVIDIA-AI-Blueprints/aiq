#!/usr/bin/env python3
"""
DRB Score Aggregation Script

Aggregates scores from multiple DRB evaluation runs, filtering out failed runs
and calculating reliable metrics across successful runs.

Based on the analysis notebook logic:
- Filter out failed runs (score < 5 as proxy for failures)
- Calculate per-question mean/std scores across successful runs
- Extract fine-grained metrics (comprehensiveness, insight, instruction_following, readability)
- Output final aggregated metrics
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


def load_race_output(file_path: Path) -> list[dict[str, Any]]:
    """Load eval_output_items from a race_output.json file."""
    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("eval_output_items", [])


def create_dataframe(file_path: Path, run_name: str) -> pd.DataFrame:
    """Create a DataFrame from a race_output.json file."""
    items = load_race_output(file_path)
    df = pd.DataFrame(items)
    df["run"] = run_name
    df["source_file"] = str(file_path)
    return df


def extract_fine_grained_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Extract fine-grained metrics from the reasoning field."""
    df = df.copy()

    def get_metric(x: Any, key: str) -> float:
        return x.get(key, 0) if isinstance(x, dict) else 0

    df["comprehensiveness"] = df["reasoning"].apply(lambda x: get_metric(x, "comprehensiveness"))
    df["insight"] = df["reasoning"].apply(lambda x: get_metric(x, "insight"))
    df["instruction_following"] = df["reasoning"].apply(lambda x: get_metric(x, "instruction_following"))
    df["readability"] = df["reasoning"].apply(lambda x: get_metric(x, "readability"))
    return df


def aggregate_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate scores by question ID."""
    agg_df = df.groupby("id")["score"].agg(["mean", "std", "count", list]).reset_index()
    agg_df.columns = ["id", "mean", "std", "num_runs", "all_scores"]
    agg_df["id"] = agg_df["id"].apply(int)
    agg_df = agg_df.sort_values("id", ascending=True).reset_index(drop=True)
    agg_df["mean"] = agg_df["mean"].apply(lambda x: round(x, 2))
    agg_df["std"] = agg_df["std"].apply(lambda x: round(x, 2) if pd.notna(x) else 0.0)
    agg_df["all_scores"] = agg_df["all_scores"].apply(lambda x: [round(s, 2) for s in x])
    return agg_df


def calculate_fine_grained_summary(df: pd.DataFrame) -> dict[str, float]:
    """Calculate fine-grained metric averages."""
    metrics = ["comprehensiveness", "insight", "instruction_following", "readability"]
    fine_grained_df = df.groupby("id")[metrics].agg("mean").reset_index()
    summary = (fine_grained_df[metrics].mean() * 100).round(2)
    return summary.to_dict()


def _expand_input_dirs(args: list[str]) -> list[Path]:
    """Resolve and expand input dir args: resolve relative paths and expand glob patterns."""
    expanded: list[Path] = []
    for arg in args:
        p = Path(arg)
        if any(c in p.name for c in "*?["):
            # Glob pattern: expand in parent directory
            base = p.parent.resolve()
            for d in sorted(base.glob(p.name)):
                if d.is_dir():
                    expanded.append(d.resolve())
        else:
            expanded.append(p.resolve())
    return expanded


def find_race_outputs(input_dir: Path) -> list[Path]:
    """Find race_output.json files: run*/race_output.json and/or top-level race_output.json."""
    files = []
    # Prefer run* subdirectories containing race_output.json
    for run_dir in sorted(input_dir.glob("run*")):
        if run_dir.is_dir():
            race_file = run_dir / "race_output.json"
            if race_file.exists():
                files.append(race_file)
    # If no run* layout, accept top-level race_output.json (e.g. results/hybrid_full/)
    if not files:
        top_level = input_dir / "race_output.json"
        if top_level.exists():
            files.append(top_level)
    return files


def main():
    parser = argparse.ArgumentParser(description="Aggregate DRB evaluation scores from multiple runs")
    parser.add_argument(
        "--input-dir",
        type=str,
        nargs="+",
        required=True,
        metavar="DIR",
        help=(
            "One or more directories (or globs like ./results/hybrid_full*); "
            "each may have run*/race_output.json and/or top-level race_output.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output file for aggregated results (path can be relative)",
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=5.0,
        help="Minimum score threshold to consider a run successful (default: 5.0)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed output",
    )
    args = parser.parse_args()

    # Resolve paths and expand glob patterns (e.g. ./results/hybrid_full*)
    input_dirs = _expand_input_dirs(args.input_dir)
    if not input_dirs:
        patterns = ", ".join(args.input_dir)
        print(f"Error: No directories matched pattern(s): {patterns}")
        sys.exit(1)
    for input_dir in input_dirs:
        if not input_dir.exists():
            print(f"Error: Input directory does not exist: {input_dir}")
            sys.exit(1)

    # Find all race_output.json files (run* subdirs or top-level) under each input dir
    files: list[Path] = []
    for input_dir in input_dirs:
        files.extend(find_race_outputs(input_dir))

    if not files:
        dirs_msg = ", ".join(str(d) for d in input_dirs)
        print(f"No race_output.json files found (run*/ or top-level) in: {dirs_msg}")
        sys.exit(1)

    print(f"Found {len(files)} result file(s):")
    for f in files:
        print(f"  - {f}")
    print()

    # Load and combine all results
    dfs = []
    for file_path in files:
        run_name = file_path.parent.name  # e.g., "run1", "run2"
        try:
            df = create_dataframe(file_path, run_name)
            dfs.append(df)
            print(f"Loaded {len(df)} items from {file_path}")
        except (json.JSONDecodeError, KeyError, FileNotFoundError) as e:
            print(f"Warning: Could not load {file_path}: {e}")

    if not dfs:
        print("No valid data files found!")
        sys.exit(1)

    # Combine all dataframes
    combined_df = pd.concat(dfs).reset_index(drop=True)
    total_runs = len(combined_df)
    print(f"\nTotal evaluation items: {total_runs}")

    # Filter out failed runs
    filtered_df = combined_df[combined_df["score"] > args.score_threshold].reset_index(drop=True)
    successful_runs = len(filtered_df)
    failed_runs = total_runs - successful_runs
    failure_rate = (failed_runs / total_runs * 100) if total_runs > 0 else 0

    print(f"Successful runs (score > {args.score_threshold}): {successful_runs}")
    print(f"Failed runs: {failed_runs} ({failure_rate:.1f}%)")
    print()

    if successful_runs == 0:
        print("No successful runs to aggregate!")
        sys.exit(1)

    # Extract fine-grained metrics
    filtered_df = extract_fine_grained_metrics(filtered_df)

    # Aggregate scores by question ID
    agg_df = aggregate_scores(filtered_df)

    # Calculate overall metrics
    overall_mean = agg_df["mean"].mean().round(2)
    overall_std = agg_df["mean"].std().round(2)

    # Calculate fine-grained summary
    fine_grained_summary = calculate_fine_grained_summary(filtered_df)

    # Print results
    print("=" * 60)
    print("AGGREGATED RESULTS")
    print("=" * 60)
    print()
    print("Per-Question Scores:")
    print("-" * 60)
    print(agg_df.to_string(index=False))
    print()
    print("-" * 60)
    print(f"Overall Mean Score: {overall_mean}")
    print(f"Overall Std Dev: {overall_std}")
    print()
    print("Fine-Grained Metrics (% of max):")
    print("-" * 60)
    for metric, value in fine_grained_summary.items():
        print(f"  {metric}: {value}")
    print()

    # Prepare output data
    output_data = {
        "summary": {
            "total_runs": total_runs,
            "successful_runs": successful_runs,
            "failed_runs": failed_runs,
            "failure_rate_percent": round(failure_rate, 2),
            "score_threshold": args.score_threshold,
            "overall_mean_score": float(overall_mean),
            "overall_std_dev": float(overall_std),
        },
        "fine_grained_metrics": fine_grained_summary,
        "per_question_scores": agg_df.to_dict(orient="records"),
        "source_files": [str(f) for f in files],
    }

    # Save output (resolve so relative path works)
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)

    print(f"Results saved to: {output_path}")
    print()
    print("=" * 60)
    print(f"FINAL SCORE: {overall_mean}")
    print("=" * 60)


if __name__ == "__main__":
    main()

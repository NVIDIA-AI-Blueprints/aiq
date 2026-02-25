#!/usr/bin/env python3
"""
DRB Dataset Download Script

Downloads the DeepResearch Bench dataset files from the public GitHub repository:
- criteria.jsonl       – evaluation criteria (24 records)
- drb_full_dataset.json – 100 benchmark questions built by joining query.jsonl
                          with reference.jsonl on `id`

Run from the repository root:
    python frontends/benchmarks/deepresearch_bench/scripts/download_drb_dataset.py
"""

import sys
import urllib.request
from pathlib import Path

import pandas as pd

DATA_DIR = Path("frontends/benchmarks/deepresearch_bench/data")

CRITERIA_URL = (
    "https://raw.githubusercontent.com/Ayanami0730/deep_research_bench/main/data/criteria_data/criteria.jsonl"
)
QUERY_URL = "https://raw.githubusercontent.com/Ayanami0730/deep_research_bench/main/data/prompt_data/query.jsonl"
REFERENCES_URL = (
    "https://raw.githubusercontent.com/Ayanami0730/deep_research_bench/main/data/test_data/cleaned_data/reference.jsonl"
)


def download_criteria(data_dir: Path) -> None:
    criteria_path = data_dir / "criteria.jsonl"
    if criteria_path.exists():
        print("criteria.jsonl already exists, skipping download.")
        return
    print("Downloading criteria.jsonl...")
    urllib.request.urlretrieve(CRITERIA_URL, criteria_path)
    print(f"Downloaded criteria.jsonl ({criteria_path.stat().st_size:,} bytes)")


def download_dataset(data_dir: Path) -> None:
    dataset_path = data_dir / "drb_full_dataset.json"
    if dataset_path.exists():
        print("drb_full_dataset.json already exists, skipping.")
        return

    print("Downloading and building drb_full_dataset.json...")

    queries = pd.read_json(QUERY_URL, lines=True)
    references = pd.read_json(REFERENCES_URL, lines=True)[["id", "article"]]

    dataset = (
        queries.merge(references, on="id", how="left")
        .assign(
            article=lambda df: df["article"].fillna(""),
            id=lambda df: df["id"].astype(str),
        )
        .rename(columns={"prompt": "question", "article": "expected_output"})[
            ["id", "question", "topic", "language", "expected_output"]
        ]
    )

    dataset.to_json(dataset_path, orient="records", force_ascii=False, indent=2)

    missing = (dataset["expected_output"] == "").sum()
    print(f"Created drb_full_dataset.json with {len(dataset)} questions.")
    if missing:
        print(f"WARNING: Missing reference article for {missing} questions.")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Data directory: {DATA_DIR.resolve()}")

    try:
        download_criteria(DATA_DIR)
        download_dataset(DATA_DIR)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

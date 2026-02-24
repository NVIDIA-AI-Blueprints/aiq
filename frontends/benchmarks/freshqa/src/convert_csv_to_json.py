#!/usr/bin/env python3
"""Convert FreshQA CSV dataset to JSON format for NAT evaluation.

This script converts the FreshQA CSV dataset to a JSON format that includes
all answer columns (answer_0 through answer_9) for comprehensive evaluation.
"""

import json
from pathlib import Path

import pandas as pd


def convert_csv_to_json(input_csv: str, output_json: str, split_filter: str | None = None) -> None:
    """Convert FreshQA CSV to JSON format.

    Args:
        input_csv: Path to input CSV file
        output_json: Path to output JSON file
        split_filter: Optional split filter (e.g., "TEST", "DEV")
    """
    df = pd.read_csv(input_csv)

    if split_filter and "split" in df.columns:
        df = df[df["split"] == split_filter]
        print(f"Filtered to {len(df)} rows with split='{split_filter}'")

    records = []
    for _, row in df.iterrows():
        # Collect all answer columns
        answers = []
        for i in range(10):
            col = f"answer_{i}"
            if col in row and pd.notna(row[col]) and str(row[col]).strip():
                answers.append(str(row[col]).strip())

        # Build record
        record = {
            "id": row["id"] if pd.notna(row.get("id")) else len(records),
            "question": str(row["question"]) if pd.notna(row.get("question")) else "",
            "expected_output": {f"answer_{i}": answers[i] if i < len(answers) else None for i in range(len(answers))},
        }

        # Add optional fields
        if "false_premise" in row and pd.notna(row["false_premise"]):
            record["false_premise"] = bool(row["false_premise"])

        if "split" in row and pd.notna(row["split"]):
            record["split"] = str(row["split"])

        if "fact_type" in row and pd.notna(row["fact_type"]):
            record["fact_type"] = str(row["fact_type"])

        records.append(record)

    # Write JSON
    output_path = Path(output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    print(f"Converted {len(records)} records to {output_json}")

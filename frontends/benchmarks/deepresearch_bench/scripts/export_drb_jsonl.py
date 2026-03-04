#!/usr/bin/env python3
"""Convert workflow_output.json to DRB submission JSONL format.

Maps: id → id, question → prompt, generated_answer → article.
"""

import argparse
import json
import sys
from pathlib import Path


def convert(input_path: Path, output_path: Path) -> int:
    """Convert workflow_output.json to DRB JSONL. Returns number of entries written."""
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for item in data:
            article = item.get("generated_answer", "")
            if not article or len(article.strip()) < 100:
                print(f"  Warning: id={item['id']} has short/empty article ({len(article.strip())} chars)")
            entry = {"id": item["id"], "prompt": item["question"], "article": article}
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            written += 1

    return written


def main():
    parser = argparse.ArgumentParser(description="Convert workflow_output.json to DRB submission JSONL")
    parser.add_argument("--input", required=True, help="Path to workflow_output.json")
    parser.add_argument("--output", required=True, help="Output JSONL path")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        sys.exit(1)

    output_path = Path(args.output)
    count = convert(input_path, output_path)
    print(f"Exported {count} entries to {output_path}")


if __name__ == "__main__":
    main()

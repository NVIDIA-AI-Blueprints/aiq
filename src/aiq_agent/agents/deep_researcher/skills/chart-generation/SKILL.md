---
name: chart-generation
description: >
  Use this skill to turn researched or computed numeric data into source-grounded
  charts (PNG) plus the underlying CSV, by writing Python/matplotlib code and running
  it in the job-scoped sandbox. The chart is harvested as a durable artifact and
  embedded in the final report.
  Triggers: "chart", "plot", "graph", "bar chart", "line chart", "visualize",
  "trend over time", "compare visually", "figure".
  Outputs: a PNG chart artifact, a CSV of the plotted data, and a manifest describing them.
---

# Chart Generation Skill

Produce accurate, source-grounded charts using Python/matplotlib, save them as durable
artifacts, and embed them in the report by reference (never by pasting image data).

## Required Execution Standard

1. **Ground the data:** build the plotted rows from researched facts or `/shared/...`
   inputs. Keep source URLs/notes alongside the values.
2. **Normalize units** before plotting (currencies, magnitudes, periods).
3. **Render with code:** call `execute` to run Python/matplotlib. Do not hand-draw or
   fabricate charts.
4. **Write to the artifact directory:** save the PNG and its CSV under
   `/sandbox/aiq-artifacts/` with descriptive filenames.
5. **Write a manifest** so the chart is harvested reliably (see below).
6. **Reference, do not embed bytes:** in the report, link the chart with
   `![caption](artifact://<filename>.png)`. The runtime resolves this to the durable
   artifact; never paste base64 image data into the report.

## Execution Flow

1. Assemble the normalized rows (prefer explicit records embedded in the script). If the
   inputs live in `/shared/...`, `read_file` them first and embed the values; sandbox
   code cannot open `/shared/...`.
2. Use `write_file` to create `/sandbox/make_chart.py` and `execute` it. The script must:
   - import pandas and matplotlib (use the non-interactive `Agg` backend),
   - build the DataFrame, compute any derived metrics,
   - save the chart to `/sandbox/aiq-artifacts/<name>.png`,
   - save the plotted data to `/sandbox/aiq-artifacts/<name>.csv`,
   - write `/sandbox/aiq-artifacts/manifest.json` declaring the outputs.
3. Inspect the `execute` output; if it fails, fix the script and re-run (max 2 retries).
4. In the report, embed the chart with `![<caption>](artifact://<name>.png)` and cite the
   original data sources in the surrounding text.

## Placement and description in the report

Each figure must appear where it is discussed, not buried in a file list:

1. **Embed once, in context:** place the `![<caption>](artifact://<name>.png)` line inside
   the section that analyzes the figure (e.g. Results, Findings, or a Visualization
   subsection) - immediately after the paragraph that introduces it.
2. **Describe it:** precede the embed with one sentence stating what the chart shows and the
   takeaway (e.g. "The chart below compares 2025 resident population across the top five
   states; California leads at roughly 3x Pennsylvania.").
3. **Reference by filename, never a raw path:** the way to show a figure is the
   `![caption](artifact://<filename>.png)` token. Do NOT instead write the sandbox path
   (`/sandbox/aiq-artifacts/<name>.png`) as prose and expect it to render - a bare path is
   not an image.
4. **One embed per artifact:** list supporting files (CSVs, manifests) by name in an
   appendix if useful, but the chart itself must be embedded inline as above.

## Manifest

Write `/sandbox/aiq-artifacts/manifest.json` so the runtime captures the chart with
metadata:

```json
{
  "version": 1,
  "artifacts": [
    {
      "path": "/sandbox/aiq-artifacts/revenue_chart.png",
      "kind": "image",
      "title": "2024 Semiconductor Revenue Comparison",
      "caption": "Revenue normalized to USD billions.",
      "inline": true,
      "source_files": ["/shared/semiconductor_revenue_normalized.csv"]
    }
  ]
}
```

## Example Script

```python
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ARTIFACT_DIR = "/sandbox/aiq-artifacts"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

rows = [
    {"company": "ExampleCo", "revenue_usd_billions": 12.4, "source": "https://example.com/filing"},
    {"company": "SampleInc", "revenue_usd_billions": 9.1, "source": "https://example.com/10k"},
]
df = pd.DataFrame(rows).sort_values("revenue_usd_billions", ascending=False)

fig, ax = plt.subplots(figsize=(8, 5))
ax.bar(df["company"], df["revenue_usd_billions"])
ax.set_ylabel("Revenue (USD billions)")
ax.set_title("2024 Revenue Comparison")
fig.tight_layout()

png_path = f"{ARTIFACT_DIR}/revenue_chart.png"
csv_path = f"{ARTIFACT_DIR}/revenue_chart.csv"
fig.savefig(png_path, dpi=150)
df.to_csv(csv_path, index=False)

manifest = {
    "version": 1,
    "artifacts": [
        {
            "path": png_path,
            "kind": "image",
            "title": "2024 Revenue Comparison",
            "caption": "Revenue normalized to USD billions.",
            "inline": True,
            "source_files": [r["source"] for r in rows],
        }
    ],
}
with open(f"{ARTIFACT_DIR}/manifest.json", "w") as handle:
    json.dump(manifest, handle)

print(f"wrote {png_path}")
```

## Notes and Limitations

- Use the `Agg` backend; the sandbox has no display.
- Keep charts legible: labeled axes, a title, and a legend when multiple series are shown.
- If matplotlib or pandas is unavailable, report that the sandbox image needs them rather
  than fabricating a chart.
- Reference charts only by `artifact://<filename>`; the runtime assigns the durable id and
  rewrites the reference for the UI, PDF export, and the packaged skill CLI.

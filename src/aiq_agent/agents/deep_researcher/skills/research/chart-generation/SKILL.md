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
4. **Write to the artifact directory:** save the PNG and its CSV under the exact
   `sandbox_artifact_dir` given in your instructions (a per-job path such as
   `/sandbox/<job_id>/aiq-artifacts`). Use that value verbatim - do NOT write to a bare
   `/sandbox/aiq-artifacts`; the runtime only harvests files under `sandbox_artifact_dir`.
5. **Write a manifest** so the chart is harvested reliably (see below).
6. **Reference, do not embed bytes:** in the report, link the chart with
   `![caption](artifact://<filename>.png)`. The runtime resolves this to the durable
   artifact; never paste base64 image data into the report.

## Data sufficiency (earn the chart)

A chart confers authority, so it must be earned - never give unreliable data a cleaner
outfit. A polished chart of wrong or sparse numbers misleads more than it informs.

1. **Source-anchored points only:** every plotted value must trace to a specific source
   (the as-reported figure and its URL). Never plot a fabricated, guessed, or inferred
   number as if it were reported; mark genuine estimates as estimates.
2. **Suppress misleading charts:** if a series is mostly missing (a majority of periods
   undisclosed) or mixes metric definitions (e.g. "cash capex" vs "capex including finance
   leases"), do NOT produce a trend chart. Present the table (which shows the gaps) and
   state the limitation in one sentence instead.
3. **Show gaps honestly:** never interpolate or connect across missing periods. Plot only
   the periods a series actually reports, and render estimates distinctly (e.g. hollow or
   dashed markers) so they do not read as reported values.
4. **Prefer gap-tolerant forms:** grouped bars show missing periods as absent bars; favor
   them over a connected line when series are uneven, since a line drawn across gaps
   implies a trend that the data does not support.

## Execution Flow

1. Assemble the normalized rows (prefer explicit records embedded in the script). If the
   inputs live in `/shared/...`, `read_file` them first and embed the values; sandbox
   code cannot open `/shared/...`.
2. Use `write_file` to create the chart script under the exact `sandbox_workdir` from your
   instructions, then `execute` it with the exact `sandbox_artifact_dir` as its first argument.
   For example, when your instructions provide `/sandbox/JOB/` and
   `/sandbox/JOB/aiq-artifacts`, run
   `python3 /sandbox/JOB/make_chart.py /sandbox/JOB/aiq-artifacts`. Never execute a literal
   `<sandbox_workdir>` or `<sandbox_artifact_dir>` token.
   `sandbox_workdir` is already per-job, so scripts there cannot collide with another job's
   leftovers. Only ever execute a script you wrote this session. The script must:
   - import pandas and matplotlib (use the non-interactive `Agg` backend),
   - build the DataFrame, compute any derived metrics,
   - set a single `ARTIFACT_DIR` to your `sandbox_artifact_dir` and write the chart
     (`<name>.png`), its data (`<name>.csv`), and `manifest.json` there (see the example).
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
   (e.g. `<sandbox_artifact_dir>/<name>.png`) as prose and expect it to render - a bare path
   is not an image.
4. **One embed per artifact:** list supporting files (CSVs, manifests) by name in an
   appendix if useful, but the chart itself must be embedded inline as above.

## Manifest

Write a `manifest.json` in your `sandbox_artifact_dir` so the runtime captures the chart
with metadata. Manifest `path` values must be absolute and inside your `sandbox_artifact_dir`
(the per-job path from your instructions). Construct every manifest path from the runtime
argument as shown below; do not hand-copy an angle-bracket placeholder into JSON. Set
`inline: true` only for a raster image intended to appear in the report.

## Example Script

```python
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

if len(sys.argv) != 2:
    raise SystemExit("usage: make_chart.py ABSOLUTE_SANDBOX_ARTIFACT_DIR")
ARTIFACT_DIR = Path(sys.argv[1])
if not ARTIFACT_DIR.is_absolute():
    raise SystemExit("artifact directory must be an absolute path")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

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

png_path = ARTIFACT_DIR / "revenue_chart.png"
csv_path = ARTIFACT_DIR / "revenue_chart.csv"
fig.savefig(png_path, dpi=150)
df.to_csv(csv_path, index=False)

manifest = {
    "version": 1,
    "artifacts": [
        {
            "path": str(png_path),
            "kind": "image",
            "title": "2024 Revenue Comparison",
            "caption": "Revenue normalized to USD billions.",
            "inline": True,
            "source_files": [r["source"] for r in rows],
        }
    ],
}
with (ARTIFACT_DIR / "manifest.json").open("w", encoding="utf-8") as handle:
    json.dump(manifest, handle)

print(f"wrote {png_path}")
```

Run the script with the two exact per-job paths given in your instructions. The second argument
must be the real absolute artifact directory, not an angle-bracket placeholder. Treat the
artifact-checkpoint response after `execute` as authoritative: reference the exact confirmed
filename in the report and do not invent or rename it later.

## Notes and Limitations

- Use the `Agg` backend; the sandbox has no display.
- Keep charts legible: labeled axes, a title, and a legend when multiple series are shown.
- Do not call `read_file` on the generated PNG merely to verify it; binary reads return base64
  and waste model context. Inspect `manifest.json` with `read_file(file_path=...)` when needed,
  then rely on the artifact-checkpoint response to confirm the accepted filename and inline state.
- If matplotlib or pandas is unavailable, report that the sandbox image needs them rather
  than fabricating a chart.
- Reference charts only by `artifact://<filename>`; the runtime assigns the durable id and
  rewrites the reference for the UI, PDF export, and the packaged skill CLI.

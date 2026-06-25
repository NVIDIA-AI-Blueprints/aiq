---
name: image-processing
description: >
  Use this skill to inspect and transform images during research by writing Python/Pillow code and running it in the job-scoped sandbox. This skill is for image metadata (dimensions, mode, format, file size), format conversion, resizing and thumbnails, cropping, rotation, grayscale, and basic color/brightness analysis. Triggers: "image", "PNG", "JPEG", "WEBP", "resize", "downscale", "thumbnail", "convert format", "crop", "rotate", "grayscale", "image dimensions", "image metadata", "EXIF", "dominant color", "brightness". Outputs: JSON/Markdown metadata and analysis notes (plus an optional small base64 thumbnail) returned in your ResearchNotes for synthesis.
---

# Image Processing Skill

Inspect and transform images with Python/Pillow in the job-scoped sandbox, then emit text-survivable results — metadata, analysis notes, and optional small base64 thumbnails — that can be read and included in the final report.

## Required Execution Standard

To keep results reproducible and report-usable, you MUST:
1. **Source the Image Explicitly:** Identify where the image bytes come from (a `/shared/...` file, or base64 provided in the request). The sandbox has no network access, so images cannot be fetched by URL from inside `execute`.
2. **Stage Into `/workspace`:** If the image is in `/shared/...`, call `read_file` first and write the bytes into a `/workspace` file (or decode an inline base64 string). Sandbox code cannot open `/shared/...` directly.
3. **Process Deterministically:** Call the `execute` tool to run Python/Pillow for metadata, conversion, resizing, cropping, rotation, grayscale, or color analysis. Do not describe image properties in prose without measuring them.
4. **Emit Text-Survivable Outputs:** Durable outputs must be text. Include the metadata/analysis (as JSON or a Markdown block) in your returned `ResearchNotes` — e.g. in a `ResearchFinding`'s `evidence` and/or `narrative_notes`. For a visual, you may include a *small* base64 `data:image/...;base64,...` thumbnail in that text; lead with the metadata/analysis, which is always readable. Do not call `write_file`; `run_research_batch` persists your returned notes.
5. **Report Caveats:** Note the source of the image, and any lossy conversion, downscaling, stripped metadata, or color-space assumptions.

**Required Tool Use:** For any image inspection or transformation, this skill requires at least one `execute` call that runs Pillow before writing the final artifacts.

## Execution Flow

1. Determine the image source (a `/shared/...` path, or inline base64 in the request).
2. Stage the bytes into `/workspace`: `read_file` the `/shared` file and write it under `/workspace/input.<ext>`, or `base64`-decode an inline string. Never read from or write to `/shared/...` inside the sandbox process.
3. Call the `execute` tool with a Python/Pillow script that:
   - opens the image from `/workspace`,
   - performs the requested inspection or transform,
   - writes any derived image to `/workspace` (not `/shared`),
   - prints metadata/analysis as JSON or Markdown text, and a base64 string only for a small thumbnail.
4. Inspect the `execute` output. For fixable errors (bad path, unreadable/decode error), fix the code and call `execute` again. If a required library is missing (e.g. Pillow), report it as a sandbox limitation and stop — do not retry or invent image properties.
5. Return the result in your `ResearchNotes` — put the metadata/analysis (and any small base64 thumbnail) into a `ResearchFinding`'s `evidence` and/or `narrative_notes`. Do not call `write_file`/`edit_file`; `run_research_batch` persists your returned notes under `/shared/` automatically.
6. In the response or report, cite where the image came from and label any computed or derived values.

---

**Other operations** use the same pattern: `im.crop((left, upper, right, lower))`,
`im.rotate(deg, expand=True)`, `im.convert("L")` (grayscale), `im.resize((w, h))`.
Keep any embedded base64 thumbnail small (≤256 px) — base64 inflates size ~33%.

---

## Example Code Templates

### A. Inspect Image Metadata

Use when you only need dimensions, mode, format, and size. EXIF orientation is applied so
width/height are the *displayed* dimensions (orientation-tagged photos store them rotated).

```python
import json
from pathlib import Path
from PIL import Image, ImageOps

src = "/workspace/input.png"  # staged from /shared or decoded from base64
with Image.open(src) as im:
    fmt = im.format                         # read before transpose (transpose drops .format)
    oriented = ImageOps.exif_transpose(im)  # honor EXIF orientation -> displayed size
    meta = {
        "width": oriented.width,            # displayed dimensions
        "height": oriented.height,
        "mode": oriented.mode,              # e.g. "RGB", "RGBA", "L"
        "format": fmt,                      # e.g. "PNG", "JPEG"
        "size_bytes": Path(src).stat().st_size,
    }
print(json.dumps(meta, indent=2))
```

### B. Make a Thumbnail and Emit a Base64 Preview

Use when the report should show a small inline preview (there is no binary-artifact capture, so embed base64 text).

```python
import base64
import io
import json
from PIL import Image, ImageOps

with Image.open("/workspace/input.png") as im:
    im = ImageOps.exif_transpose(im).convert("RGB")  # honor EXIF orientation
    im.thumbnail((256, 256))     # preserves aspect ratio
    buf = io.BytesIO()
    im.save(buf, format="PNG")

b64 = base64.b64encode(buf.getvalue()).decode("ascii")
print(json.dumps({"thumb_width": im.width, "thumb_height": im.height, "b64_len": len(b64)}))
# Emit the data URI on its own line so the agent can include it in its ResearchNotes summary:
print(f"data:image/png;base64,{b64}")
```

The agent then includes that summary in its returned `ResearchNotes` — metadata first
(source, original WxH/mode/format/size), then the preview as
`![caption](data:image/png;base64,...)`.

### C. Convert Format

Use to standardize an image to JPEG/PNG/WEBP.

```python
from PIL import Image

with Image.open("/workspace/input.png") as im:
    if im.mode in ("RGBA", "P"):
        im = im.convert("RGB")   # JPEG has no alpha channel
    im.save("/workspace/output.jpg", "JPEG", quality=90)
print("Converted /workspace/input.png -> /workspace/output.jpg (JPEG q=90)")
```

### D. Basic Color / Brightness Analysis

Use to summarize an image without a full vision model.

```python
import json
from PIL import Image, ImageStat

with Image.open("/workspace/input.png") as im:
    stat = ImageStat.Stat(im.convert("RGB").resize((64, 64)))

avg_rgb = [round(c, 1) for c in stat.mean]       # mean per R, G, B channel
mean_brightness = round(sum(stat.mean) / 3, 1)   # 0-255
print(json.dumps({"avg_rgb": avg_rgb, "mean_brightness_0_255": mean_brightness}, indent=2))
```

---

## Troubleshooting in the Sandbox

- Missing Pillow: If `from PIL import Image` fails, report that the sandbox image needs `pillow` installed. Do not describe image contents from assumption.
- No network: The sandbox cannot fetch image URLs. Stage bytes from `/shared` (via `read_file`) or accept inline base64.
- `/shared` access: Sandbox code cannot read or write `/shared/...`. Use `/workspace` inside `execute`, then return the text result in your `ResearchNotes` (the harness persists it) — do not `write_file`.
- Binary outputs: There is no durable binary-artifact capture, so transformed images live only in `/workspace`. Persist results as text (metadata/JSON/Markdown), plus a small base64 thumbnail when a preview is needed.
- JPEG and alpha: Convert `RGBA`/`P` images to `RGB` before saving as JPEG.
---

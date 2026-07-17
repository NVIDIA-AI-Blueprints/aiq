# Building the Documentation

## Prerequisites

```bash
# Install doc dependencies from pyproject.toml
uv pip install -e ".[docs]"
```

## Build

```bash
make -C docs html
```

## Preview

```bash
python -m http.server --directory docs/build/html 8080
# Open http://localhost:8080
```

## Link Check

```bash
make -C docs linkcheck
```

## Release Metadata

[`source/project.json`](source/project.json) defines the published documentation version. The Sphinx configuration
reads its `name` and `version` fields, and the NVIDIA Docs publisher uses the same file to select the deployment
directory. [`source/versions1.json`](source/versions1.json) is the publisher index deployed at
`https://docs.nvidia.com/aiq-blueprint/versions1.json`.

Use the exact release artifact version, without a leading `v`. For example, the `v2.2.0-rc1` Git tag uses
`2.2.0-rc1`. When advancing the documentation version, update `source/project.json` and the preferred entry in
`source/versions1.json` together; the Sphinx build fails when they diverge.

The version switcher always reads the publisher index from the absolute URL
`https://docs.nvidia.com/aiq-blueprint/versions1.json`. The generated HTML also includes `versions1.json` at its root
so the deployment handoff can publish the global index. Do not change the switcher back to a relative URL; relative
paths resolve differently on top-level and nested pages.

The publisher-managed index does not allow cross-origin browser requests, so a preview served from a loopback host
cannot read it directly. For local previews, `source/_static/js/local-preview.js` replaces the switcher URL at runtime
with the bundled same-origin `source/versions1.json` and suppresses the production consent UI without changing consent
state, so the overlay does not block local page controls. Deployed documentation continues to use the absolute index
URL and normal consent behavior.

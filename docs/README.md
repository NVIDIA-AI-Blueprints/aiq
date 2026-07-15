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

[`source/project.json`](source/project.json) is the single source of truth for the published documentation version.
The Sphinx configuration reads its `name` and `version` fields, and the NVIDIA Docs publisher uses the same file to
select the deployment directory.

Use the exact release artifact version, without a leading `v`. For example, the `v2.2.0-rc1` Git tag uses
`2.2.0-rc1`. Update only `source/project.json` when advancing the documentation version.

The version switcher reads the publisher-managed index at
`https://docs.nvidia.com/aiq-blueprint/versions1.json`. Do not add a per-build `versions1.json`; a copied index becomes
stale and relative switcher URLs resolve differently on top-level and nested pages.

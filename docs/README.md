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

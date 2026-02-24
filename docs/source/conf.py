# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

project = "NVIDIA AI-Q Blueprint"
copyright = "2025-2026, NVIDIA CORPORATION & AFFILIATES"
author = "NVIDIA"

extensions = [
    "myst_parser",
    "sphinx_copybutton",
    "sphinxmermaid",
]

# MyST Markdown configuration
myst_enable_extensions = ["colon_fence", "attrs_inline"]
myst_fence_as_directive = ["mermaid"]
myst_heading_anchors = 4

source_suffix = [".md"]

# Copy button: strip common prompts from copied code
copybutton_prompt_text = ">>> |$ "

# Theme (matches NAT documentation styling)
try:
    import nvidia_sphinx_theme  # noqa: F401

    html_theme = "nvidia_sphinx_theme"
except ImportError:
    html_theme = "sphinx_rtd_theme"

html_theme_options = {
    "collapse_navigation": False,
    "navigation_depth": 6,
    "show_nav_level": 1,
}

html_static_path = ["_static"]
html_favicon = "_static/favicon.ico"
html_css_files = ["css/custom.css"]
html_js_files = ["js/mermaid-fullscreen.js"]
templates_path = ["_templates"]
html_show_sourcelink = False

# Suppress warnings for missing toctree references during incremental builds
suppress_warnings = ["toc.excluded"]

# Link checking
linkcheck_ignore = [
    r"http://localhost.*",
    r"http://127\.0\.0\.1.*",
]

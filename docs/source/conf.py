# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

project = "NVIDIA AI-Q Blueprint"
copyright = "2025-%Y, NVIDIA Corporation"
author = "NVIDIA Corporation"
release = "1.2.1"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "myst_parser",  # For our markdown docs
    "sphinx.ext.viewcode",  # For adding a link to view source code in docs
    "sphinx.ext.napoleon",  # For google style docstrings
    "sphinx_copybutton",  # For copy button in code blocks
    "sphinx_design",  # For grid cards and other design elements
    "sphinxmermaid",  # For mermaid diagrams
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Options for MyST Parser (Markdown) --------------------------------------
# MyST Parser settings
myst_enable_extensions = [
    "dollarmath",  # Enables dollar math for inline math
    "amsmath",  # Enables LaTeX math for display mode
    "colon_fence",  # Enables code blocks using ::: delimiters instead of ```
    "deflist",  # Supports definition lists with term: definition format
    "fieldlist",  # Enables field lists for metadata like :author: Name
    "tasklist",  # Adds support for GitHub-style task lists with [ ] and [x]
    "attrs_block",  # Enables setting attributes on block elements using {#id .class key=val}
]
myst_heading_anchors = 5  # Generates anchor links for headings up to level 5

# Configure MyST to handle mermaid code blocks
myst_fence_as_directive = ["mermaid"]

# -- Options for Mermaid -----------------------------------------------------
# Configure mermaid diagrams
mermaid_version = "latest"  # Use the latest version of mermaid

source_suffix = [".md"]

# Copy button: strip common prompts from copied code
copybutton_prompt_text = ">>> |$ "

html_theme = "nvidia_sphinx_theme"
html_theme_options = {
    "switcher": {"json_url": "../versions1.json", "version_match": release},
    "public_docs_features": True,
    "icon_links": [
        {
            "name": "GitHub",
            "url": "https://github.com/NVIDIA-AI-Blueprints/aiq",
            "icon": "fa-brands fa-github",
        }
    ],
    "collapse_navigation": False,
    "navigation_depth": 6,
    "show_nav_level": 1,
}

html_extra_path = ["project.json", "versions1.json"]
html_static_path = ["_static"]
html_favicon = "_static/favicon.ico"
html_css_files = ["css/custom.css"]
html_js_files = ["js/mermaid-fullscreen.js"]
html_show_sourcelink = False

# Suppress warnings for missing toctree references during incremental builds
suppress_warnings = ["toc.excluded"]

# Link checking
linkcheck_ignore = [
    r"http://localhost.*",
    r"http://127\.0\.0\.1.*",
    r".*github\.com.*",
    r".*githubusercontent\.com.*",
]

# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Shared Utilities for Knowledge Layer."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

INPUT_MAX_CHARS = 4000  # ~1000 tokens input


def summarize_document(
    text: str,
    llm: Any,
    *,
    input_max_chars: int | None = INPUT_MAX_CHARS,
) -> str | None:
    """Generate a one-sentence document summary using the configured LangChain LLM."""
    if llm is None:
        return None
    if input_max_chars and input_max_chars < 1:
        raise ValueError("input_max_chars must be greater than 0")
    text = text.strip()[:input_max_chars].strip() if input_max_chars is not None else text.strip()
    if not text:
        return None
    prompt = (
        "Summarize this uploaded document in one concise sentence for a research assistant. "
        "Focus on the document's topic and likely usefulness.\n\n"
        f"Content Excerpt:\n{text}"
    )
    try:
        response = llm.invoke(prompt)
        summary = getattr(response, "content", None) or str(response)
        summary = summary.strip() if summary else None
        if not summary:
            return None
        logger.debug("Summary generated", stacklevel=2)
        return summary or None
    except Exception:
        logger.warning("Summary via LLM failed", stacklevel=2)
        return None

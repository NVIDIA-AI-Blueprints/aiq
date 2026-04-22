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

"""Cross-encoder reranker using NVIDIA NIM via LangChain.

Unlike the bi-encoder approach (dense.py) which encodes query and documents
separately then computes cosine similarity, a cross-encoder feeds the
query–document pair together into a single model pass and outputs a
relevance score directly.  This is more accurate but slower per document.

Uses ``langchain-nvidia-ai-endpoints`` (``NVIDIARerank``).  Expects
``NVIDIA_API_KEY`` in the environment.
"""

import logging

from langchain_core.documents import Document
from langchain_nvidia_ai_endpoints import NVIDIARerank

logger = logging.getLogger(__name__)


def rerank_cross_encoder(
    query: str,
    results: list[str],
    top_k: int,
    model_name: str,
) -> list[str]:
    """Return the *top_k* results ordered by cross-encoder relevance score.

    Sends query–document pairs to the NVIDIA NIM reranking endpoint and sorts
    by the returned relevance scores.
    """
    if not results:
        return []

    client = NVIDIARerank(model=model_name)

    documents = [Document(page_content=r) for r in results]
    reranked_docs = client.compress_documents(query=query, documents=documents)

    # Map reranked documents back to our SearchResult objects by matching content.
    content_to_idx: dict[str, int] = {}
    for i, r in enumerate(results):
        content_to_idx[r] = i

    ranked_results: list[str] = []
    for doc in reranked_docs:
        idx = content_to_idx.get(doc.page_content)
        if idx is not None:
            ranked_results.append(results[idx])
        if len(ranked_results) >= top_k:
            break

    return ranked_results

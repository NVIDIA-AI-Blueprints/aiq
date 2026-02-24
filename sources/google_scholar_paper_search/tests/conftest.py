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

"""Pytest fixtures for paper search tests."""

import pytest
from google_scholar_paper_search.paper_search import PaperSearchTool


@pytest.fixture
def paper_search_tool():
    """Create a PaperSearchTool instance for testing."""
    return PaperSearchTool(
        serper_api_key="test-api-key",
        timeout=30,
        max_results=10,
    )


@pytest.fixture
def sample_serper_response():
    """Sample Serper API response for testing."""
    return {
        "organic": [
            {
                "title": "Attention Is All You Need",
                "year": "2017",
                "snippet": "The dominant sequence transduction models...",
                "link": "https://arxiv.org/abs/1706.03762",
                "publicationInfo": "Advances in neural information...",
                "citedBy": 50000,
            },
            {
                "title": "BERT: Pre-training of Deep Bidirectional...",
                "year": "2018",
                "snippet": "We introduce a new language model...",
                "link": "https://arxiv.org/abs/1810.04805",
                "publicationInfo": "arXiv preprint",
                "citedBy": 40000,
            },
        ]
    }


@pytest.fixture
def sample_papers():
    """Sample paper data for format testing."""
    return [
        {
            "title": "Test Paper 1",
            "year": "2023",
            "snippet": "This is a test snippet.",
            "link": "https://example.com/paper1",
            "publicationInfo": "Test Journal",
            "citedBy": 100,
        },
        {
            "title": "Test Paper 2",
            "year": "2024",
            "snippet": "Another test snippet.",
            "link": "https://example.com/paper2",
            "publicationInfo": "Another Journal",
            "citedBy": 50,
        },
    ]

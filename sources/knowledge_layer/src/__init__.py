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

"""
Knowledge Layer - Pluggable document ingestion and retrieval.

This package provides NAT tool registrations for knowledge retrieval that can be used
across multiple applications.

Available Backends:
- llamaindex: LlamaIndex + ChromaDB (lightweight, local)
- foundational_rag: Hosted NVIDIA RAG Blueprint (production, multi-user)

Note: NAT tool registrations require NAT to be installed.
The adapter modules can be used standalone without NAT.
"""

# Eagerly import NAT functions to trigger @register_function decorators
try:
    from .register import KnowledgeRetrievalConfig
    from .register import knowledge_retrieval

    __all__ = ["KnowledgeRetrievalConfig", "knowledge_retrieval"]
except ImportError:
    # NAT not installed - skip function registration
    __all__ = []

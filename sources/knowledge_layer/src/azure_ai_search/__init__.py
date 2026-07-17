# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Azure AI Search Knowledge Layer backend."""

from .adapter import AzureAISearchIngestor
from .adapter import AzureAISearchRetriever

__all__ = ["AzureAISearchIngestor", "AzureAISearchRetriever"]

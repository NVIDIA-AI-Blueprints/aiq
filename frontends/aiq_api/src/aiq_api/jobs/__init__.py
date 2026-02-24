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
Async job infrastructure for AI-Q agents.

This module provides agent-agnostic job execution infrastructure:
- EventStore: SQLAlchemy-based event persistence for SSE streaming
- AgentEventCallback: LangChain callback handler for event emission
- run_agent_job: Dask task function for running any registered agent
- submit_agent_job: Submit jobs from application code
"""

from .callbacks import AgentEventCallback
from .callbacks import ArtifactType
from .callbacks import EventCategory
from .callbacks import EventData
from .callbacks import EventState
from .callbacks import IntermediateStepEvent
from .callbacks import ToolArtifactMapping
from .connection_manager import SSEConnectionManager
from .connection_manager import get_connection_manager
from .connection_manager import reset_connection_manager
from .event_store import EventStore
from .runner import CancellationMonitor
from .runner import run_agent_job
from .runner import run_with_cancellation
from .submit import submit_agent_job

__all__ = [
    "AgentEventCallback",
    "ArtifactType",
    "CancellationMonitor",
    "EventCategory",
    "EventData",
    "EventState",
    "EventStore",
    "IntermediateStepEvent",
    "SSEConnectionManager",
    "ToolArtifactMapping",
    "get_connection_manager",
    "reset_connection_manager",
    "run_agent_job",
    "run_with_cancellation",
    "submit_agent_job",
]

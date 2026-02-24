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

"""CLI-specific authentication utilities.

Shared utilities (get_current_user_info) are in aiq_agent.auth.
"""

from aiq_agent.auth import UserInfo
from aiq_agent.auth import decode_jwt_payload
from aiq_agent.auth import get_auth_token
from aiq_agent.auth import get_current_user_info
from aiq_agent.auth import get_user_info_from_token

from .local_token_store import LocalTokenStore
from .local_token_store import get_local_token_store

__all__ = [
    "LocalTokenStore",
    "UserInfo",
    "decode_jwt_payload",
    "get_auth_token",
    "get_current_user_info",
    "get_local_token_store",
    "get_user_info_from_token",
]

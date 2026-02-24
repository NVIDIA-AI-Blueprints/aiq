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

"""Shared authentication utilities for token retrieval and user info.

These utilities can be used by any tool or agent to get auth tokens or user info.
Token source: AIQContext cookies (idToken) - set by the frontend auth layer.
"""

import base64
import json
import logging

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class UserInfo(BaseModel):
    email: str | None = None
    name: str | None = None


def decode_jwt_payload(token: str) -> dict:
    """Decode the payload section of a JWT token without verification."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid JWT token format")

        payload = parts[1]
        padding = len(payload) % 4
        if padding:
            payload += "=" * (4 - padding)

        decoded_bytes = base64.urlsafe_b64decode(payload)
        return json.loads(decoded_bytes)
    except Exception as e:
        logger.error("Failed to decode JWT token: %s", e)
        return {}


def get_user_info_from_token(id_token: str) -> UserInfo:
    """Extract user information from a JWT ID token."""
    payload = decode_jwt_payload(id_token)

    email = payload.get("email")
    name = (
        payload.get("name") or payload.get("given_name") or payload.get("preferred_username") or payload.get("nickname")
    )

    return UserInfo(email=email, name=name)


def get_auth_token() -> str | None:
    """
    Get authentication token from the request context.

    Reads the idToken cookie set by the frontend auth layer.

    Returns:
        ID token string or None if not available.
    """
    from nat.builder.context import AIQContext

    try:
        context_metadata = AIQContext.get().metadata

        if context_metadata and context_metadata.cookies:
            id_token = context_metadata.cookies.get("idToken")
            if id_token:
                token = id_token.strip()
                logger.debug("Using token from AIQContext cookies")
                return token
    except Exception as e:
        logger.debug("Failed to retrieve token from AIQContext: %s", e)

    return None


async def get_current_user_info() -> UserInfo | None:
    """
    Get current user information from the frontend auth token.

    Reads the idToken cookie from AIQContext (set by the frontend).

    Returns:
        UserInfo object or None if no token available.
    """
    token = get_auth_token()

    if token:
        try:
            user_info = get_user_info_from_token(token)
            logger.debug("User info extracted successfully")
            return user_info
        except Exception as e:
            logger.error("Could not extract user info from token: %s", e)
            return None

    logger.debug("No token available for user info extraction")
    return None

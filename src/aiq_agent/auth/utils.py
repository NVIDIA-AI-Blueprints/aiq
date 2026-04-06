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
Token source: Context cookies (idToken) - set by the frontend auth layer.
"""

import base64
import json
import logging
import threading
from collections.abc import Callable

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_token_fetchers: list[tuple[int, Callable[[], str | None]]] = []
_fetcher_lock = threading.Lock()


def register_token_fetcher(fetcher: Callable[[], str | None], priority: int = 0) -> None:
    """Register an additional token source.

    Registered fetchers are tried in priority order (highest first) before
    the default Context cookie lookup. The first fetcher that returns a
    non-None token wins.

    Duplicate fetchers (same callable identity) are silently ignored.

    Args:
        fetcher: Callable that returns a token string or None.
        priority: Higher priority fetchers are tried first. Default: 0.
    """
    with _fetcher_lock:
        if any(f is fetcher for _, f in _token_fetchers):
            logger.debug("Token fetcher already registered, skipping duplicate")
            return
        _token_fetchers.append((priority, fetcher))
        _token_fetchers.sort(key=lambda x: x[0], reverse=True)
    logger.debug("Registered token fetcher (priority=%d), total fetchers: %d", priority, len(_token_fetchers))


def unregister_token_fetcher(fetcher: Callable[[], str | None]) -> None:
    """Remove a previously registered token fetcher.

    Matches by callable identity (``is`` check). No-op if the fetcher
    is not currently registered.

    Args:
        fetcher: The same callable object that was passed to
            :func:`register_token_fetcher`.
    """
    with _fetcher_lock:
        before = len(_token_fetchers)
        _token_fetchers[:] = [(p, f) for p, f in _token_fetchers if f is not fetcher]
        removed = before - len(_token_fetchers)
    if removed:
        logger.debug("Unregistered token fetcher, total fetchers: %d", len(_token_fetchers))


def clear_token_fetchers() -> None:
    """Remove all registered token fetchers.

    Warning: This is intended for test isolation only. Calling in production
    will silently remove all registered auth sources.
    """
    with _fetcher_lock:
        _token_fetchers.clear()


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

    Tries registered token fetchers in priority order (highest first),
    then falls back to the idToken cookie set by the frontend auth layer.

    Returns:
        ID token string or None if not available.
    """
    # Try registered fetchers first (highest priority first).
    # Iterate a snapshot so concurrent register_token_fetcher() calls
    # don't mutate the list mid-iteration.
    for _priority, fetcher in list(_token_fetchers):
        try:
            token = fetcher()
            if token:
                logger.debug("Token provided by registered fetcher")
                return token
        except Exception as e:
            logger.debug("Registered token fetcher failed: %s", e)

    # Default: Context cookies
    from nat.builder.context import Context

    try:
        context_metadata = Context.get().metadata

        if context_metadata and context_metadata.cookies:
            id_token = context_metadata.cookies.get("idToken")
            if id_token:
                token = id_token.strip()
                logger.debug("Using token from Context cookies")
                return token
    except Exception as e:
        logger.debug("Failed to retrieve token from Context: %s", e)

    return None


def get_current_user_info() -> UserInfo | None:
    """
    Get current user information from the frontend auth token.

    Reads the idToken cookie from Context (set by the frontend).

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

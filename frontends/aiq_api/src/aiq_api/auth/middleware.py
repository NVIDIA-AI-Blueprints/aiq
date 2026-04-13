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

"""Raw ASGI authentication middleware.

Three independent checks:
--------------------------------------------------
1. **Path allowlist** — blocks unexposed paths on external requests.
   *Always* enforced, regardless of ``REQUIRE_AUTH``.
2. **Token validation** — rejects missing / invalid JWT credentials.
   Controlled by the ``require_auth`` constructor arg (``REQUIRE_AUTH`` env var).
3. **Caller type detection** — sets ``user.type`` for downstream logic
   (e.g. skip the clarifier for headless callers).
   *Always* applied, even when auth is disabled.

CONTEXTVAR PROPAGATION
-----------------------
The middleware stores the resolved user dict in a ``ContextVar`` so that
NAT workflow functions (which do not receive the ASGI ``Request`` object)
can read the caller type without framework coupling.

    from aiq_api.auth.middleware import get_current_user
    user = get_current_user()          # {"type": "internal"|"anonymous", ...}
    skip = user.get("skip_clarifier")  # True / False

ENVIRONMENT VARIABLES
----------------------
``AIQ_EXTERNAL_HOSTNAMES``
    Comma-separated list of external-facing hostnames.  Requests that arrive
    with a ``Host`` header matching one of these are treated as external (auth
    + path filter applied).

``REQUIRE_AUTH``
    ``"true"`` / ``"false"`` (case-insensitive).  When ``false``, token
    validation is skipped but the path filter and caller-type detection still
    run.  Defaults to ``"false"`` (safe default; configure ``"true"`` in
    production).

``AIQ_JWT_ISSUER``
    OIDC issuer URL used for JWT signature verification
    (e.g. ``https://accounts.google.com``).  Required when ``REQUIRE_AUTH=true``.

``AIQ_JWT_AUDIENCE``
    Optional ``aud`` claim to verify.  Leave unset to skip audience
    verification.
"""

import json
import logging
import os
from contextvars import ContextVar
from typing import Any

from starlette.types import ASGIApp
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ContextVar — carries the resolved caller identity through the call stack
# ---------------------------------------------------------------------------
_current_user: ContextVar[dict[str, Any]] = ContextVar(
    "_current_user",
    default={"type": "internal", "skip_clarifier": False},
)


def get_current_user() -> dict[str, Any]:
    """Return the caller identity dict set by ``AuthMiddleware`` for this request.

    Returns the default ``{"type": "internal", "skip_clarifier": False}`` when
    the middleware is not registered or when called outside a request context.
    """
    return _current_user.get()


# ---------------------------------------------------------------------------
# Path configuration
# ---------------------------------------------------------------------------

# Paths reachable from outside the cluster.  Any external request whose path
# does NOT match one of these receives 404.  Prefix entries must end with "/".
EXTERNAL_ALLOWED_PATHS: list[str] = [
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/chat",
    "/chat/stream",
    "/v1/chat/completions",
    "/v1/data_sources",
    "/v1/jobs/async/agents",
    "/v1/jobs/async/submit",
    "/v1/jobs/async/job/",  # prefix — matches /v1/jobs/async/job/{id}/*
]

# External paths that require no token (monitoring, etc.)
AUTH_EXEMPT_PATHS: set[str] = {"/health", "/docs", "/redoc", "/openapi.json"}


def _load_external_hostnames() -> set[str]:
    """Read ``AIQ_EXTERNAL_HOSTNAMES`` env var; fall back to staging hostname."""
    env = os.getenv("AIQ_EXTERNAL_HOSTNAMES", "")
    names = {h.strip() for h in env.split(",") if h.strip()}
    return names


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class AuthMiddleware:
    """
    Raw ASGI middleware that enforces path filtering and token validation
    without buffering response bodies.

    Provider-agnostic: accepts any list of ``TokenValidator`` instances.
    Each validator implements ``can_handle()`` + ``validate()``.  The first
    validator that returns a non-None result wins.

    Register via FastAPI's ``add_middleware``

    Args:
        app: The inner ASGI application.
        validators: Ordered list of token validators to try.
        require_auth: When ``True``, external requests must carry a valid token.
        external_hostnames: Hostnames considered "external".
            Defaults to ``AIQ_EXTERNAL_HOSTNAMES`` env var.
    """

    def __init__(
        self,
        app: ASGIApp,
        validators: list | None = None,
        require_auth: bool = False,
        external_hostnames: set[str] | None = None,
    ) -> None:
        self.app = app
        self.require_auth = require_auth
        self._validators: list = validators or []
        self._external_hostnames: set[str] = external_hostnames or _load_external_hostnames()

        if require_auth and not self._validators:
            logger.warning(
                "REQUIRE_AUTH=true but no validators are configured — all authenticated requests will be rejected."
            )

        logger.info(
            "AuthMiddleware: require_auth=%s, validators=%s, external_hostnames=%s",
            require_auth,
            [type(v).__name__ for v in self._validators],
            self._external_hostnames,
        )

    # ------------------------------------------------------------------
    # ASGI entry point
    # ------------------------------------------------------------------

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        path: str = scope["path"]

        # 1. Internal traffic
        if not self._is_external(headers):
            user = self._detect_internal_caller(headers)
            await self._call_app(scope, receive, send, user)
            return

        # 2. External — enforce path allowlist
        if not self._path_allowed(path):
            await self._send_json(send, 404, {"detail": "Not found"})
            return

        # 3. Auth-exempt paths
        if path in AUTH_EXEMPT_PATHS:
            user = {"type": "anonymous", "skip_clarifier": True}
            await self._call_app(scope, receive, send, user)
            return

        # 4. Auth disabled — allow as anonymous
        if not self.require_auth:
            user = {"type": "anonymous", "skip_clarifier": True}
            await self._call_app(scope, receive, send, user)
            return

        # 5. Auth enabled — require a valid JWT Bearer token
        token = self._extract_token(headers)
        if not token:
            await self._send_json(send, 401, {"detail": "Missing auth token"})
            return

        user = await self._validate_token(token)
        if user is None:
            await self._send_json(send, 401, {"detail": "Invalid or expired auth token"})
            return

        if self._is_headless(headers):
            user["skip_clarifier"] = True

        await self._call_app(scope, receive, send, user)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call_app(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        user: dict[str, Any],
    ) -> None:
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["user"] = user

        token = _current_user.set(user)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_user.reset(token)

    def _is_external(self, headers: dict[bytes, bytes]) -> bool:
        host = headers.get(b"host", b"").decode().split(":")[0]
        return host in self._external_hostnames

    def _path_allowed(self, path: str) -> bool:
        for allowed in EXTERNAL_ALLOWED_PATHS:
            if allowed.endswith("/"):
                if path.startswith(allowed) or path == allowed.rstrip("/"):
                    return True
            elif path == allowed:
                return True
        return False

    def _extract_token(self, headers: dict[bytes, bytes]) -> str | None:
        auth = headers.get(b"authorization", b"").decode()
        if auth.startswith("Bearer "):
            return auth[7:]
        # Fall back to idToken cookie (UI / browser callers)
        cookie = headers.get(b"cookie", b"").decode()
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("idToken="):
                return part[8:]
        return None

    def _is_headless(self, headers: dict[bytes, bytes]) -> bool:
        return headers.get(b"x-aiq-mode", b"").decode().lower() == "headless"

    async def _validate_token(self, token: str) -> dict[str, Any] | None:
        for validator in self._validators:
            if validator.can_handle(token):
                user = await validator.validate(token)
                if user is not None:
                    return user
        logger.debug("Token rejected by all %d configured validator(s)", len(self._validators))
        return None

    def _detect_internal_caller(self, headers: dict[bytes, bytes]) -> dict[str, Any]:
        """Classify an internal request without validating the token."""
        auth = headers.get(b"authorization", b"").decode()
        if auth.startswith("Bearer eyJ"):
            token = auth[7:]
            headless = self._is_headless(headers)
            return {"type": "jwt", "token": token, "skip_clarifier": headless}

        cookie = headers.get(b"cookie", b"").decode()
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("idToken="):
                token = part[8:]
                headless = self._is_headless(headers)
                return {"type": "jwt", "token": token, "skip_clarifier": headless}

        headless = self._is_headless(headers)
        return {"type": "internal", "skip_clarifier": headless}

    @staticmethod
    async def _send_json(send: Send, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"content-length", str(len(payload)).encode()],
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})

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
    user = get_current_user()          # {"type": "jwt"|"internal"|"anonymous"|...}
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
from contextlib import contextmanager
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


@contextmanager
def user_context(user: dict[str, Any]):
    """Temporarily bind a resolved caller identity in the auth ContextVar."""
    token = _current_user.set(user)
    try:
        yield
    finally:
        _current_user.reset(token)


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


def is_external_request(headers: dict[bytes, bytes], external_hostnames: set[str] | None = None) -> bool:
    """Return ``True`` when the Host header matches an external-facing hostname."""
    host = headers.get(b"host", b"").decode().split(":")[0]
    return host in (external_hostnames or _load_external_hostnames())


def is_headless_request(headers: dict[bytes, bytes]) -> bool:
    """Return ``True`` for headless callers that should skip the clarifier."""
    return headers.get(b"x-aiq-mode", b"").decode().lower() == "headless"


def extract_auth_token(headers: dict[bytes, bytes]) -> str | None:
    """Extract a bearer token or idToken cookie from ASGI headers."""
    auth = headers.get(b"authorization", b"").decode()
    if auth.startswith("Bearer "):
        return auth[7:]

    cookie = headers.get(b"cookie", b"").decode()
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith("idToken="):
            return part[8:]
    return None


async def validate_token_with_validators(token: str, validators: list) -> dict[str, Any] | None:
    """Try validators in order and return the first successful identity dict."""
    for validator in validators:
        if validator.can_handle(token):
            user = await validator.validate(token)
            if user is not None:
                return user
    logger.debug("Token rejected by all %d configured validator(s)", len(validators))
    return None


def detect_internal_caller(headers: dict[bytes, bytes]) -> dict[str, Any]:
    """Classify an internal request without validating any presented token."""
    token = extract_auth_token(headers)
    headless = is_headless_request(headers)
    if token:
        return {"type": "unverified_jwt", "token": token, "skip_clarifier": headless}
    return {"type": "internal", "skip_clarifier": headless}


async def resolve_request_user(
    headers: dict[bytes, bytes],
    *,
    validators: list,
    require_auth: bool,
    external_hostnames: set[str] | None = None,
) -> tuple[dict[str, Any] | None, int | None, bool]:
    """Resolve request identity from validated credentials when present.

    Returns a tuple of:
      - resolved user dict, or None when the request should be rejected
      - HTTP status code to use on rejection, or None on success
      - whether the request was classified as external
    """
    is_external = is_external_request(headers, external_hostnames)
    token = extract_auth_token(headers)

    if token:
        user = await validate_token_with_validators(token, validators)
        if user is not None:
            if is_headless_request(headers):
                user["skip_clarifier"] = True
            return user, None, is_external

        if is_external and require_auth:
            return None, 401, is_external

    if is_external:
        if not require_auth:
            return {"type": "anonymous", "skip_clarifier": True}, None, is_external
        return None, 401, is_external

    return detect_internal_caller(headers), None, is_external


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
        is_external = self._is_external(headers)

        # External requests still honor the public path allowlist before auth.
        if is_external and not self._path_allowed(path):
            await self._send_json(send, 404, {"detail": "Not found"})
            return

        if is_external and path in AUTH_EXEMPT_PATHS:
            user = {"type": "anonymous", "skip_clarifier": True}
            await self._call_app(scope, receive, send, user)
            return

        user, error_status, _ = await resolve_request_user(
            headers,
            validators=self._validators,
            require_auth=self.require_auth,
            external_hostnames=self._external_hostnames,
        )
        if user is None:
            detail = "Invalid or expired auth token" if self._extract_token(headers) else "Missing auth token"
            await self._send_json(send, error_status or 401, {"detail": detail})
            return

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

        with user_context(user):
            await self.app(scope, receive, send)

    def _is_external(self, headers: dict[bytes, bytes]) -> bool:
        return is_external_request(headers, self._external_hostnames)

    def _path_allowed(self, path: str) -> bool:
        for allowed in EXTERNAL_ALLOWED_PATHS:
            if allowed.endswith("/"):
                if path.startswith(allowed) or path == allowed.rstrip("/"):
                    return True
            elif path == allowed:
                return True
        return False

    def _extract_token(self, headers: dict[bytes, bytes]) -> str | None:
        return extract_auth_token(headers)

    def _is_headless(self, headers: dict[bytes, bytes]) -> bool:
        return is_headless_request(headers)

    async def _validate_token(self, token: str) -> dict[str, Any] | None:
        return await validate_token_with_validators(token, self._validators)

    def _detect_internal_caller(self, headers: dict[bytes, bytes]) -> dict[str, Any]:
        """Classify an internal request without validating the token."""
        return detect_internal_caller(headers)

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

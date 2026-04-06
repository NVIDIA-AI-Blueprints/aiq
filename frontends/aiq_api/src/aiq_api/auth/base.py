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

"""Abstract base for token validators.

Each identity provider implements TokenValidator and is registered
in plugin.py via AuthMiddleware(validators=[...]).  The middleware
itself has no knowledge of any specific provider.

User dict contract
------------------
A successful ``validate()`` call must return a dict with at least::

    {
        "type":            str,        # provider label
        "sub":             str | None, # subject identifier (username / user-id)
        "email":           str | None, # best-effort email, None if unavailable
        "name":            str | None, # display name, None if unavailable
        "token":           str,        # original raw token (forwarded to ECI etc.)
        "skip_clarifier":  bool,       # True for headless/service callers
    }
"""

from abc import ABC
from abc import abstractmethod
from typing import Any


class TokenValidator(ABC):
    """Abstract token validator.  One implementation per identity provider."""

    @abstractmethod
    async def validate(self, token: str) -> dict[str, Any] | None:
        """Validate *token* and return a user dict, or ``None`` if invalid."""
        ...

    @abstractmethod
    def can_handle(self, token: str) -> bool:
        """Return ``True`` if this validator should attempt to validate *token*.

        Used as a fast pre-filter before the (potentially async) ``validate``
        call.  Implementations should check only token format / prefix — no
        network calls here.
        """
        ...

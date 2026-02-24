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

"""Local file-based token storage for CLI mode development."""

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalTokenStore:
    """
    Local file-based token storage for CLI mode development.
    Stores SSA tokens in user's home directory with restrictive file permissions.

    To clear cached tokens: rm -rf ~/.aiq/tokens/
    To disable caching: export AIQ_USE_LOCAL_TOKEN_STORAGE=false
    """

    def __init__(self, cache_dir: Path | None = None):
        if cache_dir:
            self.cache_dir = cache_dir
        else:
            self.cache_dir = Path.home() / ".aiq" / "tokens"

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.cache_dir, 0o700)

        self.ssa_token_file = self.cache_dir / "ssa_token.json"

        logger.debug(f"Initialized local token store at {self.cache_dir}")

    def _write_token_file(self, filepath: Path, data: dict) -> None:
        """Write token data to file with secure permissions."""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        os.chmod(filepath, 0o600)
        logger.debug(f"Stored tokens in {filepath}")

    def _read_token_file(self, filepath: Path) -> dict | None:
        """Read token data from file if it exists and is valid."""
        if not filepath.exists():
            return None

        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception as e:
            logger.warning(f"Failed to read token file {filepath}: {e}")
            return None

    def store_ssa_token(self, token: str, expires_in: int, client_id: str = None) -> None:
        """Store SSA token locally for e2e/server mode."""
        expires_at = time.time() + expires_in

        data = {"token": token, "expires_at": expires_at, "client_id": client_id, "updated_at": time.time()}

        self._write_token_file(self.ssa_token_file, data)
        logger.info("Stored SSA token locally")

    def get_ssa_token(self) -> str | None:
        """Retrieve SSA token if valid."""
        data = self._read_token_file(self.ssa_token_file)
        if not data:
            return None

        expires_at = data.get("expires_at", 0)
        if time.time() >= expires_at:
            logger.debug("SSA token expired")
            return None

        return data.get("token")

    def clear_all(self) -> None:
        """Clear all stored tokens."""
        if self.ssa_token_file.exists():
            self.ssa_token_file.unlink()
            logger.info("Cleared SSA token")

    def get_token_info(self) -> dict:
        """Get info about stored tokens (for debugging)."""
        info = {"cache_dir": str(self.cache_dir), "ssa_token": None}

        ssa_data = self._read_token_file(self.ssa_token_file)
        if ssa_data:
            expires_at = ssa_data.get("expires_at", 0)
            info["ssa_token"] = {
                "valid": time.time() < expires_at,
                "expires_in_seconds": max(0, int(expires_at - time.time())),
                "client_id": ssa_data.get("client_id"),
            }

        return info


_local_token_store: LocalTokenStore | None = None


def get_local_token_store() -> LocalTokenStore:
    """Get singleton instance of local token store."""
    global _local_token_store
    if _local_token_store is None:
        _local_token_store = LocalTokenStore()
    return _local_token_store

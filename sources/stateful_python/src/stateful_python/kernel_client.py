# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bounded Unix-socket client for the sandbox-local Python kernel."""

from __future__ import annotations

import socket
import sys
from pathlib import Path


def main() -> None:
    socket_path = sys.argv[1]
    request = Path(sys.argv[2]).read_bytes()
    max_response_bytes = int(sys.argv[3])
    if b"\n" in request:
        raise ValueError("kernel request must be one JSON line")

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(socket_path)
        client.sendall(request + b"\n")
        client.shutdown(socket.SHUT_WR)
        response = bytearray()
        while len(response) <= max_response_bytes:
            chunk = client.recv(min(65_536, max_response_bytes + 1 - len(response)))
            if not chunk:
                break
            response.extend(chunk)
            if b"\n" in chunk:
                break
    if len(response) > max_response_bytes:
        raise ValueError("kernel response exceeded its transport limit")
    sys.stdout.buffer.write(bytes(response))


if __name__ == "__main__":
    main()

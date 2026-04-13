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

"""Auth-related exception types."""


class AuthError(Exception):
    """Raised when a request fails due to authentication or authorization issues.

    Agent nodes catch this before the generic Exception handler and return
    str(e) directly to the user. Subclass this for specific auth failure modes
    (e.g. missing token, expired token, insufficient permissions) to ensure
    actionable error messages reach the caller rather than a generic fallback.
    """

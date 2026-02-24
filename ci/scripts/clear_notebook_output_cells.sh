#!/bin/bash

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

# Pre-commit fails when a hook modifies files. We clear outputs then stage the
# modified notebooks so the commit includes the cleared version and the hook passes.
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

clear_one() {
    local f="$1"
    [ -n "$f" ] || return 0
    jupyter nbconvert --clear-output --inplace "$f"
    git add "$f"
}

if [ $# -gt 0 ]; then
    for NOTEBOOK_FILE in "$@"; do
        clear_one "$NOTEBOOK_FILE"
    done
else
    git ls-files "*.ipynb" | while IFS= read -r NOTEBOOK_FILE; do
        clear_one "$NOTEBOOK_FILE"
    done
fi

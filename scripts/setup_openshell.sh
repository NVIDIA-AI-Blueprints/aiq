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
#
# Set up NVIDIA OpenShell for AI-Q with a named, policy-backed sandbox.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$REPO_ROOT/.venv"

# Floor aligned with the published langchain-nvidia-openshell 0.1.0 adapter, which is
# tested against OpenShell 0.0.72+. Anything below this is upgraded by the adapter during
# its install, so do not pin under it.
MIN_OPENSHELL_VERSION="0.0.72"
DEFAULT_OPENSHELL_VERSION="0.0.72"
OPENSHELL_VERSION="${AIQ_OPENSHELL_VERSION:-}"
OPENSHELL_VERSION_USER_SUPPLIED=false
if [[ -n "$OPENSHELL_VERSION" ]]; then
    OPENSHELL_VERSION_USER_SUPPLIED=true
fi
OPENSHELL_LATEST_VERSION=""
OPENSHELL_AVAILABLE_VERSIONS=""
PYTHON_BIN=""
# Official OpenShell deepagents adapter: the `langchain-nvidia-openshell` partner
# package, now published on PyPI. Override with LANGCHAIN_NVIDIA_REPO to use a git
# spec or a local checkout (e.g. to test an unreleased adapter build).
DEFAULT_LANGCHAIN_NVIDIA_INSTALL_SPEC="langchain-nvidia-openshell==0.1.0"
LANGCHAIN_NVIDIA_REPO="${LANGCHAIN_NVIDIA_REPO:-$DEFAULT_LANGCHAIN_NVIDIA_INSTALL_SPEC}"
SANDBOX_NAME="${AIQ_OPENSHELL_SANDBOX_NAME:-aiq-openshell-demo}"
IMAGE_NAME="${AIQ_OPENSHELL_IMAGE:-aiq-openshell-demo:latest}"
# Sandbox log verbosity baked into the image (RUST_LOG). Default `warn` is OpenShell's
# stock sandbox level; set to `debug` to surface in-container process/relay detail.
SANDBOX_LOG_LEVEL="${AIQ_OPENSHELL_SANDBOX_LOG_LEVEL:-warn}"
POLICY_PRESET="${AIQ_OPENSHELL_POLICY:-}"
POLICY_ALLOWLIST="${AIQ_OPENSHELL_POLICY_ALLOWLIST:-${AIQ_OPENSHELL_POLICY_SERVICES:-}}"
POLICY_FILE="${AIQ_OPENSHELL_POLICY_FILE:-$REPO_ROOT/configs/openshell/generated/aiq-openshell-policy.yaml}"
GATEWAY_NAME="${AIQ_OPENSHELL_GATEWAY_NAME:-aiq-local}"
GATEWAY_PORT="${AIQ_OPENSHELL_GATEWAY_PORT:-8080}"
DOCKER_BIN="${DOCKER_BIN:-}"
OPENSHELL_BIN="${OPENSHELL_BIN:-}"
OPENSHELL_GATEWAY_LAUNCH_BIN="${OPENSHELL_GATEWAY_LAUNCH_BIN:-}"
GATEWAY_ENDPOINT=""
GATEWAY_DISABLE_TLS=false
RESTART_GATEWAY=true
BUILD_IMAGE=true
CREATE_SANDBOX=true
LIST_OPENSHELL_VERSIONS=false

SUPPORTED_SERVICES="github,pypi,nvidia,tavily,serper,huggingface,arxiv,semantic-scholar,npm"
SUPPORTED_POLICIES="offline,research,python-packages,ai-dev,custom"

usage() {
    cat <<EOF
Usage: scripts/setup_openshell.sh [options]

Sets up OpenShell for AI-Q:
  1. Detects macOS/Linux.
  2. Checks available OpenShell releases and selects an exact version.
  3. Installs the selected OpenShell Python package version.
  4. Installs the langchain-nvidia-openshell deepagents adapter.
  5. Resolves Docker and OpenShell gateway paths.
  6. Generates an initial OpenShell policy.
  7. Starts/verifies the OpenShell gateway.
  8. Builds the AI-Q sandbox image.
  9. Creates a named policy-backed sandbox.

Options:
  --openshell-version VERSION   Exact OpenShell version, or "latest".
                                Default: asks in an interactive shell; Enter selects 0.0.72.
                                Non-interactive default: 0.0.72.
  --policy CHOICE               Sandbox network policy.
                                Choices: $SUPPORTED_POLICIES
                                Default: asks in an interactive shell, offline otherwise.
  --allow LIST                  Comma-separated services for --policy custom.
                                Services: $SUPPORTED_SERVICES
  --policy-file PATH            Output policy file.
                                Default: configs/openshell/generated/aiq-openshell-policy.yaml
  --sandbox-name NAME           OpenShell sandbox name (default: aiq-openshell-demo).
  --image-name NAME             Docker image tag (default: aiq-openshell-demo:latest).
  --sandbox-log-level LEVEL     In-container OpenShell log verbosity baked into the
                                image via RUST_LOG (default: warn). Use "debug" to
                                surface process/relay detail in the sandbox logs.
  --langchain-nvidia SPEC       uv install spec or local langchain-nvidia checkout
                                for the langchain-nvidia-openshell adapter.
  --gateway-name NAME           OpenShell gateway name (default: aiq-local).
  --gateway-port PORT           Local gateway port (default: 8080).
  --docker-bin PATH             Docker CLI path when docker is not on PATH.
  --gateway-bin PATH            OpenShell gateway launcher path.
  --no-restart-gateway          Reuse the active gateway instead of starting one.
  --skip-build                  Do not build the sandbox image.
  --skip-sandbox                Do not create the named sandbox.
  --list-policies               Print supported policy choices.
  --list-services               Print supported services for --allow.
  --list-openshell-versions     Print released OpenShell versions >= 0.0.72.
  -h, --help                    Show this help.

Examples:
  scripts/setup_openshell.sh
  scripts/setup_openshell.sh --policy python-packages
  scripts/setup_openshell.sh --policy custom --allow github,pypi,nvidia,tavily
  scripts/setup_openshell.sh --openshell-version latest --policy offline
EOF
}

log() {
    echo ""
    echo "==> $*"
}

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --openshell-version)
            OPENSHELL_VERSION="$2"
            OPENSHELL_VERSION_USER_SUPPLIED=true
            shift 2
            ;;
        --policy)
            POLICY_PRESET="$2"
            shift 2
            ;;
        --allow)
            POLICY_ALLOWLIST="$2"
            shift 2
            ;;
        --policy-services)
            POLICY_ALLOWLIST="$2"
            shift 2
            ;;
        --policy-file)
            POLICY_FILE="$2"
            shift 2
            ;;
        --sandbox-name)
            SANDBOX_NAME="$2"
            shift 2
            ;;
        --image-name)
            IMAGE_NAME="$2"
            shift 2
            ;;
        --sandbox-log-level)
            SANDBOX_LOG_LEVEL="$2"
            shift 2
            ;;
        --langchain-nvidia)
            LANGCHAIN_NVIDIA_REPO="$2"
            shift 2
            ;;
        --gateway-name)
            GATEWAY_NAME="$2"
            shift 2
            ;;
        --gateway-port)
            GATEWAY_PORT="$2"
            shift 2
            ;;
        --docker-bin)
            DOCKER_BIN="$2"
            shift 2
            ;;
        --gateway-bin)
            OPENSHELL_GATEWAY_LAUNCH_BIN="$2"
            shift 2
            ;;
        --no-restart-gateway)
            RESTART_GATEWAY=false
            shift
            ;;
        --skip-build)
            BUILD_IMAGE=false
            shift
            ;;
        --skip-sandbox)
            CREATE_SANDBOX=false
            shift
            ;;
        --list-policies)
            echo "$SUPPORTED_POLICIES" | tr ',' '\n'
            exit 0
            ;;
        --list-services)
            echo "$SUPPORTED_SERVICES" | tr ',' '\n'
            exit 0
            ;;
        --list-openshell-versions)
            LIST_OPENSHELL_VERSIONS=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage
            fail "Unknown option: $1"
            ;;
    esac
done

detect_os() {
    case "$(uname -s)" in
        Darwin)
            OS_NAME=macos
            ;;
        Linux)
            OS_NAME=linux
            ;;
        *)
            fail "Unsupported operating system: $(uname -s). This script supports macOS and Linux."
            ;;
    esac
    echo "Detected OS: $OS_NAME"
}

require_uv() {
    if ! command -v uv >/dev/null 2>&1; then
        cat <<'EOF'
uv was not found on PATH.

Install uv, then rerun:

  curl -LsSf https://astral.sh/uv/install.sh | sh

If uv is already installed, open a new shell or add it to PATH before rerunning.
EOF
        exit 1
    fi
}

resolve_python() {
    if [[ -n "$PYTHON_BIN" && -x "$PYTHON_BIN" ]]; then
        return
    fi
    PYTHON_BIN="$(uv python find 2>/dev/null || true)"
    if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
        PYTHON_BIN="$(command -v python3 || command -v python || true)"
    fi
    if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
        fail "Python was not found. Install Python 3.11+ or run ./scripts/setup.sh first."
    fi
}

fetch_openshell_versions() {
    resolve_python
    log "Checking available OpenShell versions"
    local output
    if ! output="$("$PYTHON_BIN" - "$MIN_OPENSHELL_VERSION" <<'PY'
import json
import re
import sys
import urllib.request

min_version = sys.argv[1]
version_re = re.compile(r"^\d+\.\d+\.\d+$")

def parse(version: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in version.split("."))

try:
    with urllib.request.urlopen("https://pypi.org/pypi/openshell/json", timeout=15) as response:
        payload = json.load(response)
except Exception as exc:
    raise SystemExit(f"failed to fetch OpenShell versions from PyPI: {exc}")

minimum = parse(min_version)
versions = []
for version, files in payload.get("releases", {}).items():
    if not version_re.match(version):
        continue
    if not files:
        continue
    parsed = parse(version)
    if parsed >= minimum:
        versions.append((parsed, version))

if not versions:
    raise SystemExit(f"no OpenShell releases found at or above {min_version}")

versions.sort()
print(versions[-1][1])
print(",".join(version for _, version in versions))
PY
)"; then
        fail "$output"
    fi

    OPENSHELL_LATEST_VERSION="$(printf '%s\n' "$output" | sed -n '1p')"
    OPENSHELL_AVAILABLE_VERSIONS="$(printf '%s\n' "$output" | sed -n '2p')"

    if [[ -z "$OPENSHELL_LATEST_VERSION" || -z "$OPENSHELL_AVAILABLE_VERSIONS" ]]; then
        fail "Could not determine available OpenShell versions from PyPI."
    fi
    echo "OpenShell version range: $MIN_OPENSHELL_VERSION through $OPENSHELL_LATEST_VERSION"
}

version_is_available() {
    case ",$OPENSHELL_AVAILABLE_VERSIONS," in
        *",$1,"*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

version_prompt_text() {
    echo "OpenShell version [press Enter for ${DEFAULT_OPENSHELL_VERSION}; type latest for ${OPENSHELL_LATEST_VERSION}]: "
}

choose_openshell_version_interactively() {
    local candidate
    while true; do
        read -r -p "$(version_prompt_text)" candidate
        candidate="${candidate:-$DEFAULT_OPENSHELL_VERSION}"
        if [[ "$candidate" == "latest" ]]; then
            candidate="$OPENSHELL_LATEST_VERSION"
        fi
        if version_is_available "$candidate"; then
            OPENSHELL_VERSION="$candidate"
            return
        fi
        echo "OpenShell version '$candidate' was not found between $MIN_OPENSHELL_VERSION and $OPENSHELL_LATEST_VERSION."
        echo "Try an exact released version, '$DEFAULT_OPENSHELL_VERSION', or 'latest'."
    done
}

resolve_openshell_version() {
    fetch_openshell_versions

    if [[ -n "$OPENSHELL_VERSION" ]]; then
        if [[ "$OPENSHELL_VERSION" == "latest" ]]; then
            OPENSHELL_VERSION="$OPENSHELL_LATEST_VERSION"
        fi
        if version_is_available "$OPENSHELL_VERSION"; then
            echo "OpenShell version selected: $OPENSHELL_VERSION"
            return
        fi

        if [[ -t 0 && "$OPENSHELL_VERSION_USER_SUPPLIED" == "true" ]]; then
            echo "OpenShell version '$OPENSHELL_VERSION' was not found between $MIN_OPENSHELL_VERSION and $OPENSHELL_LATEST_VERSION."
            choose_openshell_version_interactively
            echo "OpenShell version selected: $OPENSHELL_VERSION"
            return
        fi
        fail "OpenShell version '$OPENSHELL_VERSION' was not found between $MIN_OPENSHELL_VERSION and $OPENSHELL_LATEST_VERSION."
    fi

    if [[ -t 0 ]]; then
        choose_openshell_version_interactively
    else
        OPENSHELL_VERSION="$DEFAULT_OPENSHELL_VERSION"
        if ! version_is_available "$OPENSHELL_VERSION"; then
            fail "Default OpenShell version '$OPENSHELL_VERSION' was not found on PyPI."
        fi
    fi
    echo "OpenShell version selected: $OPENSHELL_VERSION"
}

ensure_aiq_env() {
    cd "$REPO_ROOT"
    if [[ ! -d "$VENV_DIR" ]]; then
        log "Creating AI-Q virtual environment"
        ./scripts/setup.sh
    else
        log "Using existing AI-Q virtual environment"
    fi
}

install_openshell_python() {
    log "Installing OpenShell Python package exactly: openshell==$OPENSHELL_VERSION"
    uv pip install "openshell==$OPENSHELL_VERSION"

    local adapter_install_spec="$LANGCHAIN_NVIDIA_REPO"
    local editable_args=()
    if [[ -d "$LANGCHAIN_NVIDIA_REPO" ]]; then
        if [[ -f "$LANGCHAIN_NVIDIA_REPO/libs/openshell/pyproject.toml" ]]; then
            adapter_install_spec="$LANGCHAIN_NVIDIA_REPO/libs/openshell"
        elif [[ -f "$LANGCHAIN_NVIDIA_REPO/pyproject.toml" ]]; then
            adapter_install_spec="$LANGCHAIN_NVIDIA_REPO"
        else
            fail "langchain-nvidia-openshell package not found in local checkout: $LANGCHAIN_NVIDIA_REPO"
        fi
        editable_args=(-e)
    fi

    log "Installing langchain-nvidia-openshell adapter: $adapter_install_spec"
    # NOTE: expand editable_args only when non-empty; macOS bash 3.2 errors on
    # "${arr[@]}" for an empty array under `set -u`.
    local adapter_install_args=()
    if [[ ${#editable_args[@]} -eq 0 ]]; then
        adapter_install_args=(--reinstall-package langchain-nvidia-openshell)
    else
        adapter_install_args=("${editable_args[@]}")
    fi
    if ! uv pip install "${adapter_install_args[@]}" "$adapter_install_spec"; then
        cat <<EOF
ERROR: Could not install the langchain-nvidia-openshell adapter.

The adapter is published on PyPI as langchain-nvidia-openshell. The default install
resolves from PyPI; if your environment cannot reach it, point LANGCHAIN_NVIDIA_REPO at
an alternate uv install spec or a local checkout, then rerun. Examples:
  LANGCHAIN_NVIDIA_REPO=langchain-nvidia-openshell scripts/setup_openshell.sh
  scripts/setup_openshell.sh --langchain-nvidia /path/to/langchain-nvidia
EOF
        exit 1
    fi

    # The adapter still declares deepagents<0.6, so its install downgrades the 0.6.x that
    # AI-Q's deep-research runtime requires (pyproject: deepagents>=0.6.5). The adapter's
    # code only uses the stable deepagents BaseSandbox/protocol surface (the same imports
    # AI-Q's own sandbox package uses on 0.6.x), so reasserting the floor AI-Q needs is
    # safe. This is the OpenShell setup script, so keeping AI-Q runnable is the goal.
    log "Reasserting deepagents>=0.6.5 (AI-Q runtime floor) after adapter install"
    uv pip install "deepagents>=0.6.5"

    local installed
    installed="$("$VENV_DIR/bin/python" - <<'PY'
import openshell
print(getattr(openshell, "__version__", "unknown"))
PY
)"
    # The adapter pins openshell>=0.0.68 and may upgrade the package above the requested
    # version during its own install; only a version BELOW the requested floor is an error
    # (an exact-match check would spuriously fail on that allowed adapter-driven upgrade).
    if ! "$VENV_DIR/bin/python" - "$OPENSHELL_VERSION" "$installed" <<'PY'
import sys


def parts(v):
    return tuple(int(p) for p in v.split(".")[:3] if p.isdigit())


sys.exit(0 if parts(sys.argv[2]) >= parts(sys.argv[1]) else 1)
PY
    then
        fail "Installed openshell $installed is older than the requested floor $OPENSHELL_VERSION"
    fi
    "$VENV_DIR/bin/python" - <<'PY'
import langchain_nvidia_openshell  # noqa: F401
PY
    echo "OpenShell Python package verified: $installed"
    echo "langchain-nvidia-openshell adapter verified"
}

resolve_openshell_cli() {
    local candidates=(
        "$OPENSHELL_BIN"
        "$VENV_DIR/bin/openshell"
        "$(command -v openshell || true)"
        "$HOME/.local/bin/openshell"
    )
    local candidate
    for candidate in "${candidates[@]}"; do
        if [[ -n "$candidate" && -x "$candidate" ]]; then
            OPENSHELL_BIN="$candidate"
            echo "OpenShell CLI: $OPENSHELL_BIN ($("$OPENSHELL_BIN" --version 2>/dev/null || true))"
            return
        fi
    done
    fail "OpenShell CLI was not found after installing openshell==$OPENSHELL_VERSION"
}

resolve_docker() {
    log "Resolving Docker CLI"
    local candidates=(
        "$DOCKER_BIN"
        "$(command -v docker || true)"
        "/opt/homebrew/bin/docker"
        "/usr/local/bin/docker"
        "/usr/bin/docker"
    )
    local candidate
    for candidate in "${candidates[@]}"; do
        if [[ -n "$candidate" && -x "$candidate" ]]; then
            DOCKER_BIN="$candidate"
            echo "Docker CLI: $DOCKER_BIN"
            return
        fi
    done

    if [[ "$OS_NAME" == "macos" ]]; then
        candidate="$(find /opt/homebrew/Cellar/docker /usr/local/Cellar/docker -path '*/bin/docker' -type f 2>/dev/null | sort | tail -1 || true)"
        if [[ -n "$candidate" && -x "$candidate" ]]; then
            DOCKER_BIN="$candidate"
            echo "Docker CLI: $DOCKER_BIN"
            return
        fi
        cat <<'EOF'
Docker CLI was not found.

Install or link Docker CLI, then rerun:

  brew install docker

If Docker is installed but not on PATH, rerun with:

  scripts/setup_openshell.sh --docker-bin /path/to/docker
EOF
    else
        cat <<'EOF'
Docker CLI was not found.

Install Docker for your Linux distribution, then rerun. For example:

  sudo apt-get update
  sudo apt-get install -y docker.io

If Docker is installed but not on PATH, rerun with:

  scripts/setup_openshell.sh --docker-bin /path/to/docker
EOF
    fi
    exit 1
}

configure_docker_host() {
    if [[ -n "${DOCKER_HOST:-}" ]]; then
        echo "DOCKER_HOST already set: $DOCKER_HOST"
        return
    fi
    local colima_openshell="$HOME/.colima/openshell/docker.sock"
    local colima_default="$HOME/.colima/default/docker.sock"
    if [[ -S "$colima_openshell" ]]; then
        export DOCKER_HOST="unix://$colima_openshell"
        echo "DOCKER_HOST: $DOCKER_HOST"
    elif [[ -S "$colima_default" ]]; then
        export DOCKER_HOST="unix://$colima_default"
        echo "DOCKER_HOST: $DOCKER_HOST"
    fi
}

verify_docker_runtime() {
    log "Verifying Docker runtime"
    if "$DOCKER_BIN" info >/dev/null 2>&1; then
        echo "Docker daemon is reachable"
        return
    fi

    if [[ -n "${DOCKER_HOST:-}" ]]; then
        cat <<EOF
Docker CLI was found, but the Docker daemon is not reachable.

DOCKER_HOST is set to:

  $DOCKER_HOST

Start that Docker daemon or update DOCKER_HOST, then rerun:

  scripts/setup_openshell.sh
EOF
        exit 1
    fi

    if [[ "$OS_NAME" == "macos" ]]; then
        local docker_desktop_app=""
        if [[ -d "/Applications/Docker.app" ]]; then
            docker_desktop_app="/Applications/Docker.app"
        elif [[ -d "$HOME/Applications/Docker.app" ]]; then
            docker_desktop_app="$HOME/Applications/Docker.app"
        fi

        if [[ -n "$docker_desktop_app" ]]; then
            cat <<EOF
Docker CLI was found, but the Docker daemon is not reachable.

No Colima socket was selected, so this setup expects Docker Desktop on macOS.
Docker Desktop appears to be installed at:

  $docker_desktop_app

Start Docker Desktop, wait until it reports that Docker is running, then rerun:

  scripts/setup_openshell.sh

If you use a remote Docker daemon, set DOCKER_HOST before rerunning.
EOF
        else
            cat <<'EOF'
Docker CLI was found, but the Docker daemon is not reachable.

No Colima socket was selected and Docker Desktop was not found in /Applications
or ~/Applications. Install and start Docker Desktop for macOS, then rerun:

  scripts/setup_openshell.sh

If you use Colima, start it first. For example:

  colima start

If you use a remote Docker daemon, set DOCKER_HOST before rerunning.
EOF
        fi
    else
        cat <<'EOF'
Docker CLI was found, but the Docker daemon is not reachable.

On Linux, start Docker and make sure your user can access it, then rerun. For example:

  sudo systemctl start docker
  docker info

If Docker is running but permission is denied, add your user to the docker group,
log out and back in, then rerun:

  sudo usermod -aG docker "$USER"

If you use a remote Docker daemon, set DOCKER_HOST before rerunning.
EOF
    fi
    exit 1
}

resolve_gateway_launcher() {
    if [[ -n "$OPENSHELL_GATEWAY_LAUNCH_BIN" && -x "$OPENSHELL_GATEWAY_LAUNCH_BIN" ]]; then
        echo "OpenShell gateway launcher: $OPENSHELL_GATEWAY_LAUNCH_BIN"
        return
    fi

    local candidates=(
        "/opt/homebrew/opt/openshell/libexec/openshell-gateway-homebrew-service"
        "$(command -v openshell-gateway || true)"
        "/opt/homebrew/bin/openshell-gateway"
        "/usr/local/bin/openshell-gateway"
        "/usr/bin/openshell-gateway"
        "$HOME/.local/bin/openshell-gateway"
        "$VENV_DIR/bin/openshell-gateway"
    )
    local candidate
    for candidate in "${candidates[@]}"; do
        if [[ -n "$candidate" && -x "$candidate" ]]; then
            OPENSHELL_GATEWAY_LAUNCH_BIN="$candidate"
            echo "OpenShell gateway launcher: $OPENSHELL_GATEWAY_LAUNCH_BIN"
            return
        fi
    done

    if [[ "$OS_NAME" == "macos" ]]; then
        # The nvidia/openshell Homebrew tap (github.com/nvidia/homebrew-openshell) is not
        # published, so `brew install nvidia/openshell/openshell` 404s. Use OpenShell's
        # official installer instead, which sets up the gateway (local brew service + mTLS).
        log "Installing the OpenShell gateway via the official installer (NVIDIA/OpenShell)"
        curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh
        local installed_candidate
        for installed_candidate in \
            "/opt/homebrew/opt/openshell/libexec/openshell-gateway-homebrew-service" \
            "$(command -v openshell-gateway || true)" \
            "/opt/homebrew/bin/openshell-gateway"; do
            if [[ -n "$installed_candidate" && -x "$installed_candidate" ]]; then
                OPENSHELL_GATEWAY_LAUNCH_BIN="$installed_candidate"
                echo "OpenShell gateway launcher: $OPENSHELL_GATEWAY_LAUNCH_BIN"
                return
            fi
        done
    fi

    cat <<EOF
OpenShell gateway launcher was not found.

Install the gateway, or rerun with:

  scripts/setup_openshell.sh --gateway-bin /path/to/openshell-gateway

On macOS, install the OpenShell gateway with the official installer:

  curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh
EOF
    exit 1
}

configure_gateway_mode() {
    GATEWAY_ENDPOINT="https://127.0.0.1:$GATEWAY_PORT"
    GATEWAY_DISABLE_TLS=false

    if [[ "$(basename "$OPENSHELL_GATEWAY_LAUNCH_BIN")" == "openshell-gateway" ]]; then
        if [[ "$CREATE_SANDBOX" == "true" ]]; then
            cat <<'EOF'
The raw openshell-gateway binary is not enough for Docker sandbox creation in
this setup because Docker sandboxes require gateway JWT/mTLS configuration.

Use the packaged gateway service wrapper when available, for example:

  scripts/setup_openshell.sh --gateway-bin /opt/homebrew/opt/openshell/libexec/openshell-gateway-homebrew-service

Or start a configured OpenShell gateway yourself, then rerun:

  scripts/setup_openshell.sh --no-restart-gateway
EOF
            exit 1
        fi
        GATEWAY_ENDPOINT="http://127.0.0.1:$GATEWAY_PORT"
        GATEWAY_DISABLE_TLS=true
        echo "OpenShell gateway mode: plaintext local HTTP"
    else
        echo "OpenShell gateway mode: local mTLS"
    fi
}

start_or_verify_gateway() {
    log "Starting/verifying OpenShell gateway"
    if [[ "$RESTART_GATEWAY" == "true" ]]; then
        resolve_gateway_launcher
        configure_gateway_mode
        pkill -f openshell-gateway >/dev/null 2>&1 || true
        sleep 2
        rm -f /tmp/aiq-openshell-gateway.log
        if [[ "$GATEWAY_DISABLE_TLS" == "true" ]]; then
            nohup env OPENSHELL_SERVER_PORT="$GATEWAY_PORT" \
                OPENSHELL_DRIVERS=docker \
                DOCKER_HOST="${DOCKER_HOST:-}" \
                "$OPENSHELL_GATEWAY_LAUNCH_BIN" --disable-tls >/tmp/aiq-openshell-gateway.log 2>&1 &
        else
            nohup env OPENSHELL_SERVER_PORT="$GATEWAY_PORT" \
                OPENSHELL_DRIVERS=docker \
                DOCKER_HOST="${DOCKER_HOST:-}" \
                "$OPENSHELL_GATEWAY_LAUNCH_BIN" >/tmp/aiq-openshell-gateway.log 2>&1 &
        fi
        "$OPENSHELL_BIN" gateway remove "$GATEWAY_NAME" >/dev/null 2>&1 || true
        if [[ "$GATEWAY_DISABLE_TLS" == "true" ]]; then
            "$OPENSHELL_BIN" gateway add --name "$GATEWAY_NAME" "$GATEWAY_ENDPOINT" --local
        else
            "$OPENSHELL_BIN" gateway add --name "$GATEWAY_NAME" "$GATEWAY_ENDPOINT" --local --gateway-insecure
        fi
        "$OPENSHELL_BIN" gateway select "$GATEWAY_NAME"
    fi

    local attempt
    for attempt in $(seq 1 60); do
        if "$OPENSHELL_BIN" status; then
            return
        fi
        sleep 1
    done

    echo "OpenShell gateway log:"
    LC_ALL=C tr -d '\000' </tmp/aiq-openshell-gateway.log 2>/dev/null | sed -n '1,220p' || true
    fail "OpenShell gateway did not become reachable"
}

print_policy_menu() {
    cat <<'EOF'

Choose an OpenShell sandbox network policy:

  1. Offline (recommended)
     No sandbox network access. AI-Q tools gather data; sandbox code computes on inputs.

  2. Research APIs
     Allow GitHub, NVIDIA API, Tavily, and Serper.

  3. Python packages
     Allow GitHub and PyPI for package metadata/download checks.

  4. AI development
     Allow GitHub, PyPI, NVIDIA API, Tavily, Serper, Hugging Face, arXiv,
     Semantic Scholar, and npm.

  5. Custom
     Type a comma-separated allowlist.

EOF
}

choose_policy_interactively() {
    if [[ -n "$POLICY_PRESET" || -n "$POLICY_ALLOWLIST" ]]; then
        return
    fi
    if [[ ! -t 0 ]]; then
        POLICY_PRESET=offline
        return
    fi

    print_policy_menu
    local choice
    while true; do
        read -r -p "Policy choice [1]: " choice
        choice="${choice:-1}"
        case "$choice" in
            1|offline)
                POLICY_PRESET=offline
                return
                ;;
            2|research)
                POLICY_PRESET=research
                return
                ;;
            3|python|python-packages)
                POLICY_PRESET=python-packages
                return
                ;;
            4|ai|ai-dev)
                POLICY_PRESET=ai-dev
                return
                ;;
            5|custom)
                POLICY_PRESET=custom
                read -r -p "Allow services ($SUPPORTED_SERVICES): " POLICY_ALLOWLIST
                return
                ;;
            *)
                echo "Choose 1, 2, 3, 4, or 5."
                ;;
        esac
    done
}

resolve_policy() {
    choose_policy_interactively
    POLICY_PRESET="$(echo "${POLICY_PRESET:-}" | tr '[:upper:]' '[:lower:]' | tr -d ' ')"
    POLICY_ALLOWLIST="$(echo "${POLICY_ALLOWLIST:-}" | tr '[:upper:]' '[:lower:]' | tr -d ' ')"

    if [[ -z "$POLICY_PRESET" && -n "$POLICY_ALLOWLIST" ]]; then
        POLICY_PRESET=custom
    fi
    if [[ -z "$POLICY_PRESET" ]]; then
        POLICY_PRESET=offline
    fi
    if [[ "$POLICY_PRESET" == "none" ]]; then
        POLICY_PRESET=offline
    fi

    case "$POLICY_PRESET" in
        offline)
            POLICY_ALLOWLIST=offline
            ;;
        research)
            POLICY_ALLOWLIST=github,nvidia,tavily,serper
            ;;
        python-packages)
            POLICY_ALLOWLIST=github,pypi
            ;;
        ai-dev)
            POLICY_ALLOWLIST=github,pypi,nvidia,tavily,serper,huggingface,arxiv,semantic-scholar,npm
            ;;
        custom)
            if [[ -z "$POLICY_ALLOWLIST" ]]; then
                fail "--policy custom requires --allow, for example: --policy custom --allow github,pypi"
            fi
            ;;
        *)
            fail "Unsupported policy '$POLICY_PRESET'. Choices: $SUPPORTED_POLICIES"
            ;;
    esac

    if [[ "$POLICY_ALLOWLIST" == *offline* && "$POLICY_ALLOWLIST" != "offline" ]]; then
        fail "Use either offline or a service allowlist, not both: $POLICY_ALLOWLIST"
    fi
}

validate_service() {
    case "$1" in
        offline|github|pypi|nvidia|tavily|serper|huggingface|arxiv|semantic-scholar|npm)
            ;;
        *)
            fail "Unsupported policy service '$1'. Supported: $SUPPORTED_SERVICES"
            ;;
    esac
}

emit_policy_header() {
    cat >"$POLICY_FILE" <<'EOF'
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Generated by scripts/setup_openshell.sh.

version: 1

filesystem_policy:
  include_workdir: true
  read_only:
    - /usr
    - /lib
    - /etc
    - /app
    - /var/log
    - /proc/self
    - /dev/urandom
  read_write:
    - /sandbox
    - /workspace
    - /tmp
    - /dev/null

# best_effort lets the sandbox start on hosts without Landlock (e.g. Docker Desktop on
# macOS), but on those hosts filesystem confinement is silently dropped. This is acceptable
# only for the local single-operator demo; production must use `hard_requirement` so a
# missing LSM fails closed instead of running unconfined.
landlock:
  compatibility: best_effort

process:
  run_as_user: sandbox
  run_as_group: sandbox

EOF
}

emit_policy_entry() {
    local key="$1"
    local name="$2"
    shift 2
    {
        echo "  $key:"
        echo "    name: $name"
        echo "    endpoints:"
        local host
        for host in "$@"; do
            echo "      - host: $host"
            echo "        port: 443"
            echo "        protocol: rest"
            echo "        enforcement: enforce"
            echo "        access: read-only"
        done
        echo "    binaries:"
        echo "      - { path: /usr/bin/curl }"
        echo "      - { path: /usr/local/bin/python3 }"
        echo "      - { path: /usr/local/bin/python }"
        echo "      - { path: /usr/local/bin/pip }"
        echo "      - { path: /usr/local/bin/pip3 }"
    } >>"$POLICY_FILE"
}

emit_policy_service() {
    case "$1" in
        github)
            emit_policy_entry github github-readonly api.github.com github.com
            ;;
        pypi)
            emit_policy_entry pypi pypi-readonly pypi.org files.pythonhosted.org
            ;;
        nvidia)
            emit_policy_entry nvidia nvidia-api-readonly integrate.api.nvidia.com
            ;;
        tavily)
            emit_policy_entry tavily tavily-api-readonly api.tavily.com
            ;;
        serper)
            emit_policy_entry serper serper-api-readonly google.serper.dev
            ;;
        huggingface)
            emit_policy_entry huggingface huggingface-readonly huggingface.co cdn-lfs.huggingface.co
            ;;
        arxiv)
            emit_policy_entry arxiv arxiv-readonly export.arxiv.org
            ;;
        semantic-scholar)
            emit_policy_entry semantic_scholar semantic-scholar-readonly api.semanticscholar.org
            ;;
        npm)
            emit_policy_entry npm npm-readonly registry.npmjs.org
            ;;
    esac
}

generate_policy() {
    log "Generating OpenShell policy"
    resolve_policy
    mkdir -p "$(dirname "$POLICY_FILE")"
    emit_policy_header
    if [[ "$POLICY_ALLOWLIST" == "offline" ]]; then
        echo "network_policies: {}" >>"$POLICY_FILE"
    else
        echo "network_policies:" >>"$POLICY_FILE"
        IFS=',' read -r -a services <<<"$POLICY_ALLOWLIST"
        local service
        for service in "${services[@]}"; do
            validate_service "$service"
            emit_policy_service "$service"
        done
    fi
    echo "Policy file: $POLICY_FILE"
    echo "Policy: $POLICY_PRESET"
    echo "Allowed services: $POLICY_ALLOWLIST"
}

build_image() {
    if [[ "$BUILD_IMAGE" != "true" ]]; then
        return
    fi
    log "Building sandbox image: $IMAGE_NAME (sandbox log level: $SANDBOX_LOG_LEVEL)"
    "$DOCKER_BIN" build -t "$IMAGE_NAME" \
        --build-arg OPENSHELL_SANDBOX_LOG_LEVEL="$SANDBOX_LOG_LEVEL" \
        -f "$REPO_ROOT/deploy/openshell/Dockerfile.aiq-demo" "$REPO_ROOT/deploy/openshell"
}

create_sandbox() {
    if [[ "$CREATE_SANDBOX" != "true" ]]; then
        return
    fi
    log "Creating named OpenShell sandbox: $SANDBOX_NAME"
    "$OPENSHELL_BIN" sandbox delete "$SANDBOX_NAME" >/dev/null 2>&1 || true
    local create_log="/tmp/${SANDBOX_NAME}-openshell-create.log"
    local policy_label="${POLICY_PRESET//,/_}"
    rm -f "$create_log"
    "$OPENSHELL_BIN" sandbox create \
        --name "$SANDBOX_NAME" \
        --from "$IMAGE_NAME" \
        --policy "$POLICY_FILE" \
        --label aiq=openshell \
        --label aiq-policy="$policy_label" \
        --no-tty \
        -- sleep infinity >"$create_log" 2>&1 &

    local attempt
    for attempt in $(seq 1 120); do
        if "$OPENSHELL_BIN" sandbox list | grep -F "$SANDBOX_NAME" | grep -F "Ready" >/dev/null 2>&1; then
            "$OPENSHELL_BIN" sandbox list | grep -F "$SANDBOX_NAME" || true
            return
        fi
        sleep 1
    done

    echo "Sandbox create log:"
    sed -n '1,220p' "$create_log" || true
    fail "Timed out waiting for sandbox '$SANDBOX_NAME' to become Ready"
}

print_next_steps() {
    cat <<EOF

OpenShell is ready for AI-Q.

Use these exports in shells where you run AI-Q:

  export AIQ_OPENSHELL_SANDBOX_NAME="$SANDBOX_NAME"
  export AIQ_OPENSHELL_POLICY_FILE="$POLICY_FILE"

Start CLI mode:

  ./scripts/start_cli.sh --config_file configs/config_openshell.yml --verbose

Start E2E mode:

  ./scripts/start_e2e.sh --config_file configs/config_openshell.yml

Useful cleanup:

  $OPENSHELL_BIN sandbox delete "$SANDBOX_NAME"
  pkill -f openshell-gateway

EOF
}

main() {
    detect_os
    require_uv
    if [[ "$LIST_OPENSHELL_VERSIONS" == "true" ]]; then
        fetch_openshell_versions
        echo "$OPENSHELL_AVAILABLE_VERSIONS" | tr ',' '\n'
        exit 0
    fi
    resolve_openshell_version
    resolve_policy
    ensure_aiq_env
    install_openshell_python
    resolve_openshell_cli
    resolve_docker
    configure_docker_host
    verify_docker_runtime
    generate_policy
    start_or_verify_gateway
    build_image
    create_sandbox
    print_next_steps
}

main

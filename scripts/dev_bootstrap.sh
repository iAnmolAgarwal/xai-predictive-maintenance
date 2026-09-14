#!/bin/sh
# Preflight for a fresh clone: prove every tool `make setup` and `make dev`
# need is installed, and print what was found. Exits non-zero on the first
# thing that is missing or too old, naming how to install it.
#
#   sh scripts/dev_bootstrap.sh

set -eu

missing=0

report_missing() {
    printf '  MISSING  %-7s  %s\n' "$1" "$2"
    missing=$((missing + 1))
}

check() {
    name="$1"
    install_hint="$2"
    if command -v "$name" >/dev/null 2>&1; then
        printf '  ok       %-7s  %s\n' "$name" "$($name --version 2>&1 | head -n 1)"
    else
        report_missing "$name" "$install_hint"
    fi
}

echo "xpm developer preflight"
echo

check docker "install Docker Desktop or OrbStack (https://orbstack.dev)"
check uv     "curl -LsSf https://astral.sh/uv/install.sh | sh"
check pnpm   "corepack enable pnpm  (or: npm install -g pnpm)"

if command -v node >/dev/null 2>&1; then
    node_version="$(node --version)"
    node_major="$(echo "$node_version" | sed 's/^v\([0-9]*\).*/\1/')"
    if [ "$node_major" -ge 20 ]; then
        printf '  ok       %-7s  %s\n' "node" "$node_version"
    else
        printf '  TOO OLD  %-7s  %s (need >= 20)\n' "node" "$node_version"
        missing=$((missing + 1))
    fi
else
    report_missing node "install Node 20 or newer (https://nodejs.org)"
fi

if command -v docker >/dev/null 2>&1; then
    if docker compose version >/dev/null 2>&1; then
        printf '  ok       %-7s  %s\n' "compose" "$(docker compose version)"
    else
        printf '  MISSING  %-7s  %s\n' "compose" "Docker Compose v2 (docker compose) is not available"
        missing=$((missing + 1))
    fi
fi

echo
if [ "$missing" -gt 0 ]; then
    echo "$missing prerequisite(s) missing; install them and re-run." >&2
    exit 1
fi

echo "All prerequisites present. Next: make setup, then make dev."

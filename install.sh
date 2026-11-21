#!/usr/bin/env bash
# ==============================================================================
# Control Hub - standalone install (outside the homelab-blueprint installer)
#
#   ./install.sh            prepare .env and a Python venv; start with ./run.sh
#   ./install.sh --docker   prepare .env and start the container (docker compose)
#
# Creates .env from .env.example once, with a freshly generated access token.
# Existing .env files are never overwritten.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="native"
case "${1:-}" in
    --docker) MODE="docker" ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    "") ;;
    *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
esac

command -v python3 >/dev/null || { echo "python3 is required." >&2; exit 1; }

set_env() {  # set_env KEY VALUE: replace KEY=... in .env, or append it
    local key="$1" value="$2"
    if grep -qE "^${key}=" .env; then
        python3 - "$key" "$value" <<'PY'
import re, sys
key, value = sys.argv[1], sys.argv[2]
text = open(".env", encoding="utf-8").read()
text = re.sub(rf"^{re.escape(key)}=.*$", f"{key}={value}", text, flags=re.M)
open(".env", "w", encoding="utf-8").write(text)
PY
    else
        printf '%s=%s\n' "$key" "$value" >> .env
    fi
}

if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env
    set_env CONTROL_HUB_TOKEN "$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')"
    echo "Created .env with a new access token."
else
    echo "Keeping the existing .env."
fi

TOKEN="$(grep -E '^CONTROL_HUB_TOKEN=' .env | cut -d= -f2-)"
PORT="$(grep -E '^CONTROL_HUB_PORT=' .env | cut -d= -f2- || true)"
PORT="${PORT:-7575}"

if [ "$MODE" = "docker" ]; then
    command -v docker >/dev/null || { echo "Docker is required for --docker." >&2; exit 1; }
    if ! grep -qE '^QBITTORRENT_PASS=.+' .env; then
        echo "Set QBITTORRENT_PASS in .env first (the compose file requires it)." >&2
        exit 1
    fi
    docker compose up -d --build
else
    if [ ! -d venv ]; then
        python3 -m venv venv
    fi
    ./venv/bin/pip install -q --upgrade pip
    ./venv/bin/pip install -q -r requirements.txt
    echo "Installed. Start it with: ./run.sh"
fi

cat <<EOF

Control Hub: http://<this-host>:${PORT}/?token=${TOKEN}
The token is stored in .env (mode 0600). Anyone holding it controls this host.
Edit .env to point the dashboard at your qBittorrent, Prowlarr and backup folders.
EOF

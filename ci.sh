#!/usr/bin/env bash
# Checks for the standalone control-hub repo. Run by its own CI workflow, and by the
# homelab-blueprint split-simulation job against an isolated copy of this folder.
# ShellCheck and Docker steps are skipped (with a note) where the tool is missing.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "== tests"
python3 -m pip install -q -r requirements.txt
python3 -m unittest discover -s tests

if command -v shellcheck >/dev/null; then
    echo "== shellcheck"
    shellcheck --severity=warning run.sh install.sh ci.sh host/server-suspend.sh
else
    echo "(shellcheck not installed, skipped)"
fi

if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    echo "== compose config"
    tmp_env="$(mktemp)"
    trap 'rm -f "$tmp_env"' EXIT
    # The compose file requires both; any value will do for validation.
    sed -e 's/^CONTROL_HUB_TOKEN=.*/CONTROL_HUB_TOKEN=ci-token/' -e 's/^QBITTORRENT_PASS=.*/QBITTORRENT_PASS=ci-pass/' .env.example > "$tmp_env"
    grep -q '^CONTROL_HUB_TOKEN=' "$tmp_env" || echo 'CONTROL_HUB_TOKEN=ci-token' >> "$tmp_env"
    grep -q '^QBITTORRENT_PASS=' "$tmp_env" || echo 'QBITTORRENT_PASS=ci-pass' >> "$tmp_env"
    CONTROL_HUB_TOKEN=ci-token QBITTORRENT_PASS=ci-pass docker compose --env-file "$tmp_env" config --quiet
    if [ "${CI_BUILD_IMAGE:-0}" = "1" ]; then
        echo "== docker build"
        docker build -q -t control-hub:ci . >/dev/null
    fi
else
    echo "(docker compose not available, skipped)"
fi
echo "control-hub checks passed"

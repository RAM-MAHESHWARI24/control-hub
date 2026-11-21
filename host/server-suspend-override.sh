#!/usr/bin/env bash
# ==============================================================================
# Schedules a one-off suspend at the given local time with a transient systemd
# timer. The Control Hub calls it through sudo. The time is validated here, so
# sudoers can allow this script with one trailing wildcard: sudo-rs (Ubuntu
# 26.04) rejects wildcards inside an argument such as --on-calendar=*.
# Usage: server-suspend-override.sh 'YYYY-MM-DD HH:MM:00'
# ==============================================================================
set -euo pipefail
spec="${1:-}"
if [[ $# -ne 1 || ! "$spec" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}\ [0-9]{2}:[0-9]{2}:00$ ]]; then
    echo "usage: $0 'YYYY-MM-DD HH:MM:00'" >&2
    exit 2
fi
systemctl stop server-suspend-override.timer 2>/dev/null || true
exec systemd-run --on-calendar="$spec" --unit=server-suspend-override /usr/local/sbin/server-suspend.sh --override

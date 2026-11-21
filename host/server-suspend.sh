#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Homelab Dynamic Suspend to RAM (S3) & Post-Wake Self-Healing Routine
# ==============================================================================

LOG_FILE="${SERVER_SUSPEND_LOG:-/var/log/server-suspend.log}"
SKIP_FILE="${SERVER_SUSPEND_SKIP:-/run/server-suspend.skip}"
OVERRIDE_FILE="${SERVER_SUSPEND_OVERRIDE:-/run/server-suspend.override}"
CONFIG_FILE="${SERVER_SUSPEND_CONF:-/etc/server-suspend.conf}"
CONTROL_HUB_ENV="${CONTROL_HUB_ENV:-/etc/homelab/control-hub.env}"

# Touch log if directory is accessible
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
touch "$LOG_FILE" 2>/dev/null || true
chmod 644 "$LOG_FILE" 2>/dev/null || true

ts() {
    date '+%Y-%m-%d %H:%M:%S %Z'
}

echo "------------------------------------------------------------" >> "$LOG_FILE"
echo "[$(ts)] [TRIGGER] Server suspend check triggered (args: $*)." >> "$LOG_FILE"

# 1. Skip Flag Check
if [ -e "$SKIP_FILE" ]; then
    echo "[$(ts)] [SKIP] Found skip flag at '$SKIP_FILE'." >> "$LOG_FILE"
    echo "[$(ts)] [SKIP] Server sleep aborted for tonight. Clearing skip flag and overrides..." >> "$LOG_FILE"
    rm -f "$SKIP_FILE"
    rm -f "$OVERRIDE_FILE"
    echo "[$(ts)] [SKIP] Flags cleared successfully. Server will remain active." >> "$LOG_FILE"
    exit 0
fi

# 2. Parse flags & check permanent enabled / tonight's override deferral
IS_OVERRIDE_RUN=false
IS_DRY_RUN=false
for arg in "$@"; do
    if [[ "$arg" == "--override" || "$arg" == "--force" ]]; then
        IS_OVERRIDE_RUN=true
    elif [[ "$arg" == "--dry-run" ]]; then
        IS_DRY_RUN=true
    fi
done

if [[ "${DRY_RUN:-0}" == "1" ]]; then
    IS_DRY_RUN=true
fi

# Honor "enabled": false in permanent config unless invoked as an explicit override
if [ "$IS_OVERRIDE_RUN" = false ] && [ -f "$CONFIG_FILE" ] && command -v jq >/dev/null 2>&1; then
    CONF_ENABLED=$(jq -r 'if has("enabled") then (.enabled | tostring) else "true" end' "$CONFIG_FILE" 2>/dev/null || echo "true")
    if [ "$CONF_ENABLED" = "false" ]; then
        echo "[$(ts)] [DISABLED] Permanent sleep schedule is disabled in '$CONFIG_FILE'. Aborting suspend." >> "$LOG_FILE"
        exit 0
    fi
fi

if [ "$IS_OVERRIDE_RUN" = false ] && [ -f "$OVERRIDE_FILE" ] && command -v jq >/dev/null 2>&1; then
    OVERRIDE_ACTIVE=$(jq -r '.active // empty' "$OVERRIDE_FILE" 2>/dev/null || echo "")
    OVERRIDE_TIME=$(jq -r '.sleep_time // empty' "$OVERRIDE_FILE" 2>/dev/null || echo "")
    CURRENT_TIME=$(date '+%H:%M')

    if [[ "$OVERRIDE_ACTIVE" == "true" && -n "$OVERRIDE_TIME" && "$OVERRIDE_TIME" != "$CURRENT_TIME" ]]; then
        echo "[$(ts)] [OVERRIDE-DEFER] Sleep is overridden for tonight to execute at $OVERRIDE_TIME (currently $CURRENT_TIME). Deferring standard schedule." >> "$LOG_FILE"
        exit 0
    fi
fi

# 3. Dynamic Safety Guards (ADR-0003): defer suspend while critical work is active
# 3a. Active cloud backup, media settings backup, restore test, or database dump
if pgrep -f "immich_backup_gdrive.sh" >/dev/null 2>&1 \
    || pgrep -f "media_config_backup.py" >/dev/null 2>&1 \
    || pgrep -f "photo_restore_test" >/dev/null 2>&1 \
    || pgrep -f "rclone sync" >/dev/null 2>&1 \
    || pgrep -f "rclone copy" >/dev/null 2>&1 \
    || pgrep -f "pg_dumpall" >/dev/null 2>&1; then
    echo "[$(ts)] [DEFER] Cloud backup, restore test, or database dump is currently in progress. Skipping suspend." >> "$LOG_FILE"
    exit 0
fi

# 3b. Active LAN SMB file transfers / share sessions (excluding idle IPC$ probes)
if command -v smbstatus >/dev/null 2>&1; then
    if smbstatus -S 2>/dev/null | awk 'NR>3 && $1 != "" && $1 != "IPC$" && $1 !~ /^-+$/ {found=1} END {exit !found}'; then
        echo "[$(ts)] [DEFER] Active LAN Samba (SMB) share session detected. Skipping suspend." >> "$LOG_FILE"
        exit 0
    fi
fi

# Helper to read a single KEY=VALUE from control-hub.env without sourcing arbitrary code
read_env_key() {
    local key="$1"
    if [ -r "$CONTROL_HUB_ENV" ]; then
        awk -F= -v k="$key" '$1 == k {sub(/^[^=]*=/, ""); gsub(/^["'\'']|["'\'']$/, ""); print; exit}' "$CONTROL_HUB_ENV" 2>/dev/null || true
    fi
}

# 3c. Active qBittorrent downloads (> 50 KB/s)
if command -v curl >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
    QBIT_URL="${QBITTORRENT_URL:-$(read_env_key QBITTORRENT_URL)}"
    QBIT_URL="${QBIT_URL:-http://127.0.0.1:8080}"
    QBIT_USER="${QBITTORRENT_USER:-$(read_env_key QBITTORRENT_USER)}"
    QBIT_USER="${QBIT_USER:-admin}"
    QBIT_PASS="${QBITTORRENT_PASS:-$(read_env_key QBITTORRENT_PASS)}"

    if [ -n "$QBIT_PASS" ]; then
        COOKIE_JAR=$(mktemp)
        if curl -fsS --max-time 2 -c "$COOKIE_JAR" \
            --data-urlencode "username=$QBIT_USER" \
            --data-urlencode "password=$QBIT_PASS" \
            "${QBIT_URL%/}/api/v2/auth/login" 2>/dev/null | grep -q "Ok\."; then
            DL_SPEED=$(curl -fsS --max-time 2 -b "$COOKIE_JAR" "${QBIT_URL%/}/api/v2/transfer/info" 2>/dev/null \
                | jq -r '.dl_info_speed // 0' 2>/dev/null || echo "0")
            rm -f "$COOKIE_JAR"
            if [[ "$DL_SPEED" =~ ^[0-9]+$ ]] && [ "$DL_SPEED" -gt 51200 ]; then
                echo "[$(ts)] [DEFER] Active qBittorrent download in progress (${DL_SPEED} B/s). Skipping suspend." >> "$LOG_FILE"
                exit 0
            fi
        else
            rm -f "$COOKIE_JAR"
        fi
    fi

    # 3d. Active Jellyfin playback (when JELLYFIN_API_KEY is configured)
    JF_URL="${JELLYFIN_URL:-$(read_env_key JELLYFIN_URL)}"
    JF_URL="${JF_URL:-http://127.0.0.1:8096}"
    JF_KEY="${JELLYFIN_API_KEY:-$(read_env_key JELLYFIN_API_KEY)}"
    if [ -n "$JF_KEY" ]; then
        JF_PLAYING=$(curl -fsS --max-time 2 -H "X-Emby-Token: $JF_KEY" "${JF_URL%/}/Sessions" 2>/dev/null \
            | jq -r '[.[] | select(.NowPlayingItem != null and ((.PlayState.IsPaused // false) == false))] | length' 2>/dev/null || echo "0")
        if [[ "$JF_PLAYING" =~ ^[0-9]+$ ]] && [ "$JF_PLAYING" -gt 0 ]; then
            echo "[$(ts)] [DEFER] Active Jellyfin media playback (${JF_PLAYING} stream(s)). Skipping suspend." >> "$LOG_FILE"
            exit 0
        fi
    fi
fi

# 4. Calculate Sleep Duration (Seconds)
SLEEP_DURATION=21600 # Default fallback: 6 hours (21600 seconds)

if [ -f "$OVERRIDE_FILE" ] && command -v jq >/dev/null 2>&1; then
    O_DUR=$(jq -r '.duration_seconds // empty' "$OVERRIDE_FILE" 2>/dev/null || echo "")
    if [[ "$O_DUR" =~ ^[0-9]+$ && "$O_DUR" -gt 0 ]]; then
        SLEEP_DURATION=$O_DUR
        echo "[$(ts)] [OVERRIDE] Using tonight's override sleep duration: ${SLEEP_DURATION}s." >> "$LOG_FILE"
    fi
elif [ -f "$CONFIG_FILE" ] && command -v jq >/dev/null 2>&1; then
    C_DUR=$(jq -r '.duration_seconds // empty' "$CONFIG_FILE" 2>/dev/null || echo "")
    if [[ "$C_DUR" =~ ^[0-9]+$ && "$C_DUR" -gt 0 ]]; then
        SLEEP_DURATION=$C_DUR
        echo "[$(ts)] [CONFIG] Using configured permanent sleep duration: ${SLEEP_DURATION}s." >> "$LOG_FILE"
    fi
fi

HOURS_FLOAT=$(awk "BEGIN {printf \"%.1f\", $SLEEP_DURATION/3600}")
echo "[$(ts)] [SUSPEND] Preparing to suspend system to RAM (S3) for ${HOURS_FLOAT} hours (${SLEEP_DURATION}s)..." >> "$LOG_FILE"

if [ "$IS_DRY_RUN" = true ]; then
    echo "[$(ts)] [DRY_RUN] Dry run enabled. Skipping actual rtcwake execution." >> "$LOG_FILE"
else
    echo "[$(ts)] [SUSPEND] Invoking '/usr/sbin/rtcwake -m mem -s ${SLEEP_DURATION}'..." >> "$LOG_FILE"
    # Run rtcwake and log output
    if /usr/sbin/rtcwake -m mem -s "$SLEEP_DURATION" >> "$LOG_FILE" 2>&1; then
        echo "[$(ts)] [RESUME] rtcwake completed successfully. System has resumed from sleep." >> "$LOG_FILE"
    else
        EXIT_CODE=$?
        echo "[$(ts)] [ERROR] rtcwake failed with exit code $EXIT_CODE!" >> "$LOG_FILE"
        exit $EXIT_CODE
    fi
fi

# Clear tonight's override upon waking up
if [ -f "$OVERRIDE_FILE" ]; then
    rm -f "$OVERRIDE_FILE"
    echo "[$(ts)] [CLEANUP] Tonight's sleep override file cleared. Schedule reverted to default." >> "$LOG_FILE"
fi

# ==============================================================================
# Post-Resume Self-Healing: Network Verification & Media Pipeline Recovery
# ==============================================================================
echo "[$(ts)] [RESUME] Waiting up to 30s for network connectivity to stabilize..." >> "$LOG_FILE"
NET_READY=false
for i in {1..15}; do
    if ping -c 1 -W 2 1.1.1.1 >/dev/null 2>&1 || ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; then
        echo "[$(ts)] [RESUME] Network connectivity verified online after ${i} check(s)." >> "$LOG_FILE"
        NET_READY=true
        break
    fi
    sleep 2
done

if [ "$NET_READY" = false ]; then
    echo "[$(ts)] [WARNING] Network did not respond to ping within 30s. Continuing recovery anyway." >> "$LOG_FILE"
fi

# Brief delay to allow background daemons to bind sockets
sleep 5

# ------------------------------------------------------------------------------
# Post-wake hooks: every executable *.sh in the hooks directory runs once, in
# name order, after resume. Modules drop their own recovery steps here (the
# blueprint installs the media stack's post-wake hook as 50-mediaserver.sh).
# A failing hook is logged and never aborts the others.
# ------------------------------------------------------------------------------
HOOKS_DIR="${SERVER_SUSPEND_HOOKS_DIR:-/etc/server-suspend.d}"
if [ -d "$HOOKS_DIR" ]; then
    for hook in "$HOOKS_DIR"/*.sh; do
        [ -e "$hook" ] || continue
        if [ -x "$hook" ]; then
            echo "[$(ts)] [HOOK] Running $hook" >> "$LOG_FILE"
            "$hook" >> "$LOG_FILE" 2>&1 || echo "[$(ts)] [HOOK] $hook exited with status $?" >> "$LOG_FILE"
        else
            echo "[$(ts)] [HOOK] Skipping $hook (not executable)" >> "$LOG_FILE"
        fi
    done
else
    echo "[$(ts)] [HOOK] No hooks directory at $HOOKS_DIR; nothing to run." >> "$LOG_FILE"
fi

echo "[$(ts)] [RECOVERY] Post-wake recovery completed." >> "$LOG_FILE"

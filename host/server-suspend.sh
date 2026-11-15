#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Homelab Dynamic Suspend to RAM (S3) & Post-Wake Self-Healing Routine
# ==============================================================================

LOG_FILE="${SERVER_SUSPEND_LOG:-/var/log/server-suspend.log}"
SKIP_FILE="${SERVER_SUSPEND_SKIP:-/run/server-suspend.skip}"
OVERRIDE_FILE="${SERVER_SUSPEND_OVERRIDE:-/run/server-suspend.override}"
CONFIG_FILE="${SERVER_SUSPEND_CONF:-/etc/server-suspend.conf}"

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

# 2. Check for Tonight's Override Deferral (unless invoked with --override or --force)
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

if [ "$IS_OVERRIDE_RUN" = false ] && [ -f "$OVERRIDE_FILE" ]; then
    OVERRIDE_ACTIVE=$(jq -r '.active // empty' "$OVERRIDE_FILE" 2>/dev/null || echo "")
    OVERRIDE_TIME=$(jq -r '.sleep_time // empty' "$OVERRIDE_FILE" 2>/dev/null || echo "")
    CURRENT_TIME=$(date '+%H:%M')

    if [[ "$OVERRIDE_ACTIVE" == "true" && -n "$OVERRIDE_TIME" && "$OVERRIDE_TIME" != "$CURRENT_TIME" ]]; then
        echo "[$(ts)] [OVERRIDE-DEFER] Sleep is overridden for tonight to execute at $OVERRIDE_TIME (currently $CURRENT_TIME). Deferring standard schedule." >> "$LOG_FILE"
        exit 0
    fi
fi

# 3. Dynamic Safety: Defer midnight suspend if backup or sync is in progress
if pgrep -f "immich_backup_gdrive.sh" >/dev/null 2>&1 || pgrep -f "rclone sync" >/dev/null 2>&1 || pgrep -f "pg_dumpall" >/dev/null 2>&1; then
    echo "[$(ts)] [DEFER] Cloud backup or database dump is currently in progress. Skipping suspend." >> "$LOG_FILE"
    exit 0
fi

# 4. Calculate Sleep Duration (Seconds)
SLEEP_DURATION=21600 # Default fallback: 6 hours (21600 seconds)

if [ -f "$OVERRIDE_FILE" ]; then
    O_DUR=$(jq -r '.duration_seconds // empty' "$OVERRIDE_FILE" 2>/dev/null || echo "")
    if [[ -n "$O_DUR" && "$O_DUR" -gt 0 ]]; then
        SLEEP_DURATION=$O_DUR
        echo "[$(ts)] [OVERRIDE] Using tonight's override sleep duration: ${SLEEP_DURATION}s." >> "$LOG_FILE"
    fi
elif [ -f "$CONFIG_FILE" ]; then
    C_DUR=$(jq -r '.duration_seconds // empty' "$CONFIG_FILE" 2>/dev/null || echo "")
    if [[ -n "$C_DUR" && "$C_DUR" -gt 0 ]]; then
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
# blueprint installs apps/mediaserver/host/post-wake-arr.sh as 50-mediaserver.sh).
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

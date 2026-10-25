"""
Widget: Sleep Guard Hero Command Module
Provides granular control for server sleep:
1. Quick Toggle (Stay awake tonight / Skip active)
2. Shift Tonight (One-off override: +1h, +2h, or custom sleep/wake time)
3. Permanent Schedule (Forever: Change default recurring sleep & wake hours)
"""

import os
import json
import datetime
import subprocess
from flask import Blueprint, jsonify, request

from config import (
    SUSPEND_SKIP_FILE, SUSPEND_OVERRIDE_FILE,
    SUSPEND_CONFIG_FILE, SUSPEND_CRON_FILE
)

sleep_guard_bp = Blueprint("sleep_guard", __name__)


def load_permanent_config():
    """Loads permanent default schedule from /etc/server-suspend.conf"""
    default_conf = {
        "enabled": True,
        "sleep_time": "00:00",
        "wake_time": "06:00",
        "duration_hours": 6.0,
        "duration_seconds": 21600
    }
    if os.path.exists(SUSPEND_CONFIG_FILE):
        try:
            with open(SUSPEND_CONFIG_FILE, "r") as f:
                data = json.load(f)
                return {**default_conf, **data}
        except Exception:
            pass
    return default_conf


def write_privileged_json(filepath, data):
    """Writes JSON payload to a privileged system path using sudo tee"""
    payload_str = json.dumps(data, indent=2)
    subprocess.run(
        ["sudo", "tee", filepath],
        input=payload_str,
        stdout=subprocess.DEVNULL,
        text=True,
        check=True
    )


def write_privileged_text(filepath, text_content):
    """Writes text content to a privileged system path using sudo tee"""
    subprocess.run(
        ["sudo", "tee", filepath],
        input=text_content,
        stdout=subprocess.DEVNULL,
        text=True,
        check=True
    )


def save_permanent_config(conf):
    """Saves permanent default schedule and updates /etc/cron.d/server-suspend"""
    write_privileged_json(SUSPEND_CONFIG_FILE, conf)

    # Update cron schedule
    sleep_t = conf.get("sleep_time", "00:00")
    parts = sleep_t.split(":")
    hour = int(parts[0]) if len(parts) >= 1 else 0
    minute = int(parts[1]) if len(parts) >= 2 else 0

    cron_line = f"{minute} {hour} * * * root /usr/local/sbin/server-suspend.sh >> /var/log/server-suspend.log 2>&1\n"
    if not conf.get("enabled", True):
        cron_line = f"# DISABLED: {cron_line}"

    content = (
        "# ServerFF Suspend to RAM (S3) schedule managed by Control Hub\n"
        f"{cron_line}"
    )
    write_privileged_text(SUSPEND_CRON_FILE, content)


def load_tonight_override():
    """Loads temporary one-off override from /run/server-suspend.override"""
    if os.path.exists(SUSPEND_OVERRIDE_FILE):
        try:
            with open(SUSPEND_OVERRIDE_FILE, "r") as f:
                data = json.load(f)
                if data.get("active", False):
                    return data
        except Exception:
            pass
    return None


def calculate_seconds_until(target_time_str):
    """Calculates seconds until the next occurrence of HH:MM in local IST time"""
    parts = target_time_str.split(":")
    target_hour = int(parts[0]) if len(parts) >= 1 else 0
    target_min = int(parts[1]) if len(parts) >= 2 else 0

    now = datetime.datetime.now()
    target_dt = now.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)
    if target_dt <= now:
        target_dt += datetime.timedelta(days=1)

    return int((target_dt - now).total_seconds())


def parse_time_minutes(time_str):
    """Converts HH:MM string to total minutes from midnight (0 - 1440)"""
    parts = time_str.split(":")
    h = int(parts[0]) if len(parts) >= 1 else 0
    m = int(parts[1]) if len(parts) >= 2 else 0
    return h * 60 + m


@sleep_guard_bp.route("/api/sleep/status", methods=["GET"])
def get_sleep_status():
    """Returns comprehensive granular sleep status: permanent, override, and skip state"""
    skip_active = os.path.exists(SUSPEND_SKIP_FILE)
    permanent = load_permanent_config()
    override = load_tonight_override()

    # Determine effective sleep time and duration
    if override:
        effective_sleep = override.get("sleep_time", "00:00")
        effective_wake = override.get("wake_time", "06:00")
        effective_dur_hours = override.get("duration_hours", 6.0)
        state_mode = "override"
        state_label = f"Shifted Tonight: {effective_sleep} ➔ {effective_wake} ({effective_dur_hours}h)"
    elif skip_active:
        effective_sleep = permanent.get("sleep_time", "00:00")
        effective_wake = permanent.get("wake_time", "06:00")
        effective_dur_hours = permanent.get("duration_hours", 6.0)
        state_mode = "skip"
        state_label = "Staying Awake Tonight (Skip Active)"
    else:
        effective_sleep = permanent.get("sleep_time", "00:00")
        effective_wake = permanent.get("wake_time", "06:00")
        effective_dur_hours = permanent.get("duration_hours", 6.0)
        state_mode = "default"
        state_label = f"Sleep Armed: {effective_sleep} ➔ {effective_wake} (Suspends nightly)"

    seconds_until_sleep = calculate_seconds_until(effective_sleep)

    # Calculate 24h timeline window positions (percentage across 1440 minutes)
    start_mins = parse_time_minutes(effective_sleep)
    dur_mins = int(effective_dur_hours * 60)
    window_left_pct = round((start_mins / 1440.0) * 100.0, 1)
    window_width_pct = round((dur_mins / 1440.0) * 100.0, 1)

    return jsonify({
        "skip_active": skip_active,
        "state_mode": state_mode,
        "state_label": state_label,
        "effective_sleep_time": f"{effective_sleep} IST",
        "effective_wake_time": f"{effective_wake} IST",
        "effective_duration_hours": effective_dur_hours,
        "seconds_until_sleep": seconds_until_sleep,
        "sleep_time": f"{effective_sleep} IST",
        "wake_time": f"{effective_wake} IST",
        "window_left_pct": window_left_pct,
        "window_width_pct": window_width_pct,
        "permanent_config": permanent,
        "tonight_override": override
    })


@sleep_guard_bp.route("/api/sleep/toggle", methods=["POST"])
def toggle_sleep():
    """Toggles /run/server-suspend.skip (stay awake completely tonight)"""
    try:
        if os.path.exists(SUSPEND_SKIP_FILE):
            subprocess.run(["sudo", "rm", "-f", SUSPEND_SKIP_FILE], check=True)
            new_state = False
            msg = "Normal midnight sleep re-armed."
        else:
            subprocess.run(["sudo", "touch", SUSPEND_SKIP_FILE], check=True)
            new_state = True
            msg = "Server will stay awake tonight (Skip active)."

        return jsonify({
            "success": True,
            "skip_active": new_state,
            "message": msg
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@sleep_guard_bp.route("/api/sleep/shift-tonight", methods=["POST"])
def shift_tonight():
    """
    Shifts sleep schedule for tonight only (one-off override).
    Payload can contain:
      - delay_hours: float/int (e.g. 1 or 2)
      - OR sleep_time: "HH:MM", wake_time: "HH:MM"
      - OR clear: true (resets tonight to default)
    """
    data = request.get_json(force=True, silent=True) or {}

    # Case 1: Clear override and revert tonight to default schedule
    if data.get("clear", False):
        try:
            if os.path.exists(SUSPEND_OVERRIDE_FILE):
                subprocess.run(["sudo", "rm", "-f", SUSPEND_OVERRIDE_FILE], check=True)
            subprocess.run(["sudo", "systemctl", "stop", "server-suspend-override.timer"], stderr=subprocess.DEVNULL)
            return jsonify({
                "success": True,
                "message": "Tonight's sleep schedule reverted back to default."
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    permanent = load_permanent_config()
    now = datetime.datetime.now()

    # Case 2: Quick Shift (+1h, +2h delay)
    if "delay_hours" in data:
        delay = float(data["delay_hours"])
        base_sleep = permanent.get("sleep_time", "00:00")
        parts = base_sleep.split(":")
        b_hour = int(parts[0])
        b_min = int(parts[1])

        target_sleep_dt = now.replace(hour=b_hour, minute=b_min, second=0, microsecond=0)
        if target_sleep_dt <= now:
            target_sleep_dt += datetime.timedelta(days=1)

        # Add delay
        target_sleep_dt += datetime.timedelta(hours=delay)
        target_sleep_str = target_sleep_dt.strftime("%H:%M")

        # Wake up after standard duration
        dur_hours = float(permanent.get("duration_hours", 6.0))
        target_wake_dt = target_sleep_dt + datetime.timedelta(hours=dur_hours)
        target_wake_str = target_wake_dt.strftime("%H:%M")
        dur_seconds = int(dur_hours * 3600)
    else:
        # Case 3: Explicit Custom Sleep & Wake Time
        target_sleep_str = data.get("sleep_time", "01:00")
        target_wake_str = data.get("wake_time", "07:00")

        p_sleep = target_sleep_str.split(":")
        s_h, s_m = int(p_sleep[0]), int(p_sleep[1])
        target_sleep_dt = now.replace(hour=s_h, minute=s_m, second=0, microsecond=0)
        if target_sleep_dt <= now:
            target_sleep_dt += datetime.timedelta(days=1)

        p_wake = target_wake_str.split(":")
        w_h, w_m = int(p_wake[0]), int(p_wake[1])
        target_wake_dt = target_sleep_dt.replace(hour=w_h, minute=w_m, second=0, microsecond=0)
        if target_wake_dt <= target_sleep_dt:
            target_wake_dt += datetime.timedelta(days=1)

        dur_seconds = int((target_wake_dt - target_sleep_dt).total_seconds())
        dur_hours = round(dur_seconds / 3600.0, 1)

    override_payload = {
        "active": True,
        "sleep_time": target_sleep_str,
        "wake_time": target_wake_str,
        "duration_hours": dur_hours,
        "duration_seconds": dur_seconds,
        "target_datetime": target_sleep_dt.strftime("%Y-%m-%d %H:%M:00"),
        "date": target_sleep_dt.strftime("%Y-%m-%d"),
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S")
    }

    try:
        # Write override configuration
        write_privileged_json(SUSPEND_OVERRIDE_FILE, override_payload)

        # Clear skip file if present so override takes effect
        if os.path.exists(SUSPEND_SKIP_FILE):
            subprocess.run(["sudo", "rm", "-f", SUSPEND_SKIP_FILE], check=False)

        # Schedule transient one-shot timer via systemd-run
        cal_spec = target_sleep_dt.strftime("%Y-%m-%d %H:%M:00")
        subprocess.run(["sudo", "systemctl", "stop", "server-suspend-override.timer"], stderr=subprocess.DEVNULL)
        cmd = [
            "sudo", "systemd-run",
            f"--on-calendar={cal_spec}",
            "--unit=server-suspend-override",
            "/usr/local/sbin/server-suspend.sh", "--override"
        ]
        subprocess.run(cmd, check=True)

        return jsonify({
            "success": True,
            "message": f"Tonight's sleep shifted to {target_sleep_str} IST (wakes at {target_wake_str} IST).",
            "override": override_payload
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@sleep_guard_bp.route("/api/sleep/schedule-permanent", methods=["POST"])
def schedule_permanent():
    """
    Updates the recurring daily sleep & wake schedule (forever).
    Payload:
      - sleep_time: "HH:MM"
      - wake_time: "HH:MM"
      - enabled: bool
    """
    data = request.get_json(force=True, silent=True) or {}
    sleep_time = data.get("sleep_time", "00:00")
    wake_time = data.get("wake_time", "06:00")
    enabled = bool(data.get("enabled", True))

    # Calculate duration
    s_parts = sleep_time.split(":")
    w_parts = wake_time.split(":")
    s_h, s_m = int(s_parts[0]), int(s_parts[1])
    w_h, w_m = int(w_parts[0]), int(w_parts[1])

    s_mins = s_h * 60 + s_m
    w_mins = w_h * 60 + w_m
    dur_mins = w_mins - s_mins
    if dur_mins <= 0:
        dur_mins += 1440

    dur_seconds = dur_mins * 60
    dur_hours = round(dur_mins / 60.0, 1)

    conf = {
        "enabled": enabled,
        "sleep_time": sleep_time,
        "wake_time": wake_time,
        "duration_hours": dur_hours,
        "duration_seconds": dur_seconds
    }

    try:
        save_permanent_config(conf)
        state_text = f"daily from {sleep_time} to {wake_time} ({dur_hours}h)" if enabled else "disabled"
        return jsonify({
            "success": True,
            "message": f"Default sleep schedule updated: {state_text}.",
            "config": conf
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

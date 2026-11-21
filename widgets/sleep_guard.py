"""
Widget: Sleep Guard Power Automation Controller
Provides granular control for server sleep:
1. Quick Toggle (Stay awake tonight / Skip active)
2. Shift Tonight (One-off override: +1h, +2h, or custom sleep/wake time)
3. Permanent Schedule (Forever: Change default recurring sleep & wake hours or disable)
"""

import datetime
import json
import os
import subprocess
from flask import Blueprint, jsonify, request

from config import (
    SUSPEND_CONFIG_FILE,
    SUSPEND_CRON_FILE,
    SUSPEND_OVERRIDE_FILE,
    SUSPEND_SCRIPT,
    SUSPEND_SKIP_FILE,
    get_host_timezone,
    get_tz_abbr,
)

sleep_guard_bp = Blueprint("sleep_guard", __name__)


def sleep_module_installed() -> bool:
    """Returns True when Sleep Guard host automation is installed on this node."""
    return bool(
        (SUSPEND_SCRIPT and os.path.isfile(SUSPEND_SCRIPT))
        or (SUSPEND_CRON_FILE and os.path.isfile(SUSPEND_CRON_FILE))
        or (SUSPEND_CONFIG_FILE and os.path.isfile(SUSPEND_CONFIG_FILE))
    )


def load_permanent_config():
    """Loads permanent default schedule from /etc/server-suspend.conf."""
    default_conf = {
        "enabled": True,
        "sleep_time": "00:00",
        "wake_time": "06:00",
        "duration_hours": 6.0,
        "duration_seconds": 21600,
    }
    if SUSPEND_CONFIG_FILE and os.path.exists(SUSPEND_CONFIG_FILE):
        try:
            with open(SUSPEND_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return {**default_conf, **data}
        except Exception:
            pass
    return default_conf


def write_privileged_json(filepath, data):
    """Writes JSON payload to a privileged system path using sudo tee."""
    payload_str = json.dumps(data, indent=2) + "\n"
    subprocess.run(
        ["sudo", "tee", filepath],
        input=payload_str,
        stdout=subprocess.DEVNULL,
        text=True,
        check=True,
        timeout=15,
    )


def write_privileged_text(filepath, text_content):
    """Writes text content to a privileged system path using sudo tee."""
    subprocess.run(
        ["sudo", "tee", filepath],
        input=text_content,
        stdout=subprocess.DEVNULL,
        text=True,
        check=True,
        timeout=15,
    )


def save_permanent_config(conf):
    """Saves permanent default schedule and updates /etc/cron.d/server-suspend."""
    write_privileged_json(SUSPEND_CONFIG_FILE, conf)

    sleep_t = conf.get("sleep_time", "00:00")
    parts = sleep_t.split(":")
    hour = int(parts[0]) if len(parts) >= 1 else 0
    minute = int(parts[1]) if len(parts) >= 2 else 0

    script_path = SUSPEND_SCRIPT or "/usr/local/sbin/server-suspend.sh"
    cron_line = f"{minute} {hour} * * * root {script_path} >> /var/log/server-suspend.log 2>&1\n"
    if not conf.get("enabled", True):
        cron_line = f"# DISABLED: {cron_line}"

    content = (
        "# Suspend to RAM (S3) schedule managed by Control Hub\n"
        f"{cron_line}"
    )
    write_privileged_text(SUSPEND_CRON_FILE, content)


def load_tonight_override():
    """Loads temporary one-off override from /run/server-suspend.override."""
    if SUSPEND_OVERRIDE_FILE and os.path.exists(SUSPEND_OVERRIDE_FILE):
        try:
            with open(SUSPEND_OVERRIDE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get("active", False):
                    return data
        except Exception:
            pass
    return None


def calculate_seconds_until(target_time_str):
    """Calculates seconds until the next occurrence of HH:MM in host local time."""
    parts = target_time_str.split(":")
    target_hour = int(parts[0]) if len(parts) >= 1 else 0
    target_min = int(parts[1]) if len(parts) >= 2 else 0

    now = datetime.datetime.now()
    target_dt = now.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)
    if target_dt <= now:
        target_dt += datetime.timedelta(days=1)

    return int((target_dt - now).total_seconds())


def parse_time_minutes(time_str):
    """Converts HH:MM string to total minutes from midnight (0 - 1439)."""
    parts = time_str.split(":")
    h = int(parts[0]) if len(parts) >= 1 else 0
    m = int(parts[1]) if len(parts) >= 2 else 0
    return (h * 60 + m) % 1440


def compute_window_segments(sleep_time: str, duration_hours: float) -> list:
    """
    Computes one or two 24-hour timeline bar segments (handling midnight wrap cleanly).
    Each segment is {"left_pct": float, "width_pct": float}.
    """
    start_mins = parse_time_minutes(sleep_time)
    dur_mins = max(0, min(1440, int(round(float(duration_hours) * 60))))
    if dur_mins <= 0:
        return []
    if start_mins + dur_mins <= 1440:
        return [{
            "left_pct": round((start_mins / 1440.0) * 100.0, 1),
            "width_pct": round((dur_mins / 1440.0) * 100.0, 1),
        }]
    first_mins = 1440 - start_mins
    second_mins = dur_mins - first_mins
    segments = [{
        "left_pct": round((start_mins / 1440.0) * 100.0, 1),
        "width_pct": round((first_mins / 1440.0) * 100.0, 1),
    }]
    if second_mins > 0:
        segments.append({
            "left_pct": 0.0,
            "width_pct": round((second_mins / 1440.0) * 100.0, 1),
        })
    return segments


@sleep_guard_bp.route("/api/sleep/status", methods=["GET"])
def get_sleep_status():
    """Returns comprehensive granular sleep status: installed, permanent, override, and skip state."""
    installed = sleep_module_installed()
    skip_active = bool(SUSPEND_SKIP_FILE and os.path.exists(SUSPEND_SKIP_FILE))
    permanent = load_permanent_config()
    enabled = bool(permanent.get("enabled", True))
    override = load_tonight_override()

    effective_sleep = permanent.get("sleep_time", "00:00")
    effective_wake = permanent.get("wake_time", "06:00")
    effective_dur_hours = float(permanent.get("duration_hours", 6.0))

    if not installed:
        state_mode = "not_installed"
        state_label = "Sleep Guard not installed on this server"
        seconds_until_sleep = 0
    elif override:
        effective_sleep = override.get("sleep_time", effective_sleep)
        effective_wake = override.get("wake_time", effective_wake)
        effective_dur_hours = float(override.get("duration_hours", effective_dur_hours))
        state_mode = "override"
        state_label = f"Shifted Tonight: {effective_sleep} \u2192 {effective_wake} ({effective_dur_hours}h)"
        seconds_until_sleep = calculate_seconds_until(effective_sleep)
    elif skip_active:
        state_mode = "skip"
        state_label = "Staying Awake Tonight (Skip Active)"
        seconds_until_sleep = calculate_seconds_until(effective_sleep) if enabled else 0
    elif not enabled:
        state_mode = "disabled"
        state_label = "Auto-Sleep Disabled (Permanent Schedule Off)"
        seconds_until_sleep = 0
    else:
        state_mode = "default"
        state_label = f"Sleep Armed: {effective_sleep} \u2192 {effective_wake} (Suspends nightly)"
        seconds_until_sleep = calculate_seconds_until(effective_sleep)

    window_segments = compute_window_segments(effective_sleep, effective_dur_hours) if installed else []
    window_left_pct = window_segments[0]["left_pct"] if window_segments else 0.0
    window_width_pct = window_segments[0]["width_pct"] if window_segments else 0.0

    tz_abbr = get_tz_abbr()
    return jsonify({
        "installed": installed,
        "enabled": enabled,
        "skip_active": skip_active,
        "state_mode": state_mode,
        "state_label": state_label,
        "effective_sleep_time": f"{effective_sleep} {tz_abbr}",
        "effective_wake_time": f"{effective_wake} {tz_abbr}",
        "effective_duration_hours": effective_dur_hours,
        "seconds_until_sleep": seconds_until_sleep,
        "sleep_time": f"{effective_sleep} {tz_abbr}",
        "wake_time": f"{effective_wake} {tz_abbr}",
        "timezone": get_host_timezone(),
        "tz_abbr": tz_abbr,
        "window_left_pct": window_left_pct,
        "window_width_pct": window_width_pct,
        "window_segments": window_segments,
        "permanent_config": permanent,
        "tonight_override": override,
    })


@sleep_guard_bp.route("/api/sleep/toggle", methods=["POST"])
def toggle_sleep():
    """Toggles /run/server-suspend.skip (stay awake completely tonight)."""
    if not sleep_module_installed():
        return jsonify({"success": False, "error": "Sleep Guard is not installed on this server."}), 404
    try:
        if os.path.exists(SUSPEND_SKIP_FILE):
            subprocess.run(["sudo", "rm", "-f", SUSPEND_SKIP_FILE], check=True, timeout=15)
            new_state = False
            msg = "Nightly sleep schedule re-armed."
        else:
            subprocess.run(["sudo", "touch", SUSPEND_SKIP_FILE], check=True, timeout=15)
            new_state = True
            msg = "Server will stay awake tonight (Skip active)."

        return jsonify({
            "success": True,
            "skip_active": new_state,
            "message": msg,
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
    if not sleep_module_installed():
        return jsonify({"success": False, "error": "Sleep Guard is not installed on this server."}), 404

    data = request.get_json(force=True, silent=True) or {}

    if data.get("clear", False):
        try:
            if os.path.exists(SUSPEND_OVERRIDE_FILE):
                subprocess.run(["sudo", "rm", "-f", SUSPEND_OVERRIDE_FILE], check=True, timeout=15)
            subprocess.run(
                ["sudo", "systemctl", "stop", "server-suspend-override.timer"],
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
            return jsonify({
                "success": True,
                "message": "Tonight's sleep schedule reverted back to default.",
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    permanent = load_permanent_config()
    now = datetime.datetime.now()

    try:
        if "delay_hours" in data:
            delay = float(data["delay_hours"])
            base_sleep = permanent.get("sleep_time", "00:00")
            parts = base_sleep.split(":")
            b_hour = int(parts[0])
            b_min = int(parts[1])

            target_sleep_dt = now.replace(hour=b_hour, minute=b_min, second=0, microsecond=0)
            if target_sleep_dt <= now:
                target_sleep_dt += datetime.timedelta(days=1)

            target_sleep_dt += datetime.timedelta(hours=delay)
            target_sleep_str = target_sleep_dt.strftime("%H:%M")

            dur_hours = float(permanent.get("duration_hours", 6.0))
            target_wake_dt = target_sleep_dt + datetime.timedelta(hours=dur_hours)
            target_wake_str = target_wake_dt.strftime("%H:%M")
            dur_seconds = int(dur_hours * 3600)
        else:
            target_sleep_str = str(data.get("sleep_time", "01:00"))
            target_wake_str = str(data.get("wake_time", "07:00"))

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
    except (ValueError, IndexError) as exc:
        return jsonify({"success": False, "error": f"Invalid time format: {exc}"}), 400

    override_payload = {
        "active": True,
        "sleep_time": target_sleep_str,
        "wake_time": target_wake_str,
        "duration_hours": dur_hours,
        "duration_seconds": dur_seconds,
        "target_datetime": target_sleep_dt.strftime("%Y-%m-%d %H:%M:00"),
        "date": target_sleep_dt.strftime("%Y-%m-%d"),
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        write_privileged_json(SUSPEND_OVERRIDE_FILE, override_payload)

        if os.path.exists(SUSPEND_SKIP_FILE):
            subprocess.run(["sudo", "rm", "-f", SUSPEND_SKIP_FILE], check=False, timeout=15)

        cal_spec = target_sleep_dt.strftime("%Y-%m-%d %H:%M:00")
        subprocess.run(
            ["sudo", "/usr/local/sbin/server-suspend-override.sh", cal_spec],
            check=True,
            timeout=15,
        )

        tz_abbr = get_tz_abbr()
        return jsonify({
            "success": True,
            "message": f"Tonight's sleep shifted to {target_sleep_str} {tz_abbr} (wakes at {target_wake_str} {tz_abbr}).",
            "override": override_payload,
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
    if not sleep_module_installed():
        return jsonify({"success": False, "error": "Sleep Guard is not installed on this server."}), 404

    data = request.get_json(force=True, silent=True) or {}
    sleep_time = str(data.get("sleep_time", "00:00"))
    wake_time = str(data.get("wake_time", "06:00"))
    enabled = bool(data.get("enabled", True))

    try:
        s_parts = sleep_time.split(":")
        w_parts = wake_time.split(":")
        s_h, s_m = int(s_parts[0]), int(s_parts[1])
        w_h, w_m = int(w_parts[0]), int(w_parts[1])
        if not (0 <= s_h < 24 and 0 <= s_m < 60 and 0 <= w_h < 24 and 0 <= w_m < 60):
            raise ValueError("Hours must be 00-23 and minutes 00-59")
    except (ValueError, IndexError) as exc:
        return jsonify({"success": False, "error": f"Invalid schedule time: {exc}"}), 400

    s_mins = s_h * 60 + s_m
    w_mins = w_h * 60 + w_m
    dur_mins = w_mins - s_mins
    if dur_mins <= 0:
        dur_mins += 1440

    dur_seconds = dur_mins * 60
    dur_hours = round(dur_mins / 60.0, 1)

    conf = {
        "enabled": enabled,
        "sleep_time": f"{s_h:02d}:{s_m:02d}",
        "wake_time": f"{w_h:02d}:{w_m:02d}",
        "duration_hours": dur_hours,
        "duration_seconds": dur_seconds,
    }

    try:
        save_permanent_config(conf)
        state_text = (
            f"daily from {conf['sleep_time']} to {conf['wake_time']} ({dur_hours}h)"
            if enabled
            else "disabled"
        )
        return jsonify({
            "success": True,
            "message": f"Default sleep schedule updated: {state_text}.",
            "config": conf,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

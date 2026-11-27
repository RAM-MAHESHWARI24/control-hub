"""
Widget: Home Assistant Sensors & NUT UPS Integration (Phase 4E)
Exposes a flat sensor snapshot + YAML snippet for Home Assistant (`rest` sensor + `rest_command`),
and probes local NUT (`upsc`) cleanly with honest `installed: False` fallback.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from flask import Blueprint, jsonify, request

from config import BACKUP_STATUS_FILE, PORT
from core import backup_health
from core.telemetry_sampler import telemetry_lock, telemetry_state
from widgets import sleep_guard, system_vitals

integrations_bp = Blueprint("integrations", __name__)


def probe_ups_nut() -> dict[str, Any]:
    """Probes local Network UPS Tools (`upsc`) status without sudo; returns honest fallback if absent."""
    upsc_bin = shutil.which("upsc")
    target_ups = (os.getenv("NUT_UPS_NAME") or "").strip() or None
    low_thresh = int(os.getenv("NUT_LOW_BATT_PCT") or "20")

    if not upsc_bin:
        return {
            "installed": False,
            "status": "not_installed",
            "ups_name": target_ups,
            "ups_model": None,
            "ups_status": None,
            "on_battery": False,
            "battery_charge": None,
            "battery_runtime_s": None,
            "input_voltage": None,
            "ups_load_pct": None,
            "low_battery": False,
            "low_battery_threshold": low_thresh,
            "shutdown_action": None,
            "error": None,
        }

    if not target_ups:
        try:
            list_proc = subprocess.run(
                [upsc_bin, "-l"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3,
            )
            if list_proc.returncode == 0:
                lines = [ln.strip() for ln in (list_proc.stdout or "").splitlines() if ln.strip()]
                if lines:
                    target_ups = lines[0]
        except Exception:
            target_ups = None

    if not target_ups:
        return {
            "installed": True,
            "status": "unconfigured",
            "ups_name": None,
            "ups_model": None,
            "ups_status": None,
            "on_battery": False,
            "battery_charge": None,
            "battery_runtime_s": None,
            "input_voltage": None,
            "ups_load_pct": None,
            "low_battery": False,
            "low_battery_threshold": low_thresh,
            "shutdown_action": None,
            "error": "No UPS configured in /etc/nut/ups.conf (set NUT_UPS_NAME if using a remote NUT host).",
        }

    try:
        proc = subprocess.run(
            [upsc_bin, target_ups],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=4,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip().splitlines()[-1][:160]
            return {
                "installed": True,
                "status": "unreachable",
                "ups_name": target_ups,
                "ups_model": None,
                "ups_status": None,
                "on_battery": False,
                "battery_charge": None,
                "battery_runtime_s": None,
                "input_voltage": None,
                "ups_load_pct": None,
                "low_battery": False,
                "low_battery_threshold": low_thresh,
                "shutdown_action": None,
                "error": err,
            }
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {
            "installed": True,
            "status": "error",
            "ups_name": target_ups,
            "ups_model": None,
            "ups_status": None,
            "on_battery": False,
            "battery_charge": None,
            "battery_runtime_s": None,
            "input_voltage": None,
            "ups_load_pct": None,
            "low_battery": False,
            "low_battery_threshold": low_thresh,
            "shutdown_action": None,
            "error": str(exc)[:160],
        }

    kv: dict[str, str] = {}
    for line in (proc.stdout or "").splitlines():
        k, sep, v = line.partition(":")
        if sep:
            kv[k.strip()] = v.strip()

    def _num(key: str) -> float | None:
        raw = kv.get(key)
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    ups_status = kv.get("ups.status") or "UNKNOWN"
    tokens = set(ups_status.split())
    on_battery = "OB" in tokens
    charge = _num("battery.charge")
    runtime_s = _num("battery.runtime")
    low_batt = bool(on_battery and charge is not None and charge <= low_thresh)
    state_label = "low_battery" if low_batt else ("on_battery" if on_battery else "online")

    return {
        "installed": True,
        "status": state_label,
        "ups_name": target_ups,
        "ups_model": kv.get("ups.model") or kv.get("device.model"),
        "ups_status": ups_status,
        "on_battery": on_battery,
        "battery_charge": round(charge, 1) if charge is not None else None,
        "battery_runtime_s": int(runtime_s) if runtime_s is not None else None,
        "input_voltage": _num("input.voltage"),
        "ups_load_pct": _num("ups.load"),
        "low_battery": low_batt,
        "low_battery_threshold": low_thresh,
        "shutdown_action": "upsmon / sudo systemctl poweroff recommended when battery drops below threshold." if low_batt else None,
        "error": None,
    }


def build_home_assistant_payload(base_url: str | None = None) -> dict[str, Any]:
    """Returns flat Home Assistant REST sensors, prevent-sleep switch state, and copyable YAML."""
    origin = (base_url or f"http://127.0.0.1:{PORT}").rstrip("/")
    vitals = {}
    try:
        vitals = system_vitals.get_system_vitals().get_json(silent=True) or {}
    except Exception:
        vitals = {}
    storage = vitals.get("storage") or {}
    ssd = storage.get("ssd") or {}
    hdd = storage.get("hdd") or {}

    snap = backup_health.read_status(BACKUP_STATUS_FILE)
    b_summary = backup_health.summarize(snap, running=False)
    sleep_data = {}
    try:
        sleep_data = sleep_guard.get_sleep_status().get_json(silent=True) or {}
    except Exception:
        sleep_data = {}

    with telemetry_lock:
        cpu_temp = telemetry_state.get("cpu", {}).get("temp_c")

    ups = probe_ups_nut()

    sensors = {
        "disk_root_pct": ssd.get("percent"),
        "disk_pool_pct": hdd.get("percent"),
        "disk_pool_free_gb": hdd.get("free_gb"),
        "backup_state": b_summary.get("state") or "unknown",
        "backup_age_hours": b_summary.get("age_hours"),
        "sleep_enabled": bool(sleep_data.get("enabled")),
        "sleep_skip_tonight": bool(sleep_data.get("skip_tonight")),
        "cpu_temp_c": cpu_temp,
        "ups_status": ups.get("status"),
        "ups_battery_charge": ups.get("battery_charge"),
    }

    yaml_snippet = f"""rest:
  - resource: "{origin}/api/integrations/homeassistant"
    scan_interval: 60
    headers:
      Authorization: "Bearer <YOUR_READ_ONLY_TOKEN>"
    sensor:
      - name: "Homelab Pool Usage"
        unit_of_measurement: "%"
        value_template: "{{{{ value_json.sensors.disk_pool_pct }}}}"
      - name: "Homelab Backup State"
        value_template: "{{{{ value_json.sensors.backup_state }}}}"
      - name: "Homelab Sleep Skip"
        value_template: "{{{{ value_json.sensors.sleep_skip_tonight }}}}"

rest_command:
  homelab_toggle_prevent_sleep:
    url: "{origin}/api/sleep/toggle"
    method: POST
    headers:
      Authorization: "Bearer <YOUR_FULL_ACCESS_TOKEN>"
      Content-Type: "application/json"
"""

    return {
        "status": "ok",
        "sensors": sensors,
        "ups": ups,
        "endpoints": {
            "sensors": f"{origin}/api/integrations/homeassistant",
            "sleep_toggle": f"{origin}/api/sleep/toggle",
            "ups": f"{origin}/api/integrations/ups",
        },
        "yaml_snippet": yaml_snippet,
    }


@integrations_bp.route("/api/integrations/homeassistant", methods=["GET"])
def api_homeassistant():
    """Returns Home Assistant sensor values and copyable configuration.yaml snippet."""
    base = request.host_url.rstrip("/") if request.host_url else None
    return jsonify(build_home_assistant_payload(base_url=base))


@integrations_bp.route("/api/integrations/ups", methods=["GET"])
def api_ups_status():
    """Returns local NUT (`upsc`) battery state and low-battery shutdown warning."""
    return jsonify({"status": "ok", **probe_ups_nut()})

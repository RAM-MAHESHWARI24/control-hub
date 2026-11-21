"""
Widget: Android TV auto-updater
Orchestrates silent ADB sideload deployments (SmartTube, CloudStream Beta; official releases only),
tracks hardware model discovery across dynamic DHCP subnets, inspects foreground app status,
and provides granular controls including force-update overrides.
"""

import json
import os
import subprocess
import sys
import threading
import time

from flask import Blueprint, jsonify, request

from config import (
    TV_UPDATER_CRON_FILE,
    TV_UPDATER_DIR,
    TV_UPDATER_LOCAL_LOG_FILE,
    TV_UPDATER_LOG_FILE,
    TV_UPDATER_PY,
    TV_UPDATER_STATE_FILE,
    get_tz_abbr,
)

# Ensure tv-updater directory is in sys.path for direct python imports and
# align TV_AUTOUPDATER_* env vars with the paths configured for control-hub.
if TV_UPDATER_DIR and TV_UPDATER_DIR not in sys.path and os.path.exists(TV_UPDATER_DIR):
    sys.path.insert(0, TV_UPDATER_DIR)
if TV_UPDATER_STATE_FILE:
    os.environ.setdefault("TV_AUTOUPDATER_STATE_DIR", os.path.dirname(TV_UPDATER_STATE_FILE))
if TV_UPDATER_LOG_FILE:
    os.environ.setdefault("TV_AUTOUPDATER_LOG", TV_UPDATER_LOG_FILE)
_default_tv_cfg = os.path.join(os.getenv("HOMELAB_ETC_DIR", "/etc/homelab"), "tv-autoupdater.json")
if os.path.isfile(_default_tv_cfg):
    os.environ.setdefault("TV_AUTOUPDATER_CONFIG", _default_tv_cfg)


def tv_module_installed() -> bool:
    """The TV auto-updater is optional; without it the dashboard hides the TV card."""
    return bool(TV_UPDATER_PY) and os.path.isfile(TV_UPDATER_PY)


NOT_INSTALLED = {
    "success": False,
    "installed": False,
    "message": "TV auto-updater is not installed (set TV_UPDATER_PY).",
}

try:
    import tv_updater
except Exception:
    tv_updater = None

tv_updater_bp = Blueprint("tv_updater", __name__)

tv_deploy_lock = threading.Lock()
is_deploying_tv = False

# Background refresh cache so HTTP GET never stalls on sleeping TVs over ADB
_telemetry_lock = threading.Lock()
_telemetry_refreshing = False
TELEMETRY_TTL_SEC = 30.0
telemetry_cache = {
    "data": None,
    "last_fetched": 0.0,
}


def get_tv_schedule_text(tz_abbr: str = None) -> str:
    """Reads actual cron cadence from /etc/cron.d/tv-autoupdater when present."""
    tz = tz_abbr or get_tz_abbr()
    if TV_UPDATER_CRON_FILE and os.path.isfile(TV_UPDATER_CRON_FILE):
        try:
            with open(TV_UPDATER_CRON_FILE, "r", encoding="utf-8", errors="replace") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#") or "tv_updater.py" not in line:
                        continue
                    parts = line.split()
                    if len(parts) >= 5:
                        m_field, h_field = parts[0], parts[1]
                        if m_field.startswith("*/") and m_field[2:].isdigit():
                            interval = int(m_field[2:])
                            if "-" in h_field:
                                lo, hi = h_field.split("-", 1)
                                return f"Every {interval} min ({int(lo):02d}:00 - {int(hi):02d}:59 {tz})"
                            return f"Every {interval} min ({tz})"
                        if m_field.isdigit() and h_field.isdigit():
                            return f"Daily at {int(h_field):02d}:{int(m_field):02d} {tz}"
                        return f"Cron ({m_field} {h_field}) {tz}"
        except Exception:
            pass
    return "Not scheduled"


def get_preferred_log_file():
    """Returns the most active/recently updated log file path."""
    if TV_UPDATER_LOG_FILE and os.path.exists(TV_UPDATER_LOG_FILE):
        return TV_UPDATER_LOG_FILE
    if TV_UPDATER_LOCAL_LOG_FILE and os.path.exists(TV_UPDATER_LOCAL_LOG_FILE):
        return TV_UPDATER_LOCAL_LOG_FILE
    return TV_UPDATER_LOG_FILE


def run_tv_deployment_thread(args_list):
    """Executes tv_updater.py with given arguments in background thread."""
    global is_deploying_tv
    with tv_deploy_lock:
        is_deploying_tv = True
        try:
            cmd = ["python3", TV_UPDATER_PY] + args_list
            subprocess.run(cmd, check=False, timeout=600)
        except Exception:
            pass
        finally:
            is_deploying_tv = False
            with _telemetry_lock:
                telemetry_cache["last_fetched"] = 0.0


def _refresh_telemetry_sync() -> dict:
    """Runs tv_updater.get_cluster_telemetry(fast_probe=True) and updates cache."""
    now = time.time()
    if tv_updater:
        try:
            data = tv_updater.get_cluster_telemetry(fast_probe=True)
            data["available"] = True
            with _telemetry_lock:
                telemetry_cache["data"] = data
                telemetry_cache["last_fetched"] = now
            return data
        except Exception:
            pass

    data = {
        "available": False,
        "status": "unknown",
        "all_up_to_date": False,
        "pending_updates_count": 0,
        "total_devices": 0,
        "online_devices": 0,
        "last_upstream_check": 0,
        "last_upstream_check_str": "Unknown",
        "devices": [],
        "upstream_apps": {},
        "incoming_apks": [],
        "schedule": get_tv_schedule_text(),
    }
    if TV_UPDATER_STATE_FILE and os.path.exists(TV_UPDATER_STATE_FILE):
        try:
            with open(TV_UPDATER_STATE_FILE, "r", encoding="utf-8") as f:
                st = json.load(f)
                data["last_upstream_check"] = st.get("last_upstream_check", 0)
                data["upstream_apps"] = st.get("upstream_apps", {})
        except Exception:
            pass
    return data


def _kick_background_refresh() -> None:
    global _telemetry_refreshing
    with _telemetry_lock:
        if _telemetry_refreshing:
            return
        _telemetry_refreshing = True

    def _worker():
        global _telemetry_refreshing
        try:
            _refresh_telemetry_sync()
        finally:
            with _telemetry_lock:
                _telemetry_refreshing = False

    threading.Thread(target=_worker, name="tv-telemetry-refresh", daemon=True).start()


def fetch_telemetry_snapshot(force=False):
    """
    Fetches cluster telemetry without stalling regular polling requests.
    - Fresh cache (< 30s): returned immediately.
    - Stale cache & not forced: returns cached data immediately and refreshes asynchronously.
    - Empty cache or force=True: refreshes synchronously.
    """
    now = time.time()
    with _telemetry_lock:
        cached = telemetry_cache["data"]
        age = now - telemetry_cache["last_fetched"]

    if not force and cached is not None:
        if age >= TELEMETRY_TTL_SEC and tv_updater is not None:
            _kick_background_refresh()
        return cached

    return _refresh_telemetry_sync()


@tv_updater_bp.route("/api/tv-updater/status", methods=["GET"])
def get_tv_updater_status():
    """Returns cluster deployment status, active stage, and device telemetry."""
    if not tv_module_installed():
        return jsonify({"installed": False, "status": "not_installed", "status_text": "Not installed"})
    force = request.args.get("refresh", "false").lower() == "true"
    is_deploying = is_deploying_tv

    if not is_deploying:
        try:
            res = subprocess.run(
                ["pgrep", "-f", r"/tv_updater\.py(\s|$)"],
                stdout=subprocess.PIPE,
                text=True,
                timeout=1.2,
            )
            lines = res.stdout.strip().splitlines()
            if lines and any(int(pid) != os.getpid() for pid in lines if pid.isdigit()):
                is_deploying = True
        except Exception:
            pass

    telemetry = fetch_telemetry_snapshot(force=force)
    devices = telemetry.get("devices") or []
    total_devices = len(devices)
    online_devices = sum(1 for d in devices if d.get("is_online"))

    stage_labels = {
        1: "1. Upstream Sync",
        2: "2. Subnet Discovery",
        3: "3. Safety Guard",
        4: "4. ADB Silent Push",
    }

    log_file = get_preferred_log_file()
    last_run_msg = "Cluster ready" if total_devices > 0 else "No TV telemetry available"
    current_stage = 4 if total_devices > 0 else 0
    is_error = False

    if log_file and os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                recent_lines = f.readlines()[-40:]

            # Scan newest -> oldest and stop at the first definitive boundary of the latest run
            # so historical resolved errors do not permanently lock the card in red.
            for line in reversed(recent_lines):
                line_str = line.strip()
                if not line_str:
                    continue
                if "[ERROR]" in line_str or "Failed to install" in line_str:
                    is_error = True
                    last_run_msg = line_str.split("[ERROR]")[-1].strip()
                    break
                if (
                    "completely up to date" in line_str
                    or "Zero pending tasks" in line_str
                    or "Daily Upstream Sync complete" in line_str
                ):
                    current_stage = 4
                    last_run_msg = line_str.split("[INFO]")[-1].strip()
                    break
                if "Successfully installed" in line_str or "Successfully deployed" in line_str:
                    current_stage = 4
                    last_run_msg = line_str.split("[INFO]")[-1].strip()
                    break
                if "Installing" in line_str:
                    current_stage = 4
                    last_run_msg = line_str.split("[INFO]")[-1].strip()
                    break
                if "Skipping installation" in line_str or "Postponing:" in line_str or "Safety" in line_str:
                    current_stage = 3
                    last_run_msg = line_str.split("[INFO]")[-1].strip()
                    break
                if "Pending TV(s)" in line_str or "Auto-Discovered" in line_str or "Discovered Online" in line_str:
                    current_stage = 2
                    last_run_msg = line_str.split("[INFO]")[-1].strip()
                    break
                if "Initiating Daily Upstream Sync" in line_str or "Downloading from" in line_str:
                    current_stage = 1
                    last_run_msg = line_str.split("[INFO]")[-1].strip()
                    break
        except Exception:
            pass

    if is_deploying:
        overall_status = "deploying"
        status_text = "Deploying Updates..."
    elif is_error:
        overall_status = "error"
        status_text = "Install Attention"
    elif total_devices == 0:
        overall_status = "unknown"
        status_text = "No TVs Configured"
    elif telemetry.get("all_up_to_date"):
        overall_status = "synced"
        status_text = "Cluster Up to Date"
        current_stage = 4
        last_run_msg = f"All target TVs up to date ({online_devices}/{total_devices} Online)"
    else:
        pending_cnt = telemetry.get("pending_updates_count", 0)
        overall_status = "pending"
        status_text = f"{pending_cnt} Update{'s' if pending_cnt != 1 else ''} Pending"

    return jsonify({
        "installed": True,
        "available": telemetry.get("available", total_devices > 0),
        "status": overall_status,
        "status_text": status_text,
        "is_deploying": is_deploying,
        "current_stage": current_stage,
        "current_stage_label": stage_labels.get(current_stage, "Not Verified"),
        "all_up_to_date": bool(total_devices > 0 and telemetry.get("all_up_to_date", False)),
        "pending_updates_count": telemetry.get("pending_updates_count", 0),
        "total_devices": total_devices,
        "online_devices": online_devices,
        "last_upstream_check": telemetry.get("last_upstream_check", 0),
        "last_upstream_check_str": telemetry.get("last_upstream_check_str", "Unknown"),
        "devices": devices,
        "upstream_apps": telemetry.get("upstream_apps", {}),
        "incoming_apks": telemetry.get("incoming_apks", []),
        "log_file": log_file,
        "message": last_run_msg,
        "schedule": get_tv_schedule_text(),
    })


@tv_updater_bp.route("/api/tv-updater/deploy", methods=["POST"])
def trigger_tv_deployment():
    """Triggers opportunistic or forced deployment across all target TVs."""
    if not tv_module_installed():
        return jsonify(NOT_INSTALLED), 404
    if is_deploying_tv:
        return jsonify({"success": False, "message": "Deployment is already in progress..."})

    req_data = request.get_json(silent=True) or {}
    force_install = bool(req_data.get("force", False))
    force_reinstall = bool(req_data.get("force_reinstall", False))
    device_id = req_data.get("device_id")
    package = req_data.get("package")

    args = []
    if force_install:
        args.append("--force")
    if force_reinstall:
        args.append("--force-reinstall")
    if device_id:
        args.extend(["--device", device_id])
    if package:
        args.extend(["--package", package])

    t = threading.Thread(target=run_tv_deployment_thread, args=(args,), daemon=True)
    t.start()
    return jsonify({
        "success": True,
        "message": "Android TV deployment started in background" + (" (Force mode enabled)" if force_install else "."),
    })


@tv_updater_bp.route("/api/tv-updater/sync-upstream", methods=["POST"])
def trigger_upstream_sync():
    """Forces an immediate daily upstream check against GitHub and official releases."""
    if not tv_module_installed():
        return jsonify(NOT_INSTALLED), 404
    if is_deploying_tv:
        return jsonify({"success": False, "message": "Another task is already in progress..."})

    t = threading.Thread(target=run_tv_deployment_thread, args=(["--sync"],), daemon=True)
    t.start()
    return jsonify({"success": True, "message": "Upstream release check initiated from GitHub & endpoints."})


@tv_updater_bp.route("/api/tv-updater/install-app", methods=["POST"])
def trigger_single_app_install():
    """Granular action: installs/updates a specific app on a specific TV with force support."""
    if not tv_module_installed():
        return jsonify(NOT_INSTALLED), 404
    req_data = request.get_json(silent=True) or {}
    device_id = req_data.get("device_id")
    package = req_data.get("package")
    force = bool(req_data.get("force", False))

    if not device_id or not package:
        return jsonify({"success": False, "message": "device_id and package are required."}), 400

    def run_direct():
        global is_deploying_tv
        with tv_deploy_lock:
            is_deploying_tv = True
            try:
                if tv_updater:
                    tv_updater.deploy_single_app(device_id, package, force=force)
                else:
                    cmd = ["python3", TV_UPDATER_PY, "--device", device_id, "--package", package]
                    if force:
                        cmd.append("--force")
                    subprocess.run(cmd, check=False, timeout=300)
            finally:
                is_deploying_tv = False
                with _telemetry_lock:
                    telemetry_cache["last_fetched"] = 0.0

    t = threading.Thread(target=run_direct, daemon=True)
    t.start()
    return jsonify({
        "success": True,
        "message": f"Deployment for '{package}' on '{device_id}' started"
        + (" (Force Mode: will update even if in foreground)" if force else "."),
    })


@tv_updater_bp.route("/api/tv-updater/devices/<device_id>/nickname", methods=["PUT"])
def set_tv_nickname(device_id):
    """Gives a TV a name of the user's choice; an empty name goes back to the detected model."""
    if not tv_module_installed() or tv_updater is None:
        return jsonify(NOT_INSTALLED), 404
    body = request.get_json(silent=True) or {}
    try:
        stored = tv_updater.set_nickname(device_id, body.get("nickname", ""))
    except KeyError:
        return jsonify({"success": False, "message": f"Unknown TV '{device_id}'."}), 404
    except ValueError as exc:
        return jsonify({"success": False, "message": str(exc)}), 400
    except OSError as exc:
        return jsonify({"success": False, "message": f"Could not save the name: {exc}"}), 500
    with _telemetry_lock:
        telemetry_cache["last_fetched"] = 0.0
    return jsonify({"success": True, "device_id": device_id, "nickname": stored})


@tv_updater_bp.route("/api/tv-updater/push-incoming", methods=["POST"])
def trigger_push_incoming():
    """Pushes manual APK drops from incoming_apks/ to all online target TVs."""
    if not tv_module_installed():
        return jsonify(NOT_INSTALLED), 404
    if is_deploying_tv:
        return jsonify({"success": False, "message": "Another task is already in progress..."})

    t = threading.Thread(target=run_tv_deployment_thread, args=(["--push-incoming"],), daemon=True)
    t.start()
    return jsonify({"success": True, "message": "Pushing incoming sideload APKs to online TVs..."})


@tv_updater_bp.route("/api/tv-updater/log", methods=["GET"])
def get_tv_updater_log():
    """Returns the tail of the updater log for the 1-click modal."""
    log_file = get_preferred_log_file()
    if not log_file or not os.path.exists(log_file):
        return jsonify({"log_file": log_file, "log": f"Log file ({log_file}) not found or empty."})

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return jsonify({
                "log_file": log_file,
                "log": "".join(lines[-150:]),
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

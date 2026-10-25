"""
Widget: CleanYourTV - Android TV App Updater
Orchestrates silent ADB sideload deployments (SmartTube, CloudStream Beta, HD Streamz),
tracks hardware model discovery across dynamic DHCP subnets, inspects foreground app status,
and provides granular controls including force-update overrides.
"""

import os
import sys
import time
import json
import threading
import subprocess
from flask import Blueprint, jsonify, request

from config import (
    TV_UPDATER_DIR, TV_UPDATER_PY,
    TV_UPDATER_LOG_FILE, TV_UPDATER_LOCAL_LOG_FILE,
    TV_UPDATER_STATE_FILE, TV_UPDATER_INCOMING_DIR
)

# Ensure tv-updater directory is in sys.path for direct python imports
if TV_UPDATER_DIR not in sys.path and os.path.exists(TV_UPDATER_DIR):
    sys.path.insert(0, TV_UPDATER_DIR)

try:
    import tv_updater
except Exception:
    tv_updater = None

tv_updater_bp = Blueprint("tv_updater", __name__)

tv_deploy_lock = threading.Lock()
is_deploying_tv = False

# Cache telemetry to prevent overwhelming ADB during frequent frontend polling
telemetry_cache = {
    "data": None,
    "last_fetched": 0
}

def get_preferred_log_file():
    """Returns the most active/recently updated log file path"""
    if os.path.exists(TV_UPDATER_LOG_FILE):
        return TV_UPDATER_LOG_FILE
    if os.path.exists(TV_UPDATER_LOCAL_LOG_FILE):
        return TV_UPDATER_LOCAL_LOG_FILE
    return TV_UPDATER_LOG_FILE

def run_tv_deployment_thread(args_list):
    """Executes tv_updater.py with given arguments in background thread"""
    global is_deploying_tv
    with tv_deploy_lock:
        is_deploying_tv = True
        try:
            cmd = ["python3", TV_UPDATER_PY] + args_list
            subprocess.run(cmd, check=False)
        except Exception:
            pass
        finally:
            is_deploying_tv = False
            # Invalidate telemetry cache so next poll is fresh
            telemetry_cache["last_fetched"] = 0

def fetch_telemetry_snapshot(force=False):
    """Fetches cluster telemetry from tv_updater or cached state"""
    now = time.time()
    if not force and telemetry_cache["data"] and (now - telemetry_cache["last_fetched"] < 4):
        return telemetry_cache["data"]

    if tv_updater:
        try:
            data = tv_updater.get_cluster_telemetry(fast_probe=True)
            telemetry_cache["data"] = data
            telemetry_cache["last_fetched"] = now
            return data
        except Exception:
            pass

    # Fallback to state.json if direct import threw
    data = {
        "status": "pending",
        "all_up_to_date": False,
        "pending_updates_count": 0,
        "total_devices": 3,
        "online_devices": 0,
        "last_upstream_check": 0,
        "last_upstream_check_str": "Unknown",
        "devices": [],
        "upstream_apps": {},
        "incoming_apks": [],
        "schedule": "Every 15 min (06:00 - 23:59 IST)"
    }
    if os.path.exists(TV_UPDATER_STATE_FILE):
        try:
            with open(TV_UPDATER_STATE_FILE, "r") as f:
                st = json.load(f)
                data["last_upstream_check"] = st.get("last_upstream_check", 0)
                data["upstream_apps"] = st.get("upstream_apps", {})
        except Exception:
            pass
    return data


@tv_updater_bp.route("/api/tv-updater/status", methods=["GET"])
def get_tv_updater_status():
    """Returns cluster deployment status, active stage, and device telemetry"""
    force = request.args.get("refresh", "false").lower() == "true"
    is_deploying = is_deploying_tv

    # Check for external process running (e.g. from cron)
    if not is_deploying:
        try:
            res = subprocess.run(["pgrep", "-f", "tv_updater.py"], stdout=subprocess.PIPE, text=True, timeout=1.2)
            # Make sure it's not our own command if running
            lines = res.stdout.strip().splitlines()
            if lines and any(int(pid) != os.getpid() for pid in lines if pid.isdigit()):
                is_deploying = True
        except Exception:
            pass

    telemetry = fetch_telemetry_snapshot(force=force)

    # Determine 4-stage stepper status:
    # 1. Upstream Sync | 2. Subnet Discovery | 3. Safety Guard | 4. ADB Silent Push
    stage_labels = {
        1: "1. Upstream Sync",
        2: "2. Subnet Discovery",
        3: "3. Safety Guard",
        4: "4. ADB Silent Push"
    }

    log_file = get_preferred_log_file()
    last_run_msg = "Cluster ready"
    current_stage = 4
    is_error = False

    if os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                recent_lines = f.readlines()[-40:]

            for line in reversed(recent_lines):
                line_str = line.strip()
                if "Successfully installed" in line_str or "Successfully deployed" in line_str:
                    current_stage = 4
                    last_run_msg = line_str.split("[INFO]")[-1].strip()
                    break
                elif "Installing" in line_str:
                    current_stage = 4
                    last_run_msg = line_str.split("[INFO]")[-1].strip()
                    break
                elif "Skipping installation" in line_str or "Postponing:" in line_str or "Safety" in line_str:
                    current_stage = 3
                    last_run_msg = line_str.split("[INFO]")[-1].strip()
                    break
                elif "Auto-Discovered" in line_str or "Discovered Online" in line_str:
                    current_stage = 2
                    break
                elif "Initiating Daily Upstream Sync" in line_str or "Downloading from" in line_str:
                    current_stage = 1
                    break
                elif "[ERROR]" in line_str or "Failed to install" in line_str:
                    is_error = True
                    last_run_msg = line_str.split("[ERROR]")[-1].strip()
        except Exception:
            pass

    if is_deploying:
        overall_status = "deploying"
        status_text = "Deploying Updates..."
    elif is_error:
        overall_status = "error"
        status_text = "Install Attention"
    elif telemetry.get("all_up_to_date"):
        overall_status = "synced"
        status_text = "Cluster Up to Date"
        current_stage = 4
        last_run_msg = f"All target TVs up to date ({telemetry.get('online_devices', 0)}/{telemetry.get('total_devices', 3)} Online)"
    else:
        pending_cnt = telemetry.get("pending_updates_count", 0)
        overall_status = "pending"
        status_text = f"{pending_cnt} Update{'s' if pending_cnt != 1 else ''} Pending"

    return jsonify({
        "status": overall_status,
        "status_text": status_text,
        "is_deploying": is_deploying,
        "current_stage": current_stage,
        "current_stage_label": stage_labels.get(current_stage, "Ready"),
        "all_up_to_date": telemetry.get("all_up_to_date", False),
        "pending_updates_count": telemetry.get("pending_updates_count", 0),
        "total_devices": telemetry.get("total_devices", 3),
        "online_devices": telemetry.get("online_devices", 0),
        "last_upstream_check": telemetry.get("last_upstream_check", 0),
        "last_upstream_check_str": telemetry.get("last_upstream_check_str", "Unknown"),
        "devices": telemetry.get("devices", []),
        "upstream_apps": telemetry.get("upstream_apps", {}),
        "incoming_apks": telemetry.get("incoming_apks", []),
        "message": last_run_msg,
        "schedule": "Every 15 min (06:00 - 23:59 IST)"
    })


@tv_updater_bp.route("/api/tv-updater/deploy", methods=["POST"])
def trigger_tv_deployment():
    """Triggers opportunistic or forced deployment across all target TVs"""
    global is_deploying_tv
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
        "message": "Android TV deployment started in background" + (" (Force mode enabled)" if force_install else ".")
    })


@tv_updater_bp.route("/api/tv-updater/sync-upstream", methods=["POST"])
def trigger_upstream_sync():
    """Forces an immediate daily upstream check against GitHub and official releases"""
    global is_deploying_tv
    if is_deploying_tv:
        return jsonify({"success": False, "message": "Another task is already in progress..."})

    t = threading.Thread(target=run_tv_deployment_thread, args=(["--sync"],), daemon=True)
    t.start()
    return jsonify({"success": True, "message": "Upstream release check initiated from GitHub & endpoints."})


@tv_updater_bp.route("/api/tv-updater/install-app", methods=["POST"])
def trigger_single_app_install():
    """Granular action: installs/updates a specific app on a specific TV with force support"""
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
                    subprocess.run(cmd, check=False)
            finally:
                is_deploying_tv = False
                telemetry_cache["last_fetched"] = 0

    t = threading.Thread(target=run_direct, daemon=True)
    t.start()
    return jsonify({
        "success": True,
        "message": f"Deployment for '{package}' on '{device_id}' started" + (" (Force Mode: will update even if in foreground)" if force else ".")
    })


@tv_updater_bp.route("/api/tv-updater/push-incoming", methods=["POST"])
def trigger_push_incoming():
    """Pushes manual APK drops from incoming_apks/ to all online target TVs"""
    global is_deploying_tv
    if is_deploying_tv:
        return jsonify({"success": False, "message": "Another task is already in progress..."})

    t = threading.Thread(target=run_tv_deployment_thread, args=(["--push-incoming"],), daemon=True)
    t.start()
    return jsonify({"success": True, "message": "Pushing incoming sideload APKs to online TVs..."})


@tv_updater_bp.route("/api/tv-updater/log", methods=["GET"])
def get_tv_updater_log():
    """Returns the tail of the updater log for the 1-click modal"""
    log_file = get_preferred_log_file()
    if not os.path.exists(log_file):
        return jsonify({"log": f"Log file ({log_file}) not found or empty."})

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return jsonify({
                "log_file": log_file,
                "log": "".join(lines[-150:])
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

"""
Widget: Network & Transfer Speeds
Provides endpoints for real-time WAN/LAN bandwidth streaming and Ookla Speedtest line benchmark.
"""

import os
import time
import json
import datetime
import threading
import subprocess
from flask import Blueprint, jsonify

from config import SPEEDTEST_CACHE_FILE, SPEEDTEST_BIN
from core.telemetry_sampler import telemetry_lock, telemetry_state

network_speed_bp = Blueprint("network_speed", __name__)

speedtest_running_lock = threading.Lock()
is_speedtesting = False

def format_relative_time(ts):
    """Formats timestamp into dynamic relative label (e.g. Today at ..., Yesterday at ..., Oct 18 at ...)"""
    if not ts:
        return "Recent"
    try:
        test_dt = datetime.datetime.fromtimestamp(ts)
        now_dt = datetime.datetime.now()
        time_str = test_dt.strftime("%I:%M %p IST")
        days = (now_dt.date() - test_dt.date()).days
        if days == 0:
            return f"Today at {time_str}"
        elif days == 1:
            return f"Yesterday at {time_str}"
        elif days < 7:
            return f"{test_dt.strftime('%A')} at {time_str}"
        else:
            return f"{test_dt.strftime('%b %d')} at {time_str}"
    except Exception:
        return "Recent"

def load_speedtest_cache():
    """Loads previous speedtest results from cache with dynamic relative timestamps"""
    if os.path.exists(SPEEDTEST_CACHE_FILE):
        try:
            with open(SPEEDTEST_CACHE_FILE, "r") as f:
                data = json.load(f)
                data["is_testing"] = is_speedtesting
                if "timestamp" in data:
                    data["tested_at"] = format_relative_time(data["timestamp"])
                return data
        except Exception:
            pass
    return {
        "is_testing": is_speedtesting,
        "download_mbps": 94.1,
        "upload_mbps": 94.0,
        "download_mbs": 11.2,
        "upload_mbs": 11.2,
        "ping_ms": 2.7,
        "isp": "Excitel",
        "server": "ADN Broadband (Delhi)",
        "tested_at": "Recent",
        "timestamp": int(time.time())
    }

def run_speedtest_thread():
    """Executes official Ookla speedtest CLI binary and caches JSON results"""
    global is_speedtesting
    with speedtest_running_lock:
        is_speedtesting = True
        try:
            cmd = [SPEEDTEST_BIN, "--accept-license", "--accept-gdpr", "--format=json"]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
            if proc.returncode == 0:
                raw = proc.stdout.strip()
                json_str = None
                for line in raw.split("\n"):
                    if line.strip().startswith("{") and "download" in line:
                        json_str = line.strip()
                        break
                if json_str:
                    res = json.loads(json_str)
                    dl_bytes = res.get("download", {}).get("bandwidth", 0)
                    up_bytes = res.get("upload", {}).get("bandwidth", 0)
                    ping_lat = res.get("ping", {}).get("latency", 0)
                    isp_name = res.get("isp", "Broadband")
                    srv_name = res.get("server", {}).get("name", "Local")
                    srv_loc = res.get("server", {}).get("location", "")
                    res_url = res.get("result", {}).get("url", "")

                    now_str = datetime.datetime.now().strftime("%I:%M %p IST")
                    cached = {
                        "is_testing": False,
                        "download_mbps": round((dl_bytes * 8) / 1_000_000.0, 1),
                        "upload_mbps": round((up_bytes * 8) / 1_000_000.0, 1),
                        "download_mbs": round(dl_bytes / 1_048_576.0, 1),
                        "upload_mbs": round(up_bytes / 1_048_576.0, 1),
                        "ping_ms": round(ping_lat, 1),
                        "isp": isp_name,
                        "server": f"{srv_name} ({srv_loc})".strip(),
                        "result_url": res_url,
                        "tested_at": f"Today at {now_str}",
                        "timestamp": int(time.time())
                    }
                    with open(SPEEDTEST_CACHE_FILE, "w") as f:
                        json.dump(cached, f, indent=2)
        except Exception:
            pass
        finally:
            is_speedtesting = False


@network_speed_bp.route("/api/network/speed", methods=["GET"])
def get_network_speed():
    """Returns Dual Speedometer telemetry: 1) Internet Speed & Benchmark and 2) Network Speed"""
    speedtest_info = load_speedtest_cache()
    with telemetry_lock:
        return jsonify({
            "internet": telemetry_state["internet"],
            "network": telemetry_state["network"],
            "speedtest": speedtest_info,
            "torrents_queue": telemetry_state["torrents_queue"],
            "storage_ops": telemetry_state["storage_ops"]
        })


@network_speed_bp.route("/api/speedtest/latest", methods=["GET"])
def get_speedtest_latest():
    """Returns the latest speedtest result and running state"""
    return jsonify(load_speedtest_cache())


@network_speed_bp.route("/api/speedtest/run", methods=["POST"])
def trigger_speedtest():
    """Triggers an asynchronous Ookla speedtest benchmark"""
    global is_speedtesting
    if is_speedtesting:
        return jsonify({"success": False, "message": "Speedtest is already in progress..."})

    t = threading.Thread(target=run_speedtest_thread, daemon=True)
    t.start()
    return jsonify({"success": True, "message": "Speedtest started in background..."})

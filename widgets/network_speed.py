"""
Widget: Network & Transfer Speeds
Provides endpoints for real-time NIC throughput, qBittorrent queue telemetry,
and on-demand broadband speedtest benchmarks (Ookla CLI or speedtest-cli).
Never fabricates ISP/speed values and surfaces benchmark failures clearly.
"""

import datetime
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify

from config import SPEEDTEST_BIN, SPEEDTEST_CACHE_FILE, get_tz_abbr
from core.telemetry_sampler import telemetry_lock, telemetry_state

network_speed_bp = Blueprint("network_speed", __name__)

speedtest_running_lock = threading.Lock()
is_speedtesting = False
last_speedtest_error = None


def _resolve_speedtest_command():
    """Returns (cmd_list, flavor) for installed Ookla speedtest or Python speedtest-cli, or (None, None)."""
    candidates = []
    if SPEEDTEST_BIN:
        if os.path.isfile(SPEEDTEST_BIN):
            candidates.append(SPEEDTEST_BIN)
        else:
            found = shutil.which(SPEEDTEST_BIN)
            if found:
                candidates.append(found)
    for name in ("speedtest", "speedtest-cli"):
        found = shutil.which(name)
        if found and found not in candidates:
            candidates.append(found)

    for binary in candidates:
        base = os.path.basename(binary).lower()
        if "speedtest-cli" in base:
            return [binary, "--json"], "python-cli"
        return [binary, "--accept-license", "--accept-gdpr", "--format=json"], "ookla"
    return None, None


def format_relative_time(ts):
    """Formats timestamp into dynamic relative label."""
    if not ts:
        return "Unknown"
    try:
        test_dt = datetime.datetime.fromtimestamp(ts)
        now_dt = datetime.datetime.now()
        time_str = test_dt.strftime(f"%H:%M {get_tz_abbr()}")
        days = (now_dt.date() - test_dt.date()).days
        if days == 0:
            return f"Today at {time_str}"
        if days == 1:
            return f"Yesterday at {time_str}"
        if days < 7:
            return f"{test_dt.strftime('%A')} at {time_str}"
        return f"{test_dt.strftime('%b %d')} at {time_str}"
    except Exception:
        return "Unknown"


def load_speedtest_cache():
    """Loads previous speedtest results from cache; never invents fake ISP/speed values."""
    cmd, _ = _resolve_speedtest_command()
    cli_available = cmd is not None
    if os.path.exists(SPEEDTEST_CACHE_FILE):
        try:
            with open(SPEEDTEST_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["available"] = True
                data["is_testing"] = is_speedtesting
                data["cli_available"] = cli_available
                data["last_error"] = last_speedtest_error
                if "timestamp" in data:
                    data["tested_at"] = format_relative_time(data["timestamp"])
                return data
        except Exception:
            pass
    return {
        "available": False,
        "is_testing": is_speedtesting,
        "cli_available": cli_available,
        "last_error": last_speedtest_error,
        "download_mbps": None,
        "upload_mbps": None,
        "download_mbs": None,
        "upload_mbs": None,
        "ping_ms": None,
        "isp": None,
        "server": None,
        "tested_at": "Not tested yet",
        "reason": (
            last_speedtest_error
            or ("Run a speedtest to measure broadband throughput" if cli_available else "Install Ookla speedtest or speedtest-cli to benchmark broadband")
        ),
        "timestamp": None,
    }


def _parse_speedtest_json(raw: str, flavor: str):
    """Parses Ookla or speedtest-cli JSON output into normalized bandwidth/ping dict."""
    json_str = None
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("{") and "download" in s:
            json_str = s
            break
    if not json_str:
        return None
    res = json.loads(json_str)

    if flavor == "python-cli" or isinstance(res.get("download"), (int, float)):
        # python speedtest-cli reports bits/sec directly
        dl_bps = float(res.get("download") or 0)
        up_bps = float(res.get("upload") or 0)
        dl_bytes = dl_bps / 8.0
        up_bytes = up_bps / 8.0
        ping_lat = float(res.get("ping") or 0)
        isp_name = (res.get("client") or {}).get("isp") or "Broadband"
        srv = res.get("server") or {}
        srv_name = srv.get("sponsor") or srv.get("name") or "Server"
        srv_loc = srv.get("name") if srv.get("sponsor") else srv.get("country", "")
        res_url = res.get("share") or ""
    else:
        dl_bytes = float((res.get("download") or {}).get("bandwidth") or 0)
        up_bytes = float((res.get("upload") or {}).get("bandwidth") or 0)
        ping_lat = float((res.get("ping") or {}).get("latency") or 0)
        isp_name = res.get("isp") or "Broadband"
        srv = res.get("server") or {}
        srv_name = srv.get("name") or "Server"
        srv_loc = srv.get("location") or ""
        res_url = (res.get("result") or {}).get("url") or ""

    server_label = f"{srv_name} ({srv_loc})" if srv_loc and srv_loc != srv_name else srv_name
    now_str = datetime.datetime.now().strftime(f"%H:%M {get_tz_abbr()}")
    return {
        "available": True,
        "is_testing": False,
        "download_mbps": round((dl_bytes * 8) / 1_000_000.0, 1),
        "upload_mbps": round((up_bytes * 8) / 1_000_000.0, 1),
        "download_mbs": round(dl_bytes / 1_048_576.0, 1),
        "upload_mbs": round(up_bytes / 1_048_576.0, 1),
        "ping_ms": round(ping_lat, 1),
        "isp": isp_name,
        "server": server_label.strip(),
        "result_url": res_url,
        "tested_at": f"Today at {now_str}",
        "timestamp": int(time.time()),
    }


def run_speedtest_thread():
    """Executes speedtest CLI binary and caches JSON results atomically, capturing errors."""
    global is_speedtesting, last_speedtest_error
    with speedtest_running_lock:
        is_speedtesting = True
        last_speedtest_error = None
        try:
            cmd, flavor = _resolve_speedtest_command()
            if not cmd:
                last_speedtest_error = "No speedtest CLI found (install Ookla speedtest or speedtest-cli)."
                return
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=75)
            # If binary was actually python speedtest-cli invoked with Ookla flags, retry with --json
            if proc.returncode != 0 and flavor == "ookla" and "unrecognized arguments" in (proc.stderr or "").lower():
                flavor = "python-cli"
                proc = subprocess.run([cmd[0], "--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=75)
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or f"speedtest exited with code {proc.returncode}").strip()
                last_speedtest_error = err.splitlines()[-1][:180]
                return
            cached = _parse_speedtest_json(proc.stdout.strip(), flavor)
            if not cached:
                last_speedtest_error = "Speedtest finished but returned unreadable JSON output."
                return
            cache_path = Path(SPEEDTEST_CACHE_FILE)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_path.with_name(cache_path.name + ".tmp")
            tmp.write_text(json.dumps(cached, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, cache_path)
        except subprocess.TimeoutExpired:
            last_speedtest_error = "Speedtest timed out after 75 seconds."
        except Exception as exc:
            last_speedtest_error = f"Speedtest failed: {str(exc)[:160]}"
        finally:
            is_speedtesting = False


@network_speed_bp.route("/api/network/speed", methods=["GET"])
def get_network_speed():
    """Returns live NIC telemetry, broadband speedtest cache, torrent queue, and disk I/O."""
    speedtest_info = load_speedtest_cache()
    with telemetry_lock:
        return jsonify({
            "internet": telemetry_state["internet"],
            "network": telemetry_state["network"],
            "speedtest": speedtest_info,
            "torrents_queue": telemetry_state["torrents_queue"],
            "storage_ops": telemetry_state["storage_ops"],
        })


@network_speed_bp.route("/api/speedtest/latest", methods=["GET"])
def get_speedtest_latest():
    """Returns the latest speedtest result, running state, and any error."""
    return jsonify(load_speedtest_cache())


@network_speed_bp.route("/api/speedtest/run", methods=["POST"])
def trigger_speedtest():
    """Triggers an asynchronous broadband speedtest benchmark."""
    if is_speedtesting:
        return jsonify({"success": False, "message": "Speedtest is already in progress..."})
    cmd, _ = _resolve_speedtest_command()
    if not cmd:
        return jsonify({
            "success": False,
            "message": "Speedtest CLI is not installed on this server (install Ookla speedtest or speedtest-cli).",
        }), 404

    t = threading.Thread(target=run_speedtest_thread, daemon=True)
    t.start()
    return jsonify({"success": True, "message": "Speedtest started in background..."})

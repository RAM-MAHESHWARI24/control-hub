"""
Widget: Hardware Vitals & Storage Headroom
Monitors host CPU load, physical RAM & swap usage, OS SSD capacity,
and secondary storage pool headroom across custom hardware profiles.
"""

import os
import sys
import shutil
import datetime
from pathlib import Path
from flask import Blueprint, jsonify
from core.telemetry_sampler import telemetry_lock, telemetry_state

system_vitals_bp = Blueprint("system_vitals", __name__)

@system_vitals_bp.route("/api/system/vitals", methods=["GET"])
def get_system_vitals():
    """Returns CPU, RAM, Swap, SSD, HDD headroom and uptime"""
    # 1. RAM and Swap from /proc/meminfo (with Windows fallback)
    mem_total_kb = 0
    mem_avail_kb = 0
    swap_total_kb = 0
    swap_free_kb = 0
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total_kb = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    mem_avail_kb = int(line.split()[1])
                elif line.startswith("SwapTotal:"):
                    swap_total_kb = int(line.split()[1])
                elif line.startswith("SwapFree:"):
                    swap_free_kb = int(line.split()[1])
    except Exception:
        pass

    if mem_total_kb == 0 and sys.platform == "win32":
        try:
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ('dwLength', ctypes.c_ulong),
                    ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong),
                    ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong),
                    ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong),
                    ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong)
                ]
            s = MEMORYSTATUSEX()
            s.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
            mem_total_kb = int(s.ullTotalPhys / 1024)
            mem_avail_kb = int(s.ullAvailPhys / 1024)
            swap_total_kb = int(max(0, s.ullTotalPageFile - s.ullTotalPhys) / 1024)
            swap_free_kb = int(max(0, s.ullAvailPageFile - s.ullAvailPhys) / 1024)
        except Exception:
            pass

    mem_used_kb = max(0, mem_total_kb - mem_avail_kb)
    mem_pct = round((mem_used_kb / max(1, mem_total_kb)) * 100, 1)
    swap_used_kb = max(0, swap_total_kb - swap_free_kb)
    swap_pct = round((swap_used_kb / max(1, swap_total_kb)) * 100, 1) if swap_total_kb > 0 else 0.0

    # 2. Disk Storage Vitals
    ssd_stat = shutil.disk_usage("/")
    ssd_total_gb = round(ssd_stat.total / (1024**3), 1)
    ssd_used_gb = round(ssd_stat.used / (1024**3), 1)
    ssd_free_gb = round(ssd_stat.free / (1024**3), 1)
    ssd_pct = round((ssd_stat.used / ssd_stat.total) * 100, 1)

    # Dynamic secondary/media storage path
    data_path = os.getenv("HDD_DATA", "/mnt/hdd/data")
    if "/data" in data_path and data_path != "/data":
        candidate_mount = data_path.rsplit("/data", 1)[0]
    else:
        candidate_mount = data_path

    if os.path.exists(candidate_mount):
        data_mount = candidate_mount
    elif os.path.exists(data_path):
        data_mount = data_path
    elif os.path.exists("/mnt/hdd"):
        data_mount = "/mnt/hdd"
    else:
        data_mount = "/"

    hdd_total_gb = 0
    hdd_used_gb = 0
    hdd_free_gb = 0
    hdd_pct = 0.0
    hdd_critical = False
    try:
        hdd_stat = shutil.disk_usage(data_mount)
        hdd_total_gb = round(hdd_stat.total / (1024**3), 1)
        hdd_used_gb = round(hdd_stat.used / (1024**3), 1)
        hdd_free_gb = round(hdd_stat.free / (1024**3), 1)
        hdd_pct = round((hdd_stat.used / hdd_stat.total) * 100, 1)
        hdd_critical = (hdd_free_gb < 100 or hdd_pct >= 90.0)
    except Exception:
        pass

    # 3. Uptime
    uptime_str = "Unknown"
    uptime_seconds = 0
    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.readline().split()[0])
            days = int(uptime_seconds // 86400)
            hours = int((uptime_seconds % 86400) // 3600)
            mins = int((uptime_seconds % 3600) // 60)
            uptime_str = f"{days}d {hours}h {mins}m"
    except Exception:
        pass

    with telemetry_lock:
        cpu_data = telemetry_state["cpu"]

    return jsonify({
        "cpu": cpu_data,
        "memory": {
            "total_gib": round(mem_total_kb / 1048576, 2),
            "used_gib": round(mem_used_kb / 1048576, 2),
            "free_gib": round(mem_avail_kb / 1048576, 2),
            "percent": mem_pct
        },
        "swap": {
            "total_gib": round(swap_total_kb / 1048576, 2),
            "used_gib": round(swap_used_kb / 1048576, 2),
            "percent": swap_pct
        },
        "storage": {
            "ssd": {
                "mount": "/",
                "total_gb": ssd_total_gb,
                "used_gb": ssd_used_gb,
                "free_gb": ssd_free_gb,
                "percent": ssd_pct
            },
            "hdd": {
                "mount": data_mount,
                "total_gb": hdd_total_gb,
                "used_gb": hdd_used_gb,
                "free_gb": hdd_free_gb,
                "percent": hdd_pct,
                "is_critical": hdd_critical,
                "warning_level": "critical" if hdd_pct >= 90 else ("warning" if hdd_pct >= 80 else "normal")
            }
        },
        "uptime": uptime_str,
        "uptime_seconds": int(uptime_seconds),
        "local_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
    })

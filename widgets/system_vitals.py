"""
Widget: Hardware Vitals & Storage Headroom
Monitors host CPU load, physical RAM & swap usage, OS SSD capacity,
and measured media/photo/appdata storage breakdown.
"""

import ctypes
import datetime
import os
import shutil
import sys

from flask import Blueprint, jsonify

from config import (
    APPDATA_DIR,
    BACKUP_DIR,
    HDD_DATA,
    HDD_MEMORIES,
    STORAGE_SIZES_CACHE_FILE,
    get_host_timezone,
    get_tz_abbr,
)
from core.storage_sizes import get_storage_sizes
from core.telemetry_sampler import telemetry_lock, telemetry_state

system_vitals_bp = Blueprint("system_vitals", __name__)


def _resolve_data_mount(data_path: str) -> tuple[str, bool]:
    """Resolves the active storage mount path and reports whether it exists."""
    if "/data" in data_path and data_path != "/data":
        candidate_mount = data_path.rsplit("/data", 1)[0]
    else:
        candidate_mount = data_path

    for path in (candidate_mount, data_path):
        if path and os.path.exists(path):
            return path, True
    if os.path.exists("/mnt/hdd"):
        return "/mnt/hdd", True
    return candidate_mount or data_path, False


@system_vitals_bp.route("/api/system/vitals", methods=["GET"])
def get_system_vitals():
    """Returns CPU, RAM, Swap, SSD, HDD headroom, measured folder breakdown, and uptime."""
    # 1. RAM and Swap from /proc/meminfo (with Windows fallback)
    mem_total_kb = 0
    mem_avail_kb = 0
    swap_total_kb = 0
    swap_free_kb = 0
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
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
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
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

    data_mount, mount_exists = _resolve_data_mount(HDD_DATA)
    hdd_total_gb = None
    hdd_used_gb = None
    hdd_free_gb = None
    hdd_pct = None
    hdd_critical = False
    hdd_warning_level = "unknown"
    if mount_exists:
        try:
            hdd_stat = shutil.disk_usage(data_mount)
            hdd_total_gb = round(hdd_stat.total / (1024**3), 1)
            hdd_used_gb = round(hdd_stat.used / (1024**3), 1)
            hdd_free_gb = round(hdd_stat.free / (1024**3), 1)
            hdd_pct = round((hdd_stat.used / hdd_stat.total) * 100, 1)
            hdd_critical = (hdd_free_gb < 100 or hdd_pct >= 90.0)
            hdd_warning_level = "critical" if hdd_pct >= 90 else ("warning" if hdd_pct >= 80 else "normal")
        except Exception:
            mount_exists = False

    # 3. Measured folder breakdown (async hourly cache, never guesses 75%/20%)
    sizes = get_storage_sizes(
        cache_file=STORAGE_SIZES_CACHE_FILE,
        media_path=HDD_DATA,
        photos_path=HDD_MEMORIES,
        appdata_path=APPDATA_DIR,
        backup_path=BACKUP_DIR,
    )
    media_gb = sizes.get("media_gb")
    photos_gb = sizes.get("photos_gb")
    appdata_gb = sizes.get("appdata_gb")

    def _pct_of_pool(gb_val):
        if gb_val is None or not hdd_total_gb or hdd_total_gb <= 0:
            return None
        return round(min(100.0, max(0.0, (gb_val / hdd_total_gb) * 100.0)), 1)

    breakdown = {
        "measured": bool(sizes.get("measured")),
        "measuring": bool(sizes.get("measuring")),
        "measured_at": sizes.get("measured_at"),
        "reason": sizes.get("reason"),
        "media_gb": media_gb,
        "photos_gb": photos_gb,
        "appdata_gb": appdata_gb,
        "media_pct": _pct_of_pool(media_gb),
        "photos_pct": _pct_of_pool(photos_gb),
        "appdata_pct": _pct_of_pool(appdata_gb),
    }

    # 4. Uptime
    uptime_str = "Unknown"
    uptime_seconds = 0
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as f:
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
            "percent": mem_pct,
        },
        "swap": {
            "total_gib": round(swap_total_kb / 1048576, 2),
            "used_gib": round(swap_used_kb / 1048576, 2),
            "percent": swap_pct,
        },
        "storage": {
            "ssd": {
                "mount": "/",
                "total_gb": ssd_total_gb,
                "used_gb": ssd_used_gb,
                "free_gb": ssd_free_gb,
                "percent": ssd_pct,
            },
            "hdd": {
                "mount": data_mount,
                "available": mount_exists,
                "reason": None if mount_exists else f"Storage path not mounted ({data_mount})",
                "total_gb": hdd_total_gb,
                "used_gb": hdd_used_gb,
                "free_gb": hdd_free_gb,
                "percent": hdd_pct,
                "is_critical": hdd_critical,
                "warning_level": hdd_warning_level,
                "breakdown": breakdown,
            },
        },
        "uptime": uptime_str,
        "uptime_seconds": int(uptime_seconds),
        "timezone": get_host_timezone(),
        "tz_abbr": get_tz_abbr(),
        "local_time": datetime.datetime.now().strftime(f"%Y-%m-%d %H:%M:%S {get_tz_abbr()}"),
    })

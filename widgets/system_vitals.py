"""
Widget: Hardware Vitals & Storage Headroom
Monitors host CPU load/temp, physical RAM & swap usage, OS root capacity,
and filesystem-accurate measured storage breakdown (never plotting SSD appdata
inside a separate data HDD pool, and aligning thresholds with Alerts config).
"""

import ctypes
import datetime
import os
import shutil
import socket
import sys

from flask import Blueprint, jsonify

from config import (
    ALERTS_CONFIG_FILE,
    APPDATA_DIR,
    BACKUP_DIR,
    HDD_DATA,
    HDD_MEMORIES,
    MEDIA_BACKUP_DIR,
    PHOTO_UPLOAD_DIR,
    PORT,
    STORAGE_HISTORY_FILE,
    STORAGE_SIZES_CACHE_FILE,
    get_host_timezone,
    get_tz_abbr,
)
from core import alerts as alerts_core
from core.storage_sizes import get_storage_sizes, record_storage_sample
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


def _disk_thresholds() -> tuple[float, float]:
    """Reads warning/critical disk percentages from the user's Alerts config."""
    try:
        cfg = alerts_core.load_config(ALERTS_CONFIG_FILE)
        warn = float(cfg.get("rules", {}).get("disk_warning", {}).get("percent", 85))
        crit = float(cfg.get("rules", {}).get("disk_critical", {}).get("percent", 95))
        return warn, crit
    except Exception:
        return 85.0, 95.0


def _st_dev(path: str):
    try:
        return os.stat(path).st_dev if path and os.path.exists(path) else None
    except OSError:
        return None


@system_vitals_bp.route("/api/system/vitals", methods=["GET"])
def get_system_vitals():
    """Returns CPU, RAM, Swap, OS root, media pool headroom, honest folder breakdown, and uptime."""
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

    warn_pct, crit_pct = _disk_thresholds()

    # 2. Disk Storage Vitals
    ssd_stat = shutil.disk_usage("/")
    ssd_total_gb = round(ssd_stat.total / (1024**3), 1)
    ssd_used_gb = round(ssd_stat.used / (1024**3), 1)
    ssd_free_gb = round(ssd_stat.free / (1024**3), 1)
    ssd_pct = round((ssd_stat.used / ssd_stat.total) * 100, 1)
    ssd_warning_level = "critical" if ssd_pct >= crit_pct else ("warning" if ssd_pct >= warn_pct else "normal")
    root_dev_id = _st_dev("/")

    data_mount, mount_exists = _resolve_data_mount(HDD_DATA)
    data_dev_id = _st_dev(data_mount) if mount_exists else None
    single_disk = bool(mount_exists and root_dev_id is not None and data_dev_id == root_dev_id)

    hdd_total_gb = None
    hdd_used_gb = None
    hdd_free_gb = None
    hdd_pct = None
    hdd_critical = False
    hdd_warning_level = "unknown"
    hdd_stat = None
    if mount_exists:
        try:
            hdd_stat = shutil.disk_usage(data_mount)
            hdd_total_gb = round(hdd_stat.total / (1024**3), 1)
            hdd_used_gb = round(hdd_stat.used / (1024**3), 1)
            hdd_free_gb = round(hdd_stat.free / (1024**3), 1)
            hdd_pct = round((hdd_stat.used / hdd_stat.total) * 100, 1)
            hdd_critical = hdd_pct >= crit_pct
            hdd_warning_level = "critical" if hdd_pct >= crit_pct else ("warning" if hdd_pct >= warn_pct else "normal")
        except Exception:
            mount_exists = False

    record_storage_sample(STORAGE_HISTORY_FILE, "/", ssd_stat.used, ssd_stat.total)
    if mount_exists and hdd_stat is not None:
        record_storage_sample(STORAGE_HISTORY_FILE, data_mount, hdd_stat.used, hdd_stat.total)

    # 3. Measured folder breakdown (async hourly cache or root systemd timer)
    sizes = get_storage_sizes(
        cache_file=STORAGE_SIZES_CACHE_FILE,
        media_path=HDD_DATA,
        photos_path=HDD_MEMORIES,
        appdata_path=APPDATA_DIR,
        backup_path=BACKUP_DIR,
        photo_upload_path=PHOTO_UPLOAD_DIR,
        media_backup_path=MEDIA_BACKUP_DIR,
    )
    media_gb = sizes.get("media_gb")
    photos_gb = sizes.get("photos_gb")
    appdata_gb = sizes.get("appdata_gb")
    fs_devs = sizes.get("fs_devs") or {}
    appdata_dev = fs_devs.get("appdata") or _st_dev(APPDATA_DIR) or fs_devs.get("backup") or _st_dev(BACKUP_DIR)

    # Only include Appdata & Backups in the Data Pool bar when they physically live on that pool.
    appdata_on_pool = bool(
        single_disk or (data_dev_id is not None and appdata_dev is not None and appdata_dev == data_dev_id)
    )
    pool_appdata_gb = appdata_gb if appdata_on_pool else None

    def _pct_of(gb_val, total_gb):
        if gb_val is None or not total_gb or total_gb <= 0:
            return None
        return round(min(100.0, max(0.0, (gb_val / total_gb) * 100.0)), 1)

    pool_measured_sum = sum(v for v in (media_gb, photos_gb, pool_appdata_gb) if isinstance(v, (int, float)))
    pool_other_gb = (
        round(max(0.0, (hdd_used_gb or 0.0) - pool_measured_sum), 2)
        if mount_exists and hdd_used_gb is not None and sizes.get("measured")
        else None
    )

    breakdown = {
        "measured": bool(sizes.get("measured")),
        "measuring": bool(sizes.get("measuring")),
        "measured_at": sizes.get("measured_at"),
        "measured_by": sizes.get("measured_by"),
        "any_partial": bool(sizes.get("any_partial")),
        "media_partial": bool(sizes.get("media_partial")),
        "photos_partial": bool(sizes.get("photos_partial")),
        "appdata_partial": bool(sizes.get("appdata_partial")),
        "appdata_on_pool": appdata_on_pool,
        "reason": sizes.get("reason"),
        "media_gb": media_gb,
        "photos_gb": photos_gb,
        "appdata_gb": pool_appdata_gb,
        "other_gb": pool_other_gb,
        "media_pct": _pct_of(media_gb, hdd_total_gb),
        "photos_pct": _pct_of(photos_gb, hdd_total_gb),
        "appdata_pct": _pct_of(pool_appdata_gb, hdd_total_gb),
        "other_pct": _pct_of(pool_other_gb, hdd_total_gb),
    }

    ssd_appdata_gb = appdata_gb if not appdata_on_pool else None
    ssd_breakdown = {
        "appdata_gb": ssd_appdata_gb,
        "appdata_pct": _pct_of(ssd_appdata_gb, ssd_total_gb),
        "other_gb": round(max(0.0, ssd_used_gb - (ssd_appdata_gb or 0.0)), 2) if ssd_appdata_gb is not None else None,
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
        "hostname": socket.gethostname(),
        "port": PORT,
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
        "thresholds": {
            "disk_warning_percent": warn_pct,
            "disk_critical_percent": crit_pct,
        },
        "storage": {
            "single_disk": single_disk,
            "ssd": {
                "mount": "/",
                "total_gb": ssd_total_gb,
                "used_gb": ssd_used_gb,
                "free_gb": ssd_free_gb,
                "percent": ssd_pct,
                "warning_level": ssd_warning_level,
                "breakdown": ssd_breakdown,
            },
            "hdd": {
                "mount": data_mount,
                "available": mount_exists,
                "same_as_root": single_disk,
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

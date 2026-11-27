"""
Control Hub - Telemetry Background Sampler
Continuous 1-second sampling of NIC throughput, qBittorrent bandwidth/queue,
disk I/O operations (/proc/diskstats), SMB client sessions, Jellyfin activity,
and CPU utilization / real thermal sensors. Never fabricates link speeds,
block devices, or idle/streaming claims.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import requests

from config import (
    ACTIVE_NIC,
    JELLYFIN_API_KEY,
    JELLYFIN_URL,
    QBITTORRENT_PASS,
    QBITTORRENT_URL,
    QBITTORRENT_USER,
)
from core.metrics_history import record_sample as record_history_sample

VIRTUAL_NIC_PREFIXES = (
    "docker",
    "veth",
    "br-",
    "tailscale",
    "tun",
    "tap",
    "virbr",
    "wg",
    "podman",
    "cni",
    "flannel",
    "kube",
)

CPU_HWMON_DRIVERS = (
    "coretemp",
    "k10temp",
    "zenpower",
    "zenergy",
    "cpu_thermal",
    "soc_thermal",
    "bcm2835_thermal",
    "armada_thermal",
    "cputemp",
    "thinkpad",
    "dell_smm",
)

CPU_THERMAL_ZONE_TYPES = (
    "x86_pkg_temp",
    "cpu-thermal",
    "cpu_thermal",
    "soc-thermal",
    "soc_thermal",
    "tcpu",
    "coretemp",
    "k10temp",
)


def read_cpu_temp(
    hwmon_root: Path = Path("/sys/class/hwmon"),
    thermal_root: Path = Path("/sys/class/thermal"),
) -> Optional[float]:
    """
    Reads real host CPU temperature in Celsius from Linux hwmon or CPU-typed
    thermal zones. Avoids unrelated sensors (acpitz, iwlwifi, nvme).
    Returns None when no genuine CPU thermal sensor is present.
    """
    # 1. Prefer hwmon CPU sensors (coretemp, k10temp, zenpower, cpu_thermal, ...)
    if hwmon_root.is_dir():
        try:
            for hwmon in sorted(hwmon_root.iterdir()):
                name_file = hwmon / "name"
                if not name_file.is_file():
                    continue
                driver = name_file.read_text(encoding="utf-8", errors="ignore").strip().lower()
                if driver not in CPU_HWMON_DRIVERS:
                    continue
                preferred: list[Path] = []
                fallback: list[Path] = []
                for inp in sorted(hwmon.glob("temp*_input")):
                    label_file = hwmon / inp.name.replace("_input", "_label")
                    label = ""
                    if label_file.is_file():
                        try:
                            label = label_file.read_text(encoding="utf-8", errors="ignore").strip().lower()
                        except OSError:
                            pass
                    if any(k in label for k in ("package", "tctl", "tdie", "core 0", "cpu")):
                        preferred.append(inp)
                    else:
                        fallback.append(inp)
                for candidate in preferred + fallback:
                    try:
                        raw = int(candidate.read_text(encoding="utf-8").strip())
                        if 1000 <= raw <= 150000:
                            return round(raw / 1000.0, 1)
                    except (OSError, ValueError):
                        continue
        except OSError:
            pass

    # 2. Fall back to thermal_zone* ONLY when its `type` identifies a CPU sensor
    if thermal_root.is_dir():
        try:
            for zone in sorted(thermal_root.glob("thermal_zone*")):
                type_file = zone / "type"
                temp_file = zone / "temp"
                if not (type_file.is_file() and temp_file.is_file()):
                    continue
                ztype = type_file.read_text(encoding="utf-8", errors="ignore").strip().lower()
                if ztype in CPU_THERMAL_ZONE_TYPES or "cpu" in ztype or "pkg_temp" in ztype:
                    try:
                        raw = int(temp_file.read_text(encoding="utf-8").strip())
                        if 1000 <= raw <= 150000:
                            return round(raw / 1000.0, 1)
                    except (OSError, ValueError):
                        continue
        except OSError:
            pass

    return None


def get_cpu_hardware_specs():
    """Detects host CPU model and core/thread count dynamically across all architectures."""
    model_name = ""
    cores = os.cpu_count() or 2
    arch = platform.machine()

    proc_cpuinfo = Path("/proc/cpuinfo")
    if proc_cpuinfo.exists():
        try:
            with open(proc_cpuinfo, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("model name"):
                        m = line.split(":", 1)[1].strip()
                        if m:
                            model_name = m
                            break
        except Exception:
            pass

    if not model_name and sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            model_name = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except Exception:
            pass

    if not model_name and sys.platform == "darwin":
        try:
            res = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                model_name = res.stdout.strip()
        except Exception:
            pass

    if not model_name:
        model_name = platform.processor() or f"{arch} Host Processor"

    return {
        "model": model_name,
        "cores": cores,
        "threads": cores,
        "architecture": arch,
    }


def _is_virtual_nic(iface: str) -> bool:
    return iface == "lo" or iface.startswith(VIRTUAL_NIC_PREFIXES)


def detect_active_nic(
    preferred_nic: Optional[str] = None,
    proc_net: Path = Path("/proc/net/dev"),
    proc_route: Path = Path("/proc/net/route"),
    sys_net: Path = Path("/sys/class/net"),
) -> Optional[str]:
    """
    Detects the primary non-virtual network interface:
    1. explicit `preferred_nic` when present in /proc/net/dev
    2. default-route interface from /proc/net/route
    3. first physical interface whose operstate is 'up'
    4. first physical interface, else None (never fabricates 'eth0' on Linux).
    """
    if not proc_net.exists():
        return preferred_nic or None

    interfaces = []
    try:
        with open(proc_net, "r", encoding="utf-8", errors="ignore") as f:
            for line in f.readlines()[2:]:
                if ":" in line:
                    iface = line.split(":", 1)[0].strip()
                    if not _is_virtual_nic(iface):
                        interfaces.append(iface)
    except OSError:
        pass

    if preferred_nic and preferred_nic in interfaces:
        return preferred_nic

    if proc_route.exists():
        try:
            with open(proc_route, "r", encoding="utf-8", errors="ignore") as f:
                for line in f.readlines()[1:]:
                    fields = line.strip().split()
                    if len(fields) >= 2 and fields[1] == "00000000":
                        route_iface = fields[0]
                        if not _is_virtual_nic(route_iface) and (not interfaces or route_iface in interfaces):
                            return route_iface
        except OSError:
            pass

    for iface in interfaces:
        state_file = sys_net / iface / "operstate"
        try:
            if state_file.is_file() and state_file.read_text(encoding="utf-8").strip() == "up":
                return iface
        except OSError:
            continue

    return interfaces[0] if interfaces else (preferred_nic or None)


def _normalize_block_device(dev_path: str) -> Optional[str]:
    """
    Maps a mount source (/dev/sda1, /dev/nvme0n1p2, /dev/mmcblk0p2,
    /dev/mapper/ubuntu--vg-ubuntu--lv, /dev/md0) to its /proc/diskstats name.
    """
    if not dev_path.startswith("/dev/"):
        return None
    resolved = dev_path
    try:
        if os.path.exists(dev_path):
            resolved = os.path.realpath(dev_path)
    except OSError:
        pass
    raw = resolved.replace("/dev/", "")
    if raw.startswith("dm-") or raw.startswith("md"):
        return raw
    if "nvme" in raw or "mmcblk" in raw:
        return raw.rsplit("p", 1)[0] if "p" in raw else raw
    stripped = raw.rstrip("0123456789")
    return stripped or raw


def detect_storage_topology(
    hdd_data_path: Optional[str] = None,
    proc_mounts: Path = Path("/proc/mounts"),
):
    """
    Dynamically detects block devices for OS root (/) and configured media mount
    from /proc/mounts (supporting LVM dm-*, NVMe, SATA, eMMC, MDADM, and single-disk
    hosts). Never fabricates 'sda' or 'sdb'.
    Returns (root_dev, data_dev, target_data_mount, single_disk).
    """
    hdd_mount_path = hdd_data_path or os.getenv("HDD_DATA", "/mnt/hdd/data")
    if "/data" in hdd_mount_path and hdd_mount_path != "/data":
        target_data_mount = hdd_mount_path.rsplit("/data", 1)[0]
    else:
        target_data_mount = hdd_mount_path

    root_dev = None
    data_dev = None
    best_data_match_len = -1

    if proc_mounts.exists():
        try:
            with open(proc_mounts, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    dev_path, mnt_point = parts[0], parts[1]
                    if not dev_path.startswith("/dev/"):
                        continue
                    base_dev = _normalize_block_device(dev_path)
                    if not base_dev:
                        continue
                    if mnt_point == "/":
                        root_dev = base_dev
                    # Longest-prefix mount match for target_data_mount
                    if target_data_mount and (
                        target_data_mount == mnt_point
                        or target_data_mount.startswith(mnt_point.rstrip("/") + "/")
                    ):
                        if len(mnt_point) > best_data_match_len:
                            best_data_match_len = len(mnt_point)
                            data_dev = base_dev
        except OSError:
            pass

    single_disk = False
    if root_dev and data_dev and root_dev == data_dev:
        single_disk = True
    else:
        try:
            if os.path.exists("/") and target_data_mount and os.path.exists(target_data_mount):
                if os.stat("/").st_dev == os.stat(target_data_mount).st_dev:
                    single_disk = True
        except OSError:
            pass

    return root_dev, data_dev, target_data_mount, single_disk


def detect_storage_devices(
    hdd_data_path: Optional[str] = None,
    proc_mounts: Path = Path("/proc/mounts"),
):
    """Backwards-compatible 3-tuple wrapper around detect_storage_topology()."""
    root_dev, data_dev, target_data_mount, _ = detect_storage_topology(
        hdd_data_path=hdd_data_path,
        proc_mounts=proc_mounts,
    )
    return root_dev, data_dev, target_data_mount


def get_nic_link_info(
    iface: Optional[str],
    sys_net: Path = Path("/sys/class/net"),
) -> tuple[Optional[int], Optional[str], str]:
    """
    Dynamically reads negotiated link speed (Mbps) and duplex from /sys/class/net.
    Never fabricates '100 Mbps Full-Duplex' when unreadable (Wi-Fi, VM, down link).
    """
    if not iface:
        return None, None, "No active network interface"

    iface_dir = sys_net / iface
    speed_mbps: Optional[int] = None
    duplex: Optional[str] = None
    is_wireless = (iface_dir / "wireless").exists()

    try:
        speed_path = iface_dir / "speed"
        if speed_path.is_file():
            val = int(speed_path.read_text(encoding="utf-8").strip())
            if val > 0:
                speed_mbps = val
    except (OSError, ValueError):
        pass

    try:
        duplex_path = iface_dir / "duplex"
        if duplex_path.is_file():
            d = duplex_path.read_text(encoding="utf-8").strip().lower()
            if d in ("full", "half"):
                duplex = d
    except OSError:
        pass

    if speed_mbps is not None:
        if speed_mbps >= 1000:
            gbps_val = round(speed_mbps / 1000.0, 1)
            speed_str = f"{gbps_val if gbps_val % 1 != 0 else int(gbps_val)} Gbps"
        else:
            speed_str = f"{speed_mbps} Mbps"
        if duplex:
            spec_text = f"{speed_str} {duplex.capitalize()}-Duplex"
        elif is_wireless:
            spec_text = f"Wi-Fi · {speed_str}"
        else:
            spec_text = speed_str
    elif is_wireless:
        spec_text = "Wi-Fi (speed not reported)"
    else:
        spec_text = "Link speed unavailable"

    return speed_mbps, duplex, spec_text


CPU_SPECS = get_cpu_hardware_specs()
DETECTED_ROOT_DEV, DETECTED_DATA_DEV, DETECTED_DATA_MOUNT, IS_SINGLE_DISK = detect_storage_topology()
DETECTED_NIC = detect_active_nic(ACTIVE_NIC)

_sampler_thread: Optional[threading.Thread] = None
_sampler_started = False

# Thread-safe global telemetry state
telemetry_lock = threading.Lock()
telemetry_state = {
    "network": {
        "interface": DETECTED_NIC,
        "rx_bytes_sec": 0,
        "tx_bytes_sec": 0,
        "rx_mbps": 0.0,
        "tx_mbps": 0.0,
        "rx_mbs": 0.0,
        "tx_mbs": 0.0,
        "total_mbps": 0.0,
        "total_mbs": 0.0,
        "link_speed_mbps": None,
        "duplex": None,
        "spec_text": "Link speed unavailable",
        "gauge_percent": None,
        "updated_at": 0,
    },
    "internet": {
        "dl_speed_bytes": 0,
        "up_speed_bytes": 0,
        "dl_mbps": 0.0,
        "up_mbps": 0.0,
        "dl_mbs": 0.0,
        "up_mbs": 0.0,
        "total_mbps": 0.0,
        "total_mbs": 0.0,
        "connection_status": "unknown",
        "dht_nodes": 0,
        "gauge_percent": None,
        "active_downloads": 0,
        "active_torrents": 0,
        "updated_at": 0,
    },
    "torrents_queue": {
        "status": "unknown",
        "status_message": None,
        "collective_dl_mbps": 0.0,
        "collective_up_mbps": 0.0,
        "collective_total_mbps": 0.0,
        "collective_dl_mbs": 0.0,
        "collective_up_mbs": 0.0,
        "collective_total_mbs": 0.0,
        "active_count": 0,
        "paused_count": 0,
        "all_paused": False,
        "total_count": 0,
        "items": [],
    },
    "storage_ops": {
        "single_disk": IS_SINGLE_DISK,
        "collective_mbps": 0.0,
        "total_read_mbps": 0.0,
        "total_write_mbps": 0.0,
        "collective_mbs": 0.0,
        "total_read_mbs": 0.0,
        "total_write_mbs": 0.0,
        "disks": [],
        "hdd": {
            "device": DETECTED_DATA_DEV,
            "read_mbps": 0.0,
            "write_mbps": 0.0,
            "read_mbs": 0.0,
            "write_mbs": 0.0,
            "name": (
                f"Media Storage ({DETECTED_DATA_MOUNT} - {DETECTED_DATA_DEV})"
                if DETECTED_DATA_DEV
                else f"Media Storage ({DETECTED_DATA_MOUNT})"
            ),
        },
        "ssd": {
            "device": DETECTED_ROOT_DEV,
            "read_mbps": 0.0,
            "write_mbps": 0.0,
            "read_mbs": 0.0,
            "write_mbs": 0.0,
            "name": f"OS Root (/ - {DETECTED_ROOT_DEV})" if DETECTED_ROOT_DEV else "OS Root (/)",
        },
        "smb_clients": [],
        "jellyfin_streams": [],
    },
    "cpu": {
        "usage_percent": 0.0,
        "cores": CPU_SPECS["cores"],
        "threads": CPU_SPECS["threads"],
        "model": CPU_SPECS["model"],
        "temp_c": None,
    },
}

# Persistent qBittorrent HTTP Session (guarded by qb_lock across threads)
qb_lock = threading.Lock()
qb_session = requests.Session()
qb_logged_in = False
qb_status = "unknown"


def qb_login() -> bool:
    """Authenticates the persistent session with qBittorrent WebUI (4.x and 5.x)."""
    global qb_logged_in, qb_status
    with qb_lock:
        if not QBITTORRENT_URL:
            qb_logged_in = False
            qb_status = "not_configured"
            return False
        try:
            resp = qb_session.post(
                f"{QBITTORRENT_URL}/api/v2/auth/login",
                data={"username": QBITTORRENT_USER, "password": QBITTORRENT_PASS},
                timeout=3,
            )
            body = (resp.text or "").strip().lower()
            # qBittorrent 5.3+ answers HTTP 204 with QBT_SID cookie; 4.x returns 200 "Ok." (200 "Fails." on bad password).
            if resp.status_code == 204 or (resp.status_code == 200 and body == "ok."):
                qb_logged_in = True
                qb_status = "connected"
                return True
            qb_logged_in = False
            qb_status = "auth_failed" if resp.status_code in (200, 401, 403) else "unreachable"
            return False
        except Exception:
            qb_logged_in = False
            qb_status = "unreachable"
            return False


def format_eta(seconds, state):
    """Converts ETA seconds to readable format (supports qBittorrent 4.x paused* and 5.x stopped*)."""
    state_l = (state or "").lower()
    if "stalled" in state_l:
        return "Stalled (Waiting for seeds)"
    if "paused" in state_l or "stopped" in state_l:
        return "Paused"
    if seconds <= 0 or seconds >= 8640000:
        return "∞"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    return f"{hours}h {mins}m"


def get_smb_sessions():
    """Parses active Samba share connections via smbstatus."""
    sessions = []
    try:
        proc = subprocess.run(
            ["sudo", "-n", "/usr/bin/smbstatus", "-S"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.5,
        )
        for line in proc.stdout.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("Service", "---", "Samba", "PID")):
                continue
            parts = stripped.split()
            if len(parts) >= 3 and parts[1].isdigit() and parts[0] != "IPC$":
                sessions.append({
                    "share": parts[0],
                    "ip": parts[2],
                    "connected_at": " ".join(parts[3:7]) if len(parts) >= 7 else "Connected",
                })
    except Exception:
        pass
    return sessions


def get_jellyfin_streams():
    """
    Detects active Jellyfin playback via /Sessions API when JELLYFIN_API_KEY is set.
    Without an API key, falls back to inspecting open TCP sockets on port 8096 and
    explicitly labels them as unverified client connections (not confirmed video playback).
    """
    if JELLYFIN_API_KEY and JELLYFIN_URL:
        try:
            resp = requests.get(
                f"{JELLYFIN_URL.rstrip('/')}/Sessions",
                headers={"X-Emby-Token": JELLYFIN_API_KEY, "Accept": "application/json"},
                timeout=2.0,
            )
            if resp.status_code == 200:
                streams = []
                for sess in resp.json() or []:
                    now_playing = sess.get("NowPlayingItem")
                    if not now_playing:
                        continue
                    play_state = sess.get("PlayState") or {}
                    method = play_state.get("PlayMethod") or "DirectPlay"
                    paused = bool(play_state.get("IsPaused"))
                    title = now_playing.get("Name") or "Media"
                    series = now_playing.get("SeriesName")
                    label = f"{series} — {title}" if series else title
                    streams.append({
                        "client_ip": sess.get("RemoteEndPoint") or sess.get("Client") or "Client",
                        "user": sess.get("UserName") or "",
                        "title": label,
                        "play_method": method,
                        "device_name": sess.get("DeviceName") or sess.get("Client") or "",
                        "type": f"{method} · {label}",
                        "status": "Paused" if paused else "Playing",
                        "verified": True,
                    })
                return streams
        except Exception:
            pass

    streams = []
    seen_peers = set()
    try:
        proc = subprocess.run(["ss", "-tn", "sport = :8096"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=1.2)
        for line in proc.stdout.splitlines():
            if "ESTAB" in line:
                parts = line.split()
                if len(parts) >= 5:
                    peer = parts[4]
                    peer_ip = peer.rsplit(":", 1)[0].replace("[", "").replace("]", "")
                    if peer_ip not in ("127.0.0.1", "::1", "::ffff:127.0.0.1") and peer_ip not in seen_peers:
                        seen_peers.add(peer_ip)
                        streams.append({
                            "client_ip": peer_ip,
                            "type": "Web / App Connection (playback unverified)",
                            "status": "Connected",
                            "verified": False,
                        })
    except Exception:
        pass
    return streams


def _read_nic_bytes(active_iface: Optional[str]) -> Optional[tuple[int, int]]:
    if not active_iface:
        return None
    try:
        with open("/proc/net/dev", "r", encoding="utf-8", errors="ignore") as f:
            for line in f.readlines()[2:]:
                if ":" not in line:
                    continue
                name, rest = line.split(":", 1)
                if name.strip() == active_iface:
                    parts = rest.split()
                    if len(parts) >= 9:
                        return int(parts[0]), int(parts[8])
    except (OSError, ValueError):
        pass
    return None


def _read_disk_sectors(targets: set[str]) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    if not targets:
        return out
    try:
        with open("/proc/diskstats", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 10 and parts[2] in targets:
                    out[parts[2]] = (int(parts[5]), int(parts[9]))
    except (OSError, ValueError):
        pass
    return out


def _poll_qbittorrent():
    """Fetches qBittorrent transfer speed and torrent queue under qb_lock."""
    dl_speed = 0
    up_speed = 0
    dht_nodes = 0
    active_dl_count = 0
    paused_count = 0
    active_torrents_count = 0
    torrent_items = []
    status = "unreachable"
    status_message = None

    if not QBITTORRENT_URL:
        return (0, 0, "not_configured", "qBittorrent URL not configured", 0, 0, 0, 0, [])

    try:
        with qb_lock:
            resp = qb_session.get(f"{QBITTORRENT_URL}/api/v2/transfer/info", timeout=1.5)
        if resp.status_code == 403:
            if not qb_login():
                msg = "qBittorrent login failed (check QBITTORRENT_PASS)" if qb_status == "auth_failed" else "qBittorrent unreachable"
                return (0, 0, qb_status, msg, 0, 0, 0, 0, [])
            with qb_lock:
                resp = qb_session.get(f"{QBITTORRENT_URL}/api/v2/transfer/info", timeout=1.5)

        if resp.status_code == 200:
            data = resp.json()
            dl_speed = data.get("dl_info_speed", 0)
            up_speed = data.get("up_info_speed", 0)
            status = "connected"
            dht_nodes = data.get("dht_nodes", 0)

            with qb_lock:
                all_resp = qb_session.get(f"{QBITTORRENT_URL}/api/v2/torrents/info?filter=all", timeout=1.8)
            if all_resp.status_code == 200:
                raw_list = all_resp.json()
                active_torrents_count = len(raw_list)
                for t in raw_list:
                    t_dl = t.get("dlspeed", 0)
                    t_up = t.get("upspeed", 0)
                    t_state = t.get("state", "")
                    t_state_l = t_state.lower()
                    t_prog = t.get("progress", 0)

                    if "paused" in t_state_l or "stopped" in t_state_l:
                        paused_count += 1
                    elif "dl" in t_state_l or "download" in t_state_l or t_dl > 0:
                        active_dl_count += 1

                    size_b = t.get("size", 0)
                    comp_b = t.get("completed", 0)
                    torrent_items.append({
                        "name": t.get("name", "Unknown"),
                        "hash": t.get("hash", ""),
                        "state": t_state,
                        "category": t.get("category", "General"),
                        "priority": int(t.get("priority") or 0),
                        "progress": round(t_prog * 100, 1),
                        "dl_mbps": round((t_dl * 8) / 1_000_000.0, 2),
                        "up_mbps": round((t_up * 8) / 1_000_000.0, 2),
                        "dl_mbs": round(t_dl / 1_048_576.0, 2),
                        "up_mbs": round(t_up / 1_048_576.0, 2),
                        "size_gb": round(size_b / (1024**3), 2),
                        "completed_gb": round(comp_b / (1024**3), 2),
                        "eta": format_eta(t.get("eta", 0), t_state),
                    })
        elif resp.status_code in (401, 403):
            status = "auth_failed"
            status_message = "qBittorrent authentication rejected"
        else:
            status = "unreachable"
            status_message = f"qBittorrent returned HTTP {resp.status_code}"
    except Exception:
        status = "unreachable"
        status_message = "qBittorrent is offline or not installed"

    return (
        dl_speed,
        up_speed,
        status,
        status_message,
        dht_nodes,
        active_dl_count,
        paused_count,
        active_torrents_count,
        torrent_items,
    )


def telemetry_worker():
    """Continuously samples NIC, disk stats, CPU, and qBittorrent at 1-second intervals."""
    active_iface = DETECTED_NIC
    prev_nic = _read_nic_bytes(active_iface)
    prev_rx = prev_nic[0] if prev_nic else 0
    prev_tx = prev_nic[1] if prev_nic else 0
    prev_time = time.time()
    last_slow_poll = 0.0
    smb_clients = []
    jellyfin_streams = []

    # Initial CPU counters
    prev_cpu_idle = 0.0
    prev_cpu_total = 0.0
    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            fields = [float(column) for column in f.readline().strip().split()[1:]]
            prev_cpu_idle = fields[3] + fields[4]
            prev_cpu_total = sum(fields)
    except Exception:
        pass

    watched_devs = {d for d in (DETECTED_DATA_DEV, DETECTED_ROOT_DEV) if d}
    prev_sectors = _read_disk_sectors(watched_devs)

    while True:
        try:
            now = time.time()
            dt = max(0.1, now - prev_time)

            # 1. Sample Network Interface Throughput
            rx_rate = 0.0
            tx_rate = 0.0
            cur_nic = _read_nic_bytes(active_iface)
            if cur_nic is not None:
                cur_rx, cur_tx = cur_nic
                if prev_nic is not None:
                    rx_rate = max(0.0, (cur_rx - prev_rx) / dt)
                    tx_rate = max(0.0, (cur_tx - prev_tx) / dt)
                prev_rx, prev_tx = cur_rx, cur_tx
                prev_nic = cur_nic

            rx_mbps = (rx_rate * 8) / 1_000_000.0
            tx_mbps = (tx_rate * 8) / 1_000_000.0
            rx_mbs = rx_rate / 1_048_576.0
            tx_mbs = tx_rate / 1_048_576.0
            total_lan_mbps = rx_mbps + tx_mbps
            link_speed, nic_duplex, nic_spec_text = get_nic_link_info(active_iface)
            lan_gauge_pct = (
                round(min(100.0, (total_lan_mbps / link_speed) * 100.0), 1)
                if link_speed and link_speed > 0
                else None
            )

            # 2. Sample CPU Usage & Real CPU Temperature
            cpu_usage_pct = 0.0
            try:
                with open("/proc/stat", "r", encoding="utf-8") as f:
                    fields = [float(column) for column in f.readline().strip().split()[1:]]
                    cur_idle = fields[3] + fields[4]
                    cur_total = sum(fields)
                    delta_idle = cur_idle - prev_cpu_idle
                    delta_total = cur_total - prev_cpu_total
                    if delta_total > 0:
                        cpu_usage_pct = round((1.0 - (delta_idle / delta_total)) * 100.0, 1)
                    prev_cpu_idle = cur_idle
                    prev_cpu_total = cur_total
            except Exception:
                pass

            cpu_temp = read_cpu_temp()

            # 3. Sample qBittorrent Transfer API & Torrent Queue
            (
                dl_speed,
                up_speed,
                conn_status,
                conn_msg,
                dht_nodes,
                active_dl_count,
                paused_count,
                active_torrents_count,
                torrent_items,
            ) = _poll_qbittorrent()

            dl_mbps = (dl_speed * 8) / 1_000_000.0
            up_mbps = (up_speed * 8) / 1_000_000.0
            dl_mbs = dl_speed / 1_048_576.0
            up_mbs = up_speed / 1_048_576.0
            total_wan_mbps = dl_mbps + up_mbps
            total_wan_mbs = dl_mbs + up_mbs

            # 4. Sample Disk I/O (/proc/diskstats) without double-counting single-disk hosts
            cur_sectors = _read_disk_sectors(watched_devs)
            rates: dict[str, tuple[float, float, float, float]] = {}
            for dev in watched_devs:
                if dev in cur_sectors and dev in prev_sectors:
                    dr = max(0, cur_sectors[dev][0] - prev_sectors[dev][0])
                    dw = max(0, cur_sectors[dev][1] - prev_sectors[dev][1])
                    rates[dev] = (
                        round((dr * 512 * 8) / (dt * 1_000_000.0), 2),
                        round((dw * 512 * 8) / (dt * 1_000_000.0), 2),
                        round((dr * 512) / (dt * 1_048_576.0), 2),
                        round((dw * 512) / (dt * 1_048_576.0), 2),
                    )
                else:
                    rates[dev] = (0.0, 0.0, 0.0, 0.0)
            prev_sectors = cur_sectors

            data_r_mbps, data_w_mbps, data_r_mbs, data_w_mbs = rates.get(DETECTED_DATA_DEV or "", (0.0, 0.0, 0.0, 0.0))
            root_r_mbps, root_w_mbps, root_r_mbs, root_w_mbs = rates.get(DETECTED_ROOT_DEV or "", (0.0, 0.0, 0.0, 0.0))

            if IS_SINGLE_DISK or (DETECTED_DATA_DEV and DETECTED_DATA_DEV == DETECTED_ROOT_DEV):
                total_disk_read_mbps = root_r_mbps or data_r_mbps
                total_disk_write_mbps = root_w_mbps or data_w_mbps
                total_disk_read_mbs = root_r_mbs or data_r_mbs
                total_disk_write_mbs = root_w_mbs or data_w_mbs
                disks_list = [{
                    "id": "primary",
                    "role": "SYSTEM & MEDIA",
                    "device": DETECTED_ROOT_DEV or DETECTED_DATA_DEV,
                    "mount": "/",
                    "name": f"Primary Storage (/ - {DETECTED_ROOT_DEV or DETECTED_DATA_DEV})"
                    if (DETECTED_ROOT_DEV or DETECTED_DATA_DEV)
                    else "Primary Storage (/)",
                    "read_mbps": total_disk_read_mbps,
                    "write_mbps": total_disk_write_mbps,
                    "read_mbs": total_disk_read_mbs,
                    "write_mbs": total_disk_write_mbs,
                }]
            else:
                total_disk_read_mbps = round(data_r_mbps + root_r_mbps, 2)
                total_disk_write_mbps = round(data_w_mbps + root_w_mbps, 2)
                total_disk_read_mbs = round(data_r_mbs + root_r_mbs, 2)
                total_disk_write_mbs = round(data_w_mbs + root_w_mbs, 2)
                disks_list = []
                if DETECTED_DATA_DEV:
                    disks_list.append({
                        "id": "data",
                        "role": "DATA",
                        "device": DETECTED_DATA_DEV,
                        "mount": DETECTED_DATA_MOUNT,
                        "name": f"Media Storage ({DETECTED_DATA_MOUNT} - {DETECTED_DATA_DEV})",
                        "read_mbps": data_r_mbps,
                        "write_mbps": data_w_mbps,
                        "read_mbs": data_r_mbs,
                        "write_mbs": data_w_mbs,
                    })
                if DETECTED_ROOT_DEV:
                    disks_list.append({
                        "id": "root",
                        "role": "ROOT",
                        "device": DETECTED_ROOT_DEV,
                        "mount": "/",
                        "name": f"OS Root (/ - {DETECTED_ROOT_DEV})",
                        "read_mbps": root_r_mbps,
                        "write_mbps": root_w_mbps,
                        "read_mbs": root_r_mbs,
                        "write_mbs": root_w_mbs,
                    })

            collective_storage_mbps = round(total_disk_read_mbps + total_disk_write_mbps, 2)
            collective_storage_mbs = round(total_disk_read_mbs + total_disk_write_mbs, 2)

            # 5. Sample SMB and Jellyfin every 15 seconds (monotonic delta, avoids sudo PAM log spam)
            if now - last_slow_poll >= 15.0:
                smb_clients = get_smb_sessions()
                jellyfin_streams = get_jellyfin_streams()
                last_slow_poll = now

            all_paused = active_torrents_count > 0 and paused_count == active_torrents_count

            with telemetry_lock:
                telemetry_state["network"] = {
                    "interface": active_iface,
                    "rx_bytes_sec": rx_rate,
                    "tx_bytes_sec": tx_rate,
                    "rx_mbps": round(rx_mbps, 2),
                    "tx_mbps": round(tx_mbps, 2),
                    "rx_mbs": round(rx_mbs, 2),
                    "tx_mbs": round(tx_mbs, 2),
                    "total_mbps": round(total_lan_mbps, 2),
                    "total_mbs": round(rx_mbs + tx_mbs, 2),
                    "link_speed_mbps": link_speed,
                    "duplex": nic_duplex,
                    "spec_text": nic_spec_text,
                    "gauge_percent": lan_gauge_pct,
                    "updated_at": now,
                }
                telemetry_state["internet"] = {
                    "dl_speed_bytes": dl_speed,
                    "up_speed_bytes": up_speed,
                    "dl_mbps": round(dl_mbps, 2),
                    "up_mbps": round(up_mbps, 2),
                    "dl_mbs": round(dl_mbs, 2),
                    "up_mbs": round(up_mbs, 2),
                    "total_mbps": round(total_wan_mbps, 2),
                    "total_mbs": round(total_wan_mbs, 2),
                    "connection_status": conn_status,
                    "dht_nodes": dht_nodes,
                    "gauge_percent": None,
                    "active_downloads": active_dl_count,
                    "active_torrents": active_torrents_count,
                    "updated_at": now,
                }
                telemetry_state["torrents_queue"] = {
                    "status": conn_status,
                    "status_message": conn_msg,
                    "collective_dl_mbps": round(dl_mbps, 2),
                    "collective_up_mbps": round(up_mbps, 2),
                    "collective_total_mbps": round(total_wan_mbps, 2),
                    "collective_dl_mbs": round(dl_mbs, 2),
                    "collective_up_mbs": round(up_mbs, 2),
                    "collective_total_mbs": round(total_wan_mbs, 2),
                    "active_count": active_dl_count,
                    "paused_count": paused_count,
                    "all_paused": all_paused,
                    "total_count": active_torrents_count,
                    "items": torrent_items,
                }
                telemetry_state["storage_ops"] = {
                    "single_disk": IS_SINGLE_DISK,
                    "collective_mbps": collective_storage_mbps,
                    "total_read_mbps": total_disk_read_mbps,
                    "total_write_mbps": total_disk_write_mbps,
                    "collective_mbs": collective_storage_mbs,
                    "total_read_mbs": total_disk_read_mbs,
                    "total_write_mbs": total_disk_write_mbs,
                    "disks": disks_list,
                    "hdd": {
                        "device": DETECTED_DATA_DEV,
                        "read_mbps": data_r_mbps,
                        "write_mbps": data_w_mbps,
                        "read_mbs": data_r_mbs,
                        "write_mbs": data_w_mbs,
                        "name": (
                            f"Media Storage ({DETECTED_DATA_MOUNT} - {DETECTED_DATA_DEV})"
                            if DETECTED_DATA_DEV
                            else f"Media Storage ({DETECTED_DATA_MOUNT})"
                        ),
                    },
                    "ssd": {
                        "device": DETECTED_ROOT_DEV,
                        "read_mbps": root_r_mbps,
                        "write_mbps": root_w_mbps,
                        "read_mbs": root_r_mbs,
                        "write_mbs": root_w_mbs,
                        "name": f"OS Root (/ - {DETECTED_ROOT_DEV})" if DETECTED_ROOT_DEV else "OS Root (/)",
                    },
                    "smb_clients": smb_clients,
                    "jellyfin_streams": jellyfin_streams,
                }
                telemetry_state["cpu"] = {
                    "usage_percent": cpu_usage_pct,
                    "cores": CPU_SPECS["cores"],
                    "threads": CPU_SPECS["threads"],
                    "model": CPU_SPECS["model"],
                    "temp_c": cpu_temp,
                }

            # 6. Append 5-minute downsampled rollup for 24h/7d/30d history charts (non-blocking)
            try:
                ram_pct = 0.0
                meminfo_path = "/proc/meminfo"
                if os.path.exists(meminfo_path):
                    vals = {}
                    with open(meminfo_path, encoding="utf-8") as mf:
                        for line in mf:
                            k, _, rest = line.partition(":")
                            if k in ("MemTotal", "MemAvailable") and rest:
                                vals[k] = float(rest.strip().split()[0])
                    if vals.get("MemTotal", 0) > 0:
                        avail = vals.get("MemAvailable", 0)
                        ram_pct = ((vals["MemTotal"] - avail) / vals["MemTotal"]) * 100.0
                pool_used_gb = None
                if DETECTED_DATA_MOUNT and os.path.exists(DETECTED_DATA_MOUNT):
                    du = shutil.disk_usage(DETECTED_DATA_MOUNT)
                    pool_used_gb = du.used / (1024 ** 3)
                record_history_sample({
                    "cpu_pct": cpu_usage_pct,
                    "cpu_temp_c": cpu_temp,
                    "ram_pct": ram_pct,
                    "lan_mbs": rx_mbs + tx_mbs,
                    "disk_io_mbs": collective_storage_mbs,
                    "pool_used_gb": pool_used_gb,
                }, now_ts=now)
            except Exception:
                pass

            prev_time = now
            time.sleep(1.0)
        except Exception:
            time.sleep(1.0)


def sampler_health() -> dict:
    """Reports background telemetry sampler liveness for /api/readyz."""
    with telemetry_lock:
        updated_at = float(telemetry_state.get("network", {}).get("updated_at") or 0)
    alive = bool(_sampler_thread and _sampler_thread.is_alive())
    age = round(time.time() - updated_at, 1) if updated_at > 0 else None
    return {"started": _sampler_started, "alive": alive, "last_sample_age_s": age}


def start_telemetry_sampler():
    """Starts the persistent background sampler thread."""
    global _sampler_thread, _sampler_started
    _sampler_started = True
    threading.Thread(target=qb_login, daemon=True).start()
    t = threading.Thread(target=telemetry_worker, name="telemetry-sampler", daemon=True)
    _sampler_thread = t
    t.start()
    return t

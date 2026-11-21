"""
Comprehensive System Prober & AI Context Generator
Probes CPU/GPU, RAM, Host User IDs, Docker status, Disks, and Network.
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from .netplan_manager import probe_network_interfaces
from .port_manager import get_default_ports
from .storage_manager import get_disk_partitions

_DRM_VENDORS = {
    "0x8086": ("intel", "Intel QuickSync / VAAPI"),
    "0x1002": ("amd", "AMD VAAPI"),
    "0x10de": ("nvidia", "NVIDIA GPU"),
}


def probe_cpu_info(model_override: Optional[str] = None) -> Dict[str, Any]:
    """Detects CPU model, core/thread count, architecture, and legacy low-power class."""
    model_name = model_override or ""
    cores = os.cpu_count() or 2
    arch = platform.machine()
    is_low_power = False

    if not model_name:
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

    # Legacy CPUs lacking HEVC 10-bit hardware decode (Haswell/Broadwell/Bay Trail/Atom).
    # Modern Alder Lake-N (N100, N200) and Jasper Lake (N5105) have full QuickSync 4K HEVC.
    model_lower = model_name.lower()
    if any(k in model_lower for k in ["i3-4", "i5-4", "i7-4", "haswell", "broadwell", "j1900", "celeron j", "atom"]):
        is_low_power = True

    return {
        "model": model_name,
        "threads": cores,
        "cores": cores,
        "architecture": arch,
        "is_low_power": is_low_power,
        "recommended_playback": "Direct Play (CPU Protection)" if is_low_power else "Hardware Transcode / Direct Play",
    }


def probe_ram_info() -> Dict[str, Any]:
    """Detects total memory and available memory in GiB across Linux, Windows, or macOS."""
    total_gib: Optional[float] = None
    free_gib: Optional[float] = None

    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        try:
            with open(meminfo, "r", encoding="utf-8") as f:
                mem = {}
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip().split()[0]
                        mem[key] = int(val)
                if "MemTotal" in mem:
                    total_gib = round(mem["MemTotal"] / (1024 * 1024), 2)
                if "MemAvailable" in mem:
                    free_gib = round(mem["MemAvailable"] / (1024 * 1024), 2)
        except Exception:
            pass
    elif sys.platform == "win32":
        try:
            import ctypes

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
            total_gib = round(s.ullTotalPhys / (1024**3), 2)
            free_gib = round(s.ullAvailPhys / (1024**3), 2)
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            res = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout.strip().isdigit():
                total_gib = round(int(res.stdout.strip()) / (1024**3), 2)
        except Exception:
            pass

    return {
        "total_gib": total_gib,
        "free_gib": free_gib,
        "is_constrained": (total_gib is not None and total_gib < 8.0),
    }


def probe_hardware_acceleration(
    dri_root: Path = Path("/dev/dri"),
    drm_sys_root: Path = Path("/sys/class/drm"),
) -> Dict[str, Any]:
    """Inspects Linux DRI render nodes, PCI vendor IDs (Intel/AMD/NVIDIA), and nvidia-smi."""
    has_vaapi_dri = False
    has_nvidia = False
    vendor = None
    vendor_label = None
    details = []

    if drm_sys_root.is_dir():
        try:
            for card in sorted(drm_sys_root.glob("card*")):
                vendor_file = card / "device" / "vendor"
                if vendor_file.is_file():
                    raw_vendor = vendor_file.read_text(encoding="utf-8", errors="ignore").strip().lower()
                    if raw_vendor in _DRM_VENDORS:
                        vendor, vendor_label = _DRM_VENDORS[raw_vendor]
                        break
        except OSError:
            pass

    render_node = dri_root / "renderD128"
    if render_node.exists():
        has_vaapi_dri = True
        desc = vendor_label or "VAAPI / Direct Rendering Manager"
        details.append(f"/dev/dri/renderD128 ({desc} available)")

    card_node = dri_root / "card0"
    if card_node.exists() and not has_vaapi_dri:
        has_vaapi_dri = True
        desc = vendor_label or "Direct Rendering Manager active"
        details.append(f"/dev/dri/card0 ({desc})")

    if shutil.which("nvidia-smi"):
        has_nvidia = True
        vendor = vendor or "nvidia"
        details.append("NVIDIA Driver detected (nvidia-smi present)")

    if not details:
        details.append("No dedicated GPU render node detected (CPU Direct Play will be used)")

    if has_nvidia:
        recommended_mode = "nvidia"
    elif has_vaapi_dri:
        recommended_mode = "qsv" if vendor == "intel" else "vaapi"
    else:
        recommended_mode = "direct_play"

    return {
        "has_vaapi_dri": has_vaapi_dri,
        "has_nvidia": has_nvidia,
        "vendor": vendor,
        "vendor_label": vendor_label,
        "details": details,
        "recommended_mode": recommended_mode,
    }


def probe_host_user() -> Dict[str, Any]:
    """
    Identifies the ideal non-root user running Docker.
    Checks SUDO_USER, configured HOST_USER/PUID/PGID, UID 1000, or current user.
    """
    env_user = (os.getenv("HOST_USER") or "").strip()
    username = env_user or os.getenv("SUDO_USER") or os.getenv("USER") or "homelab_user"
    puid = int(os.getenv("PUID", "1000")) if str(os.getenv("PUID", "")).isdigit() else 1000
    pgid = int(os.getenv("PGID", "1000")) if str(os.getenv("PGID", "")).isdigit() else 1000

    if hasattr(os, "getuid"):
        current_uid = os.getuid()
        current_gid = os.getgid()
        if current_uid == 0:
            sudo_user = os.getenv("SUDO_USER")
            if sudo_user:
                username = sudo_user
                try:
                    import pwd
                    user_info = pwd.getpwnam(sudo_user)
                    puid = user_info.pw_uid
                    pgid = user_info.pw_gid
                except Exception:
                    puid = 1000
                    pgid = 1000
        elif current_uid < 1000:
            # System service account (e.g. 'homelab' running control-hub.service):
            # prefer explicit PUID/PGID env vars or primary login user UID 1000.
            if not env_user:
                try:
                    import pwd
                    u1000 = pwd.getpwuid(1000)
                    username = u1000.pw_name
                    puid = u1000.pw_uid
                    pgid = u1000.pw_gid
                except Exception:
                    pass
        else:
            puid = current_uid
            pgid = current_gid

    return {
        "username": username,
        "puid": puid,
        "pgid": pgid,
    }


def probe_timezone() -> str:
    """Detects server timezone from /etc/timezone or /etc/localtime symlink."""
    tz_file = Path("/etc/timezone")
    if tz_file.exists():
        try:
            val = tz_file.read_text(encoding="utf-8").strip()
            if val:
                return val
        except Exception:
            pass

    localtime = Path("/etc/localtime")
    if localtime.is_symlink():
        try:
            target = os.readlink(str(localtime))
            if "zoneinfo/" in target:
                return target.split("zoneinfo/", 1)[1]
        except Exception:
            pass

    return os.getenv("TZ") or "UTC"


def probe_docker_status() -> Dict[str, Any]:
    """Checks whether Docker Engine and Docker Compose plugin are installed and running."""
    docker_bin = shutil.which("docker")
    compose_installed = False
    daemon_running = False
    docker_version = "Not installed"

    if docker_bin:
        try:
            cmd = subprocess.run([docker_bin, "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, timeout=5)
            if cmd.returncode == 0:
                daemon_running = True
                docker_version = cmd.stdout.strip()
        except Exception:
            pass

        try:
            comp_cmd = subprocess.run([docker_bin, "compose", "version"], capture_output=True, text=True, timeout=5)
            if comp_cmd.returncode == 0:
                compose_installed = True
        except Exception:
            pass

    return {
        "installed": docker_bin is not None,
        "daemon_running": daemon_running,
        "compose_installed": compose_installed,
        "version": docker_version,
    }


def get_system_snapshot() -> Dict[str, Any]:
    """Returns a comprehensive, reactive hardware and OS snapshot."""
    return {
        "cpu": probe_cpu_info(),
        "ram": probe_ram_info(),
        "hwaccel": probe_hardware_acceleration(),
        "user": probe_host_user(),
        "timezone": probe_timezone(),
        "docker": probe_docker_status(),
        "disks": get_disk_partitions(),
        "network": probe_network_interfaces(),
        "ports": get_default_ports(),
        "os_info": {
            "system": platform.system(),
            "release": platform.release(),
            "hostname": platform.node(),
        },
    }


def generate_ai_context_dump(snapshot: Dict[str, Any]) -> str:
    """
    Generates a dense, token-optimized context prompt (~300 tokens)
    tailored for ChatGPT, Claude, Cursor, and Antigravity.
    """
    cpu = snapshot["cpu"]
    ram = snapshot["ram"]
    hw = snapshot["hwaccel"]
    user = snapshot["user"]
    net = snapshot["network"]
    disks = snapshot["disks"]
    dock = snapshot["docker"]

    disk_summary = ", ".join([f"{d['mount_point']} ({d['total_gb']}GB total, {d['free_gb']}GB free)" for d in disks[:4]])
    ram_text = (
        f"{ram['total_gib']} GiB total ({ram['free_gib']} GiB available)"
        if ram.get("total_gib") is not None
        else "Unavailable"
    )
    hdd_data = os.getenv("HDD_DATA", "/mnt/hdd/data")

    return f"""# Homelab Node Diagnostic Snapshot (Token-Optimized)
- Host: {snapshot.get('os_info', {}).get('hostname', 'unknown')} ({snapshot.get('os_info', {}).get('system', 'Linux')} {snapshot.get('os_info', {}).get('release', '')})
- CPU: {cpu['model']} ({cpu['threads']}T, {cpu['architecture']}) | Low-Power: {cpu['is_low_power']} | Playback: {cpu['recommended_playback']}
- Memory: {ram_text}
- HW Acceleration: {', '.join(hw['details'])} (mode: {hw.get('recommended_mode', 'direct_play')})
- Host User: {user['username']} (PUID={user['puid']}, PGID={user['pgid']})
- Network: IP={net['current_ip']} on {net['active_nic']} | Gateway={net['default_gateway']} | DNS={', '.join(net['dns_servers'])}
- Storage Mounts: {disk_summary or 'No physical mounts detected'}
- Docker: Engine={dock['version']} | Daemon Running={dock['daemon_running']} | Compose={dock['compose_installed']}

## Architectural Invariants Reference:
1. STORAGE_AND_HARDLINKS.md: Downloaders & library managers MUST share a single mount ({hdd_data}:/data) for 0-I/O atomic hardlinks.
2. Playback & Transcoding: Use hardware decode ({hw.get('recommended_mode', 'direct_play')}) or Direct Play on legacy CPUs lacking HEVC 10-bit decode.
3. POWER_MANAGEMENT_RTCWAKE.md: Optional ACPI S3 sleep defers automatically for active backups, SMB shares, qBittorrent downloads, and Jellyfin playback.
4. NETPLAN_STATIC_IP_QUIRKS.md: Never run raw `netplan apply` over SSH; apply via `netplan_manager.py` with the 120s `homelab-netplan-revert` confirm timer.
"""

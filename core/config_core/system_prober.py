"""
Comprehensive System Prober & AI Context Generator
Probes CPU/GPU, RAM, Host User IDs, Docker status, Disks, and Network.
"""

import os
import sys
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Any

from .storage_manager import get_disk_partitions
from .netplan_manager import probe_network_interfaces
from .port_manager import get_default_ports


def probe_cpu_info() -> Dict[str, Any]:
    """Detects CPU model, core/thread count, architecture, and Haswell/Direct Play class"""
    model_name = ""
    cores = os.cpu_count() or 2
    arch = platform.machine()
    is_low_power = False

    # 1. Linux /proc/cpuinfo
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

    # 2. Windows registry fallback for clean processor brand string
    if not model_name and sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            model_name = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except Exception:
            pass

    # 3. macOS sysctl fallback
    if not model_name and sys.platform == "darwin":
        try:
            res = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                model_name = res.stdout.strip()
        except Exception:
            pass

    if not model_name:
        model_name = platform.processor() or f"{arch} Host Processor"

    # Detect older low-power architectures (e.g. Haswell, Broadwell, Celeron, Atom)
    model_lower = model_name.lower()
    if any(k in model_lower for k in ["i3-4", "i5-4", "haswell", "celeron", "atom", "j1900", "n5105", "n100"]):
        is_low_power = True

    return {
        "model": model_name,
        "threads": cores,
        "cores": cores,
        "architecture": arch,
        "is_low_power": is_low_power,
        "recommended_playback": "Direct Play (CPU Protection)" if is_low_power else "Intel QuickSync / Hardware Transcode",
    }


def probe_ram_info() -> Dict[str, Any]:
    """Detects total memory and available memory in GiB across Linux, Windows, or macOS"""
    total_gib = 8.0
    free_gib = 4.0

    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        try:
            with open(meminfo, "r") as f:
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
            total_gib = round(s.ullTotalPhys / (1024**3), 2)
            free_gib = round(s.ullAvailPhys / (1024**3), 2)
        except Exception:
            pass

    return {
        "total_gib": total_gib,
        "free_gib": free_gib,
        "is_constrained": total_gib < 8.0,
    }


def probe_hardware_acceleration() -> Dict[str, Any]:
    """Inspects Linux DRI render nodes (/dev/dri/renderD128) and NVIDIA drivers"""
    has_vaapi_dri = False
    has_nvidia = False
    details = []

    render_node = Path("/dev/dri/renderD128")
    if render_node.exists():
        has_vaapi_dri = True
        details.append("/dev/dri/renderD128 (Intel QuickSync / VAAPI available)")

    card_node = Path("/dev/dri/card0")
    if card_node.exists() and not has_vaapi_dri:
        has_vaapi_dri = True
        details.append("/dev/dri/card0 (Direct Rendering Manager active)")

    if shutil.which("nvidia-smi"):
        has_nvidia = True
        details.append("NVIDIA Driver detected (nvidia-smi present)")

    if not details:
        details.append("No dedicated GPU render node detected (CPU Direct Play will be used)")

    return {
        "has_vaapi_dri": has_vaapi_dri,
        "has_nvidia": has_nvidia,
        "details": details,
        "recommended_mode": "qsv" if has_vaapi_dri else ("nvidia" if has_nvidia else "direct_play"),
    }


def probe_host_user() -> Dict[str, Any]:
    """
    Identifies the ideal non-root user running Docker.
    Checks SUDO_USER, logname, or user with UID 1000.
    """
    username = os.getenv("SUDO_USER") or os.getenv("USER") or "homelab_user"
    puid = 1000
    pgid = 1000

    if hasattr(os, "getuid"):
        current_uid = os.getuid()
        current_gid = os.getgid()
        # If running via sudo (UID 0), prefer SUDO_USER's IDs
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
        else:
            puid = current_uid
            pgid = current_gid

    return {
        "username": username,
        "puid": puid,
        "pgid": pgid,
    }


def probe_timezone() -> str:
    """Detects server timezone from /etc/timezone or /etc/localtime symlink"""
    tz_file = Path("/etc/timezone")
    if tz_file.exists():
        try:
            val = tz_file.read_text().strip()
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

    return "Asia/Kolkata"


def probe_docker_status() -> Dict[str, Any]:
    """Checks whether Docker Engine and Docker Compose plugin are installed and running"""
    docker_bin = shutil.which("docker")
    compose_installed = False
    daemon_running = False
    docker_version = "Not installed"

    if docker_bin:
        # Check daemon status
        try:
            cmd = subprocess.run([docker_bin, "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, timeout=5)
            if cmd.returncode == 0:
                daemon_running = True
                docker_version = cmd.stdout.strip()
        except Exception:
            pass

        # Check docker compose plugin
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
    """Returns a comprehensive, reactive hardware and OS snapshot"""
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

    disk_summary = ", ".join([f"{d['mount_point']} ({d['total_gb']}GB total, {d['free_gb']}GB free)" for d in disks[:3]])

    return f"""# Homelab Node Diagnostic Snapshot (Token-Optimized)
- CPU: {cpu['model']} ({cpu['threads']}T, {cpu['architecture']}) | Low-Power: {cpu['is_low_power']}
- Memory: {ram['total_gib']} GiB total ({ram['free_gib']} GiB available)
- HW Acceleration: {', '.join(hw['details'])}
- Host User: {user['username']} (PUID={user['puid']}, PGID={user['pgid']})
- Network: IP={net['current_ip']} on {net['active_nic']} | Gateway={net['default_gateway']} | DNS={', '.join(net['dns_servers'])}
- Storage Mounts: {disk_summary or 'No physical mounts detected'}
- Docker: Engine={dock['version']} | Daemon Running={dock['daemon_running']} | Compose={dock['compose_installed']}

## Monorepo Rules Reference:
1. STORAGE_AND_HARDLINKS.md: Torrents & Media MUST share single-mount root (/mnt/hdd/data:/data).
2. HASWELL_DIRECT_PLAY_GUIDE.md: Direct Play enforced on older CPUs (<1.5% CPU vs 100% transcode lock).
3. POWER_MANAGEMENT_RTCWAKE.md: S3 sleep 00:00 - 06:00 (1.2W) with rclone/backup active deferral.
4. NETPLAN_STATIC_IP_QUIRKS.md: Use 'netplan try --timeout 45' to prevent SSH lockout.
"""

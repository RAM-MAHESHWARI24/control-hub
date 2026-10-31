"""
ServerFF Control Hub - Telemetry Background Sampler
Continuous 1-second sampling of NIC throughput, qBittorrent bandwidth/queue,
disk I/O operations (/proc/diskstats), SMB client sessions, and CPU utilization.
"""

import os
import sys
import time
import platform
import threading
import subprocess
from pathlib import Path
import requests

from config import (
    ACTIVE_NIC, LINK_SPEED_MBPS,
    QBITTORRENT_URL, QBITTORRENT_USER, QBITTORRENT_PASS
)

def get_cpu_hardware_specs():
    """Detects host CPU model and core/thread count dynamically across all architectures"""
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

def detect_active_nic(preferred_nic=None):
    """
    Returns preferred_nic if valid and present in /proc/net/dev,
    otherwise auto-detects the first physical non-virtual network interface.
    """
    proc_net = Path("/proc/net/dev")
    if not proc_net.exists():
        return preferred_nic or "eth0"

    interfaces = []
    try:
        with open(proc_net, "r") as f:
            lines = f.readlines()[2:]
            for line in lines:
                if ":" in line:
                    iface = line.split(":")[0].strip()
                    if iface == "lo" or iface.startswith(("docker", "veth", "br-", "tailscale", "tun")):
                        continue
                    interfaces.append(iface)
    except Exception:
        pass

    if preferred_nic and preferred_nic in interfaces:
        return preferred_nic

    return interfaces[0] if interfaces else (preferred_nic or "eth0")

def detect_storage_devices():
    """
    Detects root disk block device and media data disk block device dynamically.
    Returns (root_dev, data_dev, target_data_mount).
    """
    root_dev = None
    data_dev = None
    hdd_mount_path = os.getenv("HDD_DATA", "/mnt/hdd/data")
    if "/data" in hdd_mount_path and hdd_mount_path != "/data":
        target_data_mount = hdd_mount_path.rsplit("/data", 1)[0]
    else:
        target_data_mount = hdd_mount_path

    proc_mounts = Path("/proc/mounts")
    if proc_mounts.exists():
        try:
            with open(proc_mounts, "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        dev_path, mnt_point = parts[0], parts[1]
                        if dev_path.startswith("/dev/"):
                            raw_dev = dev_path.replace("/dev/", "")
                            base_dev = raw_dev
                            if "nvme" in raw_dev or "mmcblk" in raw_dev:
                                if "p" in raw_dev:
                                    base_dev = raw_dev.split("p")[0]
                            else:
                                base_dev = raw_dev.rstrip("0123456789")

                            if mnt_point == "/":
                                root_dev = base_dev
                            elif mnt_point == target_data_mount or mnt_point == "/mnt/hdd":
                                data_dev = base_dev
        except Exception:
            pass

    if not root_dev or not data_dev:
        proc_diskstats = Path("/proc/diskstats")
        if proc_diskstats.exists():
            try:
                found_disks = []
                with open(proc_diskstats, "r") as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 3:
                            dev = parts[2]
                            if dev.startswith(("loop", "ram", "dm-")):
                                continue
                            if ("nvme" in dev and "p" in dev) or ("mmcblk" in dev and "p" in dev):
                                continue
                            if any(dev.startswith(prefix) for prefix in ["sd", "vd", "hd", "xvd", "nvme", "mmcblk"]):
                                if dev not in found_disks and not (dev[-1].isdigit() and not ("nvme" in dev or "mmcblk" in dev)):
                                    found_disks.append(dev)

                if not root_dev and found_disks:
                    root_dev = found_disks[1] if len(found_disks) > 1 else found_disks[0]
                if not data_dev and found_disks:
                    data_dev = found_disks[0]
            except Exception:
                pass

    root_dev = root_dev or "sdb"
    data_dev = data_dev or "sda"

    return root_dev, data_dev, target_data_mount

CPU_SPECS = get_cpu_hardware_specs()
DETECTED_ROOT_DEV, DETECTED_DATA_DEV, DETECTED_DATA_MOUNT = detect_storage_devices()
DETECTED_NIC = detect_active_nic(ACTIVE_NIC)

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
        "link_speed_mbps": LINK_SPEED_MBPS,
        "gauge_percent": 0.0,
        "updated_at": 0
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
        "connection_status": "connected",
        "dht_nodes": 0,
        "gauge_percent": 0.0,
        "active_downloads": 0,
        "active_torrents": 0,
        "updated_at": 0
    },
    "torrents_queue": {
        "collective_dl_mbps": 0.0,
        "collective_up_mbps": 0.0,
        "collective_total_mbps": 0.0,
        "collective_dl_mbs": 0.0,
        "collective_up_mbs": 0.0,
        "collective_total_mbs": 0.0,
        "active_count": 0,
        "total_count": 0,
        "items": []
    },
    "storage_ops": {
        "collective_mbps": 0.0,
        "total_read_mbps": 0.0,
        "total_write_mbps": 0.0,
        "collective_mbs": 0.0,
        "total_read_mbs": 0.0,
        "total_write_mbs": 0.0,
        "hdd": {
            "device": DETECTED_DATA_DEV,
            "read_mbps": 0.0,
            "write_mbps": 0.0,
            "read_mbs": 0.0,
            "write_mbs": 0.0,
            "name": f"Media Storage ({DETECTED_DATA_MOUNT} - {DETECTED_DATA_DEV})"
        },
        "ssd": {
            "device": DETECTED_ROOT_DEV,
            "read_mbps": 0.0,
            "write_mbps": 0.0,
            "read_mbs": 0.0,
            "write_mbs": 0.0,
            "name": f"OS Root (/ - {DETECTED_ROOT_DEV})"
        },
        "smb_clients": [],
        "jellyfin_streams": []
    },
    "cpu": {
        "usage_percent": 0.0,
        "cores": CPU_SPECS["cores"],
        "threads": CPU_SPECS["threads"],
        "model": CPU_SPECS["model"],
        "temp_c": None
    }
}

# Persistent qBittorrent HTTP Session
qb_session = requests.Session()
qb_logged_in = False

def qb_login():
    """Authenticates the persistent session with qBittorrent WebUI"""
    global qb_logged_in
    try:
        resp = qb_session.post(
            f"{QBITTORRENT_URL}/api/v2/auth/login",
            data={"username": QBITTORRENT_USER, "password": QBITTORRENT_PASS},
            timeout=3
        )
        if resp.status_code == 200 and "Ok." in resp.text:
            qb_logged_in = True
            return True
    except Exception:
        pass
    qb_logged_in = False
    return False

def format_eta(seconds, state):
    """Converts ETA seconds to readable format"""
    if state and "stalled" in state.lower():
        return "Stalled (Waiting for seeds)"
    if state and "paused" in state.lower():
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
    """Parses active Samba connections via smbstatus"""
    sessions = []
    try:
        proc = subprocess.run(["sudo", "smbstatus", "-S"], stdout=subprocess.PIPE, text=True, timeout=1.5)
        for line in proc.stdout.split("\n"):
            if "RootFS" in line or "MediaDrive" in line:
                parts = line.split()
                if len(parts) >= 3:
                    sessions.append({
                        "share": parts[0],
                        "ip": parts[2],
                        "connected_at": " ".join(parts[3:7]) if len(parts) >= 7 else "Connected"
                    })
    except Exception:
        pass
    return sessions

def get_jellyfin_streams():
    """Detects active video playback streams on port 8096"""
    streams = []
    try:
        proc = subprocess.run(["ss", "-tn", "sport = :8096"], stdout=subprocess.PIPE, text=True, timeout=1.2)
        for line in proc.stdout.split("\n"):
            if "ESTAB" in line:
                parts = line.split()
                if len(parts) >= 5:
                    peer = parts[4]
                    peer_ip = peer.split(":")[0].replace("[", "").replace("]", "")
                    if peer_ip not in ["127.0.0.1", "::1"]:
                        streams.append({
                            "client_ip": peer_ip,
                            "type": "Direct Stream / Video Playback",
                            "status": "Streaming Active"
                        })
    except Exception:
        pass
    return streams

def get_nic_link_info(iface):
    """Dynamically reads negotiated link speed (Mbps) and duplex from /sys/class/net"""
    speed_mbps = 100
    duplex = "full"
    try:
        speed_path = f"/sys/class/net/{iface}/speed"
        if os.path.exists(speed_path):
            with open(speed_path, "r") as f:
                val = int(f.read().strip())
                if val > 0:
                    speed_mbps = val
    except Exception:
        pass

    try:
        duplex_path = f"/sys/class/net/{iface}/duplex"
        if os.path.exists(duplex_path):
            with open(duplex_path, "r") as f:
                d = f.read().strip()
                if d:
                    duplex = d
    except Exception:
        pass

    if speed_mbps >= 1000:
        gbps_val = round(speed_mbps / 1000.0, 1)
        spec_text = f"{gbps_val if gbps_val % 1 != 0 else int(gbps_val)} Gbps {duplex.capitalize()}-Duplex"
    else:
        spec_text = f"{speed_mbps} Mbps {duplex.capitalize()}-Duplex"

    return speed_mbps, duplex, spec_text

def telemetry_worker():
    """Continuously samples NIC, disk stats, CPU, and qBittorrent at 1-second intervals"""
    active_iface = DETECTED_NIC
    prev_rx = 0
    prev_tx = 0
    prev_time = time.time()

    # Initial NIC counters
    try:
        with open("/proc/net/dev", "r") as f:
            for line in f:
                if active_iface in line:
                    parts = line.replace(f"{active_iface}:", "").split()
                    prev_rx = int(parts[0])
                    prev_tx = int(parts[8])
                    break
    except Exception:
        pass

    # Initial CPU counters
    prev_cpu_idle = 0
    prev_cpu_total = 0
    try:
        with open("/proc/stat", "r") as f:
            fields = [float(column) for column in f.readline().strip().split()[1:]]
            prev_cpu_idle = fields[3] + fields[4]
            prev_cpu_total = sum(fields)
    except Exception:
        pass

    # Initial diskstat counters for detected storage devices
    prev_data_r = 0
    prev_data_w = 0
    prev_root_r = 0
    prev_root_w = 0
    try:
        with open("/proc/diskstats", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 10:
                    if parts[2] == DETECTED_DATA_DEV:
                        prev_data_r = int(parts[5])
                        prev_data_w = int(parts[9])
                    elif parts[2] == DETECTED_ROOT_DEV:
                        prev_root_r = int(parts[5])
                        prev_root_w = int(parts[9])
    except Exception:
        pass

    while True:
        try:
            now = time.time()
            dt = max(0.1, now - prev_time)

            # 1. Sample Network Interface Throughput
            rx_rate = 0
            tx_rate = 0
            try:
                with open("/proc/net/dev", "r") as f:
                    for line in f:
                        if active_iface in line:
                            parts = line.replace(f"{active_iface}:", "").split()
                            cur_rx = int(parts[0])
                            cur_tx = int(parts[8])
                            rx_rate = max(0, (cur_rx - prev_rx) / dt)
                            tx_rate = max(0, (cur_tx - prev_tx) / dt)
                            prev_rx = cur_rx
                            prev_tx = cur_tx
                            break
            except Exception:
                pass

            rx_mbps = (rx_rate * 8) / 1_000_000.0
            tx_mbps = (tx_rate * 8) / 1_000_000.0
            rx_mbs = rx_rate / 1_048_576.0
            tx_mbs = tx_rate / 1_048_576.0
            total_lan_mbps = rx_mbps + tx_mbps
            link_speed, nic_duplex, nic_spec_text = get_nic_link_info(active_iface)
            lan_gauge_pct = min(100.0, (total_lan_mbps / max(1, link_speed)) * 100.0)

            # 2. Sample CPU Usage
            cpu_usage_pct = 0.0
            try:
                with open("/proc/stat", "r") as f:
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

            # CPU Temperature (Core 0 / Package)
            cpu_temp = None
            try:
                for zone in ["/sys/class/thermal/thermal_zone0/temp", "/sys/class/thermal/thermal_zone1/temp"]:
                    if os.path.exists(zone):
                        with open(zone, "r") as tf:
                            raw_t = int(tf.read().strip())
                            if raw_t > 1000:
                                cpu_temp = round(raw_t / 1000.0, 1)
                                break
            except Exception:
                pass

            # 3. Sample Internet Speed via qBittorrent Transfer API & Torrent Queue
            dl_speed = 0
            up_speed = 0
            conn_status = "offline"
            dht_nodes = 0
            active_dl_count = 0
            active_torrents_count = 0
            torrent_items = []

            try:
                resp = qb_session.get(f"{QBITTORRENT_URL}/api/v2/transfer/info", timeout=1.5)
                if resp.status_code == 403:
                    qb_login()
                    resp = qb_session.get(f"{QBITTORRENT_URL}/api/v2/transfer/info", timeout=1.5)

                if resp.status_code == 200:
                    data = resp.json()
                    dl_speed = data.get("dl_info_speed", 0)
                    up_speed = data.get("up_info_speed", 0)
                    conn_status = data.get("connection_status", "connected")
                    dht_nodes = data.get("dht_nodes", 0)

                    # Detailed Torrent Pipeline List
                    all_resp = qb_session.get(f"{QBITTORRENT_URL}/api/v2/torrents/info?filter=all", timeout=1.8)
                    if all_resp.status_code == 200:
                        raw_list = all_resp.json()
                        active_torrents_count = len(raw_list)
                        for t in raw_list:
                            t_dl = t.get("dlspeed", 0)
                            t_up = t.get("upspeed", 0)
                            t_state = t.get("state", "")
                            t_prog = t.get("progress", 0)

                            if "DL" in t_state or "download" in t_state.lower() or t_dl > 0:
                                active_dl_count += 1

                            size_b = t.get("size", 0)
                            comp_b = t.get("completed", 0)
                            size_gb = round(size_b / (1024**3), 2)
                            comp_gb = round(comp_b / (1024**3), 2)

                            torrent_items.append({
                                "name": t.get("name", "Unknown"),
                                "hash": t.get("hash", ""),
                                "state": t_state,
                                "category": t.get("category", "General"),
                                "progress": round(t_prog * 100, 1),
                                "dl_mbps": round((t_dl * 8) / 1_000_000.0, 2),
                                "up_mbps": round((t_up * 8) / 1_000_000.0, 2),
                                "dl_mbs": round(t_dl / 1_048_576.0, 2),
                                "up_mbs": round(t_up / 1_048_576.0, 2),
                                "size_gb": size_gb,
                                "completed_gb": comp_gb,
                                "eta": format_eta(t.get("eta", 0), t_state)
                            })
            except Exception:
                pass

            dl_mbps = (dl_speed * 8) / 1_000_000.0
            up_mbps = (up_speed * 8) / 1_000_000.0
            dl_mbs = dl_speed / 1_048_576.0
            up_mbs = up_speed / 1_048_576.0
            total_wan_mbps = dl_mbps + up_mbps
            total_wan_mbs = dl_mbs + up_mbs
            wan_gauge_pct = min(100.0, (total_wan_mbps / 100.0) * 100.0)

            # 4. Sample Disk I/O (/proc/diskstats) for dynamic block devices
            data_r_mbps = 0.0
            data_w_mbps = 0.0
            root_r_mbps = 0.0
            root_w_mbps = 0.0
            data_r_mbs = 0.0
            data_w_mbs = 0.0
            root_r_mbs = 0.0
            root_w_mbs = 0.0
            try:
                with open("/proc/diskstats", "r") as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 10:
                            dev = parts[2]
                            if dev == DETECTED_DATA_DEV:
                                cur_r = int(parts[5])
                                cur_w = int(parts[9])
                                data_r_mbps = max(0.0, round(((cur_r - prev_data_r) * 512 * 8) / (dt * 1_000_000.0), 2))
                                data_w_mbps = max(0.0, round(((cur_w - prev_data_w) * 512 * 8) / (dt * 1_000_000.0), 2))
                                data_r_mbs = max(0.0, round(((cur_r - prev_data_r) * 512) / (dt * 1_048_576.0), 2))
                                data_w_mbs = max(0.0, round(((cur_w - prev_data_w) * 512) / (dt * 1_048_576.0), 2))
                                prev_data_r = cur_r
                                prev_data_w = cur_w
                            elif dev == DETECTED_ROOT_DEV:
                                cur_r = int(parts[5])
                                cur_w = int(parts[9])
                                root_r_mbps = max(0.0, round(((cur_r - prev_root_r) * 512 * 8) / (dt * 1_000_000.0), 2))
                                root_w_mbps = max(0.0, round(((cur_w - prev_root_w) * 512 * 8) / (dt * 1_000_000.0), 2))
                                root_r_mbs = max(0.0, round(((cur_r - prev_root_r) * 512) / (dt * 1_048_576.0), 2))
                                root_w_mbs = max(0.0, round(((cur_w - prev_root_w) * 512) / (dt * 1_048_576.0), 2))
                                prev_root_r = cur_r
                                prev_root_w = cur_w
            except Exception:
                pass

            total_disk_read_mbps = round(data_r_mbps + root_r_mbps, 2)
            total_disk_write_mbps = round(data_w_mbps + root_w_mbps, 2)
            collective_storage_mbps = round(total_disk_read_mbps + total_disk_write_mbps, 2)

            total_disk_read_mbs = round(data_r_mbs + root_r_mbs, 2)
            total_disk_write_mbs = round(data_w_mbs + root_w_mbs, 2)
            collective_storage_mbs = round(total_disk_read_mbs + total_disk_write_mbs, 2)

            # Sample SMB and Jellyfin every 3 seconds
            if int(now) % 3 == 0:
                smb_clients = get_smb_sessions()
                jellyfin_streams = get_jellyfin_streams()
            else:
                smb_clients = telemetry_state.get("storage_ops", {}).get("smb_clients", [])
                jellyfin_streams = telemetry_state.get("storage_ops", {}).get("jellyfin_streams", [])

            # Update shared state
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
                    "gauge_percent": round(lan_gauge_pct, 1),
                    "updated_at": now
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
                    "gauge_percent": round(wan_gauge_pct, 1),
                    "active_downloads": active_dl_count,
                    "active_torrents": active_torrents_count,
                    "updated_at": now
                }
                telemetry_state["torrents_queue"] = {
                    "collective_dl_mbps": round(dl_mbps, 2),
                    "collective_up_mbps": round(up_mbps, 2),
                    "collective_total_mbps": round(total_wan_mbps, 2),
                    "collective_dl_mbs": round(dl_mbs, 2),
                    "collective_up_mbs": round(up_mbs, 2),
                    "collective_total_mbs": round(total_wan_mbs, 2),
                    "active_count": active_dl_count,
                    "total_count": active_torrents_count,
                    "items": torrent_items
                }
                telemetry_state["storage_ops"] = {
                    "collective_mbps": collective_storage_mbps,
                    "total_read_mbps": total_disk_read_mbps,
                    "total_write_mbps": total_disk_write_mbps,
                    "collective_mbs": collective_storage_mbs,
                    "total_read_mbs": total_disk_read_mbs,
                    "total_write_mbs": total_disk_write_mbs,
                    "hdd": {
                        "device": DETECTED_DATA_DEV,
                        "read_mbps": data_r_mbps,
                        "write_mbps": data_w_mbps,
                        "read_mbs": data_r_mbs,
                        "write_mbs": data_w_mbs,
                        "name": f"Media Storage ({DETECTED_DATA_MOUNT} - {DETECTED_DATA_DEV})"
                    },
                    "ssd": {
                        "device": DETECTED_ROOT_DEV,
                        "read_mbps": root_r_mbps,
                        "write_mbps": root_w_mbps,
                        "read_mbs": root_r_mbs,
                        "write_mbs": root_w_mbs,
                        "name": f"OS Root (/ - {DETECTED_ROOT_DEV})"
                    },
                    "smb_clients": smb_clients,
                    "jellyfin_streams": jellyfin_streams
                }
                telemetry_state["cpu"] = {
                    "usage_percent": cpu_usage_pct,
                    "cores": CPU_SPECS["cores"],
                    "threads": CPU_SPECS["threads"],
                    "model": CPU_SPECS["model"],
                    "temp_c": cpu_temp
                }

            prev_time = now
            time.sleep(1.0)
        except Exception:
            time.sleep(1.0)

def start_telemetry_sampler():
    """Starts the persistent background sampler thread"""
    threading.Thread(target=qb_login, daemon=True).start()
    t = threading.Thread(target=telemetry_worker, daemon=True)
    t.start()
    return t

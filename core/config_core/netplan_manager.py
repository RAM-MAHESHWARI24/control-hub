"""
Ubuntu Netplan static-IP manager with a real confirm-or-revert safety net.

Why not `netplan try`?  `netplan try` only reverts when the *same process*
fails to receive a confirmation keypress. A web daemon cannot press Enter,
and the previous implementation fed it a newline immediately, which
confirmed the change at once and made the "rollback" a no-op.

How this works instead:

1. Back up every existing /etc/netplan/*.yaml into a timestamped directory.
2. Write 99-homelab-blueprint.yaml and validate it with `netplan generate`.
3. Arm a one-shot systemd timer (`homelab-netplan-revert`) that restores the
   backup and runs `netplan apply` after `timeout_sec` seconds.
4. Run `netplan apply`.
5. The caller (wizard or Control Hub UI) reaches the daemon on the NEW
   address and calls `confirm_netplan_change()`, which disarms the timer.
   If nobody confirms, the host automatically returns to the old network
   configuration and the operator's SSH/web session comes back.

All subprocess calls carry explicit timeouts.
"""

import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

REVERT_UNIT = "homelab-netplan-revert"
TARGET_FILENAME = "99-homelab-blueprint.yaml"
DEFAULT_TIMEOUT_SEC = 120
PENDING_STATE_FILE = Path(os.getenv("HOMELAB_STATE_DIR", "/var/lib/homelab")) / "netplan-pending.json"
REVERT_SCRIPT = Path("/usr/local/sbin/homelab-netplan-revert.sh")


def probe_network_interfaces() -> Dict[str, Any]:
    """
    Detects network interfaces, active LAN IP, default gateway, and nameservers.
    Inspects Linux /sys/class/net, /proc/net/route, and resolv.conf.
    Never assumes an interface name such as eth0; falls back to the first
    interface that is up, then to "eth0" only on non-Linux hosts.
    """
    interfaces = []
    default_ip = "127.0.0.1"
    active_nic = ""
    gateway = ""
    dns_servers: List[str] = []

    # 1. Primary outbound IP via UDP socket probe (no packets are sent)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 80))
            default_ip = s.getsockname()[0]
    except Exception:
        pass

    # 2. Interfaces from /sys/class/net
    sys_net = Path("/sys/class/net")
    if sys_net.exists():
        for iface_path in sorted(sys_net.iterdir()):
            iface_name = iface_path.name
            if iface_name == "lo" or iface_name.startswith(("docker", "veth", "br-", "tailscale", "virbr")):
                continue

            speed_mbps = 1000
            speed_file = iface_path / "speed"
            if speed_file.exists():
                try:
                    val = int(speed_file.read_text().strip())
                    if val > 0:
                        speed_mbps = val
                except Exception:
                    pass

            is_up = False
            operstate_file = iface_path / "operstate"
            if operstate_file.exists():
                try:
                    is_up = operstate_file.read_text().strip() == "up"
                except Exception:
                    pass

            interfaces.append({"name": iface_name, "is_up": is_up, "speed_mbps": speed_mbps})

    # 3. Default route → active NIC and gateway
    route_file = Path("/proc/net/route")
    if route_file.exists():
        try:
            with open(route_file, "r") as f:
                for line in f:
                    fields = line.strip().split()
                    if len(fields) >= 3 and fields[1] == "00000000":
                        active_nic = fields[0]
                        hex_gw = fields[2]
                        if len(hex_gw) == 8:
                            b = [int(hex_gw[i:i + 2], 16) for i in (6, 4, 2, 0)]
                            gateway = ".".join(map(str, b))
                        break
        except Exception:
            pass

    # 4. DNS from resolv.conf (skipping the systemd-resolved stub)
    resolv_file = Path("/etc/resolv.conf")
    if resolv_file.exists():
        try:
            with open(resolv_file, "r") as f:
                for line in f:
                    if line.startswith("nameserver"):
                        parts = line.strip().split()
                        if len(parts) >= 2 and not parts[1].startswith("127.0.0."):
                            dns_servers.append(parts[1])
        except Exception:
            pass

    if not active_nic:
        up = [i["name"] for i in interfaces if i["is_up"]]
        active_nic = up[0] if up else (interfaces[0]["name"] if interfaces else "eth0")
    if not interfaces:
        interfaces.append({"name": active_nic, "is_up": True, "speed_mbps": 1000})
    if not gateway:
        # Best-effort guess: x.y.z.1 on the detected subnet
        parts = default_ip.split(".")
        gateway = ".".join(parts[:3] + ["1"]) if len(parts) == 4 and default_ip != "127.0.0.1" else "192.168.1.1"
    if not dns_servers:
        dns_servers = ["1.1.1.1", "8.8.8.8"]

    return {
        "active_nic": active_nic,
        "current_ip": default_ip,
        "default_gateway": gateway,
        "dns_servers": dns_servers[:2],
        "interfaces": interfaces,
    }


def generate_netplan_yaml(interface: str, ip_with_cidr: str, gateway: str, dns_servers: List[str]) -> str:
    """Generates Netplan v2 YAML for a single static-IP ethernet interface."""
    dns_formatted = ", ".join(f'"{d.strip()}"' for d in dns_servers if d.strip())
    return f"""# Generated by Homelab Blueprint
network:
  version: 2
  renderer: networkd
  ethernets:
    {interface}:
      dhcp4: false
      addresses:
        - {ip_with_cidr}
      routes:
        - to: default
          via: {gateway}
      nameservers:
        addresses: [{dns_formatted}]
"""


def backup_netplan_configs(netplan_dir: str = "/etc/netplan") -> Optional[str]:
    """Copies all *.yaml in the netplan dir into a timestamped backup folder."""
    p = Path(netplan_dir)
    if not p.exists():
        return None

    backup_dir = p / f"backup_{int(time.time())}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for item in p.glob("*.yaml"):
        if item.is_file():
            shutil.copy2(item, backup_dir / item.name)
            copied += 1
    return str(backup_dir) if copied > 0 else str(backup_dir)


def _run(cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _write_revert_script(backup_dir: str, netplan_dir: str, target_file: Path) -> Path:
    """Writes the shell script the revert timer executes."""
    script = f"""#!/usr/bin/env bash
# Auto-generated by Homelab Blueprint: restores the previous Netplan configuration
# if a static IP change was not confirmed in time.
set -euo pipefail
rm -f "{target_file}"
if [ -d "{backup_dir}" ]; then
  for f in "{backup_dir}"/*.yaml; do
    [ -e "$f" ] && cp -f "$f" "{netplan_dir}/"
  done
fi
netplan apply
rm -f "{PENDING_STATE_FILE}"
"""
    REVERT_SCRIPT.parent.mkdir(parents=True, exist_ok=True)
    REVERT_SCRIPT.write_text(script, encoding="utf-8")
    os.chmod(REVERT_SCRIPT, 0o700)
    return REVERT_SCRIPT


def _arm_revert_timer(timeout_sec: int) -> subprocess.CompletedProcess:
    """Schedules the revert script via a transient systemd timer."""
    # Clear any previous pending revert first.
    _run(["systemctl", "stop", f"{REVERT_UNIT}.timer"], timeout=15)
    return _run(
        [
            "systemd-run",
            f"--unit={REVERT_UNIT}",
            f"--on-active={timeout_sec}",
            "--timer-property=AccuracySec=1s",
            str(REVERT_SCRIPT),
        ],
        timeout=15,
    )


def safe_apply_netplan(
    interface: str,
    ip_address: str,
    cidr: int = 24,
    gateway: str = "192.168.1.1",
    dns_servers: Optional[List[str]] = None,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    netplan_dir: str = "/etc/netplan",
    target_filename: str = TARGET_FILENAME,
) -> Dict[str, Any]:
    """
    Applies a static IP with an armed revert timer. Returns immediately after
    `netplan apply`; the change becomes permanent only when
    confirm_netplan_change() is called before `timeout_sec` elapses.
    """
    if dns_servers is None:
        dns_servers = ["1.1.1.1", "8.8.8.8"]

    ip_with_cidr = f"{ip_address}/{cidr}" if "/" not in ip_address else ip_address
    yaml_content = generate_netplan_yaml(interface, ip_with_cidr, gateway, dns_servers)
    p_dir = Path(netplan_dir)

    # Non-Linux / development hosts: simulate.
    if os.name == "nt" or not p_dir.exists() or shutil.which("netplan") is None:
        return {
            "success": True,
            "mode": "simulation",
            "applied_yaml": yaml_content,
            "ip": ip_with_cidr,
            "interface": interface,
            "message": "Netplan simulation verified (netplan not available on this host).",
        }

    backup_dir = backup_netplan_configs(netplan_dir)
    config_file = p_dir / target_filename

    try:
        config_file.write_text(yaml_content, encoding="utf-8")
        os.chmod(config_file, 0o600)

        gen = _run(["netplan", "generate"], timeout=30)
        if gen.returncode != 0:
            config_file.unlink(missing_ok=True)
            return {
                "success": False,
                "stage": "syntax_validation",
                "error": gen.stderr or gen.stdout,
                "message": "Netplan rejected the generated configuration. Nothing was applied.",
            }

        _write_revert_script(backup_dir or "", netplan_dir, config_file)
        armed = _arm_revert_timer(timeout_sec)
        if armed.returncode != 0:
            config_file.unlink(missing_ok=True)
            return {
                "success": False,
                "stage": "arm_revert",
                "error": armed.stderr or armed.stdout,
                "message": "Could not arm the automatic revert timer, so the change was not applied.",
            }

        PENDING_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PENDING_STATE_FILE.write_text(
            json.dumps(
                {
                    "ip": ip_with_cidr,
                    "interface": interface,
                    "backup_dir": backup_dir,
                    "armed_at": time.time(),
                    "timeout_sec": timeout_sec,
                }
            ),
            encoding="utf-8",
        )

        applied = _run(["netplan", "apply"], timeout=60)
        if applied.returncode != 0:
            # Revert right away rather than waiting for the timer.
            _run([str(REVERT_SCRIPT)], timeout=90)
            _run(["systemctl", "stop", f"{REVERT_UNIT}.timer"], timeout=15)
            return {
                "success": False,
                "stage": "apply",
                "error": applied.stderr or applied.stdout,
                "message": "netplan apply failed; the previous configuration was restored.",
            }

        return {
            "success": True,
            "pending": True,
            "ip": ip_with_cidr,
            "interface": interface,
            "backup_dir": backup_dir,
            "timeout_sec": timeout_sec,
            "message": (
                f"Static IP {ip_with_cidr} applied. Confirm within {timeout_sec}s or the "
                "previous network configuration is restored automatically."
            ),
        }

    except subprocess.TimeoutExpired as e:
        return {"success": False, "stage": "timeout", "error": str(e), "message": "A netplan command timed out."}
    except Exception as e:  # pragma: no cover - defensive
        return {"success": False, "stage": "exception", "error": str(e)}


def confirm_netplan_change() -> Dict[str, Any]:
    """Disarms the revert timer, making the applied configuration permanent."""
    if os.name == "nt" or shutil.which("systemctl") is None:
        return {"success": True, "mode": "simulation", "message": "Confirmed (simulation)."}

    stopped = _run(["systemctl", "stop", f"{REVERT_UNIT}.timer"], timeout=15)
    _run(["systemctl", "reset-failed", f"{REVERT_UNIT}.service"], timeout=15)
    try:
        PENDING_STATE_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    return {
        "success": stopped.returncode == 0,
        "message": "Network configuration confirmed and kept." if stopped.returncode == 0 else (stopped.stderr or stopped.stdout),
    }


def netplan_change_status() -> Dict[str, Any]:
    """Reports whether a change is pending confirmation and how long remains."""
    if not PENDING_STATE_FILE.exists():
        return {"pending": False}
    try:
        state = json.loads(PENDING_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"pending": False}
    remaining = max(0, int(state.get("armed_at", 0) + state.get("timeout_sec", 0) - time.time()))
    return {"pending": remaining > 0, "remaining_sec": remaining, **state}

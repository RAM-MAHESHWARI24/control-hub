#!/usr/bin/env python3
"""
Privileged Netplan helper for the Control Hub.

The daemon runs as the unprivileged 'homelab' user. Instead of granting it
sudo over netplan, systemd-run and file writes, sudoers allows exactly this
script, which validates its inputs and calls the shared library:

    sudo <venv-python> core/netplan_cli.py apply --interface enp3s0 --ip 192.168.1.50 \
         --gateway 192.168.1.1 --dns 1.1.1.1 --dns 8.8.8.8 [--timeout 120]
    sudo <venv-python> core/netplan_cli.py confirm
    sudo <venv-python> core/netplan_cli.py status

Output is JSON on stdout.
"""

import argparse
import ipaddress
import json
import re
import sys
from pathlib import Path

HUB_ROOT = Path(__file__).resolve().parent.parent
if str(HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(HUB_ROOT))

from core.config_core.netplan_manager import (  # noqa: E402
    confirm_netplan_change,
    netplan_change_status,
    safe_apply_netplan,
)

IFACE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")


def _valid_ip(value: str, allow_cidr: bool) -> str:
    try:
        if "/" in value:
            if not allow_cidr:
                raise ValueError("CIDR not allowed here")
            ipaddress.ip_interface(value)
        else:
            ipaddress.ip_address(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"invalid address '{value}': {e}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Control Hub privileged Netplan helper")
    sub = parser.add_subparsers(dest="command", required=True)

    apply_p = sub.add_parser("apply")
    apply_p.add_argument("--interface", required=True)
    apply_p.add_argument("--ip", required=True, type=lambda v: _valid_ip(v, allow_cidr=True))
    apply_p.add_argument("--gateway", required=True, type=lambda v: _valid_ip(v, allow_cidr=False))
    apply_p.add_argument("--dns", action="append", default=[], type=lambda v: _valid_ip(v, allow_cidr=False))
    apply_p.add_argument("--timeout", type=int, default=120)
    apply_p.add_argument("--delay", type=int, default=3,
                         help="Seconds before netplan apply runs, so the HTTP reply leaves on the old address (0 = now)")

    sub.add_parser("confirm")
    sub.add_parser("status")
    args = parser.parse_args()

    if args.command == "apply":
        if not IFACE_RE.match(args.interface):
            print(json.dumps({"success": False, "error": "invalid interface name"}))
            return 2
        timeout = max(30, min(args.timeout, 600))
        result = safe_apply_netplan(
            interface=args.interface,
            ip_address=args.ip,
            gateway=args.gateway,
            dns_servers=args.dns or ["1.1.1.1", "8.8.8.8"],
            timeout_sec=timeout,
            apply_delay_sec=max(0, min(args.delay, 30)),
        )
    elif args.command == "confirm":
        result = confirm_netplan_change()
    else:
        result = netplan_change_status()

    print(json.dumps(result))
    return 0 if result.get("success", True) else 1


if __name__ == "__main__":
    sys.exit(main())

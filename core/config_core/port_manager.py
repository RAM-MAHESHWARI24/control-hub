"""
Port Conflict Prober & Port Mapping Manager
Detects host port collisions before Docker containers are launched.
"""

import socket
from typing import Dict, Any, List

DEFAULT_PORT_CATALOG = {
    "control_hub": {
        "port": 7575,
        "name": "Control Hub Dashboard",
        "category": "system",
        "essential": True,
    },
    "jellyfin_http": {
        "port": 8096,
        "name": "Jellyfin Web & Streaming (HTTP)",
        "category": "media",
        "essential": True,
    },
    "jellyfin_https": {
        "port": 8920,
        "name": "Jellyfin HTTPS (Optional)",
        "category": "media",
        "essential": False,
    },
    "seerr": {
        "port": 5055,
        "name": "Seerr (Media Discovery)",
        "category": "media",
        "essential": True,
    },
    "qbittorrent_web": {
        "port": 8080,
        "name": "qBittorrent Web UI",
        "category": "ingest",
        "essential": True,
    },
    "qbittorrent_bt": {
        "port": 6881,
        "name": "qBittorrent Peer Listening",
        "category": "ingest",
        "essential": False,
    },
    "radarr": {
        "port": 7878,
        "name": "Radarr Movie Automation",
        "category": "ingest",
        "essential": True,
    },
    "sonarr": {
        "port": 8989,
        "name": "Sonarr TV Automation",
        "category": "ingest",
        "essential": True,
    },
    "prowlarr": {
        "port": 9696,
        "name": "Prowlarr Indexer Proxy",
        "category": "ingest",
        "essential": True,
    },
    "bazarr": {
        "port": 6767,
        "name": "Bazarr Subtitle Manager",
        "category": "ingest",
        "essential": False,
    },
    "byparr": {
        "port": 8191,
        "name": "Byparr Cloudflare Solver",
        "category": "ingest",
        "essential": False,
    },
    "noodle_gallery": {
        "port": 2283,
        "name": "Noodle Gallery / Immich Web",
        "category": "photos",
        "essential": True,
    },
    "setup_wizard": {
        "port": 8000,
        "name": "Homelab Setup Wizard",
        "category": "system",
        "essential": True,
    },
}


def check_port(port: int, host: str = "0.0.0.0") -> bool:
    """
    Returns True if the port is free to bind, False if already occupied.
    Attempts a socket bind on IPv4.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False


def get_default_ports() -> Dict[str, Any]:
    """Returns catalog of blueprint ports with current availability status"""
    catalog = {}
    for key, info in DEFAULT_PORT_CATALOG.items():
        is_free = check_port(info["port"])
        catalog[key] = {
            **info,
            "available": is_free,
            "status": "available" if is_free else "conflict",
        }
    return catalog


def check_ports_matrix(custom_ports: Dict[str, int]) -> Dict[str, Any]:
    """
    Validate a dictionary of key -> port mappings.
    Returns status report indicating whether any port is occupied.
    """
    report = {
        "all_available": True,
        "conflicts": [],
        "ports": {},
    }

    seen_ports = {}
    for service_key, port in custom_ports.items():
        try:
            port_num = int(port)
        except (ValueError, TypeError):
            report["all_available"] = False
            report["conflicts"].append({
                "service": service_key,
                "port": port,
                "error": "Invalid port number",
            })
            continue

        # Check self-collision within the configuration itself
        if port_num in seen_ports:
            report["all_available"] = False
            report["conflicts"].append({
                "service": service_key,
                "port": port_num,
                "error": f"Port collision: Already allocated to '{seen_ports[port_num]}'",
            })

        seen_ports[port_num] = service_key

        is_free = check_port(port_num)
        report["ports"][service_key] = {
            "port": port_num,
            "available": is_free,
        }

        if not is_free:
            report["all_available"] = False
            report["conflicts"].append({
                "service": service_key,
                "port": port_num,
                "error": "Port is currently in use on the host system",
            })

    return report

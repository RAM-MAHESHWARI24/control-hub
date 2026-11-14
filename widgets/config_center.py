"""
Widget: Configuration & Node Control Center

Environment settings, atomic hardlink testing, port conflict matrix,
credential generation, AI Copilot diagnostics and static-IP changes.

Static IP changes run through core/netplan_cli.py under sudo (the daemon is
unprivileged); the change is applied with an armed revert timer and must be
confirmed from the new address within the timeout.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from flask import Blueprint, jsonify, request

HUB_ROOT = Path(__file__).resolve().parent.parent
if str(HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(HUB_ROOT))

from core.config_core import (  # noqa: E402
    ETC_DIR,
    generate_all_secrets,
    generate_ai_context_dump,
    generate_netplan_yaml,
    get_default_ports,
    get_disk_partitions,
    get_system_snapshot,
    load_env_file,
    netplan_change_status,
    probe_network_interfaces,
    sync_all_blueprint_envs,
    test_atomic_hardlink,
)

# Monorepo root when running inside the blueprint, otherwise the hub itself (standalone).
REPO_ROOT = HUB_ROOT.parent.parent if (HUB_ROOT.parent.parent / "apps" / "control-hub").exists() else HUB_ROOT
NETPLAN_CLI = HUB_ROOT / "core" / "netplan_cli.py"

config_center_bp = Blueprint("config_center", __name__)


def _blueprint_env_path() -> Path:
    """Rendered blueprint-wide env (/etc/homelab/homelab.env) or legacy/standalone fallbacks."""
    for candidate in (ETC_DIR / "homelab.env", REPO_ROOT / ".env", HUB_ROOT / ".env", REPO_ROOT / ".env.example"):
        if candidate.exists():
            return candidate
    return REPO_ROOT / ".env.example"


def _run_privileged_netplan(args):
    """Runs the audited netplan helper via sudo (or directly when already root)."""
    cmd = [sys.executable, str(NETPLAN_CLI), *args]
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        cmd = ["sudo", "-n", *cmd]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    try:
        payload = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        payload = {"success": False, "error": proc.stdout.strip() or proc.stderr.strip()}
    if proc.returncode != 0 and "error" not in payload:
        payload["error"] = proc.stderr.strip() or f"exit code {proc.returncode}"
        payload.setdefault("success", False)
    return payload


@config_center_bp.route("/api/config/current", methods=["GET"])
def get_current_config():
    """Returns current environment values, system vitals, mounts and network interfaces."""
    try:
        env_path = _blueprint_env_path()
        env_vars = load_env_file(str(env_path))
        snapshot = get_system_snapshot()
        interfaces = probe_network_interfaces()

        config = {
            "host_user": env_vars.get("HOST_USER", ""),
            "puid": env_vars.get("PUID", "1000"),
            "pgid": env_vars.get("PGID", "1000"),
            "server_ip": env_vars.get("SERVER_IP", interfaces.get("current_ip", "")),
            "timezone": env_vars.get("TIMEZONE", snapshot.get("timezone", "UTC")),
            "ssd_root": env_vars.get("SSD_ROOT", "/"),
            "hdd_data": env_vars.get("HDD_DATA", "/mnt/hdd/data"),
            "hdd_memories": env_vars.get("HDD_MEMORIES", "/mnt/hdd/Memories"),
            "radarr_api_key": env_vars.get("RADARR_API_KEY", ""),
            "sonarr_api_key": env_vars.get("SONARR_API_KEY", ""),
            "prowlarr_api_key": env_vars.get("PROWLARR_API_KEY", ""),
            "control_hub_port": env_vars.get("CONTROL_HUB_PORT", "7575"),
            "active_nic": env_vars.get("ACTIVE_NIC") or interfaces.get("active_nic", ""),
            "link_speed_mbps": env_vars.get("LINK_SPEED_MBPS", "1000"),
            "qbittorrent_user": env_vars.get("QBITTORRENT_USER", "admin"),
            "qbittorrent_pass": env_vars.get("QBITTORRENT_PASS", ""),
            "gdrive_remote": env_vars.get("GDRIVE_REMOTE", ""),
        }

        return jsonify({
            "status": "success",
            "config": config,
            "system": snapshot,
            "mounts": get_disk_partitions(),
            "interfaces": interfaces,
            "env_path": str(env_path),
            "is_example_fallback": env_path.name == ".env.example",
            "netplan_pending": netplan_change_status(),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/update", methods=["POST"])
def update_config():
    """Re-renders the module env files from the submitted configuration."""
    try:
        data = request.get_json() or {}
        if not data:
            return jsonify({"status": "error", "message": "No configuration payload provided"}), 400

        env_dir = str(ETC_DIR) if ETC_DIR.exists() else None
        try:
            results = sync_all_blueprint_envs(str(REPO_ROOT), data, env_dir=env_dir)
        except PermissionError:
            return jsonify({
                "status": "error",
                "message": (
                    f"{ETC_DIR} is root-owned. Edit {ETC_DIR}/config.json and re-run "
                    "'sudo ./setup.sh --headless --config /etc/homelab/config.json' to apply changes."
                ),
            }), 403
        return jsonify({"status": "success", "message": "Configuration saved.", "updated_files": results})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/verify-hardlink", methods=["POST"])
def verify_hardlink():
    try:
        data = request.get_json() or {}
        return jsonify({"status": "success", "result": test_atomic_hardlink(data.get("path", "/mnt/hdd/data"))})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/ports", methods=["GET"])
def get_ports_status():
    try:
        return jsonify({"status": "success", "ports": get_default_ports()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/generate-secrets", methods=["POST"])
def generate_secrets():
    try:
        return jsonify({"status": "success", "secrets": generate_all_secrets()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/ai-diagnostics", methods=["GET"])
def get_ai_diagnostics():
    try:
        notes = request.args.get("notes", "").strip()
        snapshot = get_system_snapshot()
        ai_prompt = generate_ai_context_dump(snapshot)
        if notes:
            ai_prompt += f"\n## Custom Administrator Notes:\n{notes}\n"
        return jsonify({"status": "success", "snapshot": snapshot, "ai_prompt": ai_prompt})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def _netplan_params(data):
    net = probe_network_interfaces()
    interface = data.get("interface") or net["active_nic"]
    ip = data.get("ip") or net["current_ip"]
    gateway = data.get("gateway") or net["default_gateway"]
    dns = data.get("dns") or net["dns_servers"]
    return interface, (ip if "/" in ip else f"{ip}/24"), gateway, dns


@config_center_bp.route("/api/config/netplan-preview", methods=["POST"])
def netplan_preview():
    try:
        interface, ip_cidr, gateway, dns = _netplan_params(request.get_json() or {})
        return jsonify({"status": "success", "yaml": generate_netplan_yaml(interface, ip_cidr, gateway, dns), "ip": ip_cidr, "valid": True})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/netplan-apply", methods=["POST"])
def netplan_apply():
    """Applies a static IP with an armed revert timer (confirm via /api/config/netplan-confirm)."""
    try:
        data = request.get_json() or {}
        interface, ip_cidr, gateway, dns = _netplan_params(data)
        timeout = int(data.get("timeout", 120))
        args = ["apply", "--interface", interface, "--ip", ip_cidr, "--gateway", gateway, "--timeout", str(timeout)]
        for server in dns:
            args += ["--dns", server]
        result = _run_privileged_netplan(args)
        status = "success" if result.get("success") else "error"
        return jsonify({"status": status, "result": result}), (200 if status == "success" else 500)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/netplan-confirm", methods=["POST"])
def netplan_confirm():
    try:
        result = _run_privileged_netplan(["confirm"])
        return jsonify({"status": "success" if result.get("success") else "error", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/netplan-status", methods=["GET"])
def netplan_status():
    return jsonify({"status": "success", "result": netplan_change_status()})

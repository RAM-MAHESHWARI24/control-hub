"""
Widget: Configuration & Node Control Center (Control Hub Integration)
Provides full management API for environment settings, atomic hardlink testing,
port conflict matrix monitoring, credential generation, and AI Copilot diagnostics.
"""

import sys
from pathlib import Path
from flask import Blueprint, jsonify, request

# Ensure repository root is on sys.path to access setup.config_core
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from setup.config_core.env_manager import (
    load_env_file,
    sync_all_blueprint_envs,
)
from setup.config_core.storage_manager import (
    get_disk_partitions,
    test_atomic_hardlink,
)
from setup.config_core.port_manager import (
    get_default_ports,
    check_ports_matrix,
    check_port,
)
from setup.config_core.secrets_generator import (
    generate_all_secrets,
    generate_password,
    generate_api_key,
)
from setup.config_core.system_prober import (
    get_system_snapshot,
    generate_ai_context_dump,
)
from setup.config_core.netplan_manager import (
    probe_network_interfaces,
    generate_netplan_yaml,
    safe_apply_netplan,
)

config_center_bp = Blueprint("config_center", __name__)


@config_center_bp.route("/api/config/current", methods=["GET"])
def get_current_config():
    """Returns current environment values, system hardware vitals, mounts, and network interfaces"""
    try:
        master_env = REPO_ROOT / ".env"
        if not master_env.exists():
            master_env = REPO_ROOT / ".env.example"

        env_vars = load_env_file(str(master_env)) if master_env.exists() else {}

        snapshot = get_system_snapshot()
        mounts = get_disk_partitions()
        interfaces = probe_network_interfaces()

        config = {
            "host_user": env_vars.get("HOST_USER", "homelab_user"),
            "puid": env_vars.get("PUID", "1000"),
            "pgid": env_vars.get("PGID", "1000"),
            "server_ip": env_vars.get("SERVER_IP", "192.168.1.100"),
            "timezone": env_vars.get("TIMEZONE", "Asia/Kolkata"),
            "ssd_root": env_vars.get("SSD_ROOT", "/"),
            "hdd_data": env_vars.get("HDD_DATA", "/mnt/hdd/data"),
            "hdd_memories": env_vars.get("HDD_MEMORIES", "/mnt/hdd/Memories"),
            "radarr_api_key": env_vars.get("RADARR_API_KEY", ""),
            "sonarr_api_key": env_vars.get("SONARR_API_KEY", ""),
            "prowlarr_api_key": env_vars.get("PROWLARR_API_KEY", ""),
            "control_hub_port": env_vars.get("CONTROL_HUB_PORT", "7575"),
            "active_nic": env_vars.get("ACTIVE_NIC", "eth0"),
            "link_speed_mbps": env_vars.get("LINK_SPEED_MBPS", "1000"),
            "qbittorrent_user": env_vars.get("QBITTORRENT_USER", "admin"),
            "qbittorrent_pass": env_vars.get("QBITTORRENT_PASS", "adminadmin"),
            "gdrive_remote": env_vars.get("GDRIVE_REMOTE", "gdrive:"),
        }

        return jsonify({
            "status": "success",
            "config": config,
            "system": snapshot,
            "mounts": mounts,
            "interfaces": interfaces,
            "is_example_fallback": not (REPO_ROOT / ".env").exists()
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/update", methods=["POST"])
def update_config():
    """
    Saves updated configuration parameters and propagates them
    synchronously across root and all blueprint application .env files.
    """
    try:
        data = request.get_json() or {}
        if not data:
            return jsonify({"status": "error", "message": "No configuration payload provided"}), 400

        results = sync_all_blueprint_envs(str(REPO_ROOT), data)
        return jsonify({
            "status": "success",
            "message": "Configuration saved and synchronized across all blueprint apps.",
            "updated_files": results
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/verify-hardlink", methods=["POST"])
def verify_hardlink():
    """Tests atomic hardlink capability on the specified directory path"""
    try:
        data = request.get_json() or {}
        target_path = data.get("path", "/mnt/hdd/data")
        result = test_atomic_hardlink(target_path)
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/ports", methods=["GET"])
def get_ports_status():
    """Returns real-time availability and conflict status across all blueprint ports"""
    try:
        ports = get_default_ports()
        return jsonify({"status": "success", "ports": ports})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/generate-secrets", methods=["POST"])
def generate_secrets():
    """Generates fresh cryptographically secure passwords and API keys"""
    try:
        secrets = generate_all_secrets()
        return jsonify({"status": "success", "secrets": secrets})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/ai-diagnostics", methods=["GET"])
def get_ai_diagnostics():
    """Returns hardware snapshot and compact ~300-token AI Copilot prompt"""
    try:
        notes = request.args.get("notes", "").strip()
        snapshot = get_system_snapshot()
        ai_prompt = generate_ai_context_dump(snapshot)
        if notes:
            ai_prompt += f"\n## Custom Administrator Notes:\n{notes}\n"

        return jsonify({
            "status": "success",
            "snapshot": snapshot,
            "ai_prompt": ai_prompt
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/netplan-preview", methods=["POST"])
def netplan_preview():
    """Generates and previews Netplan v2 YAML configuration"""
    try:
        data = request.get_json() or {}
        interface = data.get("interface", "eth0")
        ip = data.get("ip", "192.168.1.100")
        gateway = data.get("gateway", "192.168.1.1")
        dns = data.get("dns", ["1.1.1.1", "1.0.0.1"])

        ip_with_cidr = f"{ip}/24" if "/" not in ip else ip
        yaml_content = generate_netplan_yaml(interface, ip_with_cidr, gateway, dns)

        return jsonify({
            "status": "success",
            "yaml": yaml_content,
            "ip": ip_with_cidr,
            "valid": True
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/netplan-apply", methods=["POST"])
def netplan_apply():
    """Applies Netplan configuration safely with automatic rollback protection"""
    try:
        data = request.get_json() or {}
        interface = data.get("interface", "eth0")
        ip = data.get("ip", "192.168.1.100")
        gateway = data.get("gateway", "192.168.1.1")
        dns = data.get("dns", ["1.1.1.1", "1.0.0.1"])
        timeout = int(data.get("timeout", 45))

        result = safe_apply_netplan(
            interface=interface,
            ip_address=ip,
            gateway=gateway,
            dns_servers=dns,
            timeout_sec=timeout
        )
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

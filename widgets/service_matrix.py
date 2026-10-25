"""
Widget: Service Matrix & 1-Click Container Logs
Monitors Docker container health, attaches 12-character hex IDs for Dozzle v11 routing,
handles passwordless container restarts, and provides direct Docker socket log tailing.
"""

import json
import subprocess
from flask import Blueprint, jsonify, request
from config import SERVICES_CATALOG

service_matrix_bp = Blueprint("service_matrix", __name__)

@service_matrix_bp.route("/api/services/status", methods=["GET"])
def get_services_status():
    """Queries Docker daemon to get the live running state of all server containers"""
    results = []
    try:
        proc = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{json .}}"],
            stdout=subprocess.PIPE, text=True, timeout=3
        )
        running_map = {}
        for line in proc.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                c = json.loads(line)
                c_name = c.get("Names", "").strip()
                running_map[c_name] = c
            except Exception:
                pass

        for c_id, meta in SERVICES_CATALOG.items():
            docker_info = running_map.get(c_id)
            state = "stopped"
            status_text = "Not running"
            is_up = False
            docker_id = ""

            if docker_info:
                state = docker_info.get("State", "unknown")
                status_text = docker_info.get("Status", "")
                is_up = (state == "running")
                raw_id = docker_info.get("ID", "")
                docker_id = raw_id[:12] if len(raw_id) >= 12 else raw_id

            results.append({
                "id": c_id,
                "docker_id": docker_id,
                "name": meta["name"],
                "port": meta["port"],
                "description": meta["desc"],
                "icon": meta["icon"],
                "category": meta["category"],
                "state": state,
                "status": status_text,
                "is_up": is_up
            })

    except Exception:
        # Fallback if docker socket error
        for c_id, meta in SERVICES_CATALOG.items():
            results.append({
                "id": c_id,
                "name": meta["name"],
                "port": meta["port"],
                "description": meta["desc"],
                "icon": meta["icon"],
                "category": meta["category"],
                "state": "unknown",
                "status": "Check daemon",
                "is_up": False
            })

    # Always append Cockpit (Host Linux Admin, port 9090)
    cockpit_up = False
    try:
        s = subprocess.run(["systemctl", "is-active", "cockpit.socket"], stdout=subprocess.PIPE, text=True)
        cockpit_up = (s.stdout.strip() == "active")
    except Exception:
        pass

    results.append({
        "id": "cockpit",
        "name": "Cockpit",
        "port": 9090,
        "description": "Linux System Administration",
        "icon": "settings",
        "category": "system",
        "state": "running" if cockpit_up else "stopped",
        "status": "Active systemd socket" if cockpit_up else "Inactive",
        "is_up": cockpit_up
    })

    return jsonify({"services": results})


@service_matrix_bp.route("/api/services/restart/<service_id>", methods=["POST"])
def restart_service(service_id):
    """Restarts a specific Docker container via passwordless sudo"""
    allowed_services = list(SERVICES_CATALOG.keys())
    if service_id not in allowed_services:
        return jsonify({"success": False, "error": f"Service {service_id} cannot be restarted via this endpoint"}), 400

    try:
        proc = subprocess.run(["sudo", "docker", "restart", service_id], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
        if proc.returncode == 0:
            return jsonify({"success": True, "message": f"{service_id} restarted successfully."})
        return jsonify({"success": False, "error": proc.stderr.strip()}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@service_matrix_bp.route("/api/services/logs/<service_id>", methods=["GET"])
def get_service_logs(service_id):
    """Returns tail lines of logs for any container or system service"""
    tail = request.args.get("tail", "100")
    if service_id == "cockpit":
        try:
            proc = subprocess.run(["journalctl", "-u", "cockpit", "-n", str(tail), "--no-pager"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=5)
            return jsonify({"service": service_id, "logs": proc.stdout})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    try:
        proc = subprocess.run(["docker", "logs", "--tail", str(tail), service_id], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=5)
        return jsonify({"service": service_id, "logs": proc.stdout})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

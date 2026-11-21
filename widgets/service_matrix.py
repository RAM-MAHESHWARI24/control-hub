"""
Widget: Service Matrix & 1-Click Container Logs
Reports only containers and host tools actually detected on the server,
handles Docker restarts directly via the service account's docker-group
membership (no sudo needed), and streams container logs.
"""

import json
import subprocess

from flask import Blueprint, jsonify, request

from config import SERVICES_CATALOG

service_matrix_bp = Blueprint("service_matrix", __name__)


@service_matrix_bp.route("/api/services/status", methods=["GET"])
def get_services_status():
    """Queries Docker daemon and systemd to return actually installed services."""
    results = []
    running_map = {}
    docker_available = True
    docker_error = None

    try:
        proc = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{json .}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3,
        )
        if proc.returncode != 0:
            docker_available = False
            docker_error = (proc.stderr or "Docker daemon unavailable").strip()[:160]
        else:
            for line in proc.stdout.strip().split("\n"):
                if not line:
                    continue
                try:
                    c = json.loads(line)
                    c_name = c.get("Names", "").strip()
                    if c_name:
                        running_map[c_name] = c
                except Exception:
                    pass
    except Exception as exc:
        docker_available = False
        docker_error = str(exc)[:160]

    if docker_available:
        for c_id, meta in SERVICES_CATALOG.items():
            docker_info = running_map.get(c_id)
            if not docker_info:
                # Only show containers that are actually created/installed on this host.
                continue
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
                "is_up": is_up,
            })

    # Include Cockpit only when its systemd socket is active on this host.
    cockpit_up = False
    try:
        s = subprocess.run(
            ["systemctl", "is-active", "cockpit.socket"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        cockpit_up = (s.stdout.strip() == "active")
    except Exception:
        pass

    if cockpit_up:
        results.append({
            "id": "cockpit",
            "name": "Cockpit",
            "port": 9090,
            "description": "Linux System Administration",
            "icon": "settings",
            "category": "system",
            "state": "running",
            "status": "Active systemd socket",
            "is_up": True,
        })

    return jsonify({
        "services": results,
        "docker_available": docker_available,
        "docker_error": docker_error,
        "dozzle_installed": "dozzle" in running_map,
        "cockpit_installed": cockpit_up,
    })


@service_matrix_bp.route("/api/services/restart/<service_id>", methods=["POST"])
def restart_service(service_id):
    """Restarts a specific Docker container (homelab user is a member of the docker group)."""
    if service_id not in SERVICES_CATALOG:
        return jsonify({"success": False, "error": f"Service {service_id} cannot be restarted via this endpoint"}), 400

    try:
        proc = subprocess.run(
            ["docker", "restart", service_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
        )
        if proc.returncode == 0:
            return jsonify({"success": True, "message": f"{service_id} restarted successfully."})
        return jsonify({"success": False, "error": proc.stderr.strip() or f"docker restart exited {proc.returncode}"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@service_matrix_bp.route("/api/services/logs/<service_id>", methods=["GET"])
def get_service_logs(service_id):
    """Returns tail lines of logs for a catalog container or Cockpit."""
    if service_id not in SERVICES_CATALOG and service_id != "cockpit":
        return jsonify({"error": f"Unknown service '{service_id}'"}), 404

    try:
        tail = max(1, min(2000, int(request.args.get("tail", "100"))))
    except ValueError:
        tail = 100

    if service_id == "cockpit":
        try:
            proc = subprocess.run(
                ["journalctl", "-u", "cockpit", "-n", str(tail), "--no-pager"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=5,
            )
            return jsonify({"service": service_id, "logs": proc.stdout})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    try:
        proc = subprocess.run(
            ["docker", "logs", "--tail", str(tail), service_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
        )
        return jsonify({"service": service_id, "logs": proc.stdout})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

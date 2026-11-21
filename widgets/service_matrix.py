"""
Widget: Service Matrix & 1-Click Container Controls / Logs
Reports containers actually detected on the server (with real Docker health,
published host ports, image versions, and optional non-catalog containers),
handles Docker start/stop/restart directly via docker-group membership, and
streams container logs inline.
"""

import json
import re
import subprocess
from typing import Optional

from flask import Blueprint, jsonify, request

from config import SERVICES_CATALOG

service_matrix_bp = Blueprint("service_matrix", __name__)

_CONTAINER_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
_PORT_MAPPING_RE = re.compile(r"(?:[\d.]+|\[::\]|::):(\d+)->(\d+)/tcp")


def parse_container_health(status_text: str) -> str:
    """Extracts Docker healthcheck state from `docker ps` Status string."""
    lower = (status_text or "").lower()
    if "(unhealthy)" in lower:
        return "unhealthy"
    if "(health: starting)" in lower or "(starting)" in lower:
        return "starting"
    if "(healthy)" in lower:
        return "healthy"
    return "none"


def parse_published_port(ports_text: str, preferred_container_port: Optional[int] = None) -> Optional[int]:
    """
    Extracts the published host TCP port from Docker's `Ports` column, e.g.
    `0.0.0.0:8097->8096/tcp, [::]:8097->8096/tcp` -> 8097.
    Prefers a mapping matching `preferred_container_port` if provided.
    """
    if not ports_text:
        return None
    matches = _PORT_MAPPING_RE.findall(ports_text)
    if not matches:
        return None
    if preferred_container_port is not None:
        for host_p, cont_p in matches:
            try:
                if int(cont_p) == int(preferred_container_port):
                    return int(host_p)
            except ValueError:
                continue
    try:
        return int(matches[0][0])
    except ValueError:
        return None


def _list_docker_containers():
    """Returns (running_map, docker_available, docker_error)."""
    running_map = {}
    try:
        proc = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{json .}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3,
        )
        if proc.returncode != 0:
            return {}, False, (proc.stderr or "Docker daemon unavailable").strip()[:160]
        for line in proc.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                c = json.loads(line)
                c_name = (c.get("Names") or "").strip()
                if c_name:
                    running_map[c_name] = c
            except Exception:
                pass
        return running_map, True, None
    except Exception as exc:
        return {}, False, str(exc)[:160]


def _serialize_container(c_id: str, docker_info: dict, meta: Optional[dict] = None) -> dict:
    state = docker_info.get("State", "unknown")
    status_text = docker_info.get("Status", "")
    health = parse_container_health(status_text)
    is_up = (state == "running" and health != "unhealthy")
    raw_id = docker_info.get("ID", "")
    docker_id = raw_id[:12] if len(raw_id) >= 12 else raw_id
    image = (docker_info.get("Image") or "").strip()
    ports_raw = docker_info.get("Ports", "")

    if meta:
        default_port = meta.get("port")
        detected_port = parse_published_port(ports_raw, preferred_container_port=default_port)
        port = detected_port if detected_port is not None else default_port
        has_web_ui = bool(meta.get("has_web_ui", port is not None)) and port is not None
        return {
            "id": c_id,
            "docker_id": docker_id,
            "name": meta["name"],
            "port": port,
            "description": meta["desc"],
            "icon": meta["icon"],
            "category": meta["category"],
            "state": state,
            "status": status_text,
            "health": health,
            "is_up": is_up,
            "has_web_ui": has_web_ui,
            "image": image,
            "scheduled": bool(meta.get("scheduled", False)),
            "optional": bool(meta.get("optional", False)),
            "is_custom": False,
        }

    detected_port = parse_published_port(ports_raw)
    return {
        "id": c_id,
        "docker_id": docker_id,
        "name": c_id,
        "port": detected_port,
        "description": image or "Custom Docker container",
        "icon": "box",
        "category": "other",
        "state": state,
        "status": status_text,
        "health": health,
        "is_up": is_up,
        "has_web_ui": detected_port is not None,
        "image": image,
        "scheduled": False,
        "optional": True,
        "is_custom": True,
    }


@service_matrix_bp.route("/api/services/status", methods=["GET"])
def get_services_status():
    """Queries Docker daemon and systemd to return actually installed services."""
    include_other = request.args.get("include_other", "false").lower() == "true"
    running_map, docker_available, docker_error = _list_docker_containers()
    results = []
    other_services = []

    if docker_available:
        for c_id, meta in SERVICES_CATALOG.items():
            docker_info = running_map.get(c_id)
            if not docker_info:
                continue
            results.append(_serialize_container(c_id, docker_info, meta=meta))

        for c_id, docker_info in sorted(running_map.items()):
            if c_id in SERVICES_CATALOG:
                continue
            other_services.append(_serialize_container(c_id, docker_info, meta=None))

    if include_other and other_services:
        results.extend(other_services)

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
        cockpit_up = s.stdout.strip() == "active"
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
            "health": "healthy",
            "is_up": True,
            "has_web_ui": True,
            "image": "systemd",
            "scheduled": False,
            "optional": True,
            "is_custom": False,
        })

    dozzle_info = running_map.get("dozzle")
    dozzle_running = bool(dozzle_info and dozzle_info.get("State") == "running")
    dozzle_port = (
        parse_published_port(dozzle_info.get("Ports", ""), preferred_container_port=8080)
        or parse_published_port(dozzle_info.get("Ports", ""), preferred_container_port=8888)
        or 8888
    ) if dozzle_info else 8888

    return jsonify({
        "services": results,
        "other_count": len(other_services),
        "docker_available": docker_available,
        "docker_error": docker_error,
        "dozzle_installed": dozzle_running,
        "dozzle_port": dozzle_port,
        "cockpit_installed": cockpit_up,
    })


@service_matrix_bp.route("/api/services/restart/<service_id>", methods=["POST"])
def restart_service(service_id):
    """Restarts a catalog Docker container (homelab user is in the docker group)."""
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


@service_matrix_bp.route("/api/services/action/<service_id>", methods=["POST"])
def service_action(service_id):
    """Starts, stops, or restarts an existing Docker container."""
    body = request.get_json(silent=True) or {}
    action = str(body.get("action", "")).strip().lower()
    if action not in ("start", "stop", "restart"):
        return jsonify({"success": False, "error": "Action must be one of: start, stop, restart."}), 400

    if service_id not in SERVICES_CATALOG:
        if not _CONTAINER_NAME_RE.match(service_id):
            return jsonify({"success": False, "error": f"Invalid container name '{service_id}'"}), 400
        running_map, docker_available, _ = _list_docker_containers()
        if not docker_available or service_id not in running_map:
            return jsonify({"success": False, "error": f"Container '{service_id}' not found."}), 404

    try:
        proc = subprocess.run(
            ["docker", action, service_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=25,
        )
        if proc.returncode == 0:
            past = {"start": "started", "stop": "stopped", "restart": "restarted"}[action]
            return jsonify({"success": True, "message": f"{service_id} {past} successfully."})
        return jsonify({"success": False, "error": proc.stderr.strip() or f"docker {action} exited {proc.returncode}"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@service_matrix_bp.route("/api/services/logs/<service_id>", methods=["GET"])
def get_service_logs(service_id):
    """Returns tail lines of logs for a container or Cockpit."""
    if service_id not in SERVICES_CATALOG and service_id != "cockpit":
        if not _CONTAINER_NAME_RE.match(service_id):
            return jsonify({"error": f"Unknown service '{service_id}'"}), 404
        running_map, docker_available, _ = _list_docker_containers()
        if not docker_available or service_id not in running_map:
            return jsonify({"error": f"Unknown service '{service_id}'"}), 404

    try:
        tail = max(1, min(2000, int(request.args.get("tail", "150"))))
    except ValueError:
        tail = 150

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

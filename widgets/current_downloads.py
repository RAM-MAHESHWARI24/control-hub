"""
Widget: Current Downloads (qBittorrent Ingest Pipeline)
Provides endpoints for active torrent queue monitoring and Pause/Resume All
compatible with both qBittorrent 5.x (/stop, /start) and 4.x (/pause, /resume).
"""

from flask import Blueprint, jsonify, request

from config import QBITTORRENT_URL
from core.telemetry_sampler import qb_lock, qb_login, qb_session, telemetry_lock, telemetry_state

current_downloads_bp = Blueprint("current_downloads", __name__)


@current_downloads_bp.route("/api/downloads/active", methods=["GET"])
def get_active_downloads():
    """Returns the live list of current downloading torrents and collective speed."""
    with telemetry_lock:
        return jsonify(telemetry_state["torrents_queue"])


def _post_qbit(endpoint: str, data: dict):
    with qb_lock:
        resp = qb_session.post(f"{QBITTORRENT_URL}{endpoint}", data=data, timeout=3)
    if resp.status_code == 403:
        if not qb_login():
            return resp
        with qb_lock:
            resp = qb_session.post(f"{QBITTORRENT_URL}{endpoint}", data=data, timeout=3)
    return resp


@current_downloads_bp.route("/api/torrents/toggle-all", methods=["POST"])
def toggle_torrents():
    """Pause/Stop All or Resume/Start All for qBittorrent (5.x first, 4.x fallback)."""
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action", "pause")).lower()
    if action not in ("pause", "resume", "stop", "start"):
        return jsonify({"success": False, "error": f"Unsupported action '{action}'"}), 400

    # qBittorrent 5.0+ renamed /pause -> /stop and /resume -> /start.
    if action in ("pause", "stop"):
        endpoints = ("/api/v2/torrents/stop", "/api/v2/torrents/pause")
        canonical = "pause"
    else:
        endpoints = ("/api/v2/torrents/start", "/api/v2/torrents/resume")
        canonical = "resume"

    try:
        last_resp = None
        for ep in endpoints:
            last_resp = _post_qbit(ep, {"hashes": "all"})
            if last_resp.status_code in (200, 204):
                return jsonify({"success": True, "action": canonical})
            if last_resp.status_code != 404:
                break
        code = last_resp.status_code if last_resp is not None else 502
        msg = (
            "qBittorrent rejected authentication (check QBITTORRENT_PASS)."
            if code in (401, 403)
            else f"qBittorrent returned HTTP {code}"
        )
        return jsonify({"success": False, "action": canonical, "error": msg}), (401 if code in (401, 403) else 502)
    except Exception as e:
        return jsonify({"success": False, "error": f"Could not reach qBittorrent: {e}"}), 502

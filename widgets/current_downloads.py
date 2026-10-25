"""
Widget: Current Downloads (qBittorrent Ingest Pipeline)
Provides endpoints for active torrent queue monitoring and emergency pause/resume controls.
"""

from flask import Blueprint, jsonify, request
from config import QBITTORRENT_URL
from core.telemetry_sampler import telemetry_lock, telemetry_state, qb_session, qb_login

current_downloads_bp = Blueprint("current_downloads", __name__)

@current_downloads_bp.route("/api/downloads/active", methods=["GET"])
def get_active_downloads():
    """Returns the live list of current downloading torrents and collective speed in Mbps"""
    with telemetry_lock:
        return jsonify(telemetry_state["torrents_queue"])


@current_downloads_bp.route("/api/torrents/toggle-all", methods=["POST"])
def toggle_torrents():
    """Emergency Pause All or Resume All for qBittorrent"""
    action = request.json.get("action", "pause") if request.is_json else "pause"
    endpoint = "/api/v2/torrents/pause" if action == "pause" else "/api/v2/torrents/resume"
    try:
        resp = qb_session.post(f"{QBITTORRENT_URL}{endpoint}", data={"hashes": "all"}, timeout=3)
        if resp.status_code == 403:
            qb_login()
            resp = qb_session.post(f"{QBITTORRENT_URL}{endpoint}", data={"hashes": "all"}, timeout=3)

        return jsonify({"success": resp.status_code == 200, "action": action})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

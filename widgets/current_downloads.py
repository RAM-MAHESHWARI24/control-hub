"""
Widget: Current Downloads & Speed Policy (qBittorrent Ingest Pipeline, Phase 3A)
Provides active torrent queue monitoring, Pause/Resume All, per-torrent
pause/resume/delete/priority actions, and global + scheduled alternative speed
limits compatible with both qBittorrent 5.x and 4.x.
"""

import json
import re
from typing import Iterable, Tuple

from flask import Blueprint, jsonify, request

from config import QBITTORRENT_URL
from core.telemetry_sampler import qb_lock, qb_login, qb_session, telemetry_lock, telemetry_state

current_downloads_bp = Blueprint("current_downloads", __name__)

_HASH_RE = re.compile(r"^[0-9a-fA-F]{32,64}$")

_ACTION_ENDPOINTS: dict[str, Tuple[str, ...]] = {
    "pause": ("/api/v2/torrents/stop", "/api/v2/torrents/pause"),
    "stop": ("/api/v2/torrents/stop", "/api/v2/torrents/pause"),
    "resume": ("/api/v2/torrents/start", "/api/v2/torrents/resume"),
    "start": ("/api/v2/torrents/start", "/api/v2/torrents/resume"),
    "delete": ("/api/v2/torrents/delete",),
    "top_prio": ("/api/v2/torrents/topPrio",),
    "bottom_prio": ("/api/v2/torrents/bottomPrio",),
    "increase_prio": ("/api/v2/torrents/increasePrio",),
    "decrease_prio": ("/api/v2/torrents/decreasePrio",),
}


@current_downloads_bp.route("/api/downloads/active", methods=["GET"])
def get_active_downloads():
    """Returns the live list of current downloading torrents and collective speed."""
    with telemetry_lock:
        return jsonify(telemetry_state["torrents_queue"])


def _qbit_request(method: str, endpoint: str, data: dict | None = None):
    fn = qb_session.post if method == "POST" else qb_session.get
    kwargs = {"data": data, "timeout": 3} if method == "POST" else {"timeout": 3}
    with qb_lock:
        resp = fn(f"{QBITTORRENT_URL}{endpoint}", **kwargs)
    if resp.status_code == 403:
        if not qb_login():
            return resp
        with qb_lock:
            resp = fn(f"{QBITTORRENT_URL}{endpoint}", **kwargs)
    return resp


def _post_qbit(endpoint: str, data: dict):
    return _qbit_request("POST", endpoint, data=data)


def _post_qbit_with_fallback(endpoints: Iterable[str], data: dict):
    last_resp = None
    for ep in endpoints:
        last_resp = _post_qbit(ep, data)
        if last_resp.status_code in (200, 204):
            return True, last_resp.status_code, ""
        if last_resp.status_code != 404:
            break
    code = last_resp.status_code if last_resp is not None else 502
    msg = (
        "qBittorrent rejected authentication (check QBITTORRENT_PASS)."
        if code in (401, 403)
        else f"qBittorrent returned HTTP {code}"
    )
    return False, (401 if code in (401, 403) else 502), msg


@current_downloads_bp.route("/api/torrents/toggle-all", methods=["POST"])
def toggle_torrents():
    """Pause/Stop All or Resume/Start All for qBittorrent (5.x first, 4.x fallback)."""
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action", "pause")).lower()
    if action not in ("pause", "resume", "stop", "start"):
        return jsonify({"success": False, "error": f"Unsupported action '{action}'"}), 400

    canonical = "pause" if action in ("pause", "stop") else "resume"
    try:
        ok, status_code, err = _post_qbit_with_fallback(_ACTION_ENDPOINTS[action], {"hashes": "all"})
        if ok:
            return jsonify({"success": True, "action": canonical})
        return jsonify({"success": False, "action": canonical, "error": err}), status_code
    except Exception as e:
        return jsonify({"success": False, "error": f"Could not reach qBittorrent: {e}"}), 502


@current_downloads_bp.route("/api/torrents/<torrent_hash>/action", methods=["POST"])
def torrent_action(torrent_hash: str):
    """Per-torrent control: pause, resume, delete (optional delete_files), or priority change."""
    if not _HASH_RE.match(torrent_hash or ""):
        return jsonify({"success": False, "error": "Invalid torrent hash."}), 400

    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action", "")).strip()
    if action not in _ACTION_ENDPOINTS:
        return jsonify({"success": False, "error": f"Unsupported torrent action '{action}'."}), 400

    data = {"hashes": torrent_hash}
    if action == "delete":
        data["deleteFiles"] = "true" if bool(payload.get("delete_files", False)) else "false"

    try:
        ok, status_code, err = _post_qbit_with_fallback(_ACTION_ENDPOINTS[action], data)
        if ok:
            return jsonify({"success": True, "hash": torrent_hash, "action": action})
        return jsonify({"success": False, "hash": torrent_hash, "action": action, "error": err}), status_code
    except Exception as e:
        return jsonify({"success": False, "error": f"Could not reach qBittorrent: {e}"}), 502


@current_downloads_bp.route("/api/torrents/limits", methods=["GET", "POST"])
def torrent_limits():
    """Reads or updates global speed caps, alternative speed toggle, and evening schedule."""
    if request.method == "GET":
        try:
            prefs_resp = _qbit_request("GET", "/api/v2/app/preferences")
            if prefs_resp.status_code in (401, 403):
                return jsonify({"success": False, "error": "qBittorrent authentication rejected."}), 401
            if prefs_resp.status_code != 200:
                return jsonify({"success": False, "error": f"qBittorrent returned HTTP {prefs_resp.status_code}"}), 502
            prefs = prefs_resp.json() or {}
            tinfo_resp = _qbit_request("GET", "/api/v2/transfer/info")
            tinfo = tinfo_resp.json() if tinfo_resp.status_code == 200 else {}
            mode_resp = _qbit_request("GET", "/api/v2/transfer/speedLimitsMode")
            alt_mode = mode_resp.status_code == 200 and (mode_resp.text or "").strip() == "1"
            dl_limit = int(tinfo.get("dl_rate_limit", prefs.get("dl_limit", 0)) or 0)
            up_limit = int(tinfo.get("up_rate_limit", prefs.get("up_limit", 0)) or 0)
            return jsonify({
                "success": True,
                "dl_limit_kbps": round(dl_limit / 1024),
                "up_limit_kbps": round(up_limit / 1024),
                "alt_dl_limit_kbps": round(int(prefs.get("alt_dl_limit") or 0) / 1024),
                "alt_up_limit_kbps": round(int(prefs.get("alt_up_limit") or 0) / 1024),
                "alt_speed_enabled": alt_mode,
                "scheduler_enabled": bool(prefs.get("scheduler_enabled", False)),
                "schedule_from_hour": int(prefs.get("schedule_from_hour", 18) or 18),
                "schedule_from_min": int(prefs.get("schedule_from_min", 0) or 0),
                "schedule_to_hour": int(prefs.get("schedule_to_hour", 23) or 23),
                "schedule_to_min": int(prefs.get("schedule_to_min", 59) or 59),
            })
        except Exception as e:
            return jsonify({"success": False, "error": f"Could not reach qBittorrent: {e}"}), 502

    body = request.get_json(silent=True) or {}
    try:
        if body.get("toggle_alt_speed"):
            ok, status_code, err = _post_qbit_with_fallback(("/api/v2/transfer/toggleSpeedLimitsMode",), {})
            if not ok:
                return jsonify({"success": False, "error": err}), status_code

        if "dl_limit_kbps" in body:
            dl_kbps = max(0, int(body["dl_limit_kbps"]))
            ok, status_code, err = _post_qbit_with_fallback(
                ("/api/v2/transfer/setDownloadLimit",), {"limit": str(dl_kbps * 1024)}
            )
            if not ok:
                return jsonify({"success": False, "error": err}), status_code

        if "up_limit_kbps" in body:
            up_kbps = max(0, int(body["up_limit_kbps"]))
            ok, status_code, err = _post_qbit_with_fallback(
                ("/api/v2/transfer/setUploadLimit",), {"limit": str(up_kbps * 1024)}
            )
            if not ok:
                return jsonify({"success": False, "error": err}), status_code

        pref_updates = {}
        if "alt_dl_limit_kbps" in body:
            pref_updates["alt_dl_limit"] = max(0, int(body["alt_dl_limit_kbps"])) * 1024
        if "alt_up_limit_kbps" in body:
            pref_updates["alt_up_limit"] = max(0, int(body["alt_up_limit_kbps"])) * 1024
        if "scheduler_enabled" in body:
            pref_updates["scheduler_enabled"] = bool(body["scheduler_enabled"])
        for hr_key in ("schedule_from_hour", "schedule_to_hour"):
            if hr_key in body:
                pref_updates[hr_key] = max(0, min(23, int(body[hr_key])))
        for min_key in ("schedule_from_min", "schedule_to_min"):
            if min_key in body:
                pref_updates[min_key] = max(0, min(59, int(body[min_key])))

        if pref_updates:
            ok, status_code, err = _post_qbit_with_fallback(
                ("/api/v2/app/setPreferences",), {"json": json.dumps(pref_updates)}
            )
            if not ok:
                return jsonify({"success": False, "error": err}), status_code

        return jsonify({"success": True})
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": f"Invalid limit parameter: {exc}"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"Could not reach qBittorrent: {e}"}), 502

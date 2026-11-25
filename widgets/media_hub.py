"""
Widget: Media Pipeline Operations (Phase 3A Slice 2)
Aggregates live Seerr requests (with approve/decline), Radarr & Sonarr 7-day
calendar + missing/wanted items, and Jellyfin recent items + library scan trigger.
Each integration activates dynamically when its URL & API key are configured and
reports honest unconfigured status otherwise.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Blueprint, jsonify

from config import (
    JELLYFIN_API_KEY,
    JELLYFIN_URL,
    RADARR_API_KEY,
    RADARR_URL,
    SEERR_API_KEY,
    SEERR_URL,
    SONARR_API_KEY,
    SONARR_URL,
)

media_hub_bp = Blueprint("media_hub", __name__)


def _api_get(url: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None, timeout: float = 4.0) -> Tuple[int, Any]:
    try:
        r = requests.get(url, headers=headers, params=params, timeout=timeout)
        if r.status_code == 200:
            return 200, r.json()
        return r.status_code, None
    except requests.RequestException:
        return 0, None


def _api_post(url: str, headers: Dict[str, str], timeout: float = 5.0) -> Tuple[int, Any]:
    try:
        r = requests.post(url, headers=headers, timeout=timeout)
        body = None
        try:
            body = r.json() if r.content else None
        except ValueError:
            body = None
        return r.status_code, body
    except requests.RequestException as exc:
        return 0, {"message": str(exc)[:160]}


def _seerr_requests() -> Dict[str, Any]:
    if not (SEERR_URL and SEERR_API_KEY):
        return {"configured": False, "items": []}
    code, data = _api_get(
        f"{SEERR_URL.rstrip('/')}/api/v1/request",
        headers={"X-Api-Key": SEERR_API_KEY, "Accept": "application/json"},
        params={"take": 20, "skip": 0, "filter": "pending"},
    )
    if code != 200 or not isinstance(data, dict):
        return {"configured": True, "reachable": False, "items": [], "error": f"Seerr HTTP {code or 'unreachable'}"}
    items = []
    for req in data.get("results") or []:
        media = req.get("media") or {}
        req_by = req.get("requestedBy") or {}
        title = media.get("title") or media.get("name") or f"TMDB #{media.get('tmdbId') or req.get('id')}"
        items.append({
            "id": req.get("id"),
            "type": req.get("type") or media.get("mediaType") or "media",
            "title": title,
            "requested_by": req_by.get("displayName") or req_by.get("username") or "User",
            "created_at": (req.get("createdAt") or "")[:10],
            "waiting_reason": "Pending approval" if req.get("status") == 1 else "Processing",
        })
    return {"configured": True, "reachable": True, "items": items}


def _arr_calendar_and_wanted(base_url: str, api_key: str, kind: str) -> Tuple[bool, List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not (base_url and api_key):
        return False, [], []
    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    now = datetime.now(timezone.utc)
    start = now.strftime("%Y-%m-%d")
    end = (now + timedelta(days=7)).strftime("%Y-%m-%d")

    cal_items: List[Dict[str, Any]] = []
    c_code, c_data = _api_get(f"{base_url.rstrip('/')}/api/v3/calendar", headers=headers, params={"start": start, "end": end})
    if c_code == 200 and isinstance(c_data, list):
        for entry in c_data[:12]:
            if kind == "movie":
                date_str = (entry.get("digitalRelease") or entry.get("physicalRelease") or entry.get("inCinemas") or "")[:10]
                label = entry.get("title") or "Movie"
            else:
                date_str = (entry.get("airDate") or entry.get("airDateUtc") or "")[:10]
                series = (entry.get("series") or {}).get("title") or ""
                ep = f"S{int(entry.get('seasonNumber') or 0):02d}E{int(entry.get('episodeNumber') or 0):02d}"
                label = f"{series} {ep}: {entry.get('title') or ''}".strip(": ")
            cal_items.append({"kind": kind, "title": label, "date": date_str, "has_file": bool(entry.get("hasFile"))})

    wanted_items: List[Dict[str, Any]] = []
    w_code, w_data = _api_get(f"{base_url.rstrip('/')}/api/v3/wanted/missing", headers=headers, params={"pageSize": 8})
    if w_code == 200 and isinstance(w_data, dict):
        for rec in w_data.get("records") or []:
            if kind == "movie":
                label = rec.get("title") or "Movie"
            else:
                series = (rec.get("series") or {}).get("title") or ""
                ep = f"S{int(rec.get('seasonNumber') or 0):02d}E{int(rec.get('episodeNumber') or 0):02d}"
                label = f"{series} {ep}".strip()
            wanted_items.append({"kind": kind, "title": label})

    return (c_code == 200 or w_code == 200), cal_items, wanted_items


def _jellyfin_recent() -> Dict[str, Any]:
    if not (JELLYFIN_URL and JELLYFIN_API_KEY):
        return {"configured": False, "recent": []}
    code, data = _api_get(
        f"{JELLYFIN_URL.rstrip('/')}/Items/Latest",
        headers={"X-Emby-Token": JELLYFIN_API_KEY, "Accept": "application/json"},
        params={"Limit": 8},
    )
    if code != 200 or not isinstance(data, list):
        return {"configured": True, "reachable": False, "recent": []}
    recent = [
        {"name": item.get("Name") or "Media", "type": item.get("Type") or "", "year": item.get("ProductionYear")}
        for item in data[:8]
        if isinstance(item, dict)
    ]
    return {"configured": True, "reachable": True, "recent": recent}


@media_hub_bp.route("/api/media/overview", methods=["GET"])
def media_overview():
    """Returns Seerr requests, 7-day *Arr calendar, missing items, and Jellyfin recent items."""
    seerr = _seerr_requests()
    radarr_ok, radarr_cal, radarr_want = _arr_calendar_and_wanted(RADARR_URL, RADARR_API_KEY, "movie")
    sonarr_ok, sonarr_cal, sonarr_want = _arr_calendar_and_wanted(SONARR_URL, SONARR_API_KEY, "tv")
    jf = _jellyfin_recent()

    calendar = sorted([*radarr_cal, *sonarr_cal], key=lambda x: x.get("date") or "9999-99-99")
    wanted = [*radarr_want, *sonarr_want]
    return jsonify({
        "requests": seerr,
        "calendar": {
            "configured": bool(RADARR_API_KEY or SONARR_API_KEY),
            "reachable": radarr_ok or sonarr_ok,
            "items": calendar[:16],
        },
        "library": {
            "jellyfin": jf,
            "wanted_configured": bool(RADARR_API_KEY or SONARR_API_KEY),
            "wanted": wanted[:16],
        },
    })


@media_hub_bp.route("/api/media/requests/<int:req_id>/<decision>", methods=["POST"])
def decide_seerr_request(req_id: int, decision: str):
    """Approves or declines a pending Seerr request."""
    if decision not in ("approve", "decline"):
        return jsonify({"success": False, "error": "Decision must be approve or decline."}), 400
    if not (SEERR_URL and SEERR_API_KEY):
        return jsonify({"success": False, "error": "SEERR_API_KEY is not configured."}), 400
    code, body = _api_post(
        f"{SEERR_URL.rstrip('/')}/api/v1/request/{req_id}/{decision}",
        headers={"X-Api-Key": SEERR_API_KEY, "Accept": "application/json"},
    )
    if code in (200, 201, 204):
        return jsonify({"success": True, "id": req_id, "decision": decision})
    msg = (body or {}).get("message") if isinstance(body, dict) else f"Seerr returned HTTP {code or 'unreachable'}"
    return jsonify({"success": False, "error": msg}), 502


@media_hub_bp.route("/api/media/jellyfin/scan", methods=["POST"])
def scan_jellyfin_library():
    """Triggers a Jellyfin library scan across all libraries."""
    if not (JELLYFIN_URL and JELLYFIN_API_KEY):
        return jsonify({"success": False, "error": "JELLYFIN_API_KEY is not configured."}), 400
    code, body = _api_post(
        f"{JELLYFIN_URL.rstrip('/')}/Library/Refresh",
        headers={"X-Emby-Token": JELLYFIN_API_KEY, "Accept": "application/json"},
    )
    if code in (200, 202, 204):
        return jsonify({"success": True, "message": "Jellyfin library scan triggered."})
    msg = (body or {}).get("message") if isinstance(body, dict) else f"Jellyfin returned HTTP {code or 'unreachable'}"
    return jsonify({"success": False, "error": msg}), 502

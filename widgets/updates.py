"""
Widget: Available Updates (Phase 2C)
Compares pinned Docker image tags and Control Hub's own blueprint version against
upstream GitHub releases using core/updates.py with on-disk 24h caching.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from flask import Blueprint, jsonify

from config import UPDATES_AUTO_CHECK, UPDATES_BLUEPRINT_REPO, UPDATES_CACHE_FILE, get_tz_abbr
from core import updates

updates_bp = Blueprint("updates", __name__)

APP_VERSION = "2.1.1"
_bg_lock = threading.Lock()
_bg_running = False


def _trigger_background_refresh(containers: List[Dict]) -> None:
    """Refreshes the GitHub release cache asynchronously without blocking HTTP handlers."""
    global _bg_running
    with _bg_lock:
        if _bg_running:
            return
        _bg_running = True

    def _worker() -> None:
        global _bg_running
        try:
            updates.refresh_if_due(Path(UPDATES_CACHE_FILE), containers, [UPDATES_BLUEPRINT_REPO], force=False)
        finally:
            with _bg_lock:
                _bg_running = False

    threading.Thread(target=_worker, name="updates-refresh", daemon=True).start()


def _format_checked_at(checked_at: Optional[float]) -> Optional[str]:
    if not checked_at:
        return None
    try:
        dt = datetime.fromtimestamp(float(checked_at)).astimezone()
        return dt.strftime(f"%Y-%m-%d %H:%M {get_tz_abbr()}")
    except (OSError, TypeError, ValueError):
        return None


def get_updates_report(refresh_mode: str = "cache") -> Dict:
    """Returns structured update status for Compose containers and the Blueprint host."""
    cache_path = Path(UPDATES_CACHE_FILE)
    containers = updates.running_containers()
    docker_available = containers is not None
    container_list = containers if containers is not None else []

    throttled = False
    cooldown_remaining_s = 0
    cache = updates.load_cache(cache_path)
    age = time.time() - float(cache.get("checked_at") or 0)

    if refresh_mode == "force":
        if cache.get("checked_at") and age < updates.MIN_MANUAL_INTERVAL:
            throttled = True
            cooldown_remaining_s = int(max(1, updates.MIN_MANUAL_INTERVAL - age))
        else:
            cache = updates.refresh_if_due(cache_path, container_list, [UPDATES_BLUEPRINT_REPO], force=True)
    elif refresh_mode == "due" and UPDATES_AUTO_CHECK and container_list and age >= updates.CHECK_EVERY_SECONDS:
        _trigger_background_refresh(container_list)

    self_row = updates.blueprint_row(f"v{APP_VERSION}", cache, UPDATES_BLUEPRINT_REPO)
    rep = updates.report(container_list, cache, self_row=self_row)
    rep["docker_available"] = docker_available
    rep["checked_at_str"] = _format_checked_at(rep.get("checked_at"))
    rep["throttled"] = throttled
    rep["cooldown_remaining_s"] = cooldown_remaining_s
    rep["auto_check_enabled"] = UPDATES_AUTO_CHECK
    if not docker_available:
        rep["docker_error"] = "Docker daemon unavailable; showing host blueprint status only."
    return rep


@updates_bp.route("/api/updates", methods=["GET"])
def api_get_updates():
    """Returns cached container & blueprint release comparison (never blocks on GitHub)."""
    return jsonify(get_updates_report(refresh_mode="due"))


@updates_bp.route("/api/updates/check", methods=["POST"])
def api_check_updates():
    """Triggers an immediate release check (subject to 10-minute cooldown)."""
    return jsonify(get_updates_report(refresh_mode="force"))

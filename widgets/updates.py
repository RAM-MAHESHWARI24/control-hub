"""
Widget: Available Updates & Safe Self/App Updater (Phase 2C)
Compares pinned Docker image tags and Control Hub's own blueprint version against
upstream GitHub releases using core/updates.py with on-disk 24h caching, and
executes one-click updates / automatic rollback / self-updates through the audited
root helper (`homelab-update`) when running in a blueprint installation.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from flask import Blueprint, jsonify, request

from config import (
    UPDATE_HELPER,
    UPDATES_AUTO_CHECK,
    UPDATES_BLUEPRINT_REPO,
    UPDATES_CACHE_FILE,
    UPDATES_POLICY_FILE,
    get_tz_abbr,
)
from core import updates

updates_bp = Blueprint("updates", __name__)

APP_VERSION = "2.2.0"
_SEMVER_TAG_RE = re.compile(r"^v?\d+\.\d+\.\d+$")

_bg_lock = threading.Lock()
_bg_running = False

_job_lock = threading.Lock()
_job_state: Dict = {
    "running": False,
    "kind": None,
    "target": None,
    "started_at": None,
    "finished_at": None,
    "ok": None,
    "rolled_back": False,
    "message": None,
    "results": [],
}


def _helper_available() -> bool:
    return bool(UPDATE_HELPER and os.path.isfile(UPDATE_HELPER))


def _run_helper(args: List[str], timeout: int = 900) -> Dict:
    if not _helper_available():
        return {"ok": False, "error": "Blueprint update helper is not installed on this host."}
    try:
        res = subprocess.run(["sudo", UPDATE_HELPER, *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Update helper timed out after {timeout}s."}
    except OSError as exc:
        return {"ok": False, "error": str(exc)[:200]}
    raw = (res.stdout or "").strip().splitlines()
    for line in reversed(raw):
        try:
            data = json.loads(line)
            if isinstance(data, dict):
                return data
        except ValueError:
            continue
    return {"ok": res.returncode == 0, "error": (res.stderr or res.stdout or f"exit {res.returncode}")[:240]}


def _job_snapshot() -> Dict:
    with _job_lock:
        return {**_job_state, "results": list(_job_state.get("results") or [])}


def _start_job(kind: str, target: str, runner) -> Optional[Dict]:
    with _job_lock:
        if _job_state["running"]:
            return None
        _job_state.update({
            "running": True,
            "kind": kind,
            "target": target,
            "started_at": time.time(),
            "finished_at": None,
            "ok": None,
            "rolled_back": False,
            "message": f"Starting {kind} for {target}...",
            "results": [],
        })
        snap = {**_job_state, "results": []}

    def _thread_target() -> None:
        try:
            outcome = runner()
        except Exception as exc:
            outcome = {"ok": False, "rolled_back": False, "message": str(exc)[:220], "results": []}
        with _job_lock:
            _job_state.update({
                "running": False,
                "finished_at": time.time(),
                "ok": bool(outcome.get("ok", False)),
                "rolled_back": bool(outcome.get("rolled_back", False)),
                "message": outcome.get("message") or ("Completed." if outcome.get("ok") else "Update failed."),
                "results": list(outcome.get("results") or []),
            })

    threading.Thread(target=_thread_target, name="updates-job", daemon=True).start()
    return snap


def _maybe_run_auto_patch(containers: List[Dict], cache: Dict) -> None:
    policy_path = Path(UPDATES_POLICY_FILE)
    policy = updates.load_policy(policy_path)
    if not policy["auto_patch"] or not _helper_available() or not containers:
        return
    last_run = float(policy.get("last_auto_run") or 0)
    if time.time() - last_run < updates.AUTO_PATCH_INTERVAL:
        return
    with _job_lock:
        if _job_state["running"]:
            return
    rep = updates.report(containers, cache)
    targets = [r for r in rep["rows"] if r.get("patch_safe") and r.get("latest") and r.get("container")]
    applied, failed = [], []
    for row in targets:
        res = _run_helper(["app", row["container"], row["latest"]], timeout=600)
        if res.get("ok"):
            applied.append(row["container"])
        else:
            failed.append(row["container"])
    summary = (
        f"Auto-patched {', '.join(applied)}" if applied else "No safe patch updates pending"
    ) + (f"; rolled back {', '.join(failed)}" if failed else "")
    policy["last_auto_run"] = int(time.time())
    policy["last_auto_summary"] = summary
    updates.save_policy(policy_path, policy)


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
            cache = updates.refresh_if_due(Path(UPDATES_CACHE_FILE), containers, [UPDATES_BLUEPRINT_REPO], force=False)
            _maybe_run_auto_patch(containers, cache)
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

    helper_ok = _helper_available()
    self_row = updates.blueprint_row(f"v{APP_VERSION}", cache, UPDATES_BLUEPRINT_REPO)
    rep = updates.report(container_list, cache, self_row=self_row)
    rep["docker_available"] = docker_available
    rep["checked_at_str"] = _format_checked_at(rep.get("checked_at"))
    rep["throttled"] = throttled
    rep["cooldown_remaining_s"] = cooldown_remaining_s
    rep["auto_check_enabled"] = UPDATES_AUTO_CHECK
    rep["helper_available"] = helper_ok
    rep["policy"] = updates.load_policy(Path(UPDATES_POLICY_FILE))
    rep["job"] = _job_snapshot()
    rep["self_update"] = {
        "available": helper_ok,
        "current": self_row.get("current"),
        "latest": self_row.get("latest"),
        "release_url": self_row.get("release_url"),
        "update_ready": bool(helper_ok and self_row.get("kind") in ("update", "rebuild", "major") and self_row.get("latest")),
        "kind": self_row.get("kind"),
    }
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


@updates_bp.route("/api/updates/job", methods=["GET"])
def api_updates_job():
    """Returns status of the running or most recent app/blueprint update job."""
    return jsonify(_job_snapshot())


@updates_bp.route("/api/updates/policy", methods=["POST"])
def api_updates_policy():
    """Updates automatic patch-only update preference."""
    body = request.get_json(silent=True) or {}
    if "auto_patch" not in body or not isinstance(body["auto_patch"], bool):
        return jsonify({"ok": False, "error": "Provide boolean 'auto_patch'."}), 400
    policy_path = Path(UPDATES_POLICY_FILE)
    cur = updates.load_policy(policy_path)
    cur["auto_patch"] = body["auto_patch"]
    saved = updates.save_policy(policy_path, cur)
    return jsonify({"ok": True, "policy": saved})


@updates_bp.route("/api/updates/apply", methods=["POST"])
def api_apply_updates():
    """Applies one app update or all safe non-major app updates through homelab-update."""
    if not _helper_available():
        return jsonify({"ok": False, "error": "One-click updates require the blueprint homelab-update helper."}), 404

    body = request.get_json(silent=True) or {}
    apply_all = bool(body.get("all"))
    target_container = str(body.get("container") or "").strip()

    rep = get_updates_report(refresh_mode="cache")
    app_rows = [r for r in rep["rows"] if r.get("container") and r["container"] != "control-hub"]

    if apply_all:
        targets = [r for r in app_rows if r.get("one_click_allowed") and r.get("latest")]
        if not targets:
            return jsonify({"ok": False, "error": "No safe non-major updates are currently available."}), 400
        job_label = f"{len(targets)} safe app(s)"
    else:
        if not target_container:
            return jsonify({"ok": False, "error": "Provide container or all=true."}), 400
        match = next((r for r in app_rows if r["container"] == target_container), None)
        if not match:
            return jsonify({"ok": False, "error": f"Container '{target_container}' not found in tracked apps."}), 404
        if match.get("kind") == "major":
            return jsonify({"ok": False, "error": match.get("reason") or "Major versions must be upgraded manually."}), 400
        if not match.get("one_click_allowed") or not match.get("latest"):
            return jsonify({"ok": False, "error": f"Container '{target_container}' has no applicable one-click update."}), 400
        targets = [match]
        job_label = target_container

    def _runner() -> Dict:
        results = []
        any_rolled_back = False
        all_ok = True
        for row in targets:
            res = _run_helper(["app", row["container"], row["latest"]], timeout=900)
            res["container"] = row["container"]
            results.append(res)
            if not res.get("ok"):
                all_ok = False
            if res.get("rolled_back"):
                any_rolled_back = True
        if all_ok:
            msg = f"Updated {', '.join(r['container'] for r in targets)} cleanly."
        elif any_rolled_back:
            msg = next((r.get("error") for r in results if not r.get("ok")), "Update failed and rolled back.")
        else:
            msg = next((r.get("error") for r in results if not r.get("ok")), "Update failed.")
        return {"ok": all_ok, "rolled_back": any_rolled_back, "message": msg, "results": results}

    job = _start_job("app_update" if not apply_all else "app_update_all", job_label, _runner)
    if job is None:
        return jsonify({"ok": False, "error": "Another update job is already running."}), 409
    return jsonify({"ok": True, "job": job}), 202


@updates_bp.route("/api/updates/self-update", methods=["POST"])
def api_self_update():
    """Updates Control Hub and Blueprint host configuration to a release tag via homelab-update."""
    if not _helper_available():
        return jsonify({"ok": False, "error": "Blueprint self-update helper is not installed on this host."}), 404

    body = request.get_json(silent=True) or {}
    tag = str(body.get("tag") or "").strip() or None
    if tag and not _SEMVER_TAG_RE.match(tag):
        return jsonify({"ok": False, "error": "Release tag must look like vX.Y.Z."}), 400

    rep = get_updates_report(refresh_mode="cache")
    if not tag:
        latest = (rep.get("self_update") or {}).get("latest")
        if latest and _SEMVER_TAG_RE.match(str(latest)):
            tag = str(latest)

    args = ["self-update", *(["--tag", tag] if tag else [])]

    def _runner() -> Dict:
        res = _run_helper(args, timeout=1800)
        ok = bool(res.get("ok"))
        rolled = bool(res.get("rolled_back"))
        if ok and res.get("changed"):
            msg = f"Blueprint updated to {res.get('tag')}; Control Hub restart scheduled."
        elif ok:
            msg = res.get("message") or "Blueprint already up to date."
        else:
            msg = res.get("error") or "Blueprint self-update failed."
        return {"ok": ok, "rolled_back": rolled, "message": msg, "results": [res]}

    job = _start_job("self_update", tag or "latest release", _runner)
    if job is None:
        return jsonify({"ok": False, "error": "Another update job is already running."}), 409
    return jsonify({"ok": True, "job": job}), 202

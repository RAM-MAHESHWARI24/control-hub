"""
Widget: Alerts (Phase 2B)
Channels, rules, quiet hours and recent alerts. The engine itself lives in
core/alerts.py; this module wires its collectors to the hub's data sources and
exposes the settings to the dashboard.
"""

import subprocess
from datetime import datetime

from flask import Blueprint, jsonify, request

from config import (
    ALERTS_CONFIG_FILE,
    ALERTS_STATE_FILE,
    BACKUP_CRON_FILE,
    BACKUP_STALE_HOURS,
    BACKUP_STATUS_FILE,
    HDD_DATA,
    MEDIA_BACKUP_CRON_FILE,
    MEDIA_BACKUP_STATUS_FILE,
    HDD_MEMORIES,
    SERVICES_CATALOG,
    TV_UPDATER_LOG_FILE,
    TV_UPDATER_PY,
    get_tz_abbr,
)
from core import alerts, auth, backup_health
from widgets import updates as updates_widget

alerts_bp = Blueprint("alerts", __name__)


def _backup_running() -> bool:
    try:
        res = subprocess.run(["pgrep", "-f", "immich_backup_gdrive.sh"], capture_output=True, text=True, timeout=2)
        return bool(res.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


def _media_backup_running() -> bool:
    try:
        res = subprocess.run(["pgrep", "-f", "media_config_backup.py"], capture_output=True, text=True, timeout=2)
        return bool(res.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


def collect(engine: alerts.AlertEngine, state: dict) -> list:
    """Reads every source once and returns what is wrong right now."""
    config = engine.config()
    conditions = []

    status = backup_health.read_status(BACKUP_STATUS_FILE)
    if status is not None:
        summary = backup_health.summarize(
            status, running=_backup_running(), schedule=backup_health.cron_time(BACKUP_CRON_FILE),
            tz_abbr=get_tz_abbr(), stale_after_hours=BACKUP_STALE_HOURS,
        )
        conditions += alerts.collect_backup(status, summary)
        conditions += alerts.collect_restore_test(status)

    media = backup_health.read_status(MEDIA_BACKUP_STATUS_FILE)
    if media is not None:
        summary = backup_health.summarize(
            media, running=_media_backup_running(),
            schedule=backup_health.cron_time(MEDIA_BACKUP_CRON_FILE, "media_config_backup.py"),
            tz_abbr=get_tz_abbr(), stale_after_hours=BACKUP_STALE_HOURS,
        )
        conditions += alerts.collect_backup(media, summary, what="media")

    mounts = ["/"] + [p for p in (HDD_DATA, HDD_MEMORIES) if p]
    conditions += alerts.collect_disks(config, mounts)

    rows = alerts.docker_containers()
    if rows is not None:
        conditions += alerts.collect_containers(config, rows, SERVICES_CATALOG)

    conditions += alerts.collect_cpu_temp(config, alerts.read_cpu_temp())

    if TV_UPDATER_PY and TV_UPDATER_LOG_FILE:
        conditions += alerts.collect_tv_errors(TV_UPDATER_LOG_FILE, state)

    conditions += alerts.collect_signins(auth.failure_counts(), auth.LOGIN_MAX_FAILURES)

    if config["rules"].get("app_updates", {}).get("enabled", True):
        conditions += alerts.collect_updates(updates_widget.get_updates_report(refresh_mode="due"), state)
    return conditions


engine = alerts.AlertEngine(ALERTS_CONFIG_FILE, ALERTS_STATE_FILE, collect)


def start_alerts() -> None:
    engine.start()


def _overview():
    config = engine.config()
    state = engine.state()
    now = datetime.now().astimezone()
    return {
        "config": alerts.masked(config),
        "rules_info": {k: {"title": t, "severity": s} for k, (t, s) in alerts.RULE_INFO.items()},
        "channel_status": state.get("channels", {}),
        "firing": [
            {"key": k, "title": f["title"], "message": f["message"], "severity": f["severity"],
             "since": datetime.fromtimestamp(f["since"]).astimezone().strftime(f"%Y-%m-%d %H:%M {get_tz_abbr()}")}
            for k, f in state.get("firing", {}).items()
        ],
        "history": state.get("history", [])[:30],
        "queued": len(state.get("queue", [])),
        "quiet_now": alerts.in_quiet_hours(config, now),
        "any_channel": any(c.get("enabled") for c in config["channels"].values()),
        "collector_error": state.get("collector_error"),
    }


@alerts_bp.route("/api/alerts", methods=["GET"])
def get_alerts():
    return jsonify(_overview())


@alerts_bp.route("/api/alerts/config", methods=["PUT"])
def put_alerts_config():
    try:
        new = alerts.apply_update(engine.config(), request.get_json(silent=True) or {})
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    engine.save_config(new)
    return jsonify(_overview())


@alerts_bp.route("/api/alerts/test", methods=["POST"])
def test_alert_channel():
    """Sends a test message to one channel, using the form's unsaved values when given."""
    body = request.get_json(silent=True) or {}
    channel = body.get("channel")
    if channel not in alerts.SENDERS:
        return jsonify({"error": f"unknown channel {channel!r}"}), 400
    try:
        config = alerts.apply_update(engine.config(), {"channels": body.get("channels") or {}})
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    msg = alerts.Outgoing("info", "Control Hub test alert",
                          f"This is a test from the Control Hub ({datetime.now().strftime('%Y-%m-%d %H:%M')}). Alerts will arrive here.")
    result = alerts.deliver(config, msg, only=channel).get(channel, "not configured")
    return jsonify({"channel": channel, "ok": result == "", "error": result or None})


@alerts_bp.route("/api/alerts/check", methods=["POST"])
def run_alert_check():
    """Evaluates every rule now instead of waiting for the next minute."""
    sent = engine.tick()
    data = _overview()
    data["sent_now"] = [{"title": m.title, "severity": m.severity} for m in sent]
    return jsonify(data)

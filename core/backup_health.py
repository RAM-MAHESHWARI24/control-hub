"""
Photo backup health, computed from the status.json the backup script writes.

One place decides what the backup card, the scheduled-jobs card and alerts say:

    unknown      no run recorded yet
    syncing      a run is in progress
    synced       the last run succeeded and the last good run is recent
    error        the last run failed (pre-flight or a later step)
    interrupted  status.json says a run was in progress, but no backup process exists
    stale        the last good run is older than STALE_AFTER_HOURS (default 26)

Pure functions (no subprocess, no Flask) so they are easy to test.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

STALE_AFTER_HOURS = 26
HISTORY_SHOWN = 7
_CRON_LINE = re.compile(r"^\s*(\S+)\s+(\S+)\s+\S+\s+\S+\s+\S+\s+\S+\s+.*immich_backup_gdrive\.sh")


def read_status(path: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.astimezone()


def cron_time(cron_file: str) -> Optional[tuple]:
    """(hour, minute) of the daily backup line in the cron file, or None."""
    try:
        text = Path(cron_file).read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        m = _CRON_LINE.match(line)
        if m and m.group(1).isdigit() and m.group(2).isdigit():
            return int(m.group(2)), int(m.group(1))
    return None


def next_run(hour_minute: Optional[tuple], now: datetime) -> Optional[datetime]:
    if not hour_minute:
        return None
    hour, minute = hour_minute
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)


def _fmt(dt: Optional[datetime], tz_abbr: str) -> Optional[str]:
    # The script writes host-local times (date -Is); show them as written.
    return dt.strftime(f"%Y-%m-%d %H:%M {tz_abbr}").strip() if dt else None


def human_age(hours: Optional[float]) -> Optional[str]:
    if hours is None:
        return None
    if hours < 1:
        return f"{max(1, int(hours * 60))} min ago"
    if hours < 48:
        return f"{int(hours)} h ago"
    return f"{int(hours // 24)} days ago"


def human_bytes(n: Optional[float]) -> Optional[str]:
    if not isinstance(n, (int, float)):
        return None
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return None


def summarize(status: Optional[Dict[str, Any]], *, running: bool, now: Optional[datetime] = None,
              schedule: Optional[tuple] = None, tz_abbr: str = "",
              stale_after_hours: float = STALE_AFTER_HOURS) -> Dict[str, Any]:
    """Everything the dashboard and alerts need to know about the photo backup."""
    now = now or datetime.now(timezone.utc).astimezone()
    status = status or {}
    raw = status.get("status") if status else None
    last_good = _parse(status.get("last_good_at"))
    age_hours = round((now - last_good).total_seconds() / 3600, 1) if last_good else None
    nxt = next_run(schedule, now)

    if running:
        state = "syncing"
    elif raw == "syncing":
        state = "interrupted"
    elif raw == "error":
        state = "error"
    elif raw == "synced":
        state = "stale" if age_hours is not None and age_hours > stale_after_hours else "synced"
    else:
        state = "unknown"
    # A failed run is reported as an error even when an older good run is recent;
    # a good run that is too old is stale whatever happened since.
    stale = age_hours is not None and age_hours > stale_after_hours
    if state == "unknown" and not status:
        message = "No backup run recorded yet"
    elif state == "interrupted":
        message = "The last run stopped without finishing (server restarted or the script was killed)"
    elif state == "stale":
        message = f"The last good backup is {human_age(age_hours)}; a nightly run was missed"
    else:
        message = status.get("message") or "No backup run recorded yet"

    history: List[Dict[str, Any]] = []
    for h in (status.get("history") or [])[:HISTORY_SHOWN]:
        started = _parse(h.get("started_at"))
        history.append({
            "started_at": h.get("started_at"),
            "when": _fmt(started, tz_abbr),
            "outcome": h.get("outcome"),
            "message": h.get("message"),
            "dump_file": h.get("dump_file"),
            "dump_size": human_bytes(h.get("dump_bytes")),
            "files": h.get("files"),
            "moved": human_bytes(h.get("bytes")),
            "duration_s": h.get("duration_s"),
        })

    retention = status.get("retention") or None
    if isinstance(retention, dict):
        retention = {
            "kept": retention.get("kept"),
            "deleted_last_run": len(retention.get("delete") or []),
            "next_delete": retention.get("next_delete") or [],
        }

    return {
        "state": state,
        "is_red": state in ("error", "interrupted", "stale") or stale,
        "stale": stale,
        "stale_after_hours": stale_after_hours,
        "message": message,
        "stage": int(status.get("stage") or 0) if status else 0,
        "last_good_at": status.get("last_good_at"),
        "last_good": _fmt(last_good, tz_abbr),
        "age_hours": age_hours,
        "age": human_age(age_hours),
        "next_run_at": nxt.isoformat() if nxt else None,
        "next_run": _fmt(nxt, tz_abbr),
        "history": history,
        "preflight": status.get("preflight"),
        "transfer": status.get("transfer"),
        "retention": retention,
        "remote": status.get("remote"),
    }

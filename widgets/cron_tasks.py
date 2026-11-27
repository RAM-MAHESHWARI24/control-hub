"""
Widget: System Automation & Scheduled Cron Tasks
Monitors and dispatches on-demand execution for actually installed background
automations (photo cloud backup, media settings backup, monthly photo restore
test, Sleep Guard suspend, TV auto-updater, Recyclarr TRaSH sync, and Immich ML).
Reads real schedules from /etc/cron.d/*, /etc/server-suspend.conf, and systemd
timers — never displays phantom uninstalled jobs or hardcoded schedules.
"""

import datetime
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

from flask import Blueprint, jsonify, request

from config import (
    BACKUP_CRON_FILE,
    BACKUP_LOG_FILE,
    BACKUP_SCRIPT,
    BACKUP_STALE_HOURS,
    BACKUP_STATUS_FILE,
    IMMICH_ML_CRON_FILE,
    IMMICH_ML_LOG_FILE,
    MEDIA_BACKUP_CRON_FILE,
    MEDIA_BACKUP_LOG_FILE,
    RECYCLARR_LOG_FILE,
    RESTORE_TEST_UNIT,
    SERVER_SUSPEND_LOG_FILE,
    STATE_DIR,
    SUSPEND_SKIP_FILE,
    get_tz_abbr,
)
from core import backup_health
from widgets.backup_sync import (
    is_syncing_backup,
    media_backup_summary,
    restore_test_info,
    run_media_backup,
    run_restore_test,
    trigger_backup_sync,
)
from widgets.sleep_guard import (
    load_permanent_config,
    load_tonight_override,
    sleep_module_installed,
    toggle_sleep,
)
from widgets.tv_updater import (
    fetch_telemetry_snapshot,
    get_preferred_log_file,
    get_tv_schedule_text,
    is_deploying_tv,
    trigger_tv_deployment,
    tv_module_installed,
)

cron_tasks_bp = Blueprint("cron_tasks", __name__)

CRON_RUNNING_LOCK = threading.Lock()
cron_running_jobs = set()


_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_CRON_LINE_RE = re.compile(r"^(\s*(?:#\s*DISABLED:\s*)?)(\d{1,2})\s+(\d{1,2})(\s+\*\s+\*\s+\*\s+.+)$")


def _validate_hhmm(val: str) -> tuple[int, int, str] | None:
    if not isinstance(val, str):
        return None
    s = val.strip()
    m = _HHMM_RE.match(s)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), s


def _format_next_daily(hour: int, minute: int, tz_abbr: str, now: datetime.datetime | None = None) -> str:
    cur = now or datetime.datetime.now()
    target = cur.replace(hour=hour, minute=minute, second=0, microsecond=0)
    prefix = "Today" if target > cur else "Tomorrow"
    return f"{prefix} {hour:02d}:{minute:02d} {tz_abbr}"


def _parse_cron_hm(cron_file: str, needle: str = ""):
    hm = backup_health.cron_time(cron_file, needle) if cron_file else None
    return hm


def _parse_cron_status_and_hm(cron_file: str, needle: str = "") -> tuple[tuple[int, int] | None, bool]:
    """Reads (hour, minute) and enabled flag even if commented with '# DISABLED:'."""
    hm = _parse_cron_hm(cron_file, needle)
    if hm:
        return hm, True
    if not cron_file or not os.path.isfile(cron_file):
        return None, True
    try:
        for line in Path(cron_file).read_text(encoding="utf-8", errors="replace").splitlines():
            m = _CRON_LINE_RE.match(line)
            if not m:
                continue
            if needle and needle not in m.group(4):
                continue
            minute, hour = int(m.group(2)), int(m.group(3))
            if 0 <= hour < 24 and 0 <= minute < 60:
                return (hour, minute), not bool(m.group(1).strip())
    except OSError:
        pass
    return None, True


def _write_cron_file(cron_file: str, content: str) -> None:
    target = Path(cron_file)
    if os.access(cron_file, os.W_OK) or (not target.exists() and os.access(str(target.parent), os.W_OK)):
        tmp = target.with_name(f".{target.name}.tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, target)
        return
    subprocess.run(
        ["sudo", "tee", cron_file],
        input=content,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
        timeout=10,
    )


def _update_daily_cron_time(cron_file: str, hour: int, minute: int, enabled: bool, needle: str = "") -> None:
    if not cron_file or not os.path.isfile(cron_file):
        raise FileNotFoundError(f"Cron file not found: {cron_file}")
    lines = Path(cron_file).read_text(encoding="utf-8", errors="replace").splitlines()
    replaced = False
    new_lines = []
    prefix = "" if enabled else "# DISABLED: "
    for line in lines:
        m = _CRON_LINE_RE.match(line)
        if m and not replaced and (not needle or needle in m.group(4)):
            new_lines.append(f"{prefix}{minute} {hour}{m.group(4)}")
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        raise ValueError(f"Could not locate daily schedule line in {cron_file}")
    _write_cron_file(cron_file, "\n".join(new_lines) + "\n")


def _in_sleep_window(job_min: int, sleep_min: int, wake_min: int) -> bool:
    if sleep_min == wake_min:
        return False
    if sleep_min < wake_min:
        return sleep_min <= job_min < wake_min
    return job_min >= sleep_min or job_min < wake_min


def _minutes_before_sleep(job_min: int, sleep_min: int) -> int:
    return (sleep_min - job_min) % 1440


def detect_schedule_clashes(jobs: list[dict]) -> list[dict]:
    """Detects overlapping backups or daily jobs scheduled inside the host sleep window."""
    clashes: list[dict] = []
    suspend_job = next((j for j in jobs if j.get("id") == "server_suspend" and j.get("enabled", True)), None)
    sleep_hhmm = suspend_job.get("time_hhmm") if suspend_job else None
    wake_hhmm = suspend_job.get("wake_hhmm") if suspend_job else None

    s_parsed = _validate_hhmm(sleep_hhmm or "")
    w_parsed = _validate_hhmm(wake_hhmm or "")
    if s_parsed and w_parsed:
        s_min = s_parsed[0] * 60 + s_parsed[1]
        w_min = w_parsed[0] * 60 + w_parsed[1]
        for job in jobs:
            jid = job.get("id")
            if jid == "server_suspend" or not job.get("enabled", True):
                continue
            t_parsed = _validate_hhmm(job.get("time_hhmm") or "")
            if not t_parsed:
                continue
            j_min = t_parsed[0] * 60 + t_parsed[1]
            if _in_sleep_window(j_min, s_min, w_min):
                clashes.append({
                    "severity": "warning",
                    "jobs": [jid, "server_suspend"],
                    "message": (
                        f"{job['name']} ({t_parsed[2]}) is inside the {s_parsed[2]} -> {w_parsed[2]} "
                        "Sleep Suspend window and may be skipped while the host sleeps."
                    ),
                })
            elif jid in ("immich_backup", "media_backup") and 0 < _minutes_before_sleep(j_min, s_min) <= 45:
                gap = _minutes_before_sleep(j_min, s_min)
                clashes.append({
                    "severity": "info",
                    "jobs": [jid, "server_suspend"],
                    "message": (
                        f"{job['name']} ({t_parsed[2]}) starts {gap} min before Sleep Suspend "
                        f"({s_parsed[2]}): Sleep Guard will delay sleep until transfers finish."
                    ),
                })

    img_bk = next((j for j in jobs if j.get("id") == "immich_backup" and j.get("enabled", True)), None)
    med_bk = next((j for j in jobs if j.get("id") == "media_backup" and j.get("enabled", True)), None)
    if img_bk and med_bk:
        p1 = _validate_hhmm(img_bk.get("time_hhmm") or "")
        p2 = _validate_hhmm(med_bk.get("time_hhmm") or "")
        if p1 and p2:
            m1, m2 = p1[0] * 60 + p1[1], p2[0] * 60 + p2[1]
            diff = min((m1 - m2) % 1440, (m2 - m1) % 1440)
            if diff <= 15:
                clashes.append({
                    "severity": "info",
                    "jobs": ["immich_backup", "media_backup"],
                    "message": (
                        f"Photo Cloud Backup ({p1[2]}) and Media Settings Backup ({p2[2]}) "
                        "start within 15 min of each other (shared disk and rclone bandwidth)."
                    ),
                })
    return clashes


def _backup_schedule_text(tz_abbr: str) -> str:
    hm, enabled = _parse_cron_status_and_hm(BACKUP_CRON_FILE)
    if not hm:
        return "Not scheduled"
    return f"Daily at {hm[0]:02d}:{hm[1]:02d} {tz_abbr}" if enabled else f"Disabled (was {hm[0]:02d}:{hm[1]:02d} {tz_abbr})"


def _parse_immich_ml_schedule(cron_file: str, tz_abbr: str) -> tuple[str, str]:
    """Reads start/stop schedule from /etc/cron.d/immich-ml if installed (including disabled lines)."""
    from widgets.photos_hub import parse_ml_cron_file

    parsed = parse_ml_cron_file(cron_file)
    s_str = parsed.get("start_time")
    e_str = parsed.get("stop_time")
    if s_str and e_str:
        if parsed.get("enabled"):
            return (
                f"{s_str} (Start) \u2192 {e_str} (Stop) {tz_abbr}",
                f"Auto-starts ML container at {s_str}; auto-stops at {e_str} {tz_abbr} to save RAM",
            )
        return (
            f"Disabled (was {s_str} \u2192 {e_str} {tz_abbr})",
            "Automatic ML schedule is paused; start or stop ML manually as needed",
        )
    return (
        "Manual / No cron schedule",
        "Machine-learning container for photo face recognition & smart search",
    )


@cron_tasks_bp.route("/api/cron/status", methods=["GET"])
def get_cron_tasks_status():
    """Returns real-time status, next run, and clash warnings for all installed schedules."""
    jobs = _collect_cron_jobs()
    clashes = detect_schedule_clashes(jobs)
    return jsonify({"jobs": jobs, "clashes": clashes})


def _collect_cron_jobs() -> list[dict]:
    """Inspects all installed cron files, systemd timers, and host schedules."""
    tz_abbr = get_tz_abbr()
    jobs = []

    # 1. Photo Cloud Backup (only if installed / has status or log)
    photo_backup_present = any(
        p and os.path.exists(p)
        for p in (BACKUP_SCRIPT, BACKUP_CRON_FILE, BACKUP_STATUS_FILE, BACKUP_LOG_FILE)
    )
    if photo_backup_present:
        gdrive_running = is_syncing_backup
        if not gdrive_running:
            try:
                res = subprocess.run(
                    ["pgrep", "-f", "immich_backup_gdrive.sh"],
                    stdout=subprocess.PIPE,
                    text=True,
                    timeout=1.5,
                )
                gdrive_running = bool(res.stdout.strip())
            except Exception:
                pass

        gdrive_last_run = "Never"
        gdrive_summary = None
        gdrive_status_text = "Not Run Yet"
        backup_state = backup_health.read_status(BACKUP_STATUS_FILE)
        if backup_state is not None:
            health = backup_health.summarize(
                backup_state,
                running=gdrive_running,
                tz_abbr=tz_abbr,
                stale_after_hours=BACKUP_STALE_HOURS,
                schedule=backup_health.cron_time(BACKUP_CRON_FILE),
            )
            ts = health["last_good_at"] or backup_state.get("completed_at") or backup_state.get("started_at")
            if ts:
                try:
                    gdrive_last_run = datetime.datetime.fromisoformat(ts).strftime(f"%b %d, %H:%M {tz_abbr}")
                except ValueError:
                    gdrive_last_run = ts
            gdrive_status_text = {
                "synced": "Synced",
                "error": "Error",
                "syncing": "Syncing...",
                "stale": "Stale",
                "interrupted": "Interrupted",
            }.get(health["state"], "Unknown")
            gdrive_summary = health["message"]
        elif BACKUP_LOG_FILE and os.path.exists(BACKUP_LOG_FILE):
            try:
                with open(BACKUP_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()[-60:]
                for line in reversed(lines):
                    for marker in ("Starting Immich Backup:", "Starting Immich / Noodle Backup:"):
                        if marker in line:
                            gdrive_last_run = line.split(marker, 1)[-1].strip()
                            break
                    if gdrive_last_run != "Never":
                        break
                for line in reversed(lines):
                    if "Immich Backup Completed Successfully:" in line:
                        gdrive_status_text = "Synced"
                        break
                    if "ERROR" in line or "Failed" in line:
                        gdrive_status_text = "Error"
                        break
            except Exception:
                pass
        if gdrive_running:
            gdrive_status_text = "Syncing..."

        b_hm, b_enabled = _parse_cron_status_and_hm(BACKUP_CRON_FILE)
        b_hhmm = f"{b_hm[0]:02d}:{b_hm[1]:02d}" if b_hm else None
        b_next = _format_next_daily(b_hm[0], b_hm[1], tz_abbr) if (b_hm and b_enabled) else ("Paused" if not b_enabled else "Not scheduled")
        jobs.append({
            "id": "immich_backup",
            "name": "Photo Cloud Backup",
            "description": "Photo library, face XMP sidecars & PostgreSQL dump to cloud remote",
            "schedule": _backup_schedule_text(tz_abbr),
            "next_run": b_next,
            "time_hhmm": b_hhmm,
            "enabled": b_enabled,
            "editable": bool(BACKUP_CRON_FILE and os.path.isfile(BACKUP_CRON_FILE)),
            "is_running": gdrive_running,
            "status_text": gdrive_status_text,
            "last_run": gdrive_last_run,
            "summary": gdrive_summary,
            "can_run": bool(BACKUP_SCRIPT and os.path.isfile(BACKUP_SCRIPT)),
            "run_label": "Run backup now",
            "icon": "cloud",
        })

    # 2. Media Settings Backup (only if installed)
    media_info = media_backup_summary()
    if media_info is not None:
        m_hm, m_enabled = _parse_cron_status_and_hm(MEDIA_BACKUP_CRON_FILE, "media_config_backup.py")
        m_hhmm = f"{m_hm[0]:02d}:{m_hm[1]:02d}" if m_hm else None
        if not m_hm:
            m_schedule = "Not scheduled"
        elif m_enabled:
            m_schedule = f"Daily at {m_hhmm} {tz_abbr}"
        else:
            m_schedule = f"Disabled (was {m_hhmm} {tz_abbr})"
        m_next = _format_next_daily(m_hm[0], m_hm[1], tz_abbr) if (m_hm and m_enabled) else ("Paused" if not m_enabled else "Not scheduled")
        m_status = {
            "synced": "Synced",
            "error": "Error",
            "syncing": "Syncing...",
            "stale": "Stale",
            "interrupted": "Interrupted",
        }.get(media_info.get("state"), "Not Run Yet")
        jobs.append({
            "id": "media_backup",
            "name": "Media Settings Backup",
            "description": "Nightly archive of Jellyfin, Seerr & *arr databases to cloud remote",
            "schedule": m_schedule,
            "next_run": m_next,
            "time_hhmm": m_hhmm,
            "enabled": m_enabled,
            "editable": bool(MEDIA_BACKUP_CRON_FILE and os.path.isfile(MEDIA_BACKUP_CRON_FILE)),
            "is_running": media_info.get("state") == "syncing",
            "status_text": m_status,
            "last_run": media_info.get("last_good") or "Never",
            "summary": media_info.get("message"),
            "can_run": bool(media_info.get("can_run")),
            "run_label": "Back up now",
            "icon": "database",
        })

    # 3. Monthly Photo Restore Test (only if systemd unit installed)
    restore_info = restore_test_info()
    if restore_info.get("installed"):
        backup_state = backup_health.read_status(BACKUP_STATUS_FILE) or {}
        rt = backup_state.get("restore_test") if isinstance(backup_state.get("restore_test"), dict) else {}
        rt_ok = rt.get("ok")
        if restore_info.get("running"):
            rt_status = "Testing..."
        elif rt_ok is True:
            rt_status = "Verified"
        elif rt_ok is False:
            rt_status = "Failed"
        else:
            rt_status = "Pending"
        jobs.append({
            "id": "photo_restore_test",
            "name": "Photo Backup Restore Test",
            "description": "Restores latest remote database dump into a throwaway Postgres container",
            "schedule": f"Monthly (Next: {restore_info['next']})" if restore_info.get("next") else "Monthly timer",
            "next_run": restore_info.get("next") or "First Sunday 11:00",
            "time_hhmm": None,
            "enabled": True,
            "editable": False,
            "is_running": bool(restore_info.get("running")),
            "status_text": rt_status,
            "last_run": rt.get("tested_at") or "Never",
            "summary": rt.get("message"),
            "can_run": True,
            "run_label": "Test restore",
            "icon": "shield",
        })

    # 4. Server Suspend (only if Sleep Guard installed)
    if sleep_module_installed():
        perm = load_permanent_config()
        override = load_tonight_override()
        sleep_skip = bool(SUSPEND_SKIP_FILE and os.path.exists(SUSPEND_SKIP_FILE))
        enabled = bool(perm.get("enabled", True))
        eff_sleep = (override or perm).get("sleep_time", "00:00")
        eff_wake = (override or perm).get("wake_time", "06:00")
        eff_dur = (override or perm).get("duration_hours", 6.0)

        sleep_last_run = "Never"
        if SERVER_SUSPEND_LOG_FILE and os.path.exists(SERVER_SUSPEND_LOG_FILE):
            try:
                with open(SERVER_SUSPEND_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    for line in reversed(f.readlines()[-30:]):
                        if "[TRIGGER]" in line or "[CRON]" in line or "[RESUME]" in line:
                            sleep_last_run = line.split("]")[0].replace("[", "").strip()
                            break
            except Exception:
                pass

        if override:
            sleep_status_text = f"Shifted ({eff_sleep})"
        elif sleep_skip:
            sleep_status_text = "Skip Tonight"
        elif not enabled:
            sleep_status_text = "Disabled"
        else:
            sleep_status_text = f"Armed ({eff_sleep})"

        sleep_sched = (
            f"Daily at {eff_sleep} {tz_abbr} ({eff_dur}h sleep)"
            if enabled or override
            else f"Disabled (was {eff_sleep} \u2192 {eff_wake} {tz_abbr})"
        )
        s_parsed = _validate_hhmm(eff_sleep)
        s_next = _format_next_daily(s_parsed[0], s_parsed[1], tz_abbr) if (s_parsed and (enabled or override)) else "Disabled"
        jobs.append({
            "id": "server_suspend",
            "name": "Nightly Sleep Suspend",
            "description": f"Suspends hardware to RAM (S3) for {eff_dur}h; wakes at {eff_wake} {tz_abbr}",
            "schedule": sleep_sched,
            "next_run": s_next,
            "time_hhmm": eff_sleep,
            "wake_hhmm": eff_wake,
            "enabled": enabled,
            "editable": True,
            "is_running": False,
            "status_text": sleep_status_text,
            "last_run": sleep_last_run,
            "can_run": False,
            "run_label": "Toggle Skip",
            "icon": "moon",
        })

    # 5. Android TV Auto-Updater (only if installed)
    if tv_module_installed():
        tv_running = is_deploying_tv
        if not tv_running:
            try:
                res = subprocess.run(["pgrep", "-f", "tv_updater.py"], stdout=subprocess.PIPE, text=True, timeout=1.5)
                lines = res.stdout.strip().splitlines()
                if lines and any(int(pid) != os.getpid() for pid in lines if pid.isdigit()):
                    tv_running = True
            except Exception:
                pass

        tv_log_file = get_preferred_log_file()
        tv_last_run = "Never"
        tv_summary = "No runs recorded"
        if tv_log_file and os.path.exists(tv_log_file):
            try:
                mtime = os.path.getmtime(tv_log_file)
                tv_last_run = datetime.datetime.fromtimestamp(mtime).strftime(f"%b %d, %H:%M {tz_abbr}")
                with open(tv_log_file, "r", encoding="utf-8", errors="replace") as f:
                    for line in reversed(f.readlines()[-30:]):
                        s = line.strip()
                        if "[INFO]" in s and ("Successfully" in s or "Installed" in s or "up to date" in s):
                            tv_summary = s.split("[INFO]")[-1].strip()
                            break
                        if "[ERROR]" in s:
                            tv_summary = s.split("[ERROR]")[-1].strip()
                            break
            except Exception:
                pass

        tv_telem = fetch_telemetry_snapshot(force=False)
        total_tvs = len(tv_telem.get("devices") or [])
        if tv_running:
            tv_status_text = "Deploying..."
        elif total_tvs == 0:
            tv_status_text = "No TVs"
        elif tv_telem.get("all_up_to_date"):
            tv_status_text = "Up to Date"
        else:
            tv_status_text = "Updates Pending"

        jobs.append({
            "id": "tv_updater",
            "name": "Android TV App Updater",
            "description": "Silent ADB sideload updater for SmartTube and CloudStream (pinned signing keys)",
            "schedule": get_tv_schedule_text(tz_abbr),
            "next_run": get_tv_schedule_text(tz_abbr),
            "time_hhmm": None,
            "enabled": True,
            "editable": False,
            "is_running": tv_running,
            "status_text": tv_status_text,
            "last_run": tv_last_run,
            "summary": tv_summary,
            "can_run": True,
            "run_label": "Deploy Now",
            "icon": "tv",
        })

    # 6. Recyclarr TRaSH Sync (ONLY if binary, cron, or log actually exists)
    recyclarr_bin = os.getenv("RECYCLARR_BIN", "recyclarr")
    recyclarr_cron = "/etc/cron.d/recyclarr"
    recyclarr_installed = bool(
        shutil.which(recyclarr_bin)
        or os.path.isfile(recyclarr_cron)
        or (RECYCLARR_LOG_FILE and os.path.isfile(RECYCLARR_LOG_FILE))
    )
    if recyclarr_installed:
        rc_running = "recyclarr" in cron_running_jobs
        if not rc_running:
            try:
                res = subprocess.run(["pgrep", "-f", "recyclarr"], stdout=subprocess.PIPE, text=True, timeout=1.5)
                rc_running = bool(res.stdout.strip())
            except Exception:
                pass

        rc_last_run = "Never"
        rc_summary = "No runs recorded"
        rc_status_text = "Syncing..." if rc_running else "Unknown"
        if RECYCLARR_LOG_FILE and os.path.exists(RECYCLARR_LOG_FILE):
            try:
                mtime = os.path.getmtime(RECYCLARR_LOG_FILE)
                rc_last_run = datetime.datetime.fromtimestamp(mtime).strftime(f"%b %d, %H:%M {tz_abbr}")
                with open(RECYCLARR_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()[-30:]
                has_err = False
                for line in reversed(lines):
                    s = line.strip()
                    if "Completed at" in s or "Finished" in s or "Created" in s or "Updated" in s:
                        rc_summary = s
                        break
                    if "[ERR]" in s or "ERROR" in s or "Failed" in s:
                        has_err = True
                        rc_summary = s
                        break
                rc_status_text = "Syncing..." if rc_running else ("Error" if has_err else "Synced")
            except Exception:
                pass

        rc_hm, rc_enabled = _parse_cron_status_and_hm(recyclarr_cron, "recyclarr")
        rc_hhmm = f"{rc_hm[0]:02d}:{rc_hm[1]:02d}" if rc_hm else None
        if not rc_hm:
            rc_schedule = "Manual / Not scheduled"
        elif rc_enabled:
            rc_schedule = f"Daily at {rc_hhmm} {tz_abbr}"
        else:
            rc_schedule = f"Disabled (was {rc_hhmm} {tz_abbr})"
        rc_next = _format_next_daily(rc_hm[0], rc_hm[1], tz_abbr) if (rc_hm and rc_enabled) else "Not scheduled"
        jobs.append({
            "id": "recyclarr",
            "name": "Recyclarr TRaSH Sync",
            "description": "Syncs TRaSH quality profiles and release scores with Sonarr and Radarr",
            "schedule": rc_schedule,
            "next_run": rc_next,
            "time_hhmm": rc_hhmm,
            "enabled": rc_enabled,
            "editable": os.path.isfile(recyclarr_cron),
            "is_running": rc_running,
            "status_text": rc_status_text,
            "last_run": rc_last_run,
            "summary": rc_summary,
            "can_run": bool(shutil.which(recyclarr_bin)),
            "run_label": "Sync TRaSH",
            "icon": "sliders",
        })

    # 7. Immich Machine Learning (ONLY if container or cron exists)
    ml_running = False
    ml_exists = False
    try:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", "immich_machine_learning"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        if res.returncode == 0 and res.stdout.strip() in ("true", "false"):
            ml_exists = True
            ml_running = res.stdout.strip() == "true"
    except Exception:
        pass

    ml_cron_exists = bool(IMMICH_ML_CRON_FILE and os.path.isfile(IMMICH_ML_CRON_FILE))
    if ml_exists or ml_cron_exists:
        ml_last_run = "Never"
        if IMMICH_ML_LOG_FILE and os.path.exists(IMMICH_ML_LOG_FILE):
            try:
                mtime = os.path.getmtime(IMMICH_ML_LOG_FILE)
                ml_last_run = datetime.datetime.fromtimestamp(mtime).strftime(f"%b %d, %H:%M {tz_abbr}")
            except Exception:
                pass

        from widgets.photos_hub import parse_ml_cron_file
        ml_parsed = parse_ml_cron_file(IMMICH_ML_CRON_FILE)
        ml_sched, ml_desc = _parse_immich_ml_schedule(IMMICH_ML_CRON_FILE, tz_abbr)
        ml_start_hm = _validate_hhmm(ml_parsed.get("start_time") or "")
        ml_next = (
            _format_next_daily(ml_start_hm[0], ml_start_hm[1], tz_abbr)
            if (ml_start_hm and ml_parsed.get("enabled"))
            else ("Paused" if ml_cron_exists and not ml_parsed.get("enabled") else "Manual")
        )
        jobs.append({
            "id": "immich_ml",
            "name": "Photo Machine Learning",
            "description": ml_desc,
            "schedule": ml_sched,
            "next_run": ml_next,
            "time_hhmm": ml_parsed.get("start_time"),
            "stop_hhmm": ml_parsed.get("stop_time"),
            "enabled": bool(ml_parsed.get("enabled", True)),
            "editable": ml_cron_exists,
            "is_running": ml_running,
            "status_text": "Active (AI)" if ml_running else ("Conserved" if ml_exists else "Not Installed"),
            "last_run": ml_last_run,
            "can_run": ml_exists,
            "run_label": "Stop ML" if ml_running else "Start ML",
            "icon": "cpu",
        })

    # 8. Mediaserver Smart Auto-Import (ONLY if cron exists)
    autoimport_cron = "/etc/cron.d/mediaserver-autoimport"
    autoimport_log = str(STATE_DIR / "mediaserver-autoimport.log")
    if os.path.isfile(autoimport_cron):
        ai_last_run = "Never"
        if os.path.isfile(autoimport_log):
            try:
                mtime = os.path.getmtime(autoimport_log)
                ai_last_run = datetime.datetime.fromtimestamp(mtime).strftime(f"%b %d, %H:%M {tz_abbr}")
            except OSError:
                pass
        jobs.append({
            "id": "mediaserver_autoimport",
            "name": "Media Smart Auto-Import",
            "description": "Clears title-verified Radarr & Sonarr Manual Import queue holds",
            "schedule": "Every 3 min",
            "next_run": "Within 3 min",
            "time_hhmm": None,
            "enabled": True,
            "editable": False,
            "is_running": False,
            "status_text": "Active",
            "last_run": ai_last_run,
            "can_run": False,
            "run_label": "Auto-runs every 3m",
            "icon": "sliders",
        })

    return jobs


@cron_tasks_bp.route("/api/cron/schedule/<job_id>", methods=["POST"])
def update_cron_schedule(job_id: str):
    """Updates or previews a scheduled job time and returns updated jobs + clash warnings."""
    body = request.get_json(silent=True) or {}
    time_str = str(body.get("time") or "").strip()
    enabled = bool(body.get("enabled", True))
    preview_only = bool(body.get("preview_only", False))

    parsed = _validate_hhmm(time_str)
    if not parsed:
        return jsonify({"ok": False, "error": "Time must use 24-hour HH:MM format."}), 400
    hour, minute, norm_time = parsed

    if preview_only:
        jobs = _collect_cron_jobs()
        found = False
        for job in jobs:
            if job.get("id") == job_id:
                job["time_hhmm"] = norm_time
                job["enabled"] = enabled
                if job_id == "server_suspend" and body.get("wake_time"):
                    w_p = _validate_hhmm(str(body.get("wake_time")))
                    if w_p:
                        job["wake_hhmm"] = w_p[2]
                if job_id == "immich_ml" and body.get("stop_time"):
                    s_p = _validate_hhmm(str(body.get("stop_time")))
                    if s_p:
                        job["stop_hhmm"] = s_p[2]
                found = True
                break
        if not found:
            return jsonify({"ok": False, "error": f"Schedule job '{job_id}' is not installed."}), 404
        return jsonify({"ok": True, "preview": True, "clashes": detect_schedule_clashes(jobs)})

    try:
        if job_id == "immich_backup":
            _update_daily_cron_time(BACKUP_CRON_FILE, hour, minute, enabled)
        elif job_id == "media_backup":
            _update_daily_cron_time(MEDIA_BACKUP_CRON_FILE, hour, minute, enabled, "media_config_backup.py")
        elif job_id == "recyclarr":
            _update_daily_cron_time("/etc/cron.d/recyclarr", hour, minute, enabled, "recyclarr")
        elif job_id == "immich_ml":
            from widgets.photos_hub import write_ml_cron_file
            stop_time = str(body.get("stop_time") or "10:00").strip()
            write_ml_cron_file(IMMICH_ML_CRON_FILE, enabled, norm_time, stop_time)
        elif job_id == "server_suspend":
            from widgets.sleep_guard import load_permanent_config, save_permanent_config
            cur_perm = load_permanent_config()
            wake_str = str(body.get("wake_time") or cur_perm.get("wake_time") or "06:00").strip()
            w_p = _validate_hhmm(wake_str)
            if not w_p:
                return jsonify({"ok": False, "error": "Wake time must use 24-hour HH:MM format."}), 400
            s_mins = hour * 60 + minute
            w_mins = w_p[0] * 60 + w_p[1]
            dur_mins = w_mins - s_mins
            if dur_mins <= 0:
                dur_mins += 1440
            save_permanent_config({
                "enabled": enabled,
                "sleep_time": norm_time,
                "wake_time": w_p[2],
                "duration_hours": round(dur_mins / 60.0, 1),
                "duration_seconds": dur_mins * 60,
            })
        else:
            return jsonify({"ok": False, "error": f"Schedule for '{job_id}' is not editable."}), 400
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or "Permission denied updating cron schedule").strip()[:200]
        return jsonify({"ok": False, "error": err}), 500
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)[:200]}), 500

    jobs = _collect_cron_jobs()
    clashes = detect_schedule_clashes(jobs)
    return jsonify({
        "ok": True,
        "message": f"Updated schedule for '{job_id}' to {norm_time}" + (" (enabled)" if enabled else " (paused)"),
        "jobs": jobs,
        "clashes": clashes,
    })


@cron_tasks_bp.route("/api/cron/log/<job_id>", methods=["GET"])
def get_cron_job_log(job_id):
    """Returns the tail of the log file for any registered cron job."""
    if job_id == "photo_restore_test":
        try:
            proc = subprocess.run(
                ["journalctl", "-u", f"{RESTORE_TEST_UNIT}.service", "-n", "120", "--no-pager"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=5,
            )
            return jsonify({
                "job_id": job_id,
                "log_file": f"journalctl -u {RESTORE_TEST_UNIT}.service",
                "log": proc.stdout or "No journal entries recorded yet.",
            })
        except Exception as exc:
            return jsonify({"job_id": job_id, "log_file": RESTORE_TEST_UNIT, "log": f"Unable to read journal: {exc}"})

    log_map = {
        "immich_backup": BACKUP_LOG_FILE,
        "media_backup": MEDIA_BACKUP_LOG_FILE,
        "server_suspend": SERVER_SUSPEND_LOG_FILE,
        "recyclarr": RECYCLARR_LOG_FILE,
        "immich_ml": IMMICH_ML_LOG_FILE,
        "tv_updater": get_preferred_log_file(),
        "mediaserver_autoimport": str(STATE_DIR / "mediaserver-autoimport.log"),
    }
    if job_id not in log_map:
        return jsonify({"error": "Unknown cron job ID"}), 404

    log_file = log_map[job_id]
    if not log_file or not os.path.exists(log_file):
        return jsonify({
            "job_id": job_id,
            "log_file": log_file,
            "log": f"Log file for '{job_id}' is empty or does not exist yet.",
        })

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return jsonify({
                "job_id": job_id,
                "log_file": log_file,
                "log": "".join(lines[-120:]),
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@cron_tasks_bp.route("/api/cron/run/<job_id>", methods=["POST"])
def trigger_cron_job(job_id):
    """Triggers on-demand execution of an automation / cron job."""
    if job_id == "immich_backup":
        return trigger_backup_sync()
    if job_id == "media_backup":
        return run_media_backup()
    if job_id == "photo_restore_test":
        return run_restore_test()
    if job_id == "server_suspend":
        return toggle_sleep()
    if job_id == "tv_updater":
        return trigger_tv_deployment()

    def run_job_thread(jid):
        with CRON_RUNNING_LOCK:
            cron_running_jobs.add(jid)
        try:
            if jid == "recyclarr":
                recyclarr_bin = os.getenv("RECYCLARR_BIN", "recyclarr")
                recyclarr_cfg = os.getenv("RECYCLARR_CONFIG", os.path.expanduser("~/.config/recyclarr/recyclarr.yml"))
                subprocess.run([recyclarr_bin, "sync", "--config", recyclarr_cfg], check=False, timeout=180)
            elif jid == "immich_ml":
                res = subprocess.run(
                    ["docker", "inspect", "-f", "{{.State.Running}}", "immich_machine_learning"],
                    stdout=subprocess.PIPE,
                    text=True,
                    timeout=5,
                )
                is_up = res.stdout.strip() == "true"
                act = "stop" if is_up else "start"
                ml_script = "/usr/local/sbin/immich-ml-control.sh"
                if os.path.isfile(ml_script):
                    subprocess.run(["sudo", ml_script, act], check=False, timeout=60)
                else:
                    subprocess.run(["docker", act, "immich_machine_learning"], check=False, timeout=60)
        except Exception:
            pass
        finally:
            with CRON_RUNNING_LOCK:
                cron_running_jobs.discard(jid)

    if job_id not in ["recyclarr", "immich_ml"]:
        return jsonify({"success": False, "error": f"Invalid job ID '{job_id}'"}), 400

    if job_id in cron_running_jobs:
        return jsonify({"success": False, "message": f"{job_id} is already executing..."})

    t = threading.Thread(target=run_job_thread, args=(job_id,), daemon=True)
    t.start()
    return jsonify({"success": True, "message": f"Task '{job_id}' started in background."})

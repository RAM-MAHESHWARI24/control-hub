"""
Widget: System Automation & Scheduled Cron Tasks
Monitors and dispatches on-demand execution for the background automations:
1) cloud photo backup, 2) midnight sleep suspend, 3) TV auto-updater (if installed),
4) Recyclarr TRaSH sync, and 5) Immich machine-learning scheduler.
Container image updates arrive as Dependabot pull requests (images are pinned);
there is no Watchtower job.
"""

import datetime
import json
import os
import subprocess
import threading
from pathlib import Path

from flask import Blueprint, jsonify

from config import (
    BACKUP_LOG_FILE,
    BACKUP_STATUS_FILE,
    IMMICH_ML_LOG_FILE,
    RECYCLARR_LOG_FILE,
    SERVER_SUSPEND_LOG_FILE,
    SUSPEND_SKIP_FILE,
    get_tz_abbr,
)
from widgets.backup_sync import is_syncing_backup, trigger_backup_sync
from widgets.sleep_guard import toggle_sleep
from widgets.tv_updater import (
    fetch_telemetry_snapshot,
    get_preferred_log_file,
    is_deploying_tv,
    trigger_tv_deployment,
    tv_module_installed,
)

cron_tasks_bp = Blueprint("cron_tasks", __name__)

CRON_RUNNING_LOCK = threading.Lock()
cron_running_jobs = set()


@cron_tasks_bp.route("/api/cron/status", methods=["GET"])
def get_cron_tasks_status():
    """Returns real-time status of registered system cron jobs and background tasks."""
    tz_abbr = get_tz_abbr()

    # 1. Google Drive Cloud Backup
    gdrive_running = is_syncing_backup
    if not gdrive_running:
        try:
            res = subprocess.run(["pgrep", "-f", "immich_backup_gdrive.sh"], stdout=subprocess.PIPE, text=True, timeout=1.5)
            gdrive_running = bool(res.stdout.strip())
        except Exception:
            pass

    gdrive_last_run = "Never"
    gdrive_status_text = "Not Run Yet"
    status_path = Path(BACKUP_STATUS_FILE)
    if status_path.exists():
        try:
            st = json.loads(status_path.read_text(encoding="utf-8"))
            ts_str = st.get("last_good_at") or st.get("completed_at") or st.get("started_at")
            if ts_str:
                try:
                    dt = datetime.datetime.fromisoformat(ts_str)
                    gdrive_last_run = dt.strftime(f"%b %d, %H:%M {tz_abbr}")
                except ValueError:
                    gdrive_last_run = ts_str
            raw_st = st.get("status")
            if raw_st == "synced":
                gdrive_status_text = "Synced"
            elif raw_st == "error":
                gdrive_status_text = "Error"
            elif raw_st == "syncing":
                gdrive_status_text = "Syncing..."
            else:
                gdrive_status_text = "Unknown"
        except Exception:
            pass
    elif os.path.exists(BACKUP_LOG_FILE):
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

    # 2. Server Suspend (Sleep)
    sleep_skip = os.path.exists(SUSPEND_SKIP_FILE)
    sleep_last_run = "Never"
    if os.path.exists(SERVER_SUSPEND_LOG_FILE):
        try:
            with open(SERVER_SUSPEND_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                for line in reversed(f.readlines()[-30:]):
                    if "[TRIGGER]" in line or "[CRON]" in line or "[RESUME]" in line:
                        sleep_last_run = line.split("]")[0].replace("[", "").strip()
                        break
        except Exception:
            pass

    # 3. Recyclarr TRaSH Sync
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
    if os.path.exists(RECYCLARR_LOG_FILE):
        try:
            mtime = os.path.getmtime(RECYCLARR_LOG_FILE)
            rc_last_run = datetime.datetime.fromtimestamp(mtime).strftime(f"%b %d, %H:%M {tz_abbr}")
            rc_status_text = "Syncing..." if rc_running else "Synced"
            with open(RECYCLARR_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                for line in reversed(lines[-20:]):
                    s = line.strip()
                    if "Completed at" in s or "Finished" in s or "Created" in s or "Updated" in s:
                        rc_summary = s
                        break
        except Exception:
            pass

    # 4. Immich ML
    ml_running = False
    ml_exists = False
    try:
        res = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", "immich_machine_learning"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=2)
        if res.returncode == 0:
            ml_exists = True
            ml_running = (res.stdout.strip() == "true")
    except Exception:
        pass

    ml_last_run = "Never"
    if os.path.exists(IMMICH_ML_LOG_FILE):
        try:
            mtime = os.path.getmtime(IMMICH_ML_LOG_FILE)
            ml_last_run = datetime.datetime.fromtimestamp(mtime).strftime(f"%b %d, %H:%M {tz_abbr}")
        except Exception:
            pass

    jobs = [
        {
            "id": "immich_backup",
            "name": "Google Drive Cloud Backup",
            "description": "Noodle Gallery media, face XMP sidecars & PostgreSQL dump",
            "schedule": f"Daily at 22:00 {tz_abbr}",
            "is_running": gdrive_running,
            "status_text": gdrive_status_text,
            "last_run": gdrive_last_run,
            "can_run": True,
            "run_label": "Sync Now",
            "icon": "cloud",
        },
        {
            "id": "server_suspend",
            "name": "Midnight Sleep Suspend",
            "description": f"Suspends hardware to RAM (S3) for 6 hours; auto-wakes at 06:00 {tz_abbr}",
            "schedule": f"Daily at 00:00 {tz_abbr} (6h sleep)",
            "is_running": False,
            "status_text": "Sleep Disabled" if sleep_skip else "Armed (00:00)",
            "last_run": sleep_last_run,
            "can_run": False,
            "run_label": "Toggle Mode",
            "icon": "moon",
        },
    ]

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
        if os.path.exists(tv_log_file):
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
            "description": "Silent ADB sideload updater for SmartTube and CloudStream (official releases, pinned signing keys)",
            "schedule": f"Every 15 min (06:00 - 23:59 {tz_abbr})",
            "is_running": tv_running,
            "status_text": tv_status_text,
            "last_run": tv_last_run,
            "summary": tv_summary,
            "can_run": True,
            "run_label": "Deploy Now",
            "icon": "tv",
        })

    jobs.extend([
        {
            "id": "recyclarr",
            "name": "Recyclarr TRaSH Sync",
            "description": "Syncs TRaSH quality profiles and release scores with Sonarr and Radarr",
            "schedule": f"Daily at 06:30 {tz_abbr}",
            "is_running": rc_running,
            "status_text": rc_status_text,
            "last_run": rc_last_run,
            "summary": rc_summary,
            "can_run": True,
            "run_label": "Sync TRaSH",
            "icon": "sliders",
        },
        {
            "id": "immich_ml",
            "name": "Immich Machine Learning",
            "description": "Auto-starts ML container at 06:00; auto-stops at 10:00 to save RAM",
            "schedule": "06:00 (Start) ➔ 10:00 (Stop)",
            "is_running": ml_running,
            "status_text": "Active (AI)" if ml_running else ("Conserved" if ml_exists else "Not Installed"),
            "last_run": ml_last_run,
            "can_run": ml_exists,
            "run_label": "Stop ML" if ml_running else "Start ML",
            "icon": "cpu",
        },
    ])

    return jsonify({"jobs": jobs})


@cron_tasks_bp.route("/api/cron/log/<job_id>", methods=["GET"])
def get_cron_job_log(job_id):
    """Returns the tail of the log file for any registered cron job."""
    if job_id == "immich_backup":
        log_file = BACKUP_LOG_FILE
    elif job_id == "server_suspend":
        log_file = SERVER_SUSPEND_LOG_FILE
    elif job_id == "recyclarr":
        log_file = RECYCLARR_LOG_FILE
    elif job_id == "immich_ml":
        log_file = IMMICH_ML_LOG_FILE
    elif job_id == "tv_updater":
        log_file = get_preferred_log_file()
    else:
        return jsonify({"error": "Unknown cron job ID"}), 404

    if not log_file or not os.path.exists(log_file):
        return jsonify({"job_id": job_id, "log_file": log_file, "log": f"Log file for '{job_id}' is empty or does not exist yet."})

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
                res = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", "immich_machine_learning"], stdout=subprocess.PIPE, text=True, timeout=5)
                is_up = (res.stdout.strip() == "true")
                act = "stop" if is_up else "start"
                subprocess.run(["sudo", "/usr/local/sbin/immich-ml-control.sh", act], check=False, timeout=60)
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

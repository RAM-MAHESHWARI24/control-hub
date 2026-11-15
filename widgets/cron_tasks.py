"""
Widget: System Automation & Scheduled Cron Tasks
Monitors and dispatches on-demand execution for the background automations:
1) cloud photo backup, 2) midnight sleep suspend, 3) TV auto-updater,
4) Recyclarr TRaSH sync, and 5) Immich machine-learning scheduler.
Container image updates arrive as Dependabot pull requests (images are pinned);
there is no Watchtower job.
"""

import os
import datetime
import threading
import subprocess
from flask import Blueprint, jsonify

from config import (
    BACKUP_LOG_FILE,
    RECYCLARR_LOG_FILE, IMMICH_ML_LOG_FILE,
    SERVER_SUSPEND_LOG_FILE, SUSPEND_SKIP_FILE
)
from widgets.backup_sync import is_syncing_backup, trigger_backup_sync
from widgets.sleep_guard import toggle_sleep
from widgets.tv_updater import (
    is_deploying_tv, trigger_tv_deployment,
    get_preferred_log_file, fetch_telemetry_snapshot
)

cron_tasks_bp = Blueprint("cron_tasks", __name__)

CRON_RUNNING_LOCK = threading.Lock()
cron_running_jobs = set()

@cron_tasks_bp.route("/api/cron/status", methods=["GET"])
def get_cron_tasks_status():
    """Returns real-time status of all 5 system cron jobs and background tasks"""
    # 1. Google Drive Cloud Backup
    gdrive_running = is_syncing_backup
    if not gdrive_running:
        try:
            res = subprocess.run(["pgrep", "-f", "immich_backup_gdrive.sh"], stdout=subprocess.PIPE, text=True)
            gdrive_running = bool(res.stdout.strip())
        except Exception:
            pass

    gdrive_last_run = "Unknown"
    if os.path.exists(BACKUP_LOG_FILE):
        try:
            with open(BACKUP_LOG_FILE, "r") as f:
                for line in reversed(f.readlines()[-60:]):
                    if "Starting Immich / Noodle Backup:" in line:
                        gdrive_last_run = line.split("Starting Immich / Noodle Backup:")[-1].strip()
                        break
        except Exception:
            pass

    # 2. Server Suspend (Sleep)
    sleep_skip = os.path.exists(SUSPEND_SKIP_FILE)
    sleep_last_run = "Unknown"
    if os.path.exists(SERVER_SUSPEND_LOG_FILE):
        try:
            with open(SERVER_SUSPEND_LOG_FILE, "r") as f:
                for line in reversed(f.readlines()[-30:]):
                    if "[CRON] Server suspend check triggered." in line or "[RESUME]" in line:
                        sleep_last_run = line.split("]")[0].replace("[", "").strip()
                        break
        except Exception:
            pass

    # 4. Recyclarr TRaSH Sync
    rc_running = "recyclarr" in cron_running_jobs
    if not rc_running:
        try:
            res = subprocess.run(["pgrep", "-f", "recyclarr"], stdout=subprocess.PIPE, text=True)
            rc_running = bool(res.stdout.strip())
        except Exception:
            pass

    rc_last_run = "Unknown"
    rc_summary = "Quality profiles synced"
    if os.path.exists(RECYCLARR_LOG_FILE):
        try:
            mtime = os.path.getmtime(RECYCLARR_LOG_FILE)
            rc_last_run = datetime.datetime.fromtimestamp(mtime).strftime("%b %d, %H:%M IST")
            with open(RECYCLARR_LOG_FILE, "r") as f:
                lines = f.readlines()
                for line in reversed(lines[-20:]):
                    s = line.strip()
                    if "Completed at" in s or "Finished" in s or "Created" in s or "Updated" in s:
                        rc_summary = s
                        break
        except Exception:
            pass

    # 5. Immich ML
    ml_running = False
    try:
        res = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", "immich_machine_learning"], stdout=subprocess.PIPE, text=True)
        ml_running = (res.stdout.strip() == "true")
    except Exception:
        pass

    ml_last_run = "Unknown"
    if os.path.exists(IMMICH_ML_LOG_FILE):
        try:
            mtime = os.path.getmtime(IMMICH_ML_LOG_FILE)
            ml_last_run = datetime.datetime.fromtimestamp(mtime).strftime("%b %d, %H:%M IST")
        except Exception:
            pass

    # 6. Android TV auto-updater
    tv_running = is_deploying_tv
    if not tv_running:
        try:
            res = subprocess.run(["pgrep", "-f", "tv_updater.py"], stdout=subprocess.PIPE, text=True)
            lines = res.stdout.strip().splitlines()
            if lines and any(int(pid) != os.getpid() for pid in lines if pid.isdigit()):
                tv_running = True
        except Exception:
            pass

    tv_log_file = get_preferred_log_file()
    tv_last_run = "Unknown"
    tv_summary = "Cluster up to date"
    if os.path.exists(tv_log_file):
        try:
            mtime = os.path.getmtime(tv_log_file)
            tv_last_run = datetime.datetime.fromtimestamp(mtime).strftime("%b %d, %H:%M IST")
            with open(tv_log_file, "r", encoding="utf-8", errors="replace") as f:
                for line in reversed(f.readlines()[-30:]):
                    s = line.strip()
                    if "[INFO]" in s and ("Successfully" in s or "Installed" in s or "up to date" in s):
                        tv_summary = s.split("[INFO]")[-1].strip()
                        break
                    elif "[ERROR]" in s:
                        tv_summary = s.split("[ERROR]")[-1].strip()
                        break
        except Exception:
            pass

    tv_telem = fetch_telemetry_snapshot(force=False)
    tv_all_ok = tv_telem.get("all_up_to_date", True)
    tv_status_text = "Deploying..." if tv_running else ("Up to Date" if tv_all_ok else "Updates Pending")

    jobs = [
        {
            "id": "immich_backup",
            "name": "Google Drive Cloud Backup",
            "description": "Noodle Gallery media, face XMP sidecars & PostgreSQL dump",
            "schedule": "Daily at 10:00 PM IST",
            "is_running": gdrive_running,
            "status_text": "Syncing..." if gdrive_running else "Synced",
            "last_run": gdrive_last_run,
            "can_run": True,
            "run_label": "Sync Now",
            "icon": "cloud"
        },
        {
            "id": "server_suspend",
            "name": "Midnight Sleep Suspend",
            "description": "Suspends hardware to RAM (S3) for 6 hours; auto-wakes at 06:00 IST",
            "schedule": "Daily at 00:00 IST (6h sleep)",
            "is_running": False,
            "status_text": "Sleep Disabled" if sleep_skip else "Armed (00:00)",
            "last_run": sleep_last_run,
            "can_run": False,
            "run_label": "Toggle Mode",
            "icon": "moon"
        },
        {
            "id": "tv_updater",
            "name": "Android TV App Updater",
            "description": "Silent ADB sideload updater for SmartTube and CloudStream (official releases, pinned signing keys)",
            "schedule": "Every 15 min (06:00 - 23:59 IST)",
            "is_running": tv_running,
            "status_text": tv_status_text,
            "last_run": tv_last_run,
            "summary": tv_summary,
            "can_run": True,
            "run_label": "Deploy Now",
            "icon": "tv"
        },
        {
            "id": "recyclarr",
            "name": "Recyclarr TRaSH Sync",
            "description": "Syncs TRaSH quality profiles and release scores with Sonarr and Radarr",
            "schedule": "Daily at 06:30 AM IST",
            "is_running": rc_running,
            "status_text": "Syncing..." if rc_running else "Synced",
            "last_run": rc_last_run,
            "summary": rc_summary,
            "can_run": True,
            "run_label": "Sync TRaSH",
            "icon": "sliders"
        },
        {
            "id": "immich_ml",
            "name": "Immich Machine Learning",
            "description": "Auto-starts ML container at 06:00 AM; auto-stops at 10:00 AM to save RAM",
            "schedule": "06:00 AM (Start) ➔ 10:00 AM (Stop)",
            "is_running": ml_running,
            "status_text": "Active (AI)" if ml_running else "Conserved",
            "last_run": ml_last_run,
            "can_run": True,
            "run_label": "Stop ML" if ml_running else "Start ML",
            "icon": "cpu"
        }
    ]

    return jsonify({"jobs": jobs})


@cron_tasks_bp.route("/api/cron/log/<job_id>", methods=["GET"])
def get_cron_job_log(job_id):
    """Returns the tail of the log file for any registered cron job"""
    log_file = None
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
        return jsonify({"job_id": job_id, "log": f"Log file for '{job_id}' is empty or does not exist yet."})

    try:
        with open(log_file, "r") as f:
            lines = f.readlines()
            return jsonify({
                "job_id": job_id,
                "log_file": log_file,
                "log": "".join(lines[-120:])
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@cron_tasks_bp.route("/api/cron/run/<job_id>", methods=["POST"])
def trigger_cron_job(job_id):
    """Triggers on-demand execution of an automation / cron job"""
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
                subprocess.run([recyclarr_bin, "sync", "--config", recyclarr_cfg], check=False)
            elif jid == "immich_ml":
                res = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", "immich_machine_learning"], stdout=subprocess.PIPE, text=True)
                is_up = (res.stdout.strip() == "true")
                act = "stop" if is_up else "start"
                subprocess.run(["sudo", "/usr/local/sbin/immich-ml-control.sh", act], check=False)
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

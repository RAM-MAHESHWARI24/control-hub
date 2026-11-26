"""
Widget: Photo & Media Cloud Backup Monitor
Monitors photo backup pipeline execution via status.json (or log fallback),
cloud remote quota, PostgreSQL dumps, restore tests, media app settings backups,
and Immich/Noodle asset & face telemetry. Never returns invented fallback values.
"""

import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

from config import (
    APPDATA_DIR,
    BACKUP_CRON_FILE,
    BACKUP_DIR,
    BACKUP_LOG_FILE,
    BACKUP_REMOTE_HELPER,
    BACKUP_SCRIPT,
    BACKUP_STALE_HOURS,
    BACKUP_STATUS_FILE,
    GDRIVE_REMOTE,
    HDD_DATA,
    HDD_MEMORIES,
    IMMICH_DB_CONTAINER,
    IMMICH_DB_NAME,
    IMMICH_DB_USER,
    MEDIA_BACKUP_CRON_FILE,
    MEDIA_BACKUP_SCRIPT,
    MEDIA_BACKUP_STATUS_FILE,
    PHOTO_UPLOAD_DIR,
    RESTORE_TEST_UNIT,
    STORAGE_SIZES_CACHE_FILE,
    SYSTEMD_UNIT_DIR,
    get_host_timezone,
    get_tz_abbr,
)
from core import backup_health
from core.storage_sizes import get_storage_sizes

backup_sync_bp = Blueprint("backup_sync", __name__)

backup_sync_lock = threading.Lock()
is_syncing_backup = False

immich_library_stats_cache = {
    "data": None,
    "last_fetched": 0,
}

STAGE_LABELS = {
    0: "0. Pre-flight",
    1: "1. Face XMP Export",
    2: "2. Postgres Dump",
    3: "3. Rclone Mirror",
    4: "4. Cloud Verified",
}

STAGE_MESSAGES = {
    0: "Checking the remote, its folders and free space...",
    1: "Exporting named faces to XMP sidecars...",
    2: "Creating PostgreSQL database dump (pg_dumpall)...",
    3: "Mirroring database dump & photo library to cloud remote...",
    4: "Cloud backup verified & protected on remote",
}


def photo_backup_installed() -> bool:
    """Returns True when the photo cloud backup module is installed or has state."""
    return any(
        bool(p) and os.path.exists(p)
        for p in (BACKUP_SCRIPT, BACKUP_CRON_FILE, BACKUP_STATUS_FILE, BACKUP_LOG_FILE)
    )


def _format_iso_display(iso_str):
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime(f"%Y-%m-%d %H:%M {get_tz_abbr()}")
    except ValueError:
        return iso_str


def _schedule_text():
    hm = backup_health.cron_time(BACKUP_CRON_FILE)
    if not hm:
        return "Not scheduled"
    return f"Daily {hm[0]:02d}:{hm[1]:02d} {get_tz_abbr()}"


def _read_status_file():
    path = Path(BACKUP_STATUS_FILE)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def run_backup_sync_thread():
    """Executes the cloud backup script in background."""
    global is_syncing_backup
    with backup_sync_lock:
        is_syncing_backup = True
        try:
            script = BACKUP_SCRIPT or "/usr/local/sbin/immich_backup_gdrive.sh"
            subprocess.run(["sudo", script], check=False, timeout=14400)
        except Exception:
            pass
        finally:
            is_syncing_backup = False


def _disk_free_stats(path_str):
    """Returns (free_gb, total_gb, used_percent) for `path_str` if accessible."""
    if not path_str or not os.path.exists(path_str):
        return None, None, None
    try:
        usage = shutil.disk_usage(path_str)
        if usage.total <= 0:
            return None, None, None
        free_gb = round(usage.free / (1024**3), 1)
        total_gb = round(usage.total / (1024**3), 1)
        used_pct = round((usage.used / usage.total) * 100, 1)
        return free_gb, total_gb, used_pct
    except OSError:
        return None, None, None


def _query_immich_db():
    """
    Queries Immich / Noodle Gallery Postgres for asset, face, per-user storage,
    and external library telemetry. Falls back gracefully if schema differs.
    """
    sql_variants = [
        """
        SELECT json_build_object(
            'total_assets', (SELECT COUNT(*) FROM asset WHERE "deletedAt" IS NULL),
            'photos_count', (SELECT COUNT(*) FROM asset WHERE type = 'IMAGE' AND "deletedAt" IS NULL),
            'videos_count', (SELECT COUNT(*) FROM asset WHERE type = 'VIDEO' AND "deletedAt" IS NULL),
            'unhidden_people', (SELECT COUNT(*) FROM person WHERE "isHidden" = false),
            'named_people', (SELECT COUNT(*) FROM person WHERE name IS NOT NULL AND name != '' AND "isHidden" = false),
            'assets_with_named_faces', (SELECT COUNT(DISTINCT "assetId") FROM asset_face af JOIN person p ON af."personGroupId" = p."personGroupId" WHERE p.name IS NOT NULL AND p.name != ''),
            'total_face_instances', (SELECT COUNT(*) FROM asset_face),
            'offline_assets', (SELECT COUNT(*) FROM asset WHERE "deletedAt" IS NULL AND "isOffline" = true),
            'pending_faces', (SELECT COUNT(*) FROM asset a LEFT JOIN asset_job_status j ON j."assetId" = a.id WHERE a."deletedAt" IS NULL AND j."facesRecognizedAt" IS NULL),
            'pending_metadata', (SELECT COUNT(*) FROM asset a LEFT JOIN asset_job_status j ON j."assetId" = a.id WHERE a."deletedAt" IS NULL AND j."metadataExtractedAt" IS NULL),
            'users', COALESCE((
                SELECT json_agg(row_to_json(u_row))
                FROM (
                    SELECT
                        COALESCE(NULLIF(u.name, ''), 'User') AS name,
                        COUNT(a.id)::bigint AS assets,
                        COALESCE(NULLIF(SUM(COALESCE(e."fileSizeInByte", 0)), 0), MAX(COALESCE(u."quotaUsageInBytes", 0)))::bigint AS used_bytes,
                        MAX(u."quotaSizeInBytes") AS quota_bytes
                    FROM "user" u
                    LEFT JOIN asset a ON a."ownerId" = u.id AND a."deletedAt" IS NULL
                    LEFT JOIN asset_exif e ON e."assetId" = a.id
                    WHERE u."deletedAt" IS NULL
                    GROUP BY u.id, u.name
                    ORDER BY used_bytes DESC, assets DESC, name ASC
                ) u_row
            ), '[]'::json),
            'libraries', COALESCE((
                SELECT json_agg(row_to_json(lib_row))
                FROM (
                    SELECT
                        COALESCE(NULLIF(l.name, ''), 'Library') AS name,
                        COALESCE(l."importPaths", ARRAY[]::text[]) AS paths,
                        l."refreshedAt" AS refreshed_at,
                        COUNT(a.id)::bigint AS assets,
                        COUNT(a.id) FILTER (WHERE a."isOffline" = true)::bigint AS offline_assets
                    FROM library l
                    LEFT JOIN asset a ON a."libraryId" = l.id AND a."deletedAt" IS NULL
                    WHERE l."deletedAt" IS NULL
                    GROUP BY l.id, l.name, l."importPaths", l."refreshedAt"
                    ORDER BY l.name ASC
                ) lib_row
            ), '[]'::json)
        )::text;
        """,
        """
        SELECT json_build_object(
            'total_assets', (SELECT COUNT(*) FROM asset WHERE "deletedAt" IS NULL),
            'photos_count', (SELECT COUNT(*) FROM asset WHERE type = 'IMAGE' AND "deletedAt" IS NULL),
            'videos_count', (SELECT COUNT(*) FROM asset WHERE type = 'VIDEO' AND "deletedAt" IS NULL),
            'unhidden_people', (SELECT COUNT(*) FROM person WHERE "isHidden" = false),
            'named_people', (SELECT COUNT(*) FROM person WHERE name IS NOT NULL AND name != '' AND "isHidden" = false),
            'assets_with_named_faces', (SELECT COUNT(DISTINCT "assetId") FROM asset_face af JOIN person p ON af."personId" = p.id WHERE p.name IS NOT NULL AND p.name != ''),
            'total_face_instances', (SELECT COUNT(*) FROM asset_face),
            'offline_assets', (SELECT COUNT(*) FROM asset WHERE "deletedAt" IS NULL AND "isOffline" = true),
            'pending_faces', (SELECT COUNT(*) FROM asset a LEFT JOIN asset_job_status j ON j."assetId" = a.id WHERE a."deletedAt" IS NULL AND j."facesRecognizedAt" IS NULL),
            'pending_metadata', (SELECT COUNT(*) FROM asset a LEFT JOIN asset_job_status j ON j."assetId" = a.id WHERE a."deletedAt" IS NULL AND j."metadataExtractedAt" IS NULL),
            'users', COALESCE((
                SELECT json_agg(row_to_json(u_row))
                FROM (
                    SELECT
                        COALESCE(NULLIF(u.name, ''), 'User') AS name,
                        COUNT(a.id)::bigint AS assets,
                        COALESCE(NULLIF(SUM(COALESCE(e."fileSizeInByte", 0)), 0), MAX(COALESCE(u."quotaUsageInBytes", 0)))::bigint AS used_bytes,
                        MAX(u."quotaSizeInBytes") AS quota_bytes
                    FROM "user" u
                    LEFT JOIN asset a ON a."ownerId" = u.id AND a."deletedAt" IS NULL
                    LEFT JOIN asset_exif e ON e."assetId" = a.id
                    WHERE u."deletedAt" IS NULL
                    GROUP BY u.id, u.name
                    ORDER BY used_bytes DESC, assets DESC, name ASC
                ) u_row
            ), '[]'::json),
            'libraries', COALESCE((
                SELECT json_agg(row_to_json(lib_row))
                FROM (
                    SELECT
                        COALESCE(NULLIF(l.name, ''), 'Library') AS name,
                        COALESCE(l."importPaths", ARRAY[]::text[]) AS paths,
                        l."refreshedAt" AS refreshed_at,
                        COUNT(a.id)::bigint AS assets,
                        COUNT(a.id) FILTER (WHERE a."isOffline" = true)::bigint AS offline_assets
                    FROM library l
                    LEFT JOIN asset a ON a."libraryId" = l.id AND a."deletedAt" IS NULL
                    WHERE l."deletedAt" IS NULL
                    GROUP BY l.id, l.name, l."importPaths", l."refreshedAt"
                    ORDER BY l.name ASC
                ) lib_row
            ), '[]'::json)
        )::text;
        """,
        """
        SELECT json_build_object(
            'total_assets', (SELECT COUNT(*) FROM asset WHERE "deletedAt" IS NULL),
            'photos_count', (SELECT COUNT(*) FROM asset WHERE type = 'IMAGE' AND "deletedAt" IS NULL),
            'videos_count', (SELECT COUNT(*) FROM asset WHERE type = 'VIDEO' AND "deletedAt" IS NULL),
            'unhidden_people', (SELECT COUNT(*) FROM person WHERE "isHidden" = false),
            'named_people', (SELECT COUNT(*) FROM person WHERE name IS NOT NULL AND name != '' AND "isHidden" = false),
            'assets_with_named_faces', (SELECT COUNT(DISTINCT "assetId") FROM asset_face af JOIN person p ON af."personGroupId" = p."personGroupId" WHERE p.name IS NOT NULL AND p.name != ''),
            'total_face_instances', (SELECT COUNT(*) FROM asset_face)
        )::text;
        """,
        """
        SELECT json_build_object(
            'total_assets', (SELECT COUNT(*) FROM asset WHERE "deletedAt" IS NULL),
            'photos_count', (SELECT COUNT(*) FROM asset WHERE type = 'IMAGE' AND "deletedAt" IS NULL),
            'videos_count', (SELECT COUNT(*) FROM asset WHERE type = 'VIDEO' AND "deletedAt" IS NULL),
            'unhidden_people', (SELECT COUNT(*) FROM person WHERE "isHidden" = false),
            'named_people', (SELECT COUNT(*) FROM person WHERE name IS NOT NULL AND name != '' AND "isHidden" = false),
            'assets_with_named_faces', (SELECT COUNT(DISTINCT "assetId") FROM asset_face af JOIN person p ON af."personId" = p.id WHERE p.name IS NOT NULL AND p.name != ''),
            'total_face_instances', (SELECT COUNT(*) FROM asset_face)
        )::text;
        """,
    ]
    last_reason = "Photo database unavailable"
    for idx, sql in enumerate(sql_variants):
        try:
            cmd = [
                "docker", "exec", IMMICH_DB_CONTAINER,
                "psql", "-U", IMMICH_DB_USER, "-d", IMMICH_DB_NAME,
                "-t", "-A", "-c", sql,
            ]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
            if proc.returncode == 0 and proc.stdout.strip():
                return json.loads(proc.stdout.strip()), None
            err = (proc.stderr or proc.stdout or "").strip()
            last_reason = err[:140] if err else "Photo database unavailable"
            # Retry simpler or upstream schema variants only if a column/relation name differed
            if idx < len(sql_variants) - 1 and ("does not exist" in err.lower() or "undefined" in err.lower()):
                continue
            return None, last_reason
        except Exception as exc:
            return None, f"Photo database unavailable ({exc})"[:140]
    return None, last_reason


def _gdrive_from_status(status_data):
    gdrive_raw = status_data.get("gdrive") if isinstance(status_data, dict) else None
    if not isinstance(gdrive_raw, dict):
        return None, "Remote quota not recorded yet (waiting for backup run)"
    total_b = gdrive_raw.get("total_bytes")
    used_b = gdrive_raw.get("used_bytes")
    free_b = gdrive_raw.get("free_bytes")
    if not total_b or total_b <= 0:
        return None, "Remote quota unavailable"
    used_b = used_b or 0
    free_b = free_b if free_b is not None else max(0, total_b - used_b)
    return {
        "total_gb": round(total_b / (1024**3), 1),
        "used_gb": round(used_b / (1024**3), 1),
        "free_gb": round(free_b / (1024**3), 1),
        "used_percent": round((used_b / total_b) * 100, 1),
    }, None


def fetch_immich_library_telemetry(force=False):
    """Fetches measured photo DB metrics, local folder size, and remote quota from status.json."""
    now = time.time()
    cached = immich_library_stats_cache["data"]
    cache_ttl = 300 if (isinstance(cached, dict) and cached.get("assets")) else 15
    if not force and cached and (now - immich_library_stats_cache["last_fetched"] < cache_ttl):
        return cached

    db_metrics, db_reason = _query_immich_db()

    sizes = get_storage_sizes(
        cache_file=STORAGE_SIZES_CACHE_FILE,
        media_path=HDD_DATA,
        photos_path=HDD_MEMORIES,
        photo_upload_path=PHOTO_UPLOAD_DIR,
        appdata_path=APPDATA_DIR,
        backup_path=BACKUP_DIR,
        force=force,
    )
    disk_size = None
    disk_reason = None
    disk_partial = bool(sizes.get("photos_partial"))
    if sizes.get("photos_gb") is not None:
        prefix = "\u2265 " if disk_partial else ""
        disk_size = f"{prefix}{sizes['photos_gb']} GB"
        if disk_partial:
            disk_reason = sizes.get("reason") or "Some photo subdirectories are unreadable without root timer"
    elif sizes.get("measuring"):
        disk_reason = "Measuring photo library size"
    else:
        disk_reason = sizes.get("reason") or "Photo directory size unavailable"

    status_data = _read_status_file()
    gdrive_usage, gdrive_reason = _gdrive_from_status(status_data)

    dump_size = None
    dump_reason = "No database dump found yet"
    try:
        if os.path.exists(BACKUP_DIR):
            dumps = [f for f in os.listdir(BACKUP_DIR) if f.startswith("immich_db_") and f.endswith(".sql.gz")]
            if dumps:
                dumps.sort(reverse=True)
                size_bytes = os.path.getsize(os.path.join(BACKUP_DIR, dumps[0]))
                dump_size = f"{round(size_bytes / (1024**2), 1)} MB"
                dump_reason = None
    except Exception as exc:
        dump_reason = str(exc)[:140]

    photos_free_gb, photos_total_gb, photos_used_pct = _disk_free_stats(HDD_MEMORIES or PHOTO_UPLOAD_DIR)
    payload = {
        "disk_size": disk_size,
        "disk_reason": disk_reason,
        "disk_partial": disk_partial,
        "disk_measured_by": sizes.get("measured_by"),
        "photos_free_gb": photos_free_gb,
        "photos_total_gb": photos_total_gb,
        "photos_used_percent": photos_used_pct,
        "gdrive": gdrive_usage,
        "gdrive_reason": gdrive_reason,
        "assets": db_metrics,
        "assets_reason": db_reason,
        "db_dump_size": dump_size,
        "db_dump_reason": dump_reason,
        "memories_dir": HDD_MEMORIES,
        "gdrive_remote": (status_data or {}).get("remote") or GDRIVE_REMOTE or None,
        "last_updated": time.strftime(f"%H:%M {get_tz_abbr()}"),
        "timezone": get_host_timezone(),
    }
    immich_library_stats_cache["data"] = payload
    immich_library_stats_cache["last_fetched"] = now
    return payload


@backup_sync_bp.route("/api/backup/status", methods=["GET"])
def get_backup_status():
    """Checks photo & media backup status from status.json (or log fallback), never returning fake numbers."""
    is_syncing = is_syncing_backup
    active_process_stage = 0

    try:
        res_sh = subprocess.run(["pgrep", "-f", "immich_backup_gdrive.sh"], stdout=subprocess.PIPE, text=True, timeout=1.5)
        if res_sh.stdout.strip():
            is_syncing = True

        res_dump = subprocess.run(["pgrep", "-f", "pg_dump"], stdout=subprocess.PIPE, text=True, timeout=1.5)
        res_rclone_sync = subprocess.run(["pgrep", "-f", "rclone sync"], stdout=subprocess.PIPE, text=True, timeout=1.5)
        res_rclone_copy = subprocess.run(["pgrep", "-f", "rclone copy"], stdout=subprocess.PIPE, text=True, timeout=1.5)
        res_face = subprocess.run(["pgrep", "-f", "export_faces_to_xmp"], stdout=subprocess.PIPE, text=True, timeout=1.5)

        if res_dump.stdout.strip():
            active_process_stage = 2
            is_syncing = True
        elif res_rclone_sync.stdout.strip() or res_rclone_copy.stdout.strip():
            active_process_stage = 3
            is_syncing = True
        elif res_face.stdout.strip():
            active_process_stage = 1
            is_syncing = True
    except Exception:
        pass

    latest_db_size = None
    latest_db_name = None
    try:
        if os.path.exists(BACKUP_DIR):
            dumps = [f for f in os.listdir(BACKUP_DIR) if f.startswith("immich_db_") and f.endswith(".sql.gz")]
            if dumps:
                dumps.sort(reverse=True)
                latest_db_name = dumps[0]
                size_bytes = os.path.getsize(os.path.join(BACKUP_DIR, latest_db_name))
                latest_db_size = f"{round(size_bytes / (1024**2), 1)} MB"
    except Exception:
        pass

    status_data = _read_status_file()
    last_sync_time = None
    backup_status = "unknown"
    current_stage = 0
    last_message = "No backup run recorded yet"
    reason = "No backup run yet"

    health = None
    if status_data:
        health = backup_health.summarize(
            status_data,
            running=is_syncing,
            schedule=backup_health.cron_time(BACKUP_CRON_FILE),
            tz_abbr=get_tz_abbr(),
            stale_after_hours=BACKUP_STALE_HOURS,
        )
        backup_status = health["state"]
        current_stage = health["stage"]
        last_message = health["message"]
        last_sync_time = health["last_good"] or _format_iso_display(status_data.get("completed_at") or status_data.get("started_at"))
        if not latest_db_name and status_data.get("dump_file"):
            latest_db_name = status_data.get("dump_file")
        if latest_db_size is None and isinstance(status_data.get("dump_bytes"), (int, float)):
            latest_db_size = f"{round(status_data['dump_bytes'] / (1024**2), 1)} MB"
        reason = None if backup_status == "synced" else last_message
    elif BACKUP_LOG_FILE and os.path.exists(BACKUP_LOG_FILE):
        log_stage = 0
        is_error = False
        try:
            with open(BACKUP_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            start_idx = -1
            for idx in range(len(lines) - 1, -1, -1):
                for marker in ("Starting Immich Backup:", "Starting Immich / Noodle Backup:"):
                    if marker in lines[idx]:
                        start_idx = idx
                        last_sync_time = lines[idx].split(marker, 1)[-1].strip()
                        break
                if start_idx != -1:
                    break

            recent_lines = lines[start_idx:] if start_idx != -1 else lines[-60:]
            for line in reversed(recent_lines):
                line_str = line.strip()
                if "Immich Backup Completed Successfully:" in line_str:
                    log_stage = 4
                    completed_time = line_str.split("Immich Backup Completed Successfully:", 1)[-1].strip()
                    if completed_time:
                        last_sync_time = completed_time
                    break
                if "[4/4] Syncing" in line_str or "[3/4] Uploading" in line_str:
                    log_stage = 3
                    break
                if "[2/4] Creating PostgreSQL" in line_str:
                    log_stage = 2
                    break
                if "[1/4] Running Face-to-XMP" in line_str:
                    log_stage = 1
                    break
                if "ERROR" in line_str or "Failed" in line_str:
                    is_error = True
                    last_message = line_str
        except Exception as exc:
            is_error = True
            last_message = f"Could not read backup log ({exc})"

        if is_error:
            backup_status = "error"
            current_stage = log_stage or 1
            reason = last_message
        elif log_stage == 4:
            backup_status = "synced"
            current_stage = 4
            last_message = STAGE_MESSAGES[4]
            reason = None
        elif log_stage > 0:
            backup_status = "error"
            current_stage = log_stage
            last_message = f"Previous backup run ended prematurely at Step {log_stage} ({STAGE_LABELS.get(log_stage, '')})"
            reason = last_message
        else:
            backup_status = "unknown"
            current_stage = 0
            last_message = "Backup log has no completed runs yet"
            reason = last_message

    if is_syncing and health is None:
        backup_status = "syncing"
        current_stage = active_process_stage if active_process_stage > 0 else (current_stage or 1)
        last_message = STAGE_MESSAGES.get(current_stage, "Syncing to cloud remote...")
        reason = None

    lib_meta = fetch_immich_library_telemetry(force=False)
    gdrive_info = lib_meta.get("gdrive") or {}
    asset_info = lib_meta.get("assets") or {}
    media_info = media_backup_summary()
    restore_info = restore_test_info()
    photo_installed = photo_backup_installed()
    any_installed = bool(photo_installed or media_info is not None or restore_info.get("installed") or asset_info)

    return jsonify({
        "installed": any_installed,
        "photo_backup_installed": photo_installed,
        "media_backup_installed": media_info is not None,
        "status": backup_status,
        "is_syncing": is_syncing,
        "current_stage": current_stage,
        "current_stage_label": STAGE_LABELS.get(current_stage, "Not Verified"),
        "last_sync": last_sync_time,
        "db_size": latest_db_size,
        "latest_dump": latest_db_name,
        "message": last_message,
        "reason": reason,
        "schedule": _schedule_text(),
        "health": health,
        "media": media_info,
        "restore": restore_info,
        "remote_editable": bool(BACKUP_REMOTE_HELPER and os.path.isfile(BACKUP_REMOTE_HELPER)),
        "gdrive_remote": lib_meta.get("gdrive_remote"),
        "log_file": BACKUP_LOG_FILE,
        "memories_dir": HDD_MEMORIES,
        "timezone": get_host_timezone(),
        "disk_size": lib_meta.get("disk_size"),
        "disk_reason": lib_meta.get("disk_reason"),
        "disk_partial": lib_meta.get("disk_partial", False),
        "disk_measured_by": lib_meta.get("disk_measured_by"),
        "photos_free_gb": lib_meta.get("photos_free_gb"),
        "photos_total_gb": lib_meta.get("photos_total_gb"),
        "photos_used_percent": lib_meta.get("photos_used_percent"),
        "gdrive_used_gb": gdrive_info.get("used_gb"),
        "gdrive_total_gb": gdrive_info.get("total_gb"),
        "gdrive_free_gb": gdrive_info.get("free_gb"),
        "gdrive_used_percent": gdrive_info.get("used_percent"),
        "gdrive_reason": lib_meta.get("gdrive_reason"),
        "total_assets": asset_info.get("total_assets"),
        "photos_count": asset_info.get("photos_count"),
        "videos_count": asset_info.get("videos_count"),
        "named_people": asset_info.get("named_people"),
        "unhidden_people": asset_info.get("unhidden_people"),
        "assets_with_named_faces": asset_info.get("assets_with_named_faces"),
        "total_face_instances": asset_info.get("total_face_instances"),
        "assets_reason": lib_meta.get("assets_reason"),
    })


def media_backup_summary():
    """The media apps' settings backup, or None when it is not installed here."""
    status = backup_health.read_status(MEDIA_BACKUP_STATUS_FILE)
    hm = backup_health.cron_time(MEDIA_BACKUP_CRON_FILE, "media_config_backup.py")
    if status is None and hm is None:
        return None
    running = False
    try:
        res = subprocess.run(["pgrep", "-f", "media_config_backup.py"], stdout=subprocess.PIPE, text=True, timeout=1.5)
        running = bool(res.stdout.strip())
    except Exception:
        pass
    health = backup_health.summarize(
        status,
        running=running,
        schedule=hm,
        tz_abbr=get_tz_abbr(),
        stale_after_hours=BACKUP_STALE_HOURS,
    )
    size = (status or {}).get("dump_bytes")
    health["archive"] = (status or {}).get("dump_file")
    health["archive_size"] = backup_health.human_bytes(size) if size else None
    health["can_run"] = bool(MEDIA_BACKUP_SCRIPT and os.path.isfile(MEDIA_BACKUP_SCRIPT))
    return health


def restore_test_info():
    """Whether the monthly restore test is installed, running, and when it runs next."""
    if not os.path.isfile(os.path.join(SYSTEMD_UNIT_DIR, f"{RESTORE_TEST_UNIT}.service")):
        return {"installed": False}
    info = {"installed": True, "running": False, "next": None}
    try:
        res = subprocess.run(["systemctl", "is-active", f"{RESTORE_TEST_UNIT}.service"], capture_output=True, text=True, timeout=2)
        info["running"] = res.stdout.strip() in ("active", "activating")
        res = subprocess.run(
            ["systemctl", "show", f"{RESTORE_TEST_UNIT}.timer", "-p", "NextElapseUSecRealtime", "--value"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        nxt = res.stdout.strip()
        info["next"] = nxt if nxt and nxt != "n/a" else None
    except Exception:
        pass
    return info


def _remote_helper(*args, timeout=180):
    """Runs the root helper through sudo and returns (http_status, json)."""
    if not BACKUP_REMOTE_HELPER or not os.path.isfile(BACKUP_REMOTE_HELPER):
        return 404, {"ok": False, "error": "Changing the remote is not available on this install."}
    try:
        res = subprocess.run(["sudo", BACKUP_REMOTE_HELPER, *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 504, {"ok": False, "error": "The remote did not answer in time."}
    except OSError as exc:
        return 500, {"ok": False, "error": str(exc)[:200]}
    try:
        data = json.loads(res.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 500, {"ok": False, "error": (res.stderr or "The helper gave no answer.").strip()[:200]}
    return 200, data


@backup_sync_bp.route("/api/backup/remotes", methods=["GET"])
def list_backup_remotes():
    """rclone remotes configured for root on this server, and the one the backups use."""
    code, data = _remote_helper("list", timeout=30)
    return jsonify(data), code


@backup_sync_bp.route("/api/backup/remote/test", methods=["POST"])
def test_backup_remote():
    remote = str((request.get_json(silent=True) or {}).get("remote", ""))
    code, data = _remote_helper("test", remote)
    return jsonify(data), code


@backup_sync_bp.route("/api/backup/remote", methods=["PUT"])
def set_backup_remote():
    """Switches the photo and media backups to another remote (tested first by the helper)."""
    remote = str((request.get_json(silent=True) or {}).get("remote", ""))
    code, data = _remote_helper("set", remote)
    if data.get("ok"):
        immich_library_stats_cache["last_fetched"] = 0
    return jsonify(data), code


@backup_sync_bp.route("/api/backup/restore-test", methods=["POST"])
def run_restore_test():
    """Starts the restore test now (a root systemd service; the dashboard only asks systemd to start it)."""
    info = restore_test_info()
    if not info.get("installed"):
        return jsonify({"success": False, "message": "The restore test is not installed."}), 404
    if info.get("running"):
        return jsonify({"success": False, "message": "A restore test is already running."})
    try:
        res = subprocess.run(
            ["sudo", "/usr/bin/systemctl", "start", "--no-block", f"{RESTORE_TEST_UNIT}.service"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)[:200]}), 500
    if res.returncode != 0:
        return jsonify({"success": False, "message": (res.stderr or "systemctl failed").strip()[:200]}), 500
    return jsonify({"success": True, "message": "Restore test started. It takes a few minutes."})


@backup_sync_bp.route("/api/backup/media/run", methods=["POST"])
def run_media_backup():
    """Starts the media settings backup now (it moves itself into its own systemd unit)."""
    if not MEDIA_BACKUP_SCRIPT or not os.path.isfile(MEDIA_BACKUP_SCRIPT):
        return jsonify({"success": False, "message": "The media settings backup is not installed."}), 404
    try:
        res = subprocess.run(["pgrep", "-f", "media_config_backup.py"], stdout=subprocess.PIPE, text=True, timeout=2)
        if res.stdout.strip():
            return jsonify({"success": False, "message": "A media settings backup is already running."})
    except Exception:
        pass
    try:
        subprocess.Popen(
            ["sudo", "/usr/bin/python3", MEDIA_BACKUP_SCRIPT],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)[:200]}), 500
    return jsonify({"success": True, "message": "Media settings backup started."})


@backup_sync_bp.route("/api/backup/sync", methods=["POST"])
def trigger_backup_sync():
    """Triggers an immediate photo library backup and cloud sync."""
    if not BACKUP_SCRIPT or not os.path.isfile(BACKUP_SCRIPT):
        return jsonify({"success": False, "message": "Photo cloud backup is not installed on this server."}), 404
    try:
        res = subprocess.run(["pgrep", "-f", "immich_backup_gdrive.sh"], stdout=subprocess.PIPE, text=True, timeout=2)
        if is_syncing_backup or res.stdout.strip():
            return jsonify({"success": False, "message": "Cloud backup sync is already in progress..."})
    except Exception:
        if is_syncing_backup:
            return jsonify({"success": False, "message": "Cloud backup sync is already in progress..."})

    t = threading.Thread(target=run_backup_sync_thread, daemon=True)
    t.start()
    return jsonify({"success": True, "message": "Photo library cloud sync started."})


@backup_sync_bp.route("/api/backup/log", methods=["GET"])
def get_backup_log():
    """Returns the tail of backup.log for the 1-click modal."""
    if not BACKUP_LOG_FILE or not os.path.exists(BACKUP_LOG_FILE):
        return jsonify({"log_file": BACKUP_LOG_FILE, "log": f"Log file ({BACKUP_LOG_FILE}) not found yet."})
    try:
        with open(BACKUP_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return jsonify({"log_file": BACKUP_LOG_FILE, "log": "".join(lines[-100:])})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@backup_sync_bp.route("/api/backup/library-stats", methods=["GET"])
def get_library_stats():
    """Returns detailed photo library storage, assets, and facial recognition stats."""
    force = request.args.get("refresh", "false").lower() == "true"
    return jsonify(fetch_immich_library_telemetry(force=force))

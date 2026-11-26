"""
Widget: Photos Hub & Machine-Learning Health
Provides deep photo library overview (assets, people, per-user storage),
Immich Machine Learning schedule management & BullMQ job queue visibility,
Face-tag XMP exporter telemetry, and upload/external folder health checks.
Never returns placeholder data when Immich components are absent.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request

from config import (
    BACKUP_LOG_FILE,
    BACKUP_SCRIPT,
    FACE_EXPORT_CACHE_FILE,
    HDD_MEMORIES,
    IMMICH_ML_CONTAINER,
    IMMICH_ML_CRON_FILE,
    IMMICH_ML_LOG_FILE,
    IMMICH_ML_SCRIPT,
    IMMICH_REDIS_CONTAINER,
    PHOTO_UPLOAD_DIR,
    get_host_timezone,
    get_tz_abbr,
)
from widgets.backup_sync import fetch_immich_library_telemetry

photos_hub_bp = Blueprint("photos_hub", __name__)

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_ML_CRON_LINE_RE = re.compile(
    r"^\s*(?:#\s*DISABLED:\s*)?(\d{1,2})\s+(\d{1,2})\s+\S+\s+\S+\s+\S+\s+\S+\s+.*\bimmich-ml-control\.sh\s+(start|stop)\b"
)
_ML_QUEUES = (
    ("faceDetection", "Face Detection"),
    ("facialRecognition", "Face Recognition"),
    ("smartSearch", "Smart Search"),
    ("classification", "Image Tagging"),
    ("thumbnailGeneration", "Thumbnails"),
    ("metadataExtraction", "Metadata"),
    ("duplicateDetection", "Duplicates"),
    ("ocr", "Text (OCR)"),
)


def parse_ml_cron_file(cron_file: str) -> Dict[str, Any]:
    """Reads Immich ML start/stop cron entries, supporting disabled lines cleanly."""
    result: Dict[str, Any] = {
        "exists": False,
        "enabled": False,
        "start_time": None,
        "stop_time": None,
        "editable": False,
        "cron_file": cron_file,
    }
    if not cron_file or not os.path.isfile(cron_file):
        return result

    try:
        text = Path(cron_file).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return result

    result["exists"] = True
    # Editable if parent dir/file can be written directly or if sudo tee /etc/cron.d/immich-ml is expected on Linux
    result["editable"] = os.access(cron_file, os.W_OK) or (os.name != "nt")
    enabled_flags: List[bool] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        is_disabled_comment = stripped.startswith("# DISABLED:")
        if stripped.startswith("#") and not is_disabled_comment:
            continue
        m = _ML_CRON_LINE_RE.match(raw)
        if not m:
            continue
        minute, hour, action = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            continue
        hhmm = f"{hour:02d}:{minute:02d}"
        enabled_flags.append(not is_disabled_comment)
        if action == "start":
            result["start_time"] = hhmm
        elif action == "stop":
            result["stop_time"] = hhmm

    if result["start_time"] and result["stop_time"]:
        result["enabled"] = any(enabled_flags)
    return result


def _validate_hhmm(value: Any) -> Optional[Tuple[int, int, str]]:
    if not isinstance(value, str):
        return None
    val = value.strip()
    m = _TIME_RE.match(val)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), val


def write_ml_cron_file(cron_file: str, enabled: bool, start_time: str, stop_time: str) -> None:
    """Renders and atomically updates `/etc/cron.d/immich-ml` (or writable override file)."""
    parsed_start = _validate_hhmm(start_time)
    parsed_stop = _validate_hhmm(stop_time)
    if not parsed_start or not parsed_stop:
        raise ValueError("Times must use 24-hour HH:MM format.")
    if parsed_start[2] == parsed_stop[2]:
        raise ValueError("Start time and stop time must be different.")

    s_h, s_m, _ = parsed_start
    e_h, e_m, _ = parsed_stop
    script = IMMICH_ML_SCRIPT or "/usr/local/sbin/immich-ml-control.sh"
    log_path = IMMICH_ML_LOG_FILE or "/var/log/immich-ml.log"
    prefix = "" if enabled else "# DISABLED: "

    content = (
        "# Photo ML schedule managed by Control Hub.\n"
        f"{prefix}{s_m} {s_h} * * * root {script} start >> {log_path} 2>&1\n"
        f"{prefix}{e_m} {e_h} * * * root {script} stop >> {log_path} 2>&1\n"
    )

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


def _query_redis_queues(redis_container: str) -> Dict[str, Any]:
    """Fetches BullMQ active/waiting/delayed/failed counts from Immich Redis in one pipeline."""
    summary: Dict[str, Any] = {
        "available": False,
        "total_waiting": 0,
        "total_active": 0,
        "total_delayed": 0,
        "total_failed": 0,
        "queues": [],
    }
    if not redis_container:
        return summary

    commands: List[str] = []
    for key, _ in _ML_QUEUES:
        commands.extend([
            f"LLEN immich_bull:{key}:wait",
            f"LLEN immich_bull:{key}:active",
            f"ZCARD immich_bull:{key}:delayed",
            f"ZCARD immich_bull:{key}:failed",
        ])
    pipeline_input = "\n".join(commands) + "\n"

    try:
        proc = subprocess.run(
            ["docker", "exec", "-i", redis_container, "redis-cli"],
            input=pipeline_input,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=4,
        )
        if proc.returncode != 0:
            return summary
        lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
        if len(lines) < len(commands):
            return summary

        summary["available"] = True
        queues_out = []
        for idx, (key, label) in enumerate(_ML_QUEUES):
            base = idx * 4
            try:
                waiting = max(0, int(lines[base]))
                active = max(0, int(lines[base + 1]))
                delayed = max(0, int(lines[base + 2]))
                failed = max(0, int(lines[base + 3]))
            except ValueError:
                waiting = active = delayed = failed = 0
            summary["total_waiting"] += waiting
            summary["total_active"] += active
            summary["total_delayed"] += delayed
            summary["total_failed"] += failed
            queues_out.append({
                "id": key,
                "label": label,
                "waiting": waiting,
                "active": active,
                "delayed": delayed,
                "failed": failed,
            })
        summary["queues"] = queues_out
        return summary
    except Exception:
        return summary


def _inspect_ml_state(tz_abbr: str, db_assets: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Reads ML container running state, cron schedule, last log line, and pending jobs."""
    exists = False
    running = False
    try:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", IMMICH_ML_CONTAINER],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.5,
        )
        if res.returncode == 0 and res.stdout.strip() in ("true", "false"):
            exists = True
            running = res.stdout.strip() == "true"
    except Exception:
        pass

    sched = parse_ml_cron_file(IMMICH_ML_CRON_FILE)
    last_event = None
    last_run = None
    if IMMICH_ML_LOG_FILE and os.path.isfile(IMMICH_ML_LOG_FILE):
        try:
            mtime = os.path.getmtime(IMMICH_ML_LOG_FILE)
            last_run = datetime.datetime.fromtimestamp(mtime).strftime(f"%b %d, %H:%M {tz_abbr}")
            with open(IMMICH_ML_LOG_FILE, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()[-25:]
            for line in reversed(lines):
                stripped = line.strip()
                if any(tag in stripped for tag in ("[START]", "[STOP]", "[ERROR]")):
                    last_event = stripped[:160]
                    break
        except OSError:
            pass

    redis_q = _query_redis_queues(IMMICH_REDIS_CONTAINER)
    pending_faces = db_assets.get("pending_faces") if isinstance(db_assets, dict) else None
    pending_metadata = db_assets.get("pending_metadata") if isinstance(db_assets, dict) else None

    return {
        "installed": bool(exists or sched["exists"]),
        "container_exists": exists,
        "running": running,
        "can_control": exists,
        "last_run": last_run,
        "last_event": last_event,
        "schedule": sched,
        "queue": {
            "redis_available": redis_q["available"],
            "active": redis_q["total_active"],
            "waiting": redis_q["total_waiting"],
            "delayed": redis_q["total_delayed"],
            "failed": redis_q["total_failed"],
            "queues": redis_q["queues"],
            "pending_faces": pending_faces,
            "pending_metadata": pending_metadata,
        },
    }


def _count_export_cache(cache_file: str) -> Optional[int]:
    if not cache_file or not os.path.isfile(cache_file):
        return None
    try:
        data = json.loads(Path(cache_file).read_text(encoding="utf-8"))
        return len(data) if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def parse_face_export_status(log_file: str, cache_file: str = "", tz_abbr: str = "") -> Dict[str, Any]:
    """Parses the latest Face-to-XMP Exporter run metrics from backup logs and cache."""
    cache_entries = _count_export_cache(cache_file)
    out: Dict[str, Any] = {
        "installed": bool(
            (BACKUP_SCRIPT and os.path.isfile(BACKUP_SCRIPT))
            or (log_file and os.path.isfile(log_file))
            or cache_entries is not None
        ),
        "status": "never",
        "last_run": None,
        "named_assets": None,
        "files_written": None,
        "cached_skipped": cache_entries,
        "errors": 0,
        "error_detail": None,
        "summary": "No Face-to-XMP run recorded yet",
    }
    if not log_file or not os.path.isfile(log_file):
        return out

    try:
        with open(log_file, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 262144), os.SEEK_SET)
            text = fh.read().decode("utf-8", errors="replace")
    except OSError as exc:
        out["error_detail"] = str(exc)[:140]
        return out

    lines = text.splitlines()
    marker_idx = None
    for idx in range(len(lines) - 1, -1, -1):
        if "Running Face-to-XMP Exporter" in lines[idx]:
            marker_idx = idx
            break

    if marker_idx is None:
        return out

    out["installed"] = True
    # Find run header timestamp right before `[1/4] Running Face-to-XMP Exporter`
    for idx in range(marker_idx, max(-1, marker_idx - 40), -1):
        line = lines[idx]
        if "Starting Immich Backup:" in line:
            out["last_run"] = line.split("Starting Immich Backup:", 1)[-1].strip()
            break

    # Extract only Step 1 (up to Step 2 marker)
    block: List[str] = []
    for line in lines[marker_idx + 1 : marker_idx + 80]:
        if "[2/4]" in line or "Creating PostgreSQL database dump" in line:
            break
        block.append(line)

    pending_num: Optional[int] = None
    completed_ok = False
    up_to_date = False
    warnings: List[str] = []

    for line in block:
        s = line.strip()
        m_found = re.search(r"Found\s+(\d+)\s+assets with named faces", s)
        if m_found:
            out["named_assets"] = int(m_found.group(1))
        m_pending = re.search(r"Pending export:\s+(\d+)\s+assets\s+\(skipped\s+(\d+)\s+cached\)", s)
        if m_pending:
            pending_num = int(m_pending.group(1))
            out["cached_skipped"] = int(m_pending.group(2))
        if "All assets are up to date" in s:
            up_to_date = True
        if "Batch export completed successfully" in s:
            completed_ok = True
        if "ExifTool had warnings/errors" in s or "Face export had warnings" in s or "Traceback" in s:
            warnings.append(s[:160])

    if warnings:
        out["status"] = "warning"
        out["errors"] = len(warnings)
        out["error_detail"] = warnings[0]
        out["files_written"] = 0
        out["summary"] = warnings[0]
    elif up_to_date:
        out["status"] = "ok"
        out["files_written"] = 0
        cached = out["cached_skipped"] or 0
        out["summary"] = f"All {cached:,} sidecars up to date" if cached else "All assets up to date"
    elif completed_ok:
        written = pending_num if pending_num is not None else 0
        out["status"] = "ok"
        out["files_written"] = written
        out["summary"] = f"Wrote {written:,} XMP sidecar(s)"
    elif pending_num is not None:
        out["status"] = "warning"
        out["files_written"] = 0
        out["summary"] = f"{pending_num:,} pending; export did not finish cleanly"

    if not out["last_run"]:
        try:
            mtime = os.path.getmtime(log_file)
            out["last_run"] = datetime.datetime.fromtimestamp(mtime).strftime(f"%b %d, %H:%M {tz_abbr}")
        except OSError:
            pass

    return out


def probe_folder_health(path_str: str, label: str, kind: str, scan_cap: int = 400) -> Dict[str, Any]:
    """Checks existence, disk free space, and fast bounded readability for a photo directory."""
    row: Dict[str, Any] = {
        "label": label,
        "kind": kind,
        "path": path_str,
        "exists": False,
        "readable": False,
        "free_gb": None,
        "total_gb": None,
        "used_percent": None,
        "unreadable_count": 0,
        "unreadable_sample": [],
        "sampled_entries": 0,
        "truncated": False,
        "status": "missing",
        "message": "Directory does not exist",
    }
    if not path_str:
        return row

    if not os.path.isdir(path_str):
        row["status"] = "missing"
        row["message"] = "Directory not mounted or missing"
        return row

    row["exists"] = True
    try:
        usage = shutil.disk_usage(path_str)
        if usage.total > 0:
            row["free_gb"] = round(usage.free / (1024**3), 1)
            row["total_gb"] = round(usage.total / (1024**3), 1)
            row["used_percent"] = round((usage.used / usage.total) * 100, 1)
    except OSError:
        pass

    root_readable = os.access(path_str, os.R_OK | os.X_OK)
    row["readable"] = root_readable
    if not root_readable:
        row["unreadable_count"] = 1
        row["unreadable_sample"] = [path_str]
        row["status"] = "unreadable"
        row["message"] = "Control Hub user cannot list this directory"
        return row

    unreadable_sample: List[str] = []
    unreadable_count = 0
    sampled = 0
    stack = [path_str]
    truncated = False

    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    sampled += 1
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if os.access(entry.path, os.R_OK | os.X_OK):
                                if sampled < scan_cap:
                                    stack.append(entry.path)
                            else:
                                unreadable_count += 1
                                if len(unreadable_sample) < 3:
                                    unreadable_sample.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            if not os.access(entry.path, os.R_OK):
                                unreadable_count += 1
                                if len(unreadable_sample) < 3:
                                    unreadable_sample.append(entry.path)
                    except OSError:
                        unreadable_count += 1
                        if len(unreadable_sample) < 3:
                            unreadable_sample.append(entry.path)
                    if sampled >= scan_cap:
                        truncated = True
                        stack.clear()
                        break
        except PermissionError:
            unreadable_count += 1
            if len(unreadable_sample) < 3:
                unreadable_sample.append(current)
        except OSError:
            pass

    row["sampled_entries"] = sampled
    row["truncated"] = truncated
    row["unreadable_count"] = unreadable_count
    row["unreadable_sample"] = unreadable_sample
    if unreadable_count > 0:
        row["status"] = "partial"
        row["message"] = f"{unreadable_count} unreadable item(s) encountered in scan"
    else:
        row["status"] = "healthy"
        row["message"] = f"Readable ({sampled}+ checked)" if truncated else f"Readable ({sampled} checked)"
    return row


def _collect_storage_health(libraries: List[Dict[str, Any]], lib_meta: Dict[str, Any]) -> Dict[str, Any]:
    folders: List[Dict[str, Any]] = []
    seen_paths = set()

    if PHOTO_UPLOAD_DIR:
        seen_paths.add(os.path.normpath(PHOTO_UPLOAD_DIR))
        folders.append(probe_folder_health(PHOTO_UPLOAD_DIR, "Upload Folder", "upload"))
    if HDD_MEMORIES:
        norm = os.path.normpath(HDD_MEMORIES)
        if norm not in seen_paths:
            seen_paths.add(norm)
            folders.append(probe_folder_health(HDD_MEMORIES, "Photo Store", "store"))

    for lib in libraries:
        lib_name = lib.get("name") or "External Library"
        for p in lib.get("paths") or []:
            if not p:
                continue
            norm = os.path.normpath(p)
            if norm in seen_paths:
                continue
            seen_paths.add(norm)
            folders.append(probe_folder_health(p, f"External: {lib_name}", "external"))

    unreadable_total = sum(f.get("unreadable_count", 0) for f in folders)
    missing_total = sum(1 for f in folders if not f.get("exists"))
    return {
        "folders": folders,
        "unreadable_total": unreadable_total,
        "missing_total": missing_total,
        "disk_partial": bool(lib_meta.get("disk_partial")),
        "disk_reason": lib_meta.get("disk_reason"),
    }


@photos_hub_bp.route("/api/photos/overview", methods=["GET"])
def get_photos_overview():
    """Returns library overview, per-user usage, ML schedule/queue, XMP status, and folder health."""
    force = request.args.get("refresh", "false").lower() == "true"
    tz_abbr = get_tz_abbr()
    lib_meta = fetch_immich_library_telemetry(force=force)
    assets = lib_meta.get("assets") if isinstance(lib_meta.get("assets"), dict) else None

    users = (assets or {}).get("users") or []
    libraries = (assets or {}).get("libraries") or []
    offline_assets = (assets or {}).get("offline_assets") if assets else None

    ml_info = _inspect_ml_state(tz_abbr, assets)
    face_export = parse_face_export_status(BACKUP_LOG_FILE, FACE_EXPORT_CACHE_FILE, tz_abbr)
    storage_health = _collect_storage_health(libraries, lib_meta)

    installed = bool(
        assets
        or ml_info["installed"]
        or face_export["installed"]
        or any(f.get("exists") for f in storage_health["folders"])
    )

    return jsonify({
        "installed": installed,
        "timezone": get_host_timezone(),
        "tz_abbr": tz_abbr,
        "library": {
            "available": assets is not None,
            "reason": lib_meta.get("assets_reason"),
            "total_assets": (assets or {}).get("total_assets"),
            "photos_count": (assets or {}).get("photos_count"),
            "videos_count": (assets or {}).get("videos_count"),
            "named_people": (assets or {}).get("named_people"),
            "unhidden_people": (assets or {}).get("unhidden_people"),
            "assets_with_named_faces": (assets or {}).get("assets_with_named_faces"),
            "total_face_instances": (assets or {}).get("total_face_instances"),
            "offline_assets": offline_assets,
            "disk_size": lib_meta.get("disk_size"),
            "photos_free_gb": lib_meta.get("photos_free_gb"),
            "photos_total_gb": lib_meta.get("photos_total_gb"),
        },
        "users": users,
        "libraries": libraries,
        "ml": ml_info,
        "face_export": face_export,
        "storage_health": storage_health,
    })


@photos_hub_bp.route("/api/photos/ml/schedule", methods=["POST"])
def update_ml_schedule():
    """Validates and updates `/etc/cron.d/immich-ml` start/stop times and enable toggle."""
    body = request.get_json(silent=True) or {}
    enabled = bool(body.get("enabled", True))
    start_time = str(body.get("start_time") or "").strip()
    stop_time = str(body.get("stop_time") or "").strip()

    try:
        write_ml_cron_file(IMMICH_ML_CRON_FILE, enabled, start_time, stop_time)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or "Could not update ML cron schedule").strip()[:200]
        return jsonify({"ok": False, "error": err}), 500
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)[:200]}), 500

    sched = parse_ml_cron_file(IMMICH_ML_CRON_FILE)
    return jsonify({
        "ok": True,
        "message": (
            f"ML schedule updated ({start_time} start, {stop_time} stop)."
            if enabled
            else "ML automatic schedule paused."
        ),
        "schedule": sched,
    })


@photos_hub_bp.route("/api/photos/ml/action", methods=["POST"])
def control_ml_container():
    """Explicitly starts or stops the Immich Machine Learning container."""
    body = request.get_json(silent=True) or {}
    action = str(body.get("action") or "").strip().lower()
    if action not in ("start", "stop"):
        return jsonify({"ok": False, "error": "action must be 'start' or 'stop'"}), 400

    try:
        if IMMICH_ML_SCRIPT and os.path.isfile(IMMICH_ML_SCRIPT):
            proc = subprocess.run(
                ["sudo", IMMICH_ML_SCRIPT, action],
                capture_output=True,
                text=True,
                timeout=30,
            )
        else:
            proc = subprocess.run(
                ["docker", action, IMMICH_ML_CONTAINER],
                capture_output=True,
                text=True,
                timeout=30,
            )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or f"Failed to {action} ML container").strip()[:200]
            return jsonify({"ok": False, "error": err}), 500
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)[:200]}), 500

    running = action == "start"
    try:
        chk = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", IMMICH_ML_CONTAINER],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if chk.returncode == 0:
            running = chk.stdout.strip() == "true"
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "running": running,
        "message": "Machine Learning started." if running else "Machine Learning stopped.",
    })

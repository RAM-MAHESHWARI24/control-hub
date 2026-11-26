"""
Widget: Storage Analytics, 30-Day Fill Forecast, Safe Cleanups & SMART Health (Phase 3C)
Combines asynchronous per-folder disk allocation metrics, linear fill forecasting
from historical samples, actionable cleanup candidates (finished torrents, rotated
qBittorrent logs, unused Docker images, excess old local dumps), and drive SMART health.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request

from config import (
    APPDATA_DIR,
    BACKUP_DIR,
    HDD_DATA,
    HDD_MEMORIES,
    MEDIA_BACKUP_DIR,
    PHOTO_UPLOAD_DIR,
    QBIT_LOG_DIR,
    QBITTORRENT_PASS,
    STORAGE_HISTORY_FILE,
    STORAGE_OPS_HELPER,
    STORAGE_SIZES_CACHE_FILE,
)
from core.storage_sizes import compute_fill_forecast, get_storage_sizes
from widgets.current_downloads import _qbit_request
from widgets.system_vitals import _resolve_data_mount

storage_hub_bp = Blueprint("storage_hub", __name__)

_SIZE_RE = re.compile(r"([\d.]+)\s*(B|kB|KB|KiB|MB|MiB|GB|GiB|TB|TiB)", re.IGNORECASE)
_QBIT_ROTATED_RE = re.compile(r"^qbittorrent\.log\.bak\d*$")
_PHOTO_DUMP_RE = re.compile(r"^immich_db_\d{8}_\d{6}\.sql\.gz$")
_MEDIA_DUMP_RE = re.compile(r"^media_config_\d{8}_\d{6}\.tar\.zst$")

_UNIT_MAP = {
    "b": 1,
    "kb": 1000,
    "kib": 1024,
    "mb": 1000**2,
    "mib": 1024**2,
    "gb": 1000**3,
    "gib": 1024**3,
    "tb": 1000**4,
    "tib": 1024**4,
}


def parse_size_bytes(raw: Any) -> int:
    """Parses strings like '5.138GB (27%)' or '178.4 MB' into integer bytes."""
    if isinstance(raw, (int, float)):
        return max(0, int(raw))
    if not isinstance(raw, str):
        return 0
    m = _SIZE_RE.search(raw)
    if not m:
        return 0
    val = float(m.group(1))
    unit = _UNIT_MAP.get(m.group(2).lower(), 1)
    return max(0, int(round(val * unit)))


def _helper_available() -> bool:
    return bool(STORAGE_OPS_HELPER and os.path.isfile(STORAGE_OPS_HELPER))


def _run_storage_helper(*args: str, timeout: int = 15) -> Optional[Dict[str, Any]]:
    if not _helper_available():
        return None
    try:
        proc = subprocess.run(
            ["sudo", STORAGE_OPS_HELPER, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.stdout.strip():
            return json.loads(proc.stdout.strip())
    except Exception:
        pass
    return None


def _eligible_finished_torrents() -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Returns completed & paused/past-seed-goal qBittorrent items safe to clear."""
    if not QBITTORRENT_PASS:
        return None, "qBittorrent password not configured"
    try:
        resp = _qbit_request("GET", "/api/v2/torrents/info")
        if resp.status_code != 200:
            return None, f"qBittorrent API returned HTTP {resp.status_code}"
        items = resp.json()
        if not isinstance(items, list):
            return [], None
    except Exception as exc:
        return None, f"qBittorrent unreachable ({exc})"[:120]

    eligible: List[Dict[str, Any]] = []
    for t in items:
        if not isinstance(t, dict):
            continue
        state = str(t.get("state") or "")
        amount_left = t.get("amount_left")
        progress = float(t.get("progress") or 0.0)
        is_complete = (amount_left == 0) or (progress >= 1.0)
        if not is_complete:
            continue
        ratio = float(t.get("ratio") or 0.0)
        max_ratio = float(t.get("max_ratio") or -1.0)
        seed_s = float(t.get("seeding_time") or 0.0)
        max_seed_min = float(t.get("max_seeding_time") or -1.0)
        is_paused = state in ("pausedUP", "stoppedUP")
        past_ratio = max_ratio >= 0 and ratio >= max_ratio
        past_time = max_seed_min >= 0 and seed_s >= max_seed_min * 60.0
        if is_paused or past_ratio or past_time:
            size_b = int(t.get("size") or t.get("total_size") or 0)
            eligible.append({
                "hash": t.get("hash"),
                "name": t.get("name"),
                "size": max(0, size_b),
            })
    return eligible, None


def _scan_qbit_logs_local(qbit_dir: str) -> Tuple[int, int, List[Path], bool]:
    if not qbit_dir or not os.path.isdir(qbit_dir):
        return 0, 0, [], False
    matches: List[Path] = []
    total_bytes = 0
    try:
        with os.scandir(qbit_dir) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False) and _QBIT_ROTATED_RE.match(entry.name):
                    try:
                        total_bytes += entry.stat(follow_symlinks=False).st_size
                        matches.append(Path(entry.path))
                    except OSError:
                        pass
        writable = os.access(qbit_dir, os.W_OK | os.X_OK)
        return len(matches), total_bytes, matches, writable
    except OSError:
        return 0, 0, [], False


def _scan_excess_dumps_local(keep: int = 3) -> Tuple[int, int, List[Path], bool]:
    excess: List[Path] = []
    total_bytes = 0
    writable_any = False
    for folder, pat in ((BACKUP_DIR, _PHOTO_DUMP_RE), (MEDIA_BACKUP_DIR, _MEDIA_DUMP_RE)):
        if not folder or not os.path.isdir(folder):
            continue
        writable_any = writable_any or os.access(folder, os.W_OK | os.X_OK)
        files: List[Tuple[str, Path, int]] = []
        try:
            with os.scandir(folder) as it:
                for entry in it:
                    if entry.is_file(follow_symlinks=False) and pat.match(entry.name):
                        try:
                            files.append((entry.name, Path(entry.path), entry.stat(follow_symlinks=False).st_size))
                        except OSError:
                            pass
        except OSError:
            continue
        files.sort(key=lambda item: item[0], reverse=True)
        for _, path, sz in files[keep:]:
            excess.append(path)
            total_bytes += sz
    return len(excess), total_bytes, excess, writable_any


def _scan_docker_reclaimable() -> Dict[str, Any]:
    out = {"available": False, "images_bytes": 0, "build_bytes": 0, "total_bytes": 0, "reason": None}
    try:
        proc = subprocess.run(
            ["docker", "system", "df", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0:
            out["reason"] = (proc.stderr or "Docker unavailable").strip()[:120]
            return out
        out["available"] = True
        for raw_line in proc.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            kind = str(row.get("Type") or "").lower()
            reclaim_b = parse_size_bytes(row.get("Reclaimable"))
            if "image" in kind:
                out["images_bytes"] += reclaim_b
            elif "build" in kind:
                out["build_bytes"] += reclaim_b
        out["total_bytes"] = out["images_bytes"] + out["build_bytes"]
    except Exception as exc:
        out["reason"] = f"Docker unavailable ({exc})"[:120]
    return out


def _probe_smart_health() -> Dict[str, Any]:
    """Queries drive health via root helper, falling back cleanly if absent."""
    helper_res = _run_storage_helper("smart", timeout=15)
    if isinstance(helper_res, dict) and isinstance(helper_res.get("disks"), list):
        return helper_res
    return {
        "available": False,
        "smartctl_installed": False,
        "reason": "Install homelab-storage-ops helper & smartmontools for SMART disk telemetry.",
        "disks": [],
    }


def _size_item(size_bytes: int) -> Tuple[float, float]:
    mb = round(size_bytes / (1024**2), 1)
    gb = round(size_bytes / (1024**3), 2)
    return mb, gb


def _build_cleanup_suggestions() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    helper_scan = _run_storage_helper("scan", timeout=10)

    # 1. Finished / seeded torrents
    torrents, qbt_err = _eligible_finished_torrents()
    if torrents is not None:
        t_bytes = sum(t["size"] for t in torrents)
        t_mb, t_gb = _size_item(t_bytes)
        items.append({
            "id": "torrents_seeded",
            "label": "Finished Torrents (Seed Goal Met)",
            "description": "Completed torrents paused or past seed target (hardlinked copies in media/ remain intact).",
            "count": len(torrents),
            "size_bytes": t_bytes,
            "size_mb": t_mb,
            "size_gb": t_gb,
            "actionable": len(torrents) > 0,
            "action_label": "Remove Finished",
            "reason": None if len(torrents) > 0 else "No completed torrents waiting for removal",
        })
    else:
        items.append({
            "id": "torrents_seeded",
            "label": "Finished Torrents (Seed Goal Met)",
            "description": qbt_err or "qBittorrent unavailable",
            "count": 0,
            "size_bytes": 0,
            "size_mb": 0.0,
            "size_gb": 0.0,
            "actionable": False,
            "action_label": "Remove Finished",
            "reason": qbt_err,
        })

    # 2. qBittorrent rotated logs
    if isinstance(helper_scan, dict) and isinstance(helper_scan.get("qbit_logs"), dict):
        q_count = int(helper_scan["qbit_logs"].get("count") or 0)
        q_bytes = int(helper_scan["qbit_logs"].get("bytes") or 0)
        q_can_clean = q_count > 0
        q_reason = None
    else:
        q_count, q_bytes, _, q_writable = _scan_qbit_logs_local(QBIT_LOG_DIR)
        q_can_clean = q_count > 0 and q_writable
        q_reason = None if q_can_clean else ("Requires storage helper permission" if q_count > 0 else "No rotated log files found")

    q_mb, q_gb = _size_item(q_bytes)
    items.append({
        "id": "qbit_logs",
        "label": "qBittorrent Rotated Logs",
        "description": "Old qbittorrent.log.bak* archives (active log file is preserved).",
        "count": q_count,
        "size_bytes": q_bytes,
        "size_mb": q_mb,
        "size_gb": q_gb,
        "actionable": q_can_clean,
        "action_label": "Purge Rotated Logs",
        "reason": q_reason,
    })

    # 3. Unused Docker images & build cache
    dk = _scan_docker_reclaimable()
    d_bytes = int(dk.get("total_bytes") or 0)
    d_mb, d_gb = _size_item(d_bytes)
    items.append({
        "id": "docker_prune",
        "label": "Unused Docker Images & Cache",
        "description": "Unreferenced image layers and build cache (running containers and volumes stay untouched).",
        "count": 1 if d_bytes > 0 else 0,
        "size_bytes": d_bytes,
        "size_mb": d_mb,
        "size_gb": d_gb,
        "actionable": bool(dk["available"] and d_bytes > 0),
        "action_label": "Prune Unused Images",
        "reason": dk.get("reason") or ("No unused Docker image space" if d_bytes == 0 else None),
    })

    # 4. Excess old local database/config dumps (>3 newest)
    if isinstance(helper_scan, dict) and isinstance(helper_scan.get("old_dumps"), dict):
        o_count = int(helper_scan["old_dumps"].get("count") or 0)
        o_bytes = int(helper_scan["old_dumps"].get("bytes") or 0)
        o_can_clean = o_count > 0
        o_reason = None if o_can_clean else "Retention policy clean (<= 3 local dumps per store)"
    else:
        o_count, o_bytes, _, o_writable = _scan_excess_dumps_local()
        o_can_clean = o_count > 0 and o_writable
        o_reason = None if o_can_clean else "Retention policy clean (<= 3 local dumps per store)"

    o_mb, o_gb = _size_item(o_bytes)
    items.append({
        "id": "old_dumps",
        "label": "Excess Local Backup Dumps",
        "description": "Local dumps beyond the 3 newest snapshots per store (cloud copies stay intact).",
        "count": o_count,
        "size_bytes": o_bytes,
        "size_mb": o_mb,
        "size_gb": o_gb,
        "actionable": o_can_clean,
        "action_label": "Prune Old Dumps",
        "reason": o_reason,
    })
    return items


@storage_hub_bp.route("/api/storage/overview", methods=["GET"])
def get_storage_overview():
    """Returns per-folder sizes, 30-day fill forecast, safe cleanups, and SMART disk health."""
    force = request.args.get("refresh", "false").lower() == "true"
    sizes = get_storage_sizes(
        cache_file=STORAGE_SIZES_CACHE_FILE,
        media_path=HDD_DATA,
        photos_path=HDD_MEMORIES,
        appdata_path=APPDATA_DIR,
        backup_path=BACKUP_DIR,
        photo_upload_path=PHOTO_UPLOAD_DIR,
        media_backup_path=MEDIA_BACKUP_DIR,
        force=force,
    )

    data_mount, mount_exists = _resolve_data_mount(HDD_DATA)
    hdd_used_b = hdd_total_b = None
    if mount_exists:
        try:
            u = shutil.disk_usage(data_mount)
            hdd_used_b, hdd_total_b = u.used, u.total
        except OSError:
            pass

    try:
        root_u = shutil.disk_usage("/")
        ssd_used_b, ssd_total_b = root_u.used, root_u.total
    except OSError:
        ssd_used_b = ssd_total_b = None

    forecasts = {
        "hdd": compute_fill_forecast(STORAGE_HISTORY_FILE, data_mount, hdd_used_b, hdd_total_b) if mount_exists else None,
        "ssd": compute_fill_forecast(STORAGE_HISTORY_FILE, "/", ssd_used_b, ssd_total_b),
    }

    return jsonify({
        "folders": {
            "measured": bool(sizes.get("measured")),
            "measuring": bool(sizes.get("measuring")),
            "measured_at": sizes.get("measured_at"),
            "measured_by": sizes.get("measured_by"),
            "any_partial": bool(sizes.get("any_partial")),
            "reason": sizes.get("reason"),
            "rows": [
                {"id": "movies", "label": "Movies", "path": os.path.join(HDD_DATA, "media", "movies"), "gb": sizes.get("movies_gb")},
                {"id": "tv", "label": "TV Shows", "path": os.path.join(HDD_DATA, "media", "tv"), "gb": sizes.get("tv_gb")},
                {"id": "downloads", "label": "Downloads / Torrents", "path": os.path.join(HDD_DATA, "torrents"), "gb": sizes.get("downloads_gb")},
                {"id": "photos", "label": "Photos & Uploads", "path": HDD_MEMORIES or PHOTO_UPLOAD_DIR, "gb": sizes.get("photos_gb")},
                {"id": "backups", "label": "Local Backups", "path": BACKUP_DIR, "gb": sizes.get("only_backups_gb")},
                {"id": "appdata", "label": "App Data", "path": APPDATA_DIR, "gb": sizes.get("only_appdata_gb")},
            ],
        },
        "forecasts": forecasts,
        "cleanup": _build_cleanup_suggestions(),
        "smart": _probe_smart_health(),
    })


@storage_hub_bp.route("/api/storage/cleanup", methods=["POST"])
def run_storage_cleanup():
    """Executes one validated storage cleanup action."""
    body = request.get_json(silent=True) or {}
    target = str(body.get("target") or "").strip()

    if target == "torrents_seeded":
        torrents, err = _eligible_finished_torrents()
        if torrents is None:
            return jsonify({"ok": False, "error": err or "qBittorrent unavailable"}), 502
        if not torrents:
            return jsonify({"ok": True, "target": target, "deleted_count": 0, "freed_bytes": 0, "message": "No completed torrents to remove."})
        hashes = "|".join(str(t["hash"]) for t in torrents if t.get("hash"))
        est_bytes = sum(t["size"] for t in torrents)
        resp = _qbit_request("POST", "/api/v2/torrents/delete", {"hashes": hashes, "deleteFiles": "true"})
        if resp.status_code != 200:
            return jsonify({"ok": False, "error": f"qBittorrent delete failed (HTTP {resp.status_code})"}), 502
        return jsonify({
            "ok": True,
            "target": target,
            "deleted_count": len(torrents),
            "freed_bytes": est_bytes,
            "message": f"Removed {len(torrents)} finished torrent(s).",
        })

    if target in ("qbit_logs", "old_dumps"):
        helper_res = _run_storage_helper("clean", target, timeout=30)
        if isinstance(helper_res, dict):
            code = 200 if helper_res.get("ok") else 500
            return jsonify(helper_res), code

        # Fallback for direct-writeable environments (unit tests / non-root setup)
        if target == "qbit_logs":
            _, _, paths, writable = _scan_qbit_logs_local(QBIT_LOG_DIR)
        else:
            _, _, paths, writable = _scan_excess_dumps_local()

        if paths and not writable:
            return jsonify({"ok": False, "error": "Requires homelab-storage-ops root helper to modify protected files."}), 403

        deleted = freed = 0
        for p in paths:
            try:
                sz = p.stat().st_size
                p.unlink()
                deleted += 1
                freed += sz
            except OSError:
                pass
        return jsonify({
            "ok": True,
            "target": target,
            "deleted_count": deleted,
            "freed_bytes": freed,
            "message": f"Removed {deleted} item(s), freeing {round(freed / (1024**2), 1)} MB.",
        })

    if target == "docker_prune":
        try:
            proc = subprocess.run(
                ["docker", "image", "prune", "-a", "-f"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode != 0:
                return jsonify({"ok": False, "error": (proc.stderr or "Docker prune failed").strip()[:160]}), 500
            freed_b = 0
            for line in proc.stdout.splitlines():
                if "reclaimed space" in line.lower():
                    freed_b = parse_size_bytes(line)
                    break
            return jsonify({
                "ok": True,
                "target": target,
                "deleted_count": 1,
                "freed_bytes": freed_b,
                "message": f"Pruned unused Docker images (reclaimed {round(freed_b / (1024**2), 1)} MB).",
            })
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)[:160]}), 500

    return jsonify({"ok": False, "error": f"Unknown cleanup target '{target}'"}), 400

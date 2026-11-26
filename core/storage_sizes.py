"""
Asynchronous cached directory size measurement for Control Hub.

Measures configured media, photo, upload, and appdata/backup directories using
allocated disk blocks (`du -s -B1`, deduplicating hardlinks without inflating
sparse files) with low CPU/I/O priority (`nice` / `ionice`) on Linux, persists
results atomically to disk (0644), and refreshes at most once per TTL (default
1 hour) so HTTP handlers never block.

On blueprint installs, `homelab-storage-sizes.timer` runs this module directly
as root (`python3 core/storage_sizes.py --once`) outside Control Hub's cgroup
so private photo subdirectories are measured accurately without granting the
unprivileged `homelab` user extra read permissions.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_TTL_SECONDS = 3600

_cache_lock = threading.Lock()
_scan_in_progress = False
_scan_thread: Optional[threading.Thread] = None
_memory_cache: Dict[str, Any] = {}


def wait_for_idle(timeout: float = 5.0) -> None:
    """Blocks until any in-flight background scan thread finishes (used in tests)."""
    with _cache_lock:
        thread = _scan_thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout)


def _path_dev(path_str: str) -> Optional[int]:
    if not path_str:
        return None
    try:
        return os.stat(path_str).st_dev
    except OSError:
        return None


def _dir_size_bytes(path_str: str, timeout: int = 1800) -> tuple[Optional[int], Optional[str]]:
    """Returns (allocated_bytes, warning_or_error) for `path_str` without raising."""
    if not path_str:
        return None, "Path not configured"
    target = Path(path_str)
    if not target.exists():
        return None, f"Directory not found ({path_str})"

    du_bin = shutil.which("du")
    if du_bin and os.name != "nt":
        # -B1 reports allocated disk bytes (hardlinks deduplicated, sparse files honest).
        cmd = [du_bin, "-s", "-B1", str(target)]
        ionice_bin = shutil.which("ionice")
        nice_bin = shutil.which("nice")
        if ionice_bin:
            cmd = [ionice_bin, "-c3", *cmd]
        if nice_bin:
            cmd = [nice_bin, "-n", "19", *cmd]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if proc.returncode in (0, 1) and proc.stdout.strip():
                first_tok = proc.stdout.strip().split()[0]
                if first_tok.isdigit():
                    warn = "some subdirectories unreadable" if proc.returncode == 1 else None
                    return int(first_tok), warn
            return None, (proc.stderr or f"du exited {proc.returncode}").strip()[:160]
        except subprocess.TimeoutExpired:
            return None, f"Timed out measuring {path_str}"
        except (OSError, ValueError) as exc:
            return None, str(exc)[:160]

    # Cross-platform fallback (Windows dev / unit tests)
    total = 0
    unreadable = False
    try:
        stack = [target]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False):
                                total += entry.stat(follow_symlinks=False).st_size
                        except PermissionError:
                            unreadable = True
                        except OSError:
                            continue
            except PermissionError:
                unreadable = True
        return total, ("some subdirectories unreadable" if unreadable else None)
    except OSError as exc:
        return None, str(exc)[:160]


def _load_disk_cache(cache_file: str) -> Optional[Dict[str, Any]]:
    path = Path(cache_file)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "measured_at" in data:
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _save_disk_cache(cache_file: str, payload: Dict[str, Any]) -> None:
    path = Path(cache_file)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o644)
        except OSError:
            pass
        os.replace(tmp, path)
    except OSError:
        pass


def _is_nested_inside(child: str, parent: str) -> bool:
    if not child or not parent:
        return False
    try:
        cp = Path(child).resolve()
        pp = Path(parent).resolve()
        return cp == pp or cp.is_relative_to(pp)
    except OSError:
        return False


def _measure_all(
    media_path: str,
    photos_path: str,
    appdata_path: str,
    backup_path: str,
    photo_upload_path: str = "",
    media_backup_path: str = "",
    measured_by: str = "control-hub",
) -> Dict[str, Any]:
    media_bytes, media_err = _dir_size_bytes(media_path)
    photos_bytes, photos_err = _dir_size_bytes(photos_path)

    # Fine-grained sub-folders (individually measured; torrents/movies share hardlinks cleanly)
    movies_bytes: Optional[int] = None
    tv_bytes: Optional[int] = None
    downloads_bytes: Optional[int] = None
    if media_path:
        m_dir = Path(media_path) / "media" / "movies"
        t_dir = Path(media_path) / "media" / "tv"
        d_dir = Path(media_path) / "torrents"
        if m_dir.is_dir():
            movies_bytes, _ = _dir_size_bytes(str(m_dir))
        if t_dir.is_dir():
            tv_bytes, _ = _dir_size_bytes(str(t_dir))
        if d_dir.is_dir():
            downloads_bytes, _ = _dir_size_bytes(str(d_dir))

    upload_bytes: Optional[int] = None
    upload_err: Optional[str] = None
    upload_distinct = bool(
        photo_upload_path
        and Path(photo_upload_path).exists()
        and not _is_nested_inside(photo_upload_path, photos_path)
    )
    if upload_distinct:
        upload_bytes, upload_err = _dir_size_bytes(photo_upload_path)

    app_bytes, app_err = _dir_size_bytes(appdata_path)
    bak_bytes, bak_err = _dir_size_bytes(backup_path)
    mbak_bytes: Optional[int] = None
    if media_backup_path and Path(media_backup_path).exists() and not _is_nested_inside(media_backup_path, backup_path):
        mbak_bytes, _ = _dir_size_bytes(media_backup_path)

    # Avoid double-counting when photos or uploads live inside the media root directory.
    if media_bytes is not None and photos_bytes is not None:
        try:
            mp = Path(media_path).resolve()
            pp = Path(photos_path).resolve()
            if pp != mp and pp.is_relative_to(mp):
                media_bytes = max(0, media_bytes - photos_bytes)
        except OSError:
            pass

    if media_bytes is not None and upload_bytes is not None and _is_nested_inside(photo_upload_path, media_path):
        media_bytes = max(0, media_bytes - upload_bytes)

    combined_photos_bytes: Optional[int] = None
    if photos_bytes is not None or upload_bytes is not None:
        combined_photos_bytes = (photos_bytes or 0) + (upload_bytes or 0)

    only_backups_total: Optional[int] = None
    if bak_bytes is not None or mbak_bytes is not None:
        only_backups_total = (bak_bytes or 0) + (mbak_bytes or 0)

    appdata_total: Optional[int] = None
    if app_bytes is not None or only_backups_total is not None:
        appdata_total = (app_bytes or 0) + (only_backups_total or 0)

    media_partial = bool(media_bytes is not None and media_err)
    photos_partial = bool(
        (photos_bytes is not None and photos_err) or (upload_bytes is not None and upload_err)
    )
    appdata_partial = bool((app_bytes is not None and app_err) or (bak_bytes is not None and bak_err))
    any_partial = media_partial or photos_partial or appdata_partial

    def to_gb(b: Optional[int]) -> Optional[float]:
        return round(b / (1024**3), 2) if b is not None else None

    reasons = []
    if media_err:
        reasons.append(f"media: {media_err}")
    if photos_err:
        reasons.append(f"photos: {photos_err}")
    if upload_err:
        reasons.append(f"photo uploads: {upload_err}")
    if app_err and app_bytes is not None:
        reasons.append(f"appdata: {app_err}")
    if bak_err and bak_bytes is not None:
        reasons.append(f"backups: {bak_err}")

    measured = (media_bytes is not None) or (combined_photos_bytes is not None) or (appdata_total is not None)
    return {
        "measured": measured,
        "measured_at": time.time(),
        "measured_by": measured_by,
        "media_bytes": media_bytes,
        "movies_bytes": movies_bytes,
        "tv_bytes": tv_bytes,
        "downloads_bytes": downloads_bytes,
        "photos_bytes": combined_photos_bytes,
        "photos_external_bytes": photos_bytes,
        "photos_upload_bytes": upload_bytes,
        "only_appdata_bytes": app_bytes,
        "only_backups_bytes": only_backups_total,
        "appdata_bytes": appdata_total,
        "media_gb": to_gb(media_bytes),
        "movies_gb": to_gb(movies_bytes),
        "tv_gb": to_gb(tv_bytes),
        "downloads_gb": to_gb(downloads_bytes),
        "photos_gb": to_gb(combined_photos_bytes),
        "only_appdata_gb": to_gb(app_bytes),
        "only_backups_gb": to_gb(only_backups_total),
        "appdata_gb": to_gb(appdata_total),
        "media_partial": media_partial,
        "photos_partial": photos_partial,
        "appdata_partial": appdata_partial,
        "any_partial": any_partial,
        "fs_devs": {
            "media": _path_dev(media_path),
            "photos": _path_dev(photos_path) or _path_dev(photo_upload_path),
            "appdata": _path_dev(appdata_path),
            "backup": _path_dev(backup_path),
        },
        "reason": "; ".join(reasons) if reasons else None,
    }


def _background_refresh(
    cache_file: str,
    media_path: str,
    photos_path: str,
    appdata_path: str,
    backup_path: str,
    photo_upload_path: str = "",
    media_backup_path: str = "",
) -> None:
    global _scan_in_progress, _scan_thread
    try:
        result = _measure_all(
            media_path,
            photos_path,
            appdata_path,
            backup_path,
            photo_upload_path=photo_upload_path,
            media_backup_path=media_backup_path,
        )
        with _cache_lock:
            _memory_cache[cache_file] = result
        _save_disk_cache(cache_file, result)
    finally:
        with _cache_lock:
            _scan_in_progress = False
            _scan_thread = None


def get_storage_sizes(
    *,
    cache_file: str,
    media_path: str,
    photos_path: str,
    appdata_path: str = "",
    backup_path: str = "",
    photo_upload_path: str = "",
    media_backup_path: str = "",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    force: bool = False,
    blocking: bool = False,
) -> Dict[str, Any]:
    """
    Returns cached folder sizes, preferring a fresh on-disk cache (such as one
    written by the root `homelab-storage-sizes.timer`), and refreshing
    asynchronously in the background only when missing or stale.
    """
    global _scan_in_progress, _scan_thread
    now = time.time()

    with _cache_lock:
        # Always check whether an external producer (root systemd timer) wrote a newer disk cache.
        disk_cached = _load_disk_cache(cache_file)
        mem_cached = _memory_cache.get(cache_file)
        if disk_cached is not None and (
            mem_cached is None or float(disk_cached.get("measured_at", 0)) >= float(mem_cached.get("measured_at", 0))
        ):
            cached = disk_cached
            _memory_cache[cache_file] = disk_cached
        else:
            cached = mem_cached

        is_fresh = cached is not None and (now - float(cached.get("measured_at", 0))) < ttl_seconds
        if cached is not None and is_fresh and not force:
            return {**cached, "measuring": _scan_in_progress, "ttl_seconds": ttl_seconds}

        # If a root timer wrote a recent full measurement and we are unprivileged, avoid clobbering it
        # with a partial unprivileged scan on non-forced requests when within 2x TTL.
        if (
            cached is not None
            and not force
            and cached.get("measured_by") == "root-timer"
            and (now - float(cached.get("measured_at", 0))) < ttl_seconds * 2
        ):
            return {**cached, "measuring": False, "stale": True, "ttl_seconds": ttl_seconds}

        any_target_exists = any(
            bool(p) and Path(p).exists()
            for p in (media_path, photos_path, photo_upload_path, appdata_path, backup_path, media_backup_path)
        )
        if blocking or not any_target_exists:
            result = _measure_all(
                media_path,
                photos_path,
                appdata_path,
                backup_path,
                photo_upload_path=photo_upload_path,
                media_backup_path=media_backup_path,
            )
            _memory_cache[cache_file] = result
            if any_target_exists:
                _save_disk_cache(cache_file, result)
            return {**result, "measuring": False, "ttl_seconds": ttl_seconds}

        should_spawn = not _scan_in_progress
        if should_spawn:
            _scan_in_progress = True
            t = threading.Thread(
                target=_background_refresh,
                args=(cache_file, media_path, photos_path, appdata_path, backup_path, photo_upload_path, media_backup_path),
                daemon=True,
            )
            _scan_thread = t
            t.start()

    if cached is not None:
        return {**cached, "measuring": True, "stale": True, "ttl_seconds": ttl_seconds}

    return {
        "measured": False,
        "measuring": True,
        "measured_at": None,
        "measured_by": None,
        "media_bytes": None,
        "movies_bytes": None,
        "tv_bytes": None,
        "downloads_bytes": None,
        "photos_bytes": None,
        "only_appdata_bytes": None,
        "only_backups_bytes": None,
        "appdata_bytes": None,
        "media_gb": None,
        "movies_gb": None,
        "tv_gb": None,
        "downloads_gb": None,
        "photos_gb": None,
        "only_appdata_gb": None,
        "only_backups_gb": None,
        "appdata_gb": None,
        "media_partial": False,
        "photos_partial": False,
        "appdata_partial": False,
        "any_partial": False,
        "fs_devs": {},
        "reason": "Measuring folder sizes in background",
        "ttl_seconds": ttl_seconds,
    }


def _load_history(history_file: str) -> list[Dict[str, Any]]:
    path = Path(history_file)
    if not history_file or not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        samples = data.get("samples") if isinstance(data, dict) else None
        return list(samples) if isinstance(samples, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def record_storage_sample(
    history_file: str,
    mount: str,
    used_bytes: int,
    total_bytes: int,
    *,
    min_interval_s: float = 21600.0,
    now_ts: Optional[float] = None,
) -> None:
    """Appends periodic disk-usage snapshots for 30-day fill-rate forecasting (throttled per mount)."""
    if not history_file or not mount or total_bytes <= 0 or used_bytes < 0:
        return
    ts = float(now_ts if now_ts is not None else time.time())
    with _cache_lock:
        series = _load_history(history_file)
        mount_pts = [pt for pt in series if isinstance(pt, dict) and pt.get("mount") == mount]
        if mount_pts and (ts - float(mount_pts[-1].get("ts", 0))) < min_interval_s:
            return
        series.append({"ts": round(ts, 1), "mount": mount, "used_bytes": int(used_bytes), "total_bytes": int(total_bytes)})
        cutoff = ts - (35 * 86400)
        series = [pt for pt in series if isinstance(pt, dict) and float(pt.get("ts", 0)) >= cutoff][-360:]
        _save_disk_cache(history_file, {"samples": series})


def compute_fill_forecast(
    history_file: str,
    mount: str,
    current_used_bytes: Optional[int],
    current_total_bytes: Optional[int],
    *,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    """Calculates a linear 30-day growth rate & days-until-full forecast from recorded samples."""
    ts = float(now_ts if now_ts is not None else time.time())
    if current_used_bytes is None or current_total_bytes is None or current_total_bytes <= 0:
        return {
            "ready": False,
            "mount": mount,
            "days_until_full": None,
            "daily_delta_gb": None,
            "window_days": 0,
            "message": "Storage mount unavailable for forecast.",
        }

    series = _load_history(history_file)
    cutoff = ts - (30 * 86400)
    pts = [
        pt for pt in series
        if isinstance(pt, dict)
        and pt.get("mount") == mount
        and float(pt.get("ts", 0)) >= cutoff
        and isinstance(pt.get("used_bytes"), (int, float))
    ]
    pts.sort(key=lambda item: float(item.get("ts", 0)))

    if not pts:
        return {
            "ready": False,
            "mount": mount,
            "days_until_full": None,
            "daily_delta_gb": None,
            "window_days": 0,
            "message": "Collecting disk usage history (needs at least 24 hours of samples).",
        }

    earliest = pts[0]
    days_elapsed = (ts - float(earliest.get("ts", ts))) / 86400.0
    if days_elapsed < 1.0:
        return {
            "ready": False,
            "mount": mount,
            "days_until_full": None,
            "daily_delta_gb": None,
            "window_days": round(days_elapsed, 2),
            "message": "Collecting disk usage history (forecast available after 24 hours of samples).",
        }

    delta_bytes = float(current_used_bytes) - float(earliest["used_bytes"])
    daily_bytes = delta_bytes / days_elapsed
    daily_gb = round(daily_bytes / (1024**3), 2)
    window_days = max(1, int(round(days_elapsed)))

    if daily_bytes <= 1024 * 1024:  # <= ~1 MB/day treated as stable
        return {
            "ready": True,
            "mount": mount,
            "trend": "stable" if abs(daily_gb) < 0.05 else "shrinking",
            "days_until_full": None,
            "daily_delta_gb": daily_gb,
            "window_days": window_days,
            "message": f"Usage steady ({daily_gb:+.2f} GB/day over last {window_days}d).",
        }

    free_bytes = max(0.0, float(current_total_bytes) - float(current_used_bytes))
    days_left = round(free_bytes / daily_bytes, 1)
    used_pct = round((float(current_used_bytes) / float(current_total_bytes)) * 100.0, 1)
    return {
        "ready": True,
        "mount": mount,
        "trend": "growing",
        "days_until_full": days_left,
        "daily_delta_gb": daily_gb,
        "used_percent": used_pct,
        "window_days": window_days,
        "message": f"At the last {window_days} days' rate (+{daily_gb:.2f} GB/day), {mount} ({used_pct}% used) is full in ~{int(round(days_left))} days.",
    }


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint for `homelab-storage-sizes.service` (runs once as root and exits)."""
    parser = argparse.ArgumentParser(description="Measure homelab folder sizes and write storage_sizes_cache.json.")
    parser.add_argument("--once", action="store_true", help="Measure once and write cache atomically (0644).")
    args = parser.parse_args(argv)
    if not args.once:
        parser.print_help()
        return 2

    hub_root = Path(__file__).resolve().parent.parent
    if str(hub_root) not in sys.path:
        sys.path.insert(0, str(hub_root))
    import config  # noqa: E402

    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    result = _measure_all(
        media_path=config.HDD_DATA,
        photos_path=config.HDD_MEMORIES,
        appdata_path=config.APPDATA_DIR,
        backup_path=config.BACKUP_DIR,
        photo_upload_path=config.PHOTO_UPLOAD_DIR,
        media_backup_path=config.MEDIA_BACKUP_DIR,
        measured_by="root-timer" if is_root else "cli",
    )
    _save_disk_cache(config.STORAGE_SIZES_CACHE_FILE, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

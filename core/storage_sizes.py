"""
Asynchronous cached directory size measurement for Control Hub.

Measures configured media, photo, and appdata/backup directories using `du`
with low CPU/I/O priority (`nice` / `ionice`) on Linux (or `os.scandir` when
`du` is unavailable), persists results atomically to disk, and refreshes in the
background at most once per TTL (default 1 hour) so HTTP handlers never block.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
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


def _dir_size_bytes(path_str: str, timeout: int = 120) -> tuple[Optional[int], Optional[str]]:
    """Returns (bytes, error_reason) for `path_str` without raising."""
    if not path_str:
        return None, "Path not configured"
    target = Path(path_str)
    if not target.exists():
        return None, f"Directory not found ({path_str})"

    du_bin = shutil.which("du")
    if du_bin and os.name != "nt":
        cmd = [du_bin, "-sb", str(target)]
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
    try:
        stack = [target]
        while stack:
            current = stack.pop()
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        return total, None
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
        os.replace(tmp, path)
    except OSError:
        pass


def _measure_all(media_path: str, photos_path: str, appdata_path: str, backup_path: str) -> Dict[str, Any]:
    media_bytes, media_err = _dir_size_bytes(media_path)
    photos_bytes, photos_err = _dir_size_bytes(photos_path)
    app_bytes, _ = _dir_size_bytes(appdata_path)
    bak_bytes, _ = _dir_size_bytes(backup_path)

    # Avoid double-counting when photos live inside the media root directory.
    if media_bytes is not None and photos_bytes is not None:
        try:
            mp = Path(media_path).resolve()
            pp = Path(photos_path).resolve()
            if pp != mp and pp.is_relative_to(mp):
                media_bytes = max(0, media_bytes - photos_bytes)
        except OSError:
            pass

    appdata_total: Optional[int] = None
    if app_bytes is not None or bak_bytes is not None:
        appdata_total = (app_bytes or 0) + (bak_bytes or 0)

    def to_gb(b: Optional[int]) -> Optional[float]:
        return round(b / (1024**3), 2) if b is not None else None

    reasons = []
    if media_err:
        reasons.append(f"media: {media_err}")
    if photos_err:
        reasons.append(f"photos: {photos_err}")

    measured = (media_bytes is not None) or (photos_bytes is not None) or (appdata_total is not None)
    return {
        "measured": measured,
        "measured_at": time.time(),
        "media_bytes": media_bytes,
        "photos_bytes": photos_bytes,
        "appdata_bytes": appdata_total,
        "media_gb": to_gb(media_bytes),
        "photos_gb": to_gb(photos_bytes),
        "appdata_gb": to_gb(appdata_total),
        "reason": "; ".join(reasons) if reasons else None,
    }


def _background_refresh(cache_file: str, media_path: str, photos_path: str, appdata_path: str, backup_path: str) -> None:
    global _scan_in_progress, _scan_thread
    try:
        result = _measure_all(media_path, photos_path, appdata_path, backup_path)
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
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    force: bool = False,
    blocking: bool = False,
) -> Dict[str, Any]:
    """
    Returns cached folder sizes, refreshing asynchronously in the background if stale.
    When `blocking=True` (used by explicit refresh or unit tests), measures inline.
    """
    global _scan_in_progress, _scan_thread
    now = time.time()

    with _cache_lock:
        cached = _memory_cache.get(cache_file)
        if cached is None:
            cached = _load_disk_cache(cache_file)
            if cached is not None:
                _memory_cache[cache_file] = cached

        is_fresh = cached is not None and (now - float(cached.get("measured_at", 0))) < ttl_seconds
        if cached is not None and is_fresh and not force:
            return {**cached, "measuring": _scan_in_progress, "ttl_seconds": ttl_seconds}

        any_target_exists = any(bool(p) and Path(p).exists() for p in (media_path, photos_path, appdata_path, backup_path))
        if blocking or not any_target_exists:
            result = _measure_all(media_path, photos_path, appdata_path, backup_path)
            _memory_cache[cache_file] = result
            if any_target_exists:
                _save_disk_cache(cache_file, result)
            return {**result, "measuring": False, "ttl_seconds": ttl_seconds}

        should_spawn = not _scan_in_progress
        if should_spawn:
            _scan_in_progress = True
            t = threading.Thread(
                target=_background_refresh,
                args=(cache_file, media_path, photos_path, appdata_path, backup_path),
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
        "media_bytes": None,
        "photos_bytes": None,
        "appdata_bytes": None,
        "media_gb": None,
        "photos_gb": None,
        "appdata_gb": None,
        "reason": "Measuring folder sizes in background",
        "ttl_seconds": ttl_seconds,
    }

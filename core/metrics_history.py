"""
Bounded time-series metrics store, 30-day monthly report, and Sleep Guard power-savings estimator.
Thread-safe, atomic (.tmp + os.replace), and pure-stdlib so Control Hub stays ultra-lean.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Optional

import config
from core import backup_health, storage_sizes
from core import updates as updates_core
from widgets import sleep_guard

_LOCK = threading.Lock()
_LAST_RECORDED_TS = 0.0
_CACHE: Optional[dict[str, Any]] = None

SAMPLE_INTERVAL_S = 300
RETENTION_SECONDS = 30 * 86400
MAX_SAMPLES = 8640  # 30d * 24h * 12 samples/hr
RANGE_SECONDS = {
    "24h": 24 * 3600,
    "7d": 7 * 86400,
    "30d": 30 * 86400,
}


def _history_path(path_override: Optional[str | Path] = None) -> Path:
    return Path(path_override or getattr(config, "TELEMETRY_HISTORY_FILE", "") or (config.HUB_CACHE_DIR / "telemetry_history.json"))


def _reset_for_tests() -> None:
    global _LAST_RECORDED_TS, _CACHE
    with _LOCK:
        _LAST_RECORDED_TS = 0.0
        _CACHE = None


def _load_unlocked(path: Path) -> dict[str, Any]:
    global _CACHE
    if _CACHE is not None and _CACHE.get("_path") == str(path):
        return _CACHE
    samples: list[dict[str, Any]] = []
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("samples"), list):
                samples = [s for s in raw["samples"] if isinstance(s, dict) and "ts" in s]
        except (OSError, json.JSONDecodeError):
            samples = []
    _CACHE = {"_path": str(path), "samples": samples}
    return _CACHE


def _write_atomic_unlocked(path: Path, samples: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}")
    payload = {"version": 1, "updated_at": int(time.time()), "samples": samples}
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def record_sample(
    sample: dict[str, Any],
    *,
    now_ts: Optional[float] = None,
    min_interval_s: float = SAMPLE_INTERVAL_S,
    path_override: Optional[str | Path] = None,
) -> bool:
    """Appends one metrics bucket if at least `min_interval_s` elapsed since the previous one."""
    global _LAST_RECORDED_TS
    now = float(now_ts if now_ts is not None else time.time())
    with _LOCK:
        path = _history_path(path_override)
        state = _load_unlocked(path)
        samples = state["samples"]
        last_ts = _LAST_RECORDED_TS or (float(samples[-1]["ts"]) if samples else 0.0)
        if last_ts and (now - last_ts) < min_interval_s:
            return False

        entry = {
            "ts": int(now),
            "cpu_pct": round(float(sample.get("cpu_pct") or 0.0), 1),
            "cpu_temp_c": round(float(sample["cpu_temp_c"]), 1) if sample.get("cpu_temp_c") is not None else None,
            "ram_pct": round(float(sample.get("ram_pct") or 0.0), 1),
            "lan_mbs": round(float(sample.get("lan_mbs") or 0.0), 2),
            "disk_io_mbs": round(float(sample.get("disk_io_mbs") or 0.0), 2),
            "pool_used_gb": round(float(sample["pool_used_gb"]), 2) if sample.get("pool_used_gb") is not None else None,
        }
        cutoff = int(now) - RETENTION_SECONDS
        samples = [s for s in samples if int(s.get("ts") or 0) >= cutoff]
        samples.append(entry)
        if len(samples) > MAX_SAMPLES:
            samples = samples[-MAX_SAMPLES:]

        try:
            _write_atomic_unlocked(path, samples)
        except OSError:
            return False
        state["samples"] = samples
        _LAST_RECORDED_TS = now
        return True


def _downsample(points: list[dict[str, Any]], max_points: int = 96) -> list[dict[str, Any]]:
    if len(points) <= max_points:
        return points
    bucket_size = max(1, (len(points) + max_points - 1) // max_points)
    out: list[dict[str, Any]] = []
    for idx in range(0, len(points), bucket_size):
        chunk = points[idx:idx + bucket_size]
        temps = [float(p["cpu_temp_c"]) for p in chunk if p.get("cpu_temp_c") is not None]
        pools = [float(p["pool_used_gb"]) for p in chunk if p.get("pool_used_gb") is not None]
        out.append({
            "ts": int(chunk[-1]["ts"]),
            "cpu_pct": round(sum(float(p.get("cpu_pct") or 0.0) for p in chunk) / len(chunk), 1),
            "cpu_temp_c": round(sum(temps) / len(temps), 1) if temps else None,
            "ram_pct": round(sum(float(p.get("ram_pct") or 0.0) for p in chunk) / len(chunk), 1),
            "lan_mbs": round(max(float(p.get("lan_mbs") or 0.0) for p in chunk), 2),
            "disk_io_mbs": round(max(float(p.get("disk_io_mbs") or 0.0) for p in chunk), 2),
            "pool_used_gb": round(pools[-1], 2) if pools else None,
        })
    return out


def query_history(
    range_key: str = "24h",
    *,
    now_ts: Optional[float] = None,
    path_override: Optional[str | Path] = None,
) -> dict[str, Any]:
    """Returns downsampled telemetry points and summary statistics for 24h, 7d, or 30d."""
    key = range_key if range_key in RANGE_SECONDS else "24h"
    now = float(now_ts if now_ts is not None else time.time())
    cutoff = int(now) - RANGE_SECONDS[key]
    with _LOCK:
        path = _history_path(path_override)
        samples = [dict(s) for s in _load_unlocked(path)["samples"] if int(s.get("ts") or 0) >= cutoff]

    points = _downsample(samples, max_points=96)
    temps = [float(s["cpu_temp_c"]) for s in samples if s.get("cpu_temp_c") is not None]
    pools = [float(s["pool_used_gb"]) for s in samples if s.get("pool_used_gb") is not None]
    stats = {
        "cpu_avg": round(sum(float(s.get("cpu_pct") or 0.0) for s in samples) / len(samples), 1) if samples else None,
        "cpu_peak": round(max(float(s.get("cpu_pct") or 0.0) for s in samples), 1) if samples else None,
        "temp_avg": round(sum(temps) / len(temps), 1) if temps else None,
        "temp_max": round(max(temps), 1) if temps else None,
        "ram_avg": round(sum(float(s.get("ram_pct") or 0.0) for s in samples) / len(samples), 1) if samples else None,
        "lan_peak_mbs": round(max(float(s.get("lan_mbs") or 0.0) for s in samples), 2) if samples else None,
        "disk_peak_mbs": round(max(float(s.get("disk_io_mbs") or 0.0) for s in samples), 2) if samples else None,
        "pool_delta_gb": round(pools[-1] - pools[0], 2) if len(pools) >= 2 else None,
    }
    return {
        "status": "ok",
        "range": key,
        "raw_samples": len(samples),
        "points": points,
        "stats": stats,
    }


def _host_uptime_hours() -> Optional[float]:
    try:
        proc_uptime = Path("/proc/uptime")
        if proc_uptime.exists():
            secs = float(proc_uptime.read_text(encoding="utf-8").split()[0])
            return round(secs / 3600.0, 1)
    except Exception:
        pass
    return None


def estimate_power_savings(
    *,
    active_idle_watts: Optional[float] = None,
    standby_watts: Optional[float] = None,
) -> dict[str, Any]:
    """Calculates monthly/annual kWh and CO2 savings from the Sleep Guard schedule."""
    installed = sleep_guard.sleep_module_installed()
    perm = sleep_guard.load_permanent_config()
    enabled = bool(perm.get("enabled", True)) and installed
    duration_h = max(0.0, min(24.0, float(perm.get("duration_hours") or 6.0)))
    active_w = float(active_idle_watts if active_idle_watts is not None else getattr(config, "ACTIVE_IDLE_WATTS", 18.0))
    standby_w = float(standby_watts if standby_watts is not None else getattr(config, "SLEEP_STANDBY_WATTS", 1.2))
    delta_w = max(0.0, active_w - standby_w)

    # Monthly energy saved = (watts saved * hours/day * 30 days) / 1000
    hours_asleep_month = round(duration_h * 30.0, 1) if enabled else 0.0
    potential_kwh_month = round((delta_w * duration_h * 30.0) / 1000.0, 2)
    monthly_kwh_saved = potential_kwh_month if enabled else 0.0
    annual_kwh_saved = round(monthly_kwh_saved * 12.0, 1)
    co2_kg_annual = round(annual_kwh_saved * 0.4, 1)  # ~0.4 kg CO2/kWh grid average

    return {
        "installed": installed,
        "enabled": enabled,
        "sleep_time": perm.get("sleep_time", "00:00"),
        "wake_time": perm.get("wake_time", "06:00"),
        "hours_per_day": round(duration_h, 1),
        "hours_asleep_30d": hours_asleep_month,
        "active_idle_watts": round(active_w, 1),
        "standby_watts": round(standby_w, 1),
        "monthly_kwh_saved": monthly_kwh_saved,
        "potential_monthly_kwh_saved": potential_kwh_month,
        "annual_kwh_saved": annual_kwh_saved,
        "co2_kg_annual": co2_kg_annual,
    }


def compute_monthly_insights(
    *,
    now_ts: Optional[float] = None,
    path_override: Optional[str | Path] = None,
) -> dict[str, Any]:
    """Builds the 30-day Monthly Report (uptime, backups, updates, space delta) and power savings."""
    now = float(now_ts if now_ts is not None else time.time())
    hist = query_history("30d", now_ts=now, path_override=path_override)
    raw_samples = hist["raw_samples"]

    # Backups summary from status.json history
    snap = backup_health.read_status(config.BACKUP_STATUS_FILE)
    backup_history = (snap or {}).get("history") or []
    cutoff_iso = datetime.datetime.fromtimestamp(now - 30 * 86400, tz=datetime.timezone.utc).isoformat()
    passed_30d = 0
    failed_30d = 0
    for item in backup_history:
        if not isinstance(item, dict):
            continue
        at = str(item.get("at") or "")
        if at and at < cutoff_iso:
            continue
        if item.get("status") == "ok":
            passed_30d += 1
        elif item.get("status"):
            failed_30d += 1

    # Updates summary from updates_cache + updates_policy
    policy = updates_core.load_policy(Path(config.UPDATES_POLICY_FILE))
    pending_updates = 0
    try:
        cache_path = Path(config.UPDATES_CACHE_FILE)
        if cache_path.exists():
            cdata = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cdata, dict):
                pending_updates = int(cdata.get("pending") or 0)
    except Exception:
        pass

    # Storage 30-day forecast/delta
    forecast: dict[str, Any] = {"ready": False}
    try:
        if config.HDD_DATA and os.path.exists(config.HDD_DATA):
            du = shutil.disk_usage(config.HDD_DATA)
            forecast = storage_sizes.compute_fill_forecast(
                config.STORAGE_HISTORY_FILE,
                config.HDD_DATA,
                du.used,
                du.total,
                now_ts=now,
            )
    except Exception:
        forecast = {"ready": False}
    space_delta_gb = hist["stats"].get("pool_delta_gb")
    if space_delta_gb is None and forecast.get("ready") and forecast.get("daily_delta_gb") is not None:
        space_delta_gb = round(float(forecast["daily_delta_gb"]) * float(forecast.get("window_days") or 30), 1)

    return {
        "status": "ok",
        "generated_at": datetime.datetime.fromtimestamp(now, tz=datetime.timezone.utc).isoformat(timespec="seconds"),
        "monthly_report": {
            "uptime_hours": _host_uptime_hours(),
            "samples_30d": raw_samples,
            "coverage_hours_30d": round((raw_samples * SAMPLE_INTERVAL_S) / 3600.0, 1),
            "backups_passed_30d": passed_30d,
            "backups_failed_30d": failed_30d,
            "pending_updates": pending_updates,
            "auto_patch_enabled": bool(policy.get("auto_patch")),
            "last_auto_summary": policy.get("last_auto_summary"),
            "storage_delta_gb": space_delta_gb,
            "storage_trend": forecast.get("trend") if forecast.get("ready") else None,
        },
        "power_savings": estimate_power_savings(),
    }

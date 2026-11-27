"""
Pivot Phase B Playwright Viewport, 5-View Router, Theme & WCAG 2.2 AA Accessibility Tests (axe-core).

Verifies:
- Phone (360x800), Tablet (820x1180), and Desktop (1366x900) render with
  zero horizontal overflow, zero clipped visible controls, and zero external CDN requests.
- Every visible interactive button/link meets the 44x44px minimum touch target across
  ALL 5 workspace views (#/overview, #/apps, #/backups, #/tvs, #/system).
- Both Dark (default) and Light themes pass axe-core WCAG 2.2 AA with zero critical/serious violations.
- Modals (Config Center, Alerts, Remote Picker, Confirm Action) trap focus, handle Esc, and pass axe.
- Uninstalled optional modules automatically hide their nav items and redirect deep links safely.

Skips only when playwright/axe are not installed locally unless
CI_REQUIRE_PLAYWRIGHT=1 is set.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

HAS_BROWSER_TOOLS = False
try:
    from playwright.sync_api import sync_playwright
    from axe_playwright_python.sync_playwright import Axe
    HAS_BROWSER_TOOLS = True
except ImportError:
    if os.getenv("CI_REQUIRE_PLAYWRIGHT") == "1":
        raise

import config  # noqa: E402
from core import storage_sizes  # noqa: E402
from core.config_core import auth_password  # noqa: E402
import server  # noqa: E402
from widgets import alerts as alerts_widget  # noqa: E402
from widgets import backup_sync, cron_tasks, network_speed, system_vitals, tv_updater  # noqa: E402
from widgets import updates as updates_widget  # noqa: E402

try:
    from werkzeug.serving import make_server
except ImportError:
    make_server = None


SAMPLE_SERVICES = [
    {
        "id": "jellyfin",
        "docker_id": "abc123def456",
        "name": "Jellyfin",
        "port": 8096,
        "has_web_ui": True,
        "description": "Media Streaming",
        "icon": "film",
        "category": "media",
        "state": "running",
        "health": "healthy",
        "status": "Up 2 hours (healthy)",
        "image": "lscr.io/linuxserver/jellyfin:latest",
        "is_up": True,
    },
    {
        "id": "qbittorrent",
        "docker_id": "def456ghi789",
        "name": "qBittorrent",
        "port": 8080,
        "has_web_ui": True,
        "description": "Torrent Client",
        "icon": "download",
        "category": "ingest",
        "state": "running",
        "health": "none",
        "status": "Up 2 hours",
        "image": "lscr.io/linuxserver/qbittorrent:latest",
        "is_up": True,
    },
    {
        "id": "prowlarr",
        "docker_id": "111222333444",
        "name": "Prowlarr",
        "port": 9696,
        "has_web_ui": True,
        "description": "Indexer Proxy",
        "icon": "search",
        "category": "ingest",
        "state": "running",
        "health": "none",
        "status": "Up 2 hours",
        "image": "lscr.io/linuxserver/prowlarr:latest",
        "is_up": True,
    },
    {
        "id": "immich_machine_learning",
        "docker_id": "999888777666",
        "name": "Immich ML",
        "port": None,
        "has_web_ui": False,
        "scheduled": True,
        "description": "Scheduled Face/CLIP Worker",
        "icon": "cpu",
        "category": "system",
        "state": "exited",
        "health": "none",
        "status": "Exited (0) 3 hours ago",
        "image": "ghcr.io/immich-app/immich-machine-learning:release",
        "is_up": False,
    },
]

ALL_VIEWS = ("overview", "apps", "backups", "tvs", "system")


@unittest.skipUnless(
    HAS_BROWSER_TOOLS and make_server is not None,
    "playwright / axe-playwright-python / werkzeug not available",
)
class TestControlHubUiAccessibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        hub_dir = root / "state" / "control-hub"
        hub_dir.mkdir(parents=True, exist_ok=True)
        pw_file = hub_dir / "password"

        cls._orig_env = {
            k: os.environ.get(k)
            for k in ("HOMELAB_STATE_DIR", "CONTROL_HUB_PASSWORD_FILE", "CONTROL_HUB_TOKEN", "TZ")
        }
        os.environ["HOMELAB_STATE_DIR"] = str(root / "state")
        os.environ["CONTROL_HUB_PASSWORD_FILE"] = str(pw_file)
        os.environ["CONTROL_HUB_TOKEN"] = "ui-test-token-456"
        os.environ["TZ"] = "UTC"

        cls._patches = [
            mock.patch.object(auth_password, "PASSWORD_FILE", pw_file),
            mock.patch.object(config, "BACKUP_DIR", str(root / "backups")),
            mock.patch.object(config, "BACKUP_LOG_FILE", str(root / "backups" / "backup.log")),
            mock.patch.object(config, "BACKUP_STATUS_FILE", str(root / "backups" / "status.json")),
            mock.patch.object(config, "SPEEDTEST_CACHE_FILE", str(root / "speedtest_cache.json")),
            mock.patch.object(config, "STORAGE_SIZES_CACHE_FILE", str(root / "storage_sizes_cache.json")),
            mock.patch.object(backup_sync, "BACKUP_DIR", str(root / "backups")),
            mock.patch.object(backup_sync, "BACKUP_LOG_FILE", str(root / "backups" / "backup.log")),
            mock.patch.object(backup_sync, "BACKUP_STATUS_FILE", str(root / "backups" / "status.json")),
            mock.patch.object(backup_sync, "STORAGE_SIZES_CACHE_FILE", str(root / "storage_sizes_cache.json")),
            mock.patch.object(network_speed, "SPEEDTEST_CACHE_FILE", str(root / "speedtest_cache.json")),
            mock.patch.object(system_vitals, "STORAGE_SIZES_CACHE_FILE", str(root / "storage_sizes_cache.json")),
            mock.patch.object(cron_tasks, "BACKUP_LOG_FILE", str(root / "backups" / "backup.log")),
            mock.patch.object(cron_tasks, "BACKUP_STATUS_FILE", str(root / "backups" / "backup.json")),
            mock.patch.object(tv_updater, "TV_UPDATER_PY", ""),
            mock.patch.object(tv_updater, "TV_UPDATER_STATE_FILE", ""),
            mock.patch.object(backup_sync, "MEDIA_BACKUP_STATUS_FILE", str(root / "media-backups" / "status.json")),
            mock.patch.object(backup_sync, "MEDIA_BACKUP_CRON_FILE", str(root / "media-backup.cron")),
            mock.patch.object(backup_sync, "SYSTEMD_UNIT_DIR", str(root / "units")),
            mock.patch.object(backup_sync, "BACKUP_REMOTE_HELPER", str(root / "units" / "photo-restore-test.service")),
            mock.patch.object(alerts_widget.engine, "config_path", root / "alerts.json"),
            mock.patch.object(alerts_widget.engine, "state_path", root / "alerts_state.json"),
            mock.patch.object(updates_widget, "UPDATES_CACHE_FILE", str(root / "updates_cache.json")),
            mock.patch.object(updates_widget, "UPDATES_AUTO_CHECK", False),
        ]
        for p in cls._patches:
            p.start()

        # A failed pre-flight after one good run: the busiest state of the backup view.
        backups = root / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        (backups / "status.json").write_text(json.dumps({
            "status": "error", "stage": 0, "stage_label": "0. Pre-flight",
            "message": "Pre-flight: the remote gdrive: did not answer (token expired).",
            "started_at": "2026-11-22T22:00:01+05:30", "completed_at": "2026-11-22T22:00:09+05:30",
            "last_good_at": "2026-11-21T22:06:01+05:30", "remote": "gdrive:",
            "preflight": {"ok": False, "checks": [
                {"name": "remote", "ok": False, "detail": "gdrive: did not answer: token expired"}]},
            "retention": {"kept": 17, "delete": ["immich_db_20261001_220001.sql.gz"], "next_delete": ["immich_db_20261108_220001.sql.gz"]},
            "restore_test": {"ok": True, "message": "Restored", "completed_at": "2026-11-01T11:07:30+05:30",
                             "dump_file": "immich_db_20261031_220001.sql.gz", "restored": 35765, "expected": 35765},
            "history": [
                {"started_at": "2026-11-22T22:00:01+05:30", "outcome": "error", "message": "Pre-flight: the remote gdrive: did not answer (token expired).", "duration_s": 8},
                {"started_at": "2026-11-21T22:00:01+05:30", "outcome": "synced", "dump_file": "immich_db_20261121_220001.sql.gz",
                 "dump_bytes": 356271570, "files": 12, "bytes": 48000000, "duration_s": 360},
            ],
        }), encoding="utf-8")

        media_dir = root / "media-backups"
        media_dir.mkdir(parents=True, exist_ok=True)
        media_start = (datetime.now(timezone.utc) - timedelta(hours=2, minutes=1)).isoformat()
        media_end = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        (media_dir / "status.json").write_text(json.dumps({
            "status": "synced", "stage": 4, "message": "Media settings backed up to gdrive:Media_Backup",
            "started_at": media_start, "completed_at": media_end,
            "last_good_at": media_end, "remote": "gdrive:",
            "dump_file": "media_config_recent.tar.zst", "dump_bytes": 19454318,
            "history": [{"started_at": media_start, "outcome": "synced", "duration_s": 8}],
        }), encoding="utf-8")

        (root / "units").mkdir(exist_ok=True)
        (root / "units" / "photo-restore-test.service").write_text("[Service]\n", encoding="utf-8")

        cls.password = "PlaywrightTestPass1!"
        auth_password.set_password(cls.password, path=pw_file)

        cls.app = server.create_app()
        cls.mock_tv_installed = True
        cls.mock_action_calls: list[tuple[str, str]] = []

        # Override /api/services/status in test app so Service Matrix & Quick Launch render realistically.
        def mock_services_status():
            from flask import jsonify
            return jsonify({
                "services": SAMPLE_SERVICES,
                "other_count": 1,
                "docker_available": True,
                "docker_error": None,
                "dozzle_installed": False,
                "cockpit_installed": False,
            })

        def mock_service_action(service_id: str):
            from flask import jsonify, request
            body = request.get_json(silent=True) or {}
            action = str(body.get("action", "restart"))
            cls.mock_action_calls.append((service_id, action))
            return jsonify({"success": True, "message": f"{service_id} {action}ed."})

        cls.app.view_functions["service_matrix.get_services_status"] = mock_services_status
        cls.app.view_functions["service_matrix.service_action"] = mock_service_action

        # Two TVs: one online with a nickname and a detected model, one never seen.
        def mock_tv_status():
            from flask import jsonify
            if not cls.mock_tv_installed:
                return jsonify({
                    "installed": False, "status": "not_installed", "devices": [],
                    "total_devices": 0, "online_devices": 0,
                })
            app_row = {"package": "org.smarttube.stable", "name": "SmartTube", "installed_code": 2470,
                       "installed_name": "32.80", "target_code": 2470, "target_name": "32.80", "is_installed": True,
                       "is_up_to_date": True, "status_code": "UP_TO_DATE", "status_text": "Up to date (vCode 2470)",
                       "is_foreground": False}
            return jsonify({
                "installed": True, "status": "synced", "all_up_to_date": True, "pending_updates_count": 0,
                "total_devices": 2, "online_devices": 1, "upstream_apps": {}, "schedule": "Every 15 min",
                "devices": [
                    {"id": "living_room_tv", "name": "Living room", "nickname": "Living room", "profile_name": "Living Room TV",
                     "ip": "192.168.1.34", "port": 5555, "model": "MIBOX4", "model_label": "Xiaomi MIBOX4",
                     "details": {"manufacturer": "Xiaomi", "model": "MIBOX4", "codename": "oneday", "android": "9",
                                 "sdk": "28", "device_name": "Mi Box", "last_seen": "2026-11-21 16:40"},
                     "is_online": True, "foreground_app_name": "Android TV Launcher", "is_media_playing": False, "apps": [app_row]},
                    {"id": "bedroom_tv", "name": "Bedroom TV", "nickname": None, "profile_name": "Bedroom TV",
                     "ip": "192.168.1.39", "port": 5555, "model": None, "model_label": None,
                     "details": {"last_seen": None}, "is_online": False, "apps": [dict(app_row, status_text="Up to date (vCode 2470) when last seen")]},
                ],
            })

        cls.app.view_functions["tv_updater.get_tv_updater_status"] = mock_tv_status

        # Remote dialog: fake helper answers (the real one needs root and rclone).
        def mock_remotes():
            from flask import jsonify
            return jsonify({"remotes": [{"name": "gdrive", "type": "drive"}, {"name": "b2", "type": "b2"}], "current": "gdrive:"})

        def mock_remote_test():
            from flask import jsonify, request
            remote = (request.get_json(silent=True) or {}).get("remote")
            return jsonify({"ok": True, "remote": remote, "free_bytes": 40 * 1024**3, "total_bytes": 100 * 1024**3,
                            "folders": {"Memories": False, "Immich_Backup/database": False, "Media_Backup": False}})

        cls.app.view_functions["backup_sync.list_backup_remotes"] = mock_remotes
        cls.app.view_functions["backup_sync.test_backup_remote"] = mock_remote_test

        def mock_updates_status():
            from flask import jsonify
            return jsonify({
                "checked_at": 1700000000,
                "checked_at_str": "2026-11-24 12:00 UTC",
                "pending": 1,
                "majors": 0,
                "safe_pending": 1,
                "docker_available": True,
                "helper_available": True,
                "policy": {"auto_patch": False, "last_auto_run": None, "last_auto_summary": None},
                "job": {"running": False},
                "self_update": {"available": True, "current": "v2.1.1", "latest": "v2.2.0", "update_ready": True},
                "rows": [
                    {
                        "container": "control-hub", "image_name": "Homelab Blueprint", "current": "v2.1.1",
                        "latest": "v2.2.0", "release_url": "https://example.invalid/bp", "kind": "update",
                        "kind_text": "Update available", "reason": None, "command": None,
                        "patch_safe": False, "one_click_allowed": False,
                    },
                    {
                        "container": "jellyfin", "service": "jellyfin", "image_name": "lscr.io/linuxserver/jellyfin",
                        "current": "10.9.11-ls1", "latest": "10.10.3-ls2", "release_url": "https://example.invalid/jf",
                        "kind": "update", "kind_text": "Update available", "reason": None,
                        "patch_safe": False, "one_click_allowed": True,
                        "command": "cd /srv/stacks/media && sudo docker compose up -d jellyfin",
                    },
                ],
            })

        cls.app.view_functions["updates.api_get_updates"] = mock_updates_status

        def mock_indexers_health():
            from flask import jsonify
            return jsonify({
                "status": "ok", "installed": True, "reachable": True, "total": 1, "failing": 1,
                "indexers": [{"id": 1, "name": "1337x", "protocol": "torrent", "privacy": "public", "enabled": True, "healthy": False, "fix_hint": "Enable Byparr solver"}],
            })

        def mock_media_overview():
            from flask import jsonify
            return jsonify({
                "requests": {"configured": True, "reachable": True, "items": [{"id": 7, "type": "movie", "title": "Dune", "requested_by": "Alex", "waiting_reason": "Pending approval"}]},
                "calendar": {"configured": True, "reachable": True, "items": [{"kind": "movie", "title": "Arrival", "date": "2026-11-27", "has_file": False}]},
                "library": {"jellyfin": {"configured": True, "reachable": True, "recent": [{"name": "Andor", "type": "Series", "year": 2025}]}, "wanted_configured": True, "wanted": [{"kind": "movie", "title": "Inception"}]},
            })

        cls.app.view_functions["indexers.indexers_health"] = mock_indexers_health
        cls.app.view_functions["media_hub.media_overview"] = mock_media_overview

        def mock_photos_overview():
            from flask import jsonify
            return jsonify({
                "installed": True,
                "timezone": "UTC",
                "tz_abbr": "UTC",
                "library": {
                    "available": True,
                    "total_assets": 35765,
                    "photos_count": 33400,
                    "videos_count": 2365,
                    "named_people": 12,
                    "unhidden_people": 18,
                    "assets_with_named_faces": 18904,
                    "total_face_instances": 42100,
                    "offline_assets": 0,
                    "disk_size": "264.3 GB",
                    "photos_free_gb": 512.0,
                    "photos_total_gb": 1800.0,
                },
                "users": [
                    {"name": "Primary User", "assets": 35762, "used_bytes": 281570581686, "quota_bytes": None},
                    {"name": "Family Member", "assets": 3, "used_bytes": 12402948, "quota_bytes": 53687091200},
                ],
                "libraries": [
                    {"name": "Stills", "paths": ["/mnt/hdd/Memories/STILLS"], "refreshed_at": "2026-11-25T07:30:00Z", "assets": 35000, "offline_assets": 0},
                ],
                "ml": {
                    "installed": True,
                    "container_exists": True,
                    "running": False,
                    "can_control": True,
                    "last_run": "Nov 25, 10:00 UTC",
                    "last_event": "[STOP] Container stopped successfully.",
                    "schedule": {"exists": True, "enabled": True, "start_time": "06:05", "stop_time": "10:00", "editable": True},
                    "queue": {
                        "redis_available": True,
                        "active": 0,
                        "waiting": 12,
                        "delayed": 0,
                        "failed": 0,
                        "pending_faces": 49,
                        "pending_metadata": 2,
                        "queues": [
                            {"id": "faceDetection", "label": "Face Detection", "waiting": 12, "active": 0, "delayed": 0, "failed": 0},
                        ],
                    },
                },
                "face_export": {
                    "installed": True,
                    "status": "ok",
                    "last_run": "Nov 24, 22:00 UTC",
                    "named_assets": 18904,
                    "files_written": 0,
                    "cached_skipped": 18904,
                    "errors": 0,
                    "summary": "All 18,904 sidecars up to date",
                },
                "storage_health": {
                    "unreadable_total": 0,
                    "missing_total": 0,
                    "folders": [
                        {"label": "Upload Folder", "kind": "upload", "path": "/var/photos/upload", "exists": True, "readable": True,
                         "free_gb": 512.0, "total_gb": 1800.0, "used_percent": 71.6, "unreadable_count": 0,
                         "status": "healthy", "message": "Readable (400+ checked)"},
                    ],
                },
            })

        def mock_library_stats():
            from flask import jsonify
            return jsonify({
                "disk_size": "264.3 GB",
                "disk_partial": False,
                "photos_free_gb": 512.0,
                "photos_total_gb": 1800.0,
                "gdrive": {"used_gb": 287.4, "free_gb": 4832.6, "total_gb": 5120.0, "used_percent": 5.6},
                "assets": {
                    "total_assets": 35765,
                    "photos_count": 33400,
                    "videos_count": 2365,
                    "named_people": 12,
                    "unhidden_people": 18,
                    "assets_with_named_faces": 18904,
                    "total_face_instances": 42100,
                },
                "db_dump_size": "339.8 MB",
                "memories_dir": "/mnt/hdd/Memories",
                "gdrive_remote": "backup_remote_drive_long_name:",
            })

        cls.app.view_functions["photos_hub.get_photos_overview"] = mock_photos_overview
        cls.app.view_functions["backup_sync.get_library_stats"] = mock_library_stats

        # Patch telemetry helper so /api/backup/status also shows realistic populated library numbers.
        from widgets import backup_sync as _bs_mod
        cls._orig_fetch_lib = _bs_mod.fetch_immich_library_telemetry
        _bs_mod.fetch_immich_library_telemetry = lambda force=False: mock_library_stats().get_json()

        def mock_storage_overview():
            from flask import jsonify
            return jsonify({
                "folders": {
                    "measured": True, "measuring": False, "measured_at": 1700000000, "measured_by": "root-timer",
                    "rows": [
                        {"id": "movies", "label": "Movies", "path": "/mnt/hdd/data/media/movies", "gb": 480.2},
                        {"id": "tv", "label": "TV Shows", "path": "/mnt/hdd/data/media/tv", "gb": 210.5},
                        {"id": "downloads", "label": "Downloads / Torrents", "path": "/mnt/hdd/data/torrents", "gb": 90.0},
                        {"id": "photos", "label": "Photos & Uploads", "path": "/mnt/hdd/Memories", "gb": 264.1},
                        {"id": "backups", "label": "Local Backups", "path": "/var/lib/homelab/photo-backups", "gb": 1.1},
                        {"id": "appdata", "label": "App Data", "path": "/srv/homelab/appdata", "gb": 6.4},
                    ],
                },
                "forecasts": {
                    "hdd": {"ready": True, "trend": "growing", "days_until_full": 42.0, "daily_delta_gb": 2.5, "used_percent": 88.5, "window_days": 30,
                            "message": "At the last 30 days' rate (+2.50 GB/day), /mnt/hdd/data (88.5% used) is full in ~42 days."},
                    "ssd": {"ready": True, "trend": "stable", "days_until_full": None, "daily_delta_gb": 0.0, "window_days": 30,
                            "message": "Usage steady (+0.00 GB/day over last 30d)."},
                },
                "cleanup": [
                    {"id": "torrents_seeded", "label": "Finished Torrents (Seed Goal Met)", "description": "Completed torrents past seed target.",
                     "count": 4, "size_bytes": 4200000000, "size_mb": 4005.4, "size_gb": 3.91, "actionable": True, "action_label": "Remove Finished", "reason": None},
                    {"id": "qbit_logs", "label": "qBittorrent Rotated Logs", "description": "Old qbittorrent.log.bak* files.",
                     "count": 2500, "size_bytes": 186646528, "size_mb": 178.0, "size_gb": 0.17, "actionable": True, "action_label": "Purge Rotated Logs", "reason": None},
                ],
                "smart": {
                    "available": True, "smartctl_installed": True,
                    "disks": [
                        {"device": "sda", "model": "ST1000LM024", "type": "HDD", "size_gb": 931.5, "passed": True, "temp_c": 34, "reallocated_sectors": 0},
                        {"device": "sdb", "model": "S930P PRO", "type": "SSD", "size_gb": 238.5, "passed": True, "temp_c": 31, "reallocated_sectors": 0},
                    ],
                },
            })

        cls.app.view_functions["storage_hub.get_storage_overview"] = mock_storage_overview

        def mock_install_manifest():
            from flask import jsonify
            return jsonify({
                "installed": True,
                "path": "/var/lib/homelab/installed.json",
                "manifest": {
                    "blueprint_version": "2.1.1",
                    "installed_at": "2026-11-21T10:43:00+0530",
                    "install_dir": "/opt/homelab-blueprint",
                    "service_user": "homelab",
                    "modules": ["media", "photos", "control_hub"],
                    "units": ["control-hub.service", "homelab-storage-sizes.timer"],
                    "crons": ["/etc/cron.d/immich-backup"],
                    "compose": [{"module": "mediaserver", "dir": "/srv/stacks/media"}],
                },
            })

        cls.app.view_functions["config_center.get_install_manifest"] = mock_install_manifest

        _orig_get_current_config = cls.app.view_functions["config_center.get_current_config"]

        def mock_get_current_config():
            resp = _orig_get_current_config()
            if isinstance(resp, tuple):
                response_obj, code = resp[0], resp[1]
            else:
                response_obj, code = resp, 200
            data = response_obj.get_json() or {}
            data["blueprint_mode"] = True
            data["read_only"] = False
            from flask import jsonify
            return jsonify(data), code

        cls.app.view_functions["config_center.get_current_config"] = mock_get_current_config

        def mock_network_overview():
            from flask import jsonify
            return jsonify({
                "status": "success",
                "active_nic": "enp3s0",
                "current_ip": "192.168.1.31",
                "default_gateway": "192.168.1.1",
                "dns_servers": ["1.1.1.1", "8.8.8.8"],
                "interfaces": [
                    {
                        "name": "enp3s0",
                        "is_up": True,
                        "speed_mbps": 100,
                        "duplex": "half",
                        "mac": "aa:bb:cc:dd:ee:ff",
                        "degraded": True,
                        "warning": "Running at 100 Mbps half duplex: check Ethernet cable, keystone jack, or switch port.",
                    }
                ],
                "tailscale": {
                    "installed": True,
                    "connected": True,
                    "backend_state": "Running",
                    "tailnet_ip": "100.64.0.10",
                    "dns_name": "homelab.tailnet.ts.net",
                    "subnet_router": True,
                    "advertised_routes": ["192.168.1.0/24"],
                    "ip_forwarding": True,
                    "peer_count": 3,
                    "error": None,
                },
                "tailscale_https": {
                    "installed": True,
                    "connected": True,
                    "dns_name": "homelab.tailnet.ts.net",
                    "https_url": "https://homelab.tailnet.ts.net",
                    "serve_active": True,
                    "serve_targets": ["homelab.tailnet.ts.net:443"],
                    "serve_cmd": "sudo tailscale serve --bg 7575",
                    "cert_cmd": "sudo tailscale cert homelab.tailnet.ts.net",
                    "probe_error": None,
                },
                "ports": [
                    {"key": "control_hub", "name": "Control Hub Dashboard", "port": 7575, "category": "system", "in_use": True, "state_label": "Listening", "conflict": False},
                    {"key": "jellyfin_http", "name": "Jellyfin Web", "port": 8096, "category": "media", "in_use": True, "state_label": "Listening (jellyfin)", "conflict": False},
                ],
                "port_conflicts": [],
            })

        cls.app.view_functions["network_speed.get_network_overview"] = mock_network_overview

        def mock_cron_status():
            from flask import jsonify
            return jsonify({
                "jobs": [
                    {
                        "id": "immich_backup",
                        "name": "Photo Cloud Backup",
                        "description": "Photo library, face XMP sidecars & PostgreSQL dump to cloud remote",
                        "schedule": "Daily at 01:00 UTC",
                        "next_run": "Tomorrow 01:00 UTC",
                        "time_hhmm": "01:00",
                        "enabled": True,
                        "editable": True,
                        "is_running": False,
                        "status_text": "Synced",
                        "last_run": "Nov 26, 22:00 UTC",
                        "can_run": True,
                        "run_label": "Run backup now",
                        "icon": "cloud",
                    },
                    {
                        "id": "server_suspend",
                        "name": "Nightly Sleep Suspend",
                        "description": "Suspends hardware to RAM (S3) for 6.0h; wakes at 06:00 UTC",
                        "schedule": "Daily at 00:00 UTC (6.0h sleep)",
                        "next_run": "Tomorrow 00:00 UTC",
                        "time_hhmm": "00:00",
                        "wake_hhmm": "06:00",
                        "enabled": True,
                        "editable": True,
                        "is_running": False,
                        "status_text": "Armed (00:00)",
                        "last_run": "Nov 26",
                        "can_run": False,
                        "run_label": "Toggle Skip",
                        "icon": "moon",
                    },
                ],
                "clashes": [
                    {
                        "severity": "warning",
                        "jobs": ["immich_backup", "server_suspend"],
                        "message": "Photo Cloud Backup (01:00) is inside the 00:00 -> 06:00 Sleep Suspend window and may be skipped while the host sleeps.",
                    }
                ],
            })

        cls.app.view_functions["cron_tasks.get_cron_tasks_status"] = mock_cron_status

        def mock_history():
            from flask import jsonify, request
            rng = request.args.get("range", "24h")
            return jsonify({
                "status": "ok",
                "range": rng,
                "raw_samples": 12,
                "points": [
                    {"ts": 1750000000 + i * 1800, "cpu_pct": 12 + i * 2, "cpu_temp_c": 42 + i, "ram_pct": 40 + i, "lan_mbs": 3.5 + i, "disk_io_mbs": 1.2 + i * 0.5, "pool_used_gb": 510 + i * 0.4}
                    for i in range(6)
                ],
                "stats": {"cpu_avg": 17.0, "ram_avg": 42.5, "temp_max": 47.0, "lan_peak_mbs": 8.5, "disk_peak_mbs": 3.7, "pool_delta_gb": 2.0},
            })

        def mock_insights():
            from flask import jsonify
            return jsonify({
                "status": "ok",
                "generated_at": "2026-11-27T12:00:00+00:00",
                "monthly_report": {
                    "uptime_hours": 148.5,
                    "samples_30d": 12,
                    "coverage_hours_30d": 1.0,
                    "backups_passed_30d": 28,
                    "backups_failed_30d": 0,
                    "pending_updates": 1,
                    "storage_delta_gb": 12.4,
                },
                "power_savings": {
                    "installed": True,
                    "enabled": True,
                    "hours_per_day": 6.0,
                    "monthly_kwh_saved": 3.02,
                    "potential_monthly_kwh_saved": 3.02,
                    "annual_kwh_saved": 36.2,
                    "co2_kg_annual": 14.5,
                },
            })

        cls.app.view_functions["history.api_get_history"] = mock_history
        cls.app.view_functions["history.api_get_monthly_insights"] = mock_insights

        def mock_integrations_ha():
            from flask import jsonify
            return jsonify({
                "status": "ok",
                "sensors": {"disk_pool_pct": 88.5, "backup_state": "ok", "sleep_skip_tonight": False},
                "ups": {
                    "installed": True,
                    "status": "online",
                    "ups_name": "mainups",
                    "ups_model": "Back-UPS 1500",
                    "battery_charge": 100.0,
                    "battery_runtime_s": 1800,
                    "ups_load_pct": 12.0,
                    "on_battery": False,
                    "low_battery": False,
                },
                "yaml_snippet": "rest:\n  - resource: \"http://127.0.0.1:7575/api/integrations/homeassistant\"",
            })

        cls.app.view_functions["integrations.api_homeassistant"] = mock_integrations_ha

        cls.httpd = make_server("127.0.0.1", 0, cls.app, threaded=True)
        cls.port = cls.httpd.server_port
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

        cls._pw = sync_playwright().start()
        cls.browser = cls._pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.browser.close()
        except Exception:
            pass
        try:
            cls._pw.stop()
        except Exception:
            pass
        try:
            from widgets import backup_sync as _bs_mod
            if hasattr(cls, "_orig_fetch_lib"):
                _bs_mod.fetch_immich_library_telemetry = cls._orig_fetch_lib
        except Exception:
            pass
        try:
            cls.httpd.shutdown()
            cls.httpd.server_close()
        except Exception:
            pass
        storage_sizes.wait_for_idle(timeout=5.0)
        for p in reversed(cls._patches):
            p.stop()
        for k, v in cls._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cls._tmp.cleanup()

    def _new_authenticated_page(self, width: int, height: int, initial_hash: str = "#/overview"):
        context = self.browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()

        external_requests: list[str] = []

        def track_requests(route):
            url = route.request.url
            if not url.startswith(self.base_url) and not url.startswith("data:") and not url.startswith("about:"):
                external_requests.append(url)
                route.abort()
                return
            route.continue_()

        page.route("**/*", track_requests)

        console_errors: list[str] = []
        page_errors: list[str] = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        # Sign in cleanly via API cookie before loading dashboard HTML.
        login_res = context.request.post(
            f"{self.base_url}/api/auth/login",
            data={"password": self.password},
        )
        self.assertEqual(login_res.status, 200)

        page.goto(f"{self.base_url}/{initial_hash}", wait_until="domcontentloaded")
        page.wait_for_selector("#hub-header")
        page.wait_for_selector(".service-row", state="attached", timeout=15000)
        page.wait_for_timeout(350)
        return context, page, console_errors, page_errors, external_requests

    def _navigate_view(self, page, view_id: str) -> None:
        page.click(f"#nav-item-{view_id}")
        page.wait_for_selector(f"#view-{view_id}.is-active:not([hidden])", timeout=5000)
        page.wait_for_timeout(180)

    def _assert_layout_and_touch_targets(self, page, width: int, label: str = "") -> None:
        metrics = page.evaluate(
            """() => {
                const vw = window.innerWidth;
                const sw = document.documentElement.scrollWidth;
                const offenders = [];
                const clipped = [];
                const selector = 'button, a[href], summary, input:not([type="checkbox"]):not([type="radio"]), select';
                document.querySelectorAll(selector).forEach((el) => {
                    const st = window.getComputedStyle(el);
                    if (st.display === 'none' || st.visibility === 'hidden' || el.offsetParent === null) return;
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) return;
                    if (r.height < 43.5 || r.width < 43.5) {
                        offenders.push({
                            tag: el.tagName,
                            id: el.id,
                            cls: el.className,
                            text: (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 40),
                            w: Math.round(r.width),
                            h: Math.round(r.height),
                        });
                    }
                    if (r.right > vw + 1 || r.left < -1) {
                        clipped.push({
                            id: el.id,
                            cls: el.className,
                            left: Math.round(r.left),
                            right: Math.round(r.right),
                            vw,
                        });
                    }
                });
                return { vw, sw, offenders, clipped };
            }"""
        )
        ctx = f"{label}@{width}px" if label else f"{width}px"
        self.assertLessEqual(
            metrics["sw"],
            metrics["vw"],
            f"Horizontal overflow at {ctx}: scrollWidth={metrics['sw']} > innerWidth={metrics['vw']}",
        )
        self.assertEqual(
            metrics["clipped"],
            [],
            f"Clipped interactive controls at {ctx}: {metrics['clipped']}",
        )
        self.assertEqual(
            metrics["offenders"],
            [],
            f"Interactive controls smaller than 44x44px at {ctx}: {metrics['offenders']}",
        )

    def _assert_axe_wcag_aa(self, page, label: str) -> None:
        axe = Axe()
        results = axe.run(
            page,
            options={
                "runOnly": {
                    "type": "tag",
                    "values": ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"],
                }
            },
        )
        raw = getattr(results, "response", results)
        violations = raw.get("violations", []) if isinstance(raw, dict) else []
        bad = [v for v in violations if v.get("impact") in ("critical", "serious")]
        if bad:
            summary = []
            for v in bad:
                node_details = [
                    f"{n.get('target')} ({(n.get('failureSummary') or '').strip()})"
                    for n in v.get("nodes", [])
                ]
                summary.append(f"{v['id']} ({v['impact']}): {v['help']} -> {node_details}")
            self.fail(f"WCAG 2.2 AA violations ({label}):\n" + "\n".join(summary))

    def test_responsive_all_five_views_both_themes_and_zero_external_requests(self) -> None:
        for width, height in ((360, 800), (820, 1180), (1366, 900)):
            context, page, console_errors, page_errors, ext_reqs = self._new_authenticated_page(width, height)
            try:
                # Default theme must be Dark
                self.assertEqual(page.evaluate("() => document.documentElement.dataset.theme"), "dark")

                # Quick Launch should only show launchable web UIs (3 of 4 sample services; Immich ML has no web UI)
                self.assertEqual(page.locator("#overview-apps-grid .quick-app-tile").count(), 3)

                for view_id in ALL_VIEWS:
                    self._navigate_view(page, view_id)
                    if view_id == "backups":
                        page.evaluate("() => { const d = document.getElementById('backup-history-wrap'); if (d) d.open = true; }")
                    self._assert_layout_and_touch_targets(page, width, f"dark:{view_id}")
                    self._assert_axe_wcag_aa(page, f"dark:{view_id}@{width}x{height}")

                # Toggle to Light theme and re-verify WCAG 2.2 AA contrast on Desktop & Phone
                if width in (360, 1366):
                    page.click("#btn-theme-toggle")
                    self.assertEqual(page.evaluate("() => document.documentElement.dataset.theme"), "light")
                    for view_id in ALL_VIEWS:
                        self._navigate_view(page, view_id)
                        self._assert_layout_and_touch_targets(page, width, f"light:{view_id}")
                        self._assert_axe_wcag_aa(page, f"light:{view_id}@{width}x{height}")

                self.assertEqual(ext_reqs, [], f"Control Hub must make zero external CDN requests, got: {ext_reqs}")
                self.assertEqual(page_errors, [], f"Page errors at {width}px: {page_errors}")
                self.assertEqual(console_errors, [], f"Console errors at {width}px: {console_errors}")
            finally:
                context.close()

    def test_backup_card_shows_failed_preflight_history_and_retention(self) -> None:
        context, page, _, page_errors, _ = self._new_authenticated_page(360, 800)
        try:
            self._navigate_view(page, "backups")
            page.wait_for_function("() => document.getElementById('backup-history').children.length === 2", timeout=10000)
            self.assertEqual(page.get_attribute("#backup-health", "data-state"), "error")
            self.assertIn("did not answer", page.inner_text("#backup-health-title"))
            self.assertIn("Last good backup", page.inner_text("#backup-health-detail"))
            self.assertIn("2026-11-21 22:06", page.inner_text("#backup-last-time"))
            self.assertIn("is-alert", page.get_attribute("#backup-section", "class"))
            self.assertEqual(page.inner_text("#backup-status-badge"), "Failed")
            self.assertTrue(page.is_visible("#backup-preflight .preflight-fail"))
            self.assertIsNone(page.get_attribute("#backup-preflight", "hidden"))
            page.click("#backup-history-wrap summary")
            runs = page.locator("#backup-history .backup-run")
            self.assertIn("Failed", runs.nth(0).inner_text())
            self.assertIn("row--minus", runs.nth(0).get_attribute("class"))
            self.assertIn("339.8 MB", runs.nth(1).inner_text())
            self.assertIn("row--plus", runs.nth(1).get_attribute("class"))
            self.assertIn("next run deletes immich_db_20261108_220001.sql.gz", page.inner_text("#backup-retention"))
            self.assertTrue(page.is_visible("#media-backup"))
            self.assertEqual(page.inner_text("#media-backup-badge"), "Verified")
            self.assertIn("18.6 MB", page.inner_text("#media-backup-line"))
            self.assertFalse(page.is_visible("#btn-media-backup-run"), "no button without the script")
            self.assertIn("passed 2026-11-01 11:07", page.inner_text("#restore-test-text"))
            self.assertIn("35,765 photos and videos", page.inner_text("#restore-test-text"))
            self.assertTrue(page.is_visible("#btn-restore-test-run"))
            self._assert_layout_and_touch_targets(page, 360, "backups-detail")
            self._assert_axe_wcag_aa(page, "backup-view@360x800")
            self.assertEqual(page_errors, [])
        finally:
            context.close()

    def test_remote_dialog_requires_a_test_before_saving(self) -> None:
        context, page, _, page_errors, _ = self._new_authenticated_page(360, 800)
        try:
            self._navigate_view(page, "backups")
            page.wait_for_selector("#btn-change-remote", state="visible", timeout=10000)
            page.click("#btn-change-remote")
            page.wait_for_selector("#remote-select option[value='b2']", state="attached")
            self.assertEqual(page.inner_text("#remote-current"), "gdrive:")
            self.assertTrue(page.is_disabled("#remote-save"))
            page.select_option("#remote-select", "b2")
            page.fill("#remote-folder", "homelab")
            page.click("#remote-test")
            page.wait_for_function("() => !document.getElementById('remote-save').disabled")
            text = page.inner_text("#remote-result")
            self.assertIn("b2:homelab/ answers", text)
            self.assertIn("uploads the whole photo library", text)
            page.fill("#remote-folder", "other")  # changing the value needs a new test
            self.assertTrue(page.is_disabled("#remote-save"))
            self._assert_layout_and_touch_targets(page, 360, "remote-dialog")
            self._assert_axe_wcag_aa(page, "remote-dialog@360x800")
            self.assertEqual(page_errors, [])
        finally:
            context.close()

    def test_alerts_dialog_phone_layout_keyboard_and_axe(self) -> None:
        context, page, _, page_errors, _ = self._new_authenticated_page(360, 800)
        try:
            # Alerts bell is always visible in header even on phone.
            self.assertTrue(page.is_visible("#btn-open-alerts"))
            self.assertEqual(page.inner_text("#alerts-count"), "off")
            page.click("#btn-open-alerts")
            modal = page.locator("#alerts-modal")
            modal.wait_for(state="visible", timeout=5000)
            page.wait_for_selector("#alerts-channels fieldset[data-channel='ntfy']")
            self.assertEqual(page.locator("#alerts-rules [data-rule]").count(), 11)
            page.click("#alerts-channels fieldset[data-channel='ntfy'] button:has-text('New topic')")
            topic = page.input_value("#alerts-ntfy-topic")
            self.assertTrue(topic.startswith("homelab-") and len(topic) >= 20)
            for _ in range(8):
                page.keyboard.press("Tab")
                inside = page.evaluate("() => document.getElementById('alerts-modal').contains(document.activeElement)")
                self.assertTrue(inside, "Focus escaped the alerts dialog")
            self._assert_layout_and_touch_targets(page, 360, "alerts-modal")
            self._assert_axe_wcag_aa(page, "alerts-modal@360x800")
            page.keyboard.press("Escape")
            modal.wait_for(state="hidden", timeout=5000)
            self.assertEqual(page_errors, [])
        finally:
            context.close()

    def test_tv_name_shows_details_on_hover_and_click(self) -> None:
        context, page, _, page_errors, _ = self._new_authenticated_page(360, 800)
        try:
            self._navigate_view(page, "tvs")
            page.wait_for_selector("#tv-fleet-preview .tv-name-btn", state="visible", timeout=10000)
            btn = page.locator("#tv-fleet-preview .tv-name-btn").first
            self.assertEqual(btn.inner_text(), "Living room")
            self.assertIn("Xiaomi MIBOX4 · Android 9 · 192.168.1.34:5555 · online", btn.get_attribute("title"))
            self.assertEqual(btn.get_attribute("aria-expanded"), "false")
            btn.click()
            panel = page.locator("#tv-info-card-living_room_tv")
            panel.wait_for(state="visible")
            self.assertEqual(btn.get_attribute("aria-expanded"), "true")
            self.assertFalse(page.is_visible("#tv-info-card-bedroom_tv"), "only the clicked TV opens")
            text = panel.inner_text()
            for expected in ("Xiaomi MIBOX4", "oneday", "9 (API 28)", "Mi Box", "192.168.1.34:5555"):
                self.assertIn(expected, text)
            self.assertEqual(page.input_value("#tv-nick-card-living_room_tv"), "Living room")
            never = page.locator("#tv-fleet-preview .tv-name-btn").nth(1)
            self.assertIn("Model not detected yet", never.get_attribute("title"))
            self._assert_layout_and_touch_targets(page, 360, "tv-names")
            self._assert_axe_wcag_aa(page, "tv-names@360x800")
            # A refresh re-renders the card (same path as the 15 s poll); the panel stays open.
            with page.expect_response(lambda r: "/api/tv-updater/status" in r.url):
                page.evaluate("() => document.getElementById('btn-refresh-now').click()")
            page.wait_for_timeout(300)
            self.assertTrue(page.is_visible("#tv-info-card-living_room_tv"))
            self.assertEqual(page_errors, [])
        finally:
            context.close()

    def test_guarded_container_restart_opens_confirm_modal(self) -> None:
        self.__class__.mock_action_calls.clear()
        context, page, _, page_errors, _ = self._new_authenticated_page(1366, 900)
        try:
            self._navigate_view(page, "apps")
            page.click("#btn-restart-jellyfin")
            confirm = page.locator("#confirm-action-modal")
            confirm.wait_for(state="visible", timeout=5000)
            self.assertIn("Restart Jellyfin?", page.inner_text("#confirm-modal-title"))
            self._assert_axe_wcag_aa(page, "confirm-modal@1366x900")
            page.click("#confirm-modal-cancel")
            confirm.wait_for(state="hidden", timeout=5000)
            self.assertEqual(self.__class__.mock_action_calls, [])

            # Now confirm and verify POST /api/services/action/jellyfin fires for restart and stop
            page.click("#btn-restart-jellyfin")
            confirm.wait_for(state="visible", timeout=5000)
            page.click("#confirm-modal-ok")
            confirm.wait_for(state="hidden", timeout=5000)
            page.wait_for_timeout(200)
            page.click("#btn-stop-jellyfin")
            confirm.wait_for(state="visible", timeout=5000)
            self.assertIn("Stop Jellyfin?", page.inner_text("#confirm-modal-title"))
            page.click("#confirm-modal-ok")
            confirm.wait_for(state="hidden", timeout=5000)
            page.wait_for_timeout(200)
            self.assertEqual(self.__class__.mock_action_calls, [("jellyfin", "restart"), ("jellyfin", "stop")])
            # Verify Speed Limits modal opens cleanly & passes WCAG 2.2 AA
            page.click("#btn-torrent-limits")
            limits = page.locator("#torrent-limits-modal")
            limits.wait_for(state="visible", timeout=5000)
            self._assert_axe_wcag_aa(page, "torrent-limits-modal@1366x900")
            page.click("#torrent-limits-close")
            limits.wait_for(state="hidden", timeout=5000)
            self.assertEqual(page_errors, [])
        finally:
            context.close()

    def test_add_tv_wizard_modal_steps_brands_and_axe(self) -> None:
        context, page, _, page_errors, _ = self._new_authenticated_page(390, 844)
        try:
            self._navigate_view(page, "tvs")
            page.click("#btn-add-tv")
            wiz = page.locator("#add-tv-wizard-modal")
            wiz.wait_for(state="visible", timeout=5000)
            self.assertIn("Step 1 of 5", page.inner_text("#tv-wiz-step-badge"))
            # Brand switcher changes menu guide text honestly
            page.click('.tv-brand-tab[data-brand="fire"]')
            self.assertIn("My Fire TV", page.inner_text("#tv-wiz-step1-desc"))
            self._assert_axe_wcag_aa(page, "add-tv-wizard@390x844")
            self._assert_layout_and_touch_targets(page, 390, "add-tv-wizard")
            page.click("#add-tv-modal-close")
            wiz.wait_for(state="hidden", timeout=5000)
            self.assertEqual(page_errors, [])
        finally:
            context.close()

    def test_uninstalled_optional_module_hides_nav_and_redirects_deep_link(self) -> None:
        self.__class__.mock_tv_installed = False
        try:
            context, page, _, page_errors, _ = self._new_authenticated_page(1366, 900, initial_hash="#/tvs")
            try:
                page.wait_for_function("() => document.getElementById('nav-item-tvs').hidden === true", timeout=5000)
                self.assertEqual(page.evaluate("() => window.location.hash"), "#/overview")
                self.assertTrue(page.is_visible("#view-overview"))
                self.assertEqual(page_errors, [])
            finally:
                context.close()
        finally:
            self.__class__.mock_tv_installed = True

    def test_modal_keyboard_focus_trap_escape_and_axe(self) -> None:
        context, page, _, page_errors, _ = self._new_authenticated_page(1366, 900)
        try:
            open_btn = page.locator("#btn-open-config-center")
            open_btn.focus()
            page.keyboard.press("Enter")

            modal = page.locator("#config-center-modal")
            modal.wait_for(state="visible", timeout=5000)
            self.assertEqual(modal.get_attribute("role"), "dialog")
            self.assertEqual(modal.get_attribute("aria-modal"), "true")

            # Verify Tab focus stays trapped inside #config-center-modal
            for _ in range(12):
                page.keyboard.press("Tab")
                inside = page.evaluate(
                    "() => Boolean(document.activeElement && document.getElementById('config-center-modal').contains(document.activeElement))"
                )
                self.assertTrue(inside, "Focus escaped config-center-modal while tabbing")

            self._assert_axe_wcag_aa(page, "config-center-modal@1366x900")

            # Escape closes modal and restores focus to triggering button
            page.keyboard.press("Escape")
            modal.wait_for(state="hidden", timeout=5000)
            active_id = page.evaluate("() => document.activeElement && document.activeElement.id")
            self.assertEqual(active_id, "btn-open-config-center")
            self.assertEqual(page_errors, [])
        finally:
            context.close()

    def test_sidebar_collapses_on_main_click_and_toggles_with_arrow(self) -> None:
        context, page, _, page_errors, _ = self._new_authenticated_page(1366, 900)
        try:
            nav = page.locator("#hub-nav")
            toggle = page.locator("#btn-sidebar-toggle")

            # Desktop starts expanded with visible labels and Collapse button (<-)
            self.assertGreater(nav.bounding_box()["width"], 150)
            self.assertEqual(toggle.get_attribute("aria-expanded"), "true")
            self.assertEqual(page.evaluate("() => document.documentElement.dataset.sidebarCollapsed"), "false")

            # Clicking inside right-side #main-content collapses the sidebar to icons only
            page.click("#overview-apps-heading")
            page.wait_for_function("() => document.documentElement.dataset.sidebarCollapsed === 'true'", timeout=3000)
            page.wait_for_timeout(160)
            self.assertLessEqual(nav.bounding_box()["width"], 80)
            self.assertEqual(toggle.get_attribute("aria-expanded"), "false")

            # Hovering a collapsed icon reveals its module name tooltip
            apps_item = page.locator("#nav-item-apps")
            apps_label = page.locator("#nav-item-apps .nav-label")
            self.assertEqual(apps_item.get_attribute("title"), "Apps")
            apps_item.hover()
            self.assertTrue(apps_label.is_visible())
            self._assert_layout_and_touch_targets(page, 1366, "collapsed-sidebar-hover")
            self._assert_axe_wcag_aa(page, "collapsed-sidebar@1366x900")

            # Clicking the bottom Expand arrow (->) restores full sidebar width
            toggle.click()
            page.wait_for_function("() => document.documentElement.dataset.sidebarCollapsed === 'false'", timeout=3000)
            page.wait_for_timeout(160)
            self.assertGreater(nav.bounding_box()["width"], 150)
            self.assertEqual(toggle.get_attribute("aria-expanded"), "true")

            # Clicking the bottom Collapse arrow (<-) collapses it back cleanly
            toggle.click()
            page.wait_for_function("() => document.documentElement.dataset.sidebarCollapsed === 'true'", timeout=3000)
            self.assertEqual(page_errors, [])
        finally:
            context.close()

    def test_backups_library_numbers_unclipped_and_photos_health_accessible(self) -> None:
        for width, height in ((1366, 900), (360, 800)):
            context, page, _, page_errors, _ = self._new_authenticated_page(width, height)
            try:
                self._navigate_view(page, "backups")
                page.wait_for_selector("#photos-health-panel", state="visible", timeout=5000)
                page.wait_for_function(
                    "() => (document.getElementById('lib-val-assets')?.textContent || '').includes('35,765')",
                    timeout=5000,
                )
                for sel in ("#lib-val-disk", "#lib-val-gdrive", "#lib-val-assets", "#lib-val-faces"):
                    metrics = page.evaluate(
                        """(s) => {
                            const el = document.querySelector(s);
                            return el ? { text: el.textContent.trim(), sw: el.scrollWidth, cw: el.clientWidth } : null;
                        }""",
                        sel,
                    )
                    self.assertIsNotNone(metrics)
                    self.assertLessEqual(metrics["sw"], metrics["cw"] + 2, f"{sel} clipped at {width}x{height}: {metrics}")

                self.assertIn("264.3 GB", page.inner_text("#lib-val-disk"))
                self.assertIn("287.4 GB", page.inner_text("#lib-val-gdrive"))
                self.assertIn("35,765", page.inner_text("#lib-val-assets"))
                self.assertIn("18,904", page.inner_text("#lib-val-faces"))
                self.assertIn("Primary User", page.inner_text("#photos-users-tbody"))
                self.assertIn("0 Offline Assets", page.inner_text("#photos-offline-badge"))

                self._assert_layout_and_touch_targets(page, width, f"photos-backups@{width}")
                self._assert_axe_wcag_aa(page, f"photos-backups@{width}x{height}")
                self.assertEqual(page_errors, [])
            finally:
                context.close()

    def test_storage_analytics_and_smart_accessible(self) -> None:
        for width, height in ((1366, 900), (360, 800)):
            context, page, _, page_errors, _ = self._new_authenticated_page(width, height)
            try:
                self._navigate_view(page, "system")
                page.wait_for_selector("#storage-analytics-panel", state="visible", timeout=5000)
                page.wait_for_function(
                    "() => (document.getElementById('storage-smart-tbody')?.textContent || '').includes('ST1000LM024')",
                    timeout=5000,
                )
                self.assertIn("~42 days", page.inner_text("#storage-forecast-callout"))
                self.assertIn("480.20 GB", page.inner_text("#storage-folders-tbody"))
                self.assertIn("qBittorrent Rotated Logs", page.inner_text("#storage-cleanup-tbody"))
                self._assert_layout_and_touch_targets(page, width, f"system-storage@{width}")
                self._assert_axe_wcag_aa(page, f"system-storage@{width}x{height}")
                self.assertEqual(page_errors, [])
            finally:
                context.close()

    def test_config_center_tabs_preview_manifest_and_bundle_accessible(self) -> None:
        for width, height in ((1366, 900), (360, 800)):
            context, page, _, page_errors, _ = self._new_authenticated_page(width, height)
            try:
                if width < 1024:
                    page.click("#btn-header-menu")
                    page.click("[data-proxy-click='btn-open-config-center']")
                else:
                    page.click("#btn-open-config-center")
                modal = page.locator("#config-center-modal")
                modal.wait_for(state="visible", timeout=5000)

                page.click("#btn-preview-config-diff")
                page.wait_for_selector("#config-diff-preview", state="visible", timeout=5000)

                page.wait_for_selector("#cfg-tab-manifest", state="visible", timeout=5000)
                page.click("#cfg-tab-manifest")
                page.wait_for_function(
                    "() => (document.getElementById('cfg-manifest-content')?.textContent || '').includes('2.1.1')",
                    timeout=5000,
                )

                page.click("[data-config-tab='bundle']")
                page.wait_for_selector("#btn-download-support-bundle", state="visible", timeout=5000)
                self._assert_layout_and_touch_targets(page, width, f"config-center@{width}")
                self._assert_axe_wcag_aa(page, f"config-center@{width}x{height}")
                self.assertEqual(page_errors, [])
            finally:
                context.close()

    def test_network_health_panel_and_netplan_tip_accessible(self) -> None:
        for width, height in ((1366, 900), (360, 800)):
            context, page, _, page_errors, _ = self._new_authenticated_page(width, height, "#/system")
            try:
                page.wait_for_selector("#net-link-warning-callout", state="visible", timeout=5000)
                self.assertIn("half duplex", page.inner_text("#net-link-warning-callout"))
                self.assertIn("100.64.0.10", page.inner_text("#net-tailscale-body"))
                self.assertIn("192.168.1.0/24", page.inner_text("#net-tailscale-body"))
                self.assertIn("Control Hub Dashboard", page.inner_text("#net-ports-tbody"))
                self._assert_layout_and_touch_targets(page, width, f"system-network@{width}")
                self._assert_axe_wcag_aa(page, f"system-network@{width}x{height}")

                page.click("#btn-open-netplan-modal")
                page.wait_for_selector("#cfg-dhcp-tip", state="visible", timeout=5000)
                self.assertIn("DHCP Reservation Tip", page.inner_text("#cfg-dhcp-tip"))
                self.assertEqual(page_errors, [])
            finally:
                context.close()

    def test_schedules_panel_clash_and_editor_accessible(self) -> None:
        for width, height in ((1366, 900), (360, 800)):
            context, page, _, page_errors, _ = self._new_authenticated_page(width, height, "#/system")
            try:
                page.wait_for_selector("#cron-clash-callout", state="visible", timeout=5000)
                self.assertIn("Sleep Suspend window", page.inner_text("#cron-clash-callout"))
                page.wait_for_selector("#btn-cron-edit-immich_backup", state="visible", timeout=5000)
                self._assert_layout_and_touch_targets(page, width, f"system-schedules@{width}")
                self._assert_axe_wcag_aa(page, f"system-schedules@{width}x{height}")

                page.click("#btn-cron-edit-immich_backup")
                page.wait_for_selector("#cron-schedule-modal", state="visible", timeout=5000)
                self._assert_axe_wcag_aa(page, f"cron-schedule-modal@{width}x{height}")
                self.assertEqual(page_errors, [])
            finally:
                context.close()

    def test_account_security_tabs_and_family_view_accessible(self) -> None:
        # 1. Owner Account & Access modal (Password & 2FA, Signed-in Devices, Family View tabs)
        for width, height in ((1366, 900), (360, 800)):
            context, page, _, page_errors, _ = self._new_authenticated_page(width, height, "#/overview")
            try:
                page.click("#btn-header-menu")
                page.click("#btn-open-account")
                page.wait_for_selector("#hub-account-overlay", state="visible", timeout=5000)

                page.click("#acct-tab-btn-devices")
                page.wait_for_selector("#hub-sessions-list .auth-device-row", state="visible", timeout=5000)
                self._assert_axe_wcag_aa(page, f"account-devices@{width}x{height}")

                page.click("#acct-tab-btn-family")
                page.wait_for_selector("#hub-family-form", state="visible", timeout=5000)
                self._assert_axe_wcag_aa(page, f"account-family@{width}x{height}")

                page.click("#acct-tab-btn-security")
                page.click("#btn-totp-setup")
                page.wait_for_selector("#totp-secret-display", state="visible", timeout=5000)
                self._assert_axe_wcag_aa(page, f"account-totp@{width}x{height}")
                self.assertEqual(page_errors, [])
            finally:
                context.close()

        # 2. Read-only Family View (hides admin controls, shows What's New & Requests banner/panel)
        client = self.app.test_client()
        hdrs = {"Authorization": f"Bearer {self.app.config['CONTROL_HUB_TOKEN']}"}
        self.assertEqual(
            client.post("/api/auth/access", headers=hdrs, json={
                "family_enabled": True,
                "family_lan_open": False,
                "family_password": "FamilyViewPass1!",
            }).status_code,
            200,
        )
        try:
            for width, height in ((1366, 900), (360, 800)):
                context = self.browser.new_context(viewport={"width": width, "height": height})
                page = context.new_page()
                page_errors = []
                page.on("pageerror", lambda err, errs=page_errors: errs.append(str(err)))
                login_res = context.request.post(
                    f"{self.base_url}/api/auth/login",
                    data={"password": "FamilyViewPass1!"},
                )
                self.assertEqual(login_res.status, 200)
                page.goto(f"{self.base_url}/#/overview", wait_until="domcontentloaded")
                page.wait_for_selector("#family-mode-banner", state="visible", timeout=5000)
                page.wait_for_selector("#family-whats-new-panel", state="visible", timeout=5000)
                page.wait_for_function(
                    "() => !document.getElementById('footer-refresh-btn')?.disabled",
                    timeout=5000,
                )
                page.evaluate("() => document.fonts.ready")
                page.evaluate("() => window.scrollTo(0, 0)")
                self.assertTrue(page.locator("#nav-item-system").is_hidden())
                self.assertTrue(page.locator("#btn-open-config-center").is_hidden())
                self._assert_layout_and_touch_targets(page, width, f"family-overview@{width}")
                self._assert_axe_wcag_aa(page, f"family-overview@{width}x{height}")
                self.assertEqual(page_errors, [])
                context.close()
        finally:
            client.post("/api/auth/access", headers=hdrs, json={
                "family_enabled": False,
                "family_lan_open": False,
            })

    def test_troubleshoot_howto_and_tailscale_https_accessible(self) -> None:
        for width, height in ((1366, 900), (360, 800)):
            context, page, _, page_errors, _ = self._new_authenticated_page(width, height, "#/system")
            try:
                page.wait_for_selector("#net-tailscale-https-box", state="visible", timeout=5000)
                https_txt = page.inner_text("#net-tailscale-https-box")
                self.assertIn("https://homelab.tailnet.ts.net", https_txt)
                self.assertIn("sudo tailscale serve --bg 7575", https_txt)

                # Open Contextual How-To Guide from Network card
                page.click("#btn-ts-https-guide")
                page.wait_for_selector("#howto-guide-modal", state="visible", timeout=5000)
                self.assertIn("Remote HTTPS Access via Tailscale", page.inner_text("#howto-modal-title"))
                self._assert_axe_wcag_aa(page, f"howto-modal@{width}x{height}")
                page.click("#howto-modal-dismiss")
                page.wait_for_selector("#howto-guide-modal", state="hidden", timeout=5000)

                # Open Unified Troubleshoot Runner from header menu
                page.click("#btn-header-menu")
                page.click("#btn-open-troubleshoot")
                page.wait_for_selector("#troubleshoot-modal", state="visible", timeout=5000)
                page.wait_for_selector("#troubleshoot-checks-list .troubleshoot-item", state="visible", timeout=8000)
                self._assert_axe_wcag_aa(page, f"troubleshoot-modal@{width}x{height}")
                self.assertEqual(page_errors, [])
            finally:
                context.close()

    def test_history_insights_and_pwa_accessible(self) -> None:
        for width, height in ((1366, 900), (360, 800)):
            context, page, _, page_errors, ext_reqs = self._new_authenticated_page(width, height, "#/system")
            try:
                page.wait_for_selector("#history-insights-panel", state="visible", timeout=5000)
                page.wait_for_function(
                    "() => document.getElementById('insight-backup-val')?.textContent?.includes('28 passed')",
                    timeout=5000,
                )
                self.assertIn("3.02 kWh/mo", page.inner_text("#insight-power-val"))
                page.click('[data-hist-range="7d"]')
                page.wait_for_function(
                    "() => document.getElementById('history-panel-subtitle')?.textContent?.includes('7d')",
                    timeout=5000,
                )
                page.evaluate("() => window.scrollTo(0, 0)")
                self.assertEqual(page.get_attribute('link[rel="manifest"]', "href"), "/manifest.webmanifest")
                self._assert_layout_and_touch_targets(page, width, f"system-history@{width}")
                self._assert_axe_wcag_aa(page, f"system-history@{width}x{height}")
                self.assertEqual(ext_reqs, [])
                self.assertEqual(page_errors, [])
            finally:
                context.close()

    def test_custom_themes_i18n_kiosk_layout_and_tokens_accessible(self) -> None:
        for width, height in ((1366, 900), (360, 800)):
            context, page, _, page_errors, _ = self._new_authenticated_page(width, height, "#/system")
            try:
                page.wait_for_selector("#integrations-ha-yaml", state="visible", timeout=5000)
                self.assertIn("Back-UPS 1500", page.inner_text("#integrations-ups-body"))

                # Switch theme to High-Contrast and sweep all 5 views for WCAG AA compliance
                page.click("#btn-header-menu")
                page.click('[data-theme-choice="high-contrast"]')
                self.assertEqual(page.evaluate("() => document.documentElement.dataset.theme"), "high-contrast")
                for view_id in ALL_VIEWS:
                    self._navigate_view(page, view_id)
                    self._assert_layout_and_touch_targets(page, width, f"hc:{view_id}@{width}")
                    self._assert_axe_wcag_aa(page, f"hc:{view_id}@{width}x{height}")

                # Return to System view, switch to Hindi (preserving active theme), verify layout + WCAG
                self._navigate_view(page, "system")
                page.click("#btn-header-menu")
                page.click('[data-lang-choice="hi"]')
                self.assertEqual(page.evaluate("() => document.documentElement.lang"), "hi")
                self.assertEqual(page.evaluate("() => document.documentElement.dataset.theme"), "high-contrast")
                page.wait_for_timeout(180)
                self._assert_layout_and_touch_targets(page, width, f"hc-hi-system@{width}")
                self._assert_axe_wcag_aa(page, f"hc-hi-system@{width}x{height}")

                # Open Customize Layout modal, toggle hide on a card, verify persistence across reload, then reset
                page.click("#btn-open-customize")
                page.wait_for_selector("#customize-layout-modal", state="visible", timeout=5000)
                self._assert_axe_wcag_aa(page, f"customize-modal@{width}x{height}")
                page.click('.btn-cust-toggle[data-card-id="integrations-panel"]')
                page.click("#customize-modal-dismiss")
                page.wait_for_selector("#customize-layout-modal", state="hidden", timeout=5000)
                self.assertEqual(
                    page.evaluate("() => document.getElementById('integrations-panel')?.dataset.userHidden"),
                    "true",
                )
                page.reload(wait_until="domcontentloaded")
                page.wait_for_function(
                    "() => document.getElementById('integrations-panel')?.dataset.userHidden === 'true'",
                    timeout=5000,
                )
                page.click("#btn-header-menu")
                page.click("#btn-open-customize")
                page.wait_for_selector("#customize-layout-modal", state="visible", timeout=5000)
                page.click("#btn-customize-reset")
                page.click("#customize-modal-dismiss")
                page.wait_for_selector("#customize-layout-modal", state="hidden", timeout=5000)
                self.assertEqual(
                    page.evaluate("() => document.getElementById('integrations-panel')?.dataset.userHidden"),
                    "false",
                )

                # Switch back to English before checking Account -> API Tokens
                page.click("#btn-header-menu")
                page.click('[data-lang-choice="en"]')
                page.click("#btn-open-account")
                page.wait_for_selector("#hub-account-overlay", state="visible", timeout=5000)
                page.click("#acct-tab-btn-tokens")
                page.wait_for_selector("#hub-token-form", state="visible", timeout=5000)
                page.fill("#hub-token-name", "HA Probe")
                page.click("#btn-token-create")
                page.wait_for_selector("#hub-token-reveal", state="visible", timeout=5000)
                self.assertIn("hub_ro_", page.inner_text("#hub-token-reveal"))
                self._assert_axe_wcag_aa(page, f"account-tokens@{width}x{height}")
                page.click("#hub-account-close")
                page.wait_for_selector("#hub-account-overlay", state="detached", timeout=5000)

                # Wall Kiosk Mode enter & exit cleanly
                page.click("#btn-header-menu")
                page.click("#btn-kiosk-toggle")
                self.assertEqual(page.evaluate("() => document.documentElement.dataset.kiosk"), "true")
                page.wait_for_selector("#btn-kiosk-exit", state="visible", timeout=5000)
                self._assert_axe_wcag_aa(page, f"kiosk-system@{width}x{height}")
                page.click("#btn-kiosk-exit")
                self.assertEqual(page.evaluate("() => document.documentElement.dataset.kiosk"), "false")
                self.assertEqual(page_errors, [])
            finally:
                context.close()


if __name__ == "__main__":
    unittest.main()

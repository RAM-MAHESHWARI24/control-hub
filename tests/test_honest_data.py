"""
Phase 1A & 1D Honest-Data and Backend Safety Tests for Control Hub.

Verifies that when config files, Docker containers, storage mounts, caches, or logs
are absent, every API endpoint and HTML view reports honest empty/unknown/untested
states instead of hardcoded personal or synthetic fallback values.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import config  # noqa: E402
from core import storage_sizes  # noqa: E402
from core.config_core import auth_password  # noqa: E402
import server  # noqa: E402
from widgets import backup_sync, cron_tasks, network_speed, system_vitals, tv_updater  # noqa: E402

BANNED_FALLBACKS = (
    "35762",
    "33497",
    "18904",
    "98813",
    "35,762",
    "33,497",
    "18,904",
    "98,813",
    "265 GB",
    "272.4",
    "5120",
    "4847.6",
    "341.4",
    "Excitel",
    "94.1",
    "ADN Broadband",
    "Mi Box 4",
    "Mi TV 4A",
    "Acer TV",
    "ServerFF",
    "Homarr",
    "620 GB",
    "140 GB",
)


class _IsolatedEnvMixin:
    def _setup_isolated_env(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        state_dir = root / "state"
        hub_dir = state_dir / "control-hub"
        hub_dir.mkdir(parents=True, exist_ok=True)

        self._orig_env = {
            k: os.environ.get(k)
            for k in (
                "HOMELAB_STATE_DIR",
                "CONTROL_HUB_PASSWORD_FILE",
                "CONTROL_HUB_TOKEN",
                "TZ",
            )
        }
        os.environ["HOMELAB_STATE_DIR"] = str(state_dir)
        pw_file = hub_dir / "password"
        os.environ["CONTROL_HUB_PASSWORD_FILE"] = str(pw_file)
        os.environ["CONTROL_HUB_TOKEN"] = "test-honest-token-123"
        os.environ["TZ"] = "UTC"

        # Patch imported module constants so tests remain isolated regardless of import order.
        missing_backup_dir = str(root / "missing-photo-backups")
        missing_backup_log = str(root / "missing-photo-backups" / "backup.log")
        missing_status_file = str(root / "missing-photo-backups" / "status.json")
        missing_speedtest = str(root / "speedtest_cache.json")
        missing_sizes_cache = str(root / "storage_sizes_cache.json")
        missing_hdd_data = str(root / "missing-hdd" / "data")
        missing_hdd_memories = str(root / "missing-hdd" / "Memories")
        missing_appdata = str(root / "missing-appdata")

        self._patches = [
            mock.patch.object(auth_password, "PASSWORD_FILE", pw_file),
            mock.patch.object(config, "BACKUP_DIR", missing_backup_dir),
            mock.patch.object(config, "BACKUP_LOG_FILE", missing_backup_log),
            mock.patch.object(config, "BACKUP_STATUS_FILE", missing_status_file),
            mock.patch.object(config, "SPEEDTEST_CACHE_FILE", missing_speedtest),
            mock.patch.object(config, "STORAGE_SIZES_CACHE_FILE", missing_sizes_cache),
            mock.patch.object(config, "HDD_DATA", missing_hdd_data),
            mock.patch.object(config, "HDD_MEMORIES", missing_hdd_memories),
            mock.patch.object(config, "APPDATA_DIR", missing_appdata),
            mock.patch.object(config, "TV_UPDATER_PY", ""),
            mock.patch.object(config, "TV_UPDATER_STATE_FILE", ""),
            mock.patch.object(backup_sync, "BACKUP_DIR", missing_backup_dir),
            mock.patch.object(backup_sync, "BACKUP_LOG_FILE", missing_backup_log),
            mock.patch.object(backup_sync, "BACKUP_STATUS_FILE", missing_status_file),
            mock.patch.object(backup_sync, "STORAGE_SIZES_CACHE_FILE", missing_sizes_cache),
            mock.patch.object(backup_sync, "HDD_DATA", missing_hdd_data),
            mock.patch.object(backup_sync, "HDD_MEMORIES", missing_hdd_memories),
            mock.patch.object(backup_sync, "APPDATA_DIR", missing_appdata),
            mock.patch.object(backup_sync, "GDRIVE_REMOTE", ""),
            mock.patch.object(network_speed, "SPEEDTEST_CACHE_FILE", missing_speedtest),
            mock.patch.object(system_vitals, "STORAGE_SIZES_CACHE_FILE", missing_sizes_cache),
            mock.patch.object(system_vitals, "HDD_DATA", missing_hdd_data),
            mock.patch.object(system_vitals, "HDD_MEMORIES", missing_hdd_memories),
            mock.patch.object(system_vitals, "APPDATA_DIR", missing_appdata),
            mock.patch.object(system_vitals, "BACKUP_DIR", missing_backup_dir),
            mock.patch.object(cron_tasks, "BACKUP_LOG_FILE", missing_backup_log),
            mock.patch.object(cron_tasks, "BACKUP_STATUS_FILE", missing_status_file),
            mock.patch.object(tv_updater, "TV_UPDATER_PY", ""),
            mock.patch.object(tv_updater, "TV_UPDATER_STATE_FILE", ""),
        ]
        for p in self._patches:
            p.start()

        with storage_sizes._cache_lock:
            storage_sizes._memory_cache.clear()
        backup_sync.immich_library_stats_cache["data"] = None
        backup_sync.immich_library_stats_cache["last_fetched"] = 0

        return root

    def _teardown_isolated_env(self) -> None:
        storage_sizes.wait_for_idle(timeout=5.0)
        for p in reversed(getattr(self, "_patches", [])):
            p.stop()
        for k, v in getattr(self, "_orig_env", {}).items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if hasattr(self, "_tmp"):
            self._tmp.cleanup()


class TestHonestData(_IsolatedEnvMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.root = self._setup_isolated_env()
        self.app = server.create_app()
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer test-honest-token-123"}

    def tearDown(self) -> None:
        self._teardown_isolated_env()

    def _assert_no_banned_literals(self, text: str, context: str) -> None:
        for bad in BANNED_FALLBACKS:
            self.assertNotIn(bad, text, f"Found hardcoded fallback literal {bad!r} in {context}")

    def test_empty_env_html_and_endpoints_have_no_fake_fallbacks(self) -> None:
        html_resp = self.client.get("/")
        self.assertEqual(html_resp.status_code, 200)
        html = html_resp.get_data(as_text=True)
        self._assert_no_banned_literals(html, "GET /")
        self.assertNotIn("IST", html)

        def fake_empty_run(*args, **kwargs):
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch("subprocess.run", side_effect=fake_empty_run):
            endpoints = [
                "/api/backup/status",
                "/api/backup/library-stats",
                "/api/speedtest/latest",
                "/api/network/speed",
                "/api/system/vitals",
                "/api/tv-updater/status",
                "/api/cron/status",
                "/api/services/status",
                "/api/sleep/status",
            ]
            for ep in endpoints:
                resp = self.client.get(ep, headers=self.headers)
                self.assertEqual(resp.status_code, 200, f"{ep} returned {resp.status_code}")
                payload_text = json.dumps(resp.get_json())
                self._assert_no_banned_literals(payload_text, ep)

        backup = self.client.get("/api/backup/status", headers=self.headers).get_json()
        self.assertEqual(backup["status"], "unknown")
        self.assertIsNone(backup["last_sync"])
        self.assertIsNone(backup["total_assets"])
        self.assertIsNone(backup["assets_with_named_faces"])
        self.assertIsNone(backup["named_people"])
        self.assertIsNone(backup["gdrive_used_gb"])

        lib = self.client.get("/api/backup/library-stats", headers=self.headers).get_json()
        self.assertIsNone(lib["assets"])
        self.assertIsNone(lib["gdrive"])

        speed = self.client.get("/api/speedtest/latest", headers=self.headers).get_json()
        self.assertFalse(speed["available"])

        tv = self.client.get("/api/tv-updater/status", headers=self.headers).get_json()
        self.assertFalse(tv["installed"])
        self.assertEqual(tv["status"], "not_installed")
        with mock.patch.object(tv_updater, "tv_updater", None):
            snap = tv_updater.fetch_telemetry_snapshot(force=True)
            self.assertEqual(snap["total_devices"], 0)
            self.assertEqual(snap["devices"], [])

        with mock.patch("subprocess.run", side_effect=fake_empty_run):
            svcs = self.client.get("/api/services/status", headers=self.headers).get_json()
            self.assertEqual(svcs["services"], [])
            self.assertFalse(svcs["dozzle_installed"])

    def test_backup_status_reads_atomic_status_json_without_sudo_rclone(self) -> None:
        bak_dir = self.root / "photo-backups"
        bak_dir.mkdir()
        status_path = bak_dir / "status.json"
        status_payload = {
            "status": "synced",
            "stage": 4,
            "message": "Completed cleanly",
            "started_at": "2026-11-21T03:00:00+00:00",
            "completed_at": "2026-11-21T03:12:00+00:00",
            "last_good_at": "2026-11-21T03:12:00+00:00",
            "dump_file": "immich_db_20261121.sql.gz",
            "dump_bytes": 10 * 1024 * 1024,
            "remote": "gdrive:immich-backup",
            "gdrive": {
                "total_bytes": 200 * (1024**3),
                "used_bytes": 50 * (1024**3),
                "free_bytes": 150 * (1024**3),
            },
        }
        status_path.write_text(json.dumps(status_payload), encoding="utf-8")

        def no_sudo_rclone(*args, **kwargs):
            cmd = args[0] if args else []
            self.assertNotIn("rclone", cmd, "Dashboard should read status.json without invoking rclone")
            return mock.Mock(returncode=1, stdout="", stderr="not running")

        with mock.patch.object(backup_sync, "BACKUP_DIR", str(bak_dir)), \
             mock.patch.object(backup_sync, "BACKUP_STATUS_FILE", str(status_path)), \
             mock.patch.object(cron_tasks, "BACKUP_STATUS_FILE", str(status_path)), \
             mock.patch("subprocess.run", side_effect=no_sudo_rclone):
            res = self.client.get("/api/backup/status", headers=self.headers).get_json()
            self.assertEqual(res["status"], "synced")
            self.assertEqual(res["current_stage"], 4)
            self.assertEqual(res["db_size"], "10.0 MB")
            self.assertEqual(res["gdrive_remote"], "gdrive:immich-backup")
            self.assertEqual(res["gdrive_used_gb"], 50.0)
            self.assertEqual(res["gdrive_free_gb"], 150.0)

            cron_res = self.client.get("/api/cron/status", headers=self.headers).get_json()
            cloud_job = next(j for j in cron_res["jobs"] if j["id"] == "immich_backup")
            self.assertEqual(cloud_job["status_text"], "Synced")

    def test_backup_log_parses_starting_immich_backup_marker(self) -> None:
        bak_dir = self.root / "log-only-backups"
        bak_dir.mkdir()
        log_path = bak_dir / "backup.log"
        log_path.write_text(
            "Starting Immich Backup: 2026-11-21 04:00 UTC\n"
            "[4/4] Syncing library...\n"
            "Immich Backup Completed Successfully: 2026-11-21 04:05 UTC\n",
            encoding="utf-8",
        )
        with mock.patch.object(backup_sync, "BACKUP_DIR", str(bak_dir)), \
             mock.patch.object(backup_sync, "BACKUP_LOG_FILE", str(log_path)), \
             mock.patch.object(cron_tasks, "BACKUP_LOG_FILE", str(log_path)), \
             mock.patch("subprocess.run", return_value=mock.Mock(returncode=1, stdout="", stderr="")):
            res = self.client.get("/api/backup/status", headers=self.headers).get_json()
            self.assertEqual(res["status"], "synced")
            self.assertIn("2026-11-21 04:05", res["last_sync"])

            cron_res = self.client.get("/api/cron/status", headers=self.headers).get_json()
            cloud_job = next(j for j in cron_res["jobs"] if j["id"] == "immich_backup")
            self.assertEqual(cloud_job["status_text"], "Synced")
            self.assertEqual(cloud_job["last_run"], "2026-11-21 04:00 UTC")

    def test_storage_sizes_measures_directories_and_deduplicates_nested_photos(self) -> None:
        data_root = self.root / "hdd" / "data"
        photos_root = data_root / "Photos"
        appdata_root = self.root / "appdata"
        bak_root = self.root / "backups"
        data_root.mkdir(parents=True)
        photos_root.mkdir(parents=True)
        appdata_root.mkdir(parents=True)
        bak_root.mkdir(parents=True)

        (data_root / "movie.bin").write_bytes(b"a" * 1024)
        (photos_root / "pic.jpg").write_bytes(b"b" * 2048)
        (appdata_root / "db.sqlite").write_bytes(b"c" * 512)
        (bak_root / "dump.sql").write_bytes(b"d" * 256)

        cache_file = str(self.root / "sizes_cache.json")
        res = storage_sizes.get_storage_sizes(
            cache_file=cache_file,
            media_path=str(data_root),
            photos_path=str(photos_root),
            appdata_path=str(appdata_root),
            backup_path=str(bak_root),
            blocking=True,
        )
        self.assertTrue(res["measured"])
        self.assertEqual(res["media_bytes"], 1024)
        self.assertEqual(res["photos_bytes"], 2048)
        self.assertEqual(res["appdata_bytes"], 768)

    def test_service_restart_uses_direct_docker_without_sudo_and_validates_id(self) -> None:
        bad_resp = self.client.post("/api/services/restart/not-a-service", headers=self.headers)
        self.assertEqual(bad_resp.status_code, 400)

        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout="", stderr="")) as m_run:
            ok_resp = self.client.post("/api/services/restart/jellyfin", headers=self.headers)
            self.assertEqual(ok_resp.status_code, 200)
            called_cmd = m_run.call_args[0][0]
            self.assertEqual(called_cmd, ["docker", "restart", "jellyfin"])


if __name__ == "__main__":
    unittest.main()

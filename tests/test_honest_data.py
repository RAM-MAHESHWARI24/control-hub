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

    def test_du_partial_permission_exit_1_still_parses_bytes(self) -> None:
        existing_dir = self.root / "memories"
        existing_dir.mkdir()
        proc_partial = mock.Mock(
            returncode=1,
            stdout=f"48585989231\t{existing_dir}\n",
            stderr="du: cannot read directory: Permission denied\n",
        )
        with mock.patch("os.name", "posix"), \
             mock.patch("shutil.which", side_effect=lambda x: "/usr/bin/du" if x == "du" else None), \
             mock.patch("subprocess.run", return_value=proc_partial):
            byte_count, warn = storage_sizes._dir_size_bytes(str(existing_dir))
            self.assertEqual(byte_count, 48585989231)
            self.assertIsNotNone(warn)

    def test_qbit_v5_stop_start_and_fails_login_rejected(self) -> None:
        from core import telemetry_sampler
        from widgets import current_downloads

        # 1. qBittorrent 200 "Fails." must be rejected (not treated as logged in)
        bad_resp = mock.Mock(status_code=200, text="Fails.")
        with mock.patch.object(telemetry_sampler, "QBITTORRENT_PASS", "secret"), \
             mock.patch.object(telemetry_sampler.qb_session, "post", return_value=bad_resp):
            ok = telemetry_sampler.qb_login()
            self.assertFalse(ok)
            self.assertEqual(telemetry_sampler.qb_status, "auth_failed")

        # 2. qBittorrent 5.x stoppedDL formats cleanly in format_eta
        self.assertEqual(telemetry_sampler.format_eta(8640000, state="stoppedDL"), "Paused")

        # 3. toggle_all_torrents tries v5 /stop first and falls back to v4 /pause on 404
        calls = []

        def fake_post(url, data=None, timeout=None):
            calls.append(url)
            if url.endswith("/stop"):
                return mock.Mock(status_code=404, text="Not Found")
            return mock.Mock(status_code=200, text="")

        with mock.patch.object(current_downloads, "qb_login", return_value=True), \
             mock.patch.object(current_downloads.qb_session, "post", side_effect=fake_post):
            res = self.client.post(
                "/api/torrents/toggle-all",
                headers=self.headers,
                json={"action": "pause"},
            )
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.get_json()["success"])
            self.assertTrue(any(u.endswith("/stop") for u in calls))
            self.assertTrue(any(u.endswith("/pause") for u in calls))

    def test_cpu_temp_ignores_acpitz_and_reads_hwmon_coretemp(self) -> None:
        from core import telemetry_sampler

        hwmon_root = self.root / "hwmon"
        thermal_root = self.root / "thermal"
        # Fake acpitz thermal zone (should be ignored)
        tz0 = thermal_root / "thermal_zone0"
        tz0.mkdir(parents=True)
        (tz0 / "type").write_text("acpitz\n", encoding="utf-8")
        (tz0 / "temp").write_text("27800\n", encoding="utf-8")
        self.assertIsNone(telemetry_sampler.read_cpu_temp(hwmon_root=hwmon_root, thermal_root=thermal_root))

        # Add hwmon coretemp sensor (should be picked)
        hm1 = hwmon_root / "hwmon1"
        hm1.mkdir(parents=True)
        (hm1 / "name").write_text("coretemp\n", encoding="utf-8")
        (hm1 / "temp1_label").write_text("Package id 0\n", encoding="utf-8")
        (hm1 / "temp1_input").write_text("47500\n", encoding="utf-8")
        self.assertEqual(telemetry_sampler.read_cpu_temp(hwmon_root=hwmon_root, thermal_root=thermal_root), 47.5)

    def test_detect_active_nic_and_link_info_never_fabricate_100m(self) -> None:
        from core import telemetry_sampler

        proc_net = self.root / "proc_net_dev"
        proc_route = self.root / "proc_net_route"
        sys_net = self.root / "sys_class_net"
        (sys_net / "enp3s0").mkdir(parents=True)
        (sys_net / "wlp2s0" / "wireless").mkdir(parents=True)
        (sys_net / "enp3s0" / "operstate").write_text("down\n", encoding="utf-8")
        (sys_net / "wlp2s0" / "operstate").write_text("up\n", encoding="utf-8")
        proc_net.write_text(
            "Inter-|\n face |bytes\n"
            "  lo: 0\n"
            "  docker0: 0\n"
            "  enp3s0: 0\n"
            "  wlp2s0: 100\n",
            encoding="utf-8",
        )
        proc_route.write_text(
            "Iface\tDestination\tGateway\n"
            "wlp2s0\t00000000\t0101A8C0\n",
            encoding="utf-8",
        )
        nic = telemetry_sampler.detect_active_nic(
            preferred_nic="",
            proc_net=proc_net,
            proc_route=proc_route,
            sys_net=sys_net,
        )
        self.assertEqual(nic, "wlp2s0")

        speed, duplex, spec = telemetry_sampler.get_nic_link_info("wlp2s0", sys_net=sys_net)
        self.assertIsNone(speed)
        self.assertIsNone(duplex)
        self.assertIn("Wi-Fi", spec)
        self.assertNotIn("100 Mbps", spec)

    def test_storage_manager_parses_proc_mounts_without_skipping(self) -> None:
        from core.config_core import storage_manager

        fake_mounts_file = self.root / "proc_mounts"
        fake_mounts_file.write_text(
            "/dev/nvme0n1p2 / ext4 rw 0 0\n"
            "/dev/sda1 /mnt/hdd ext4 rw 0 0\n"
            "/dev/md0 /mnt/raid ext4 rw 0 0\n"
            "tmpfs /run tmpfs rw 0 0\n",
            encoding="utf-8",
        )
        Usage = type("Usage", (), {"total": 500 * 1024**3, "used": 200 * 1024**3, "free": 300 * 1024**3})
        dev_ids = {"/": 1, "/mnt/hdd": 2, "/mnt/raid": 3}

        orig_stat = os.stat

        def fake_stat(p, **kw):
            key = str(p)
            if key in dev_ids:
                return mock.Mock(st_dev=dev_ids[key])
            return orig_stat(p, **kw)

        with mock.patch("os.name", "posix"), \
             mock.patch("os.path.exists", side_effect=lambda p: str(p) in dev_ids), \
             mock.patch("os.stat", side_effect=fake_stat), \
             mock.patch("shutil.disk_usage", return_value=Usage()):
            parts = storage_manager.get_disk_partitions(proc_mounts=fake_mounts_file)
            mounts = [p["mount_point"] for p in parts]
            self.assertIn("/", mounts)
            self.assertIn("/mnt/hdd", mounts)
            self.assertIn("/mnt/raid", mounts)

    def test_sleep_guard_disabled_and_midnight_wrap(self) -> None:
        from widgets import sleep_guard

        segs = sleep_guard.compute_window_segments("23:00", 7.0)
        self.assertEqual(len(segs), 2)
        self.assertAlmostEqual(segs[0]["left_pct"] + segs[0]["width_pct"], 100.0, places=0)
        self.assertEqual(segs[1]["left_pct"], 0.0)

        conf_path = self.root / "server-suspend.conf"
        conf_path.write_text(
            json.dumps({"enabled": False, "sleep_time": "23:00", "wake_time": "06:00", "duration_hours": 7.0}),
            encoding="utf-8",
        )
        with mock.patch.object(sleep_guard, "SUSPEND_CONFIG_FILE", str(conf_path)), \
             mock.patch.object(sleep_guard, "SUSPEND_SCRIPT", str(self.root / "missing.sh")), \
             mock.patch.object(sleep_guard, "SUSPEND_CRON_FILE", str(self.root / "missing.cron")), \
             mock.patch.object(sleep_guard, "SUSPEND_SKIP_FILE", str(self.root / "missing.skip")), \
             mock.patch.object(sleep_guard, "SUSPEND_OVERRIDE_FILE", str(self.root / "missing.ov")):
            data = self.client.get("/api/sleep/status", headers=self.headers).get_json()
            self.assertTrue(data["installed"])
            self.assertEqual(data["state_mode"], "disabled")
            self.assertEqual(data["seconds_until_sleep"], 0)

    def test_service_matrix_parses_health_and_published_ports(self) -> None:
        from widgets import service_matrix

        self.assertEqual(service_matrix.parse_container_health("Up 2 hours (unhealthy)"), "unhealthy")
        self.assertEqual(service_matrix.parse_container_health("Up 2 hours (healthy)"), "healthy")
        self.assertEqual(service_matrix.parse_published_port("0.0.0.0:8097->8096/tcp", 8096), 8097)

        docker_out = "\n".join([
            json.dumps({
                "ID": "abcdef1234567890",
                "Names": "jellyfin",
                "State": "running",
                "Status": "Up 2 hours (unhealthy)",
                "Ports": "0.0.0.0:8097->8096/tcp",
                "Image": "jellyfin/jellyfin:10.10",
            }),
            json.dumps({
                "ID": "1122334455667788",
                "Names": "my_custom_app",
                "State": "running",
                "Status": "Up 10 minutes",
                "Ports": "0.0.0.0:3000->3000/tcp",
                "Image": "nginx:alpine",
            }),
        ])

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["docker", "ps"]:
                return mock.Mock(returncode=0, stdout=docker_out, stderr="")
            return mock.Mock(returncode=1, stdout="", stderr="")

        with mock.patch("subprocess.run", side_effect=fake_run):
            res = self.client.get("/api/services/status", headers=self.headers).get_json()
            self.assertEqual(res["other_count"], 1)
            jf = res["services"][0]
            self.assertEqual(jf["port"], 8097)
            self.assertEqual(jf["health"], "unhealthy")
            self.assertFalse(jf["is_up"])

            res_all = self.client.get("/api/services/status?include_other=true", headers=self.headers).get_json()
            names = [s["id"] for s in res_all["services"]]
            self.assertIn("my_custom_app", names)

    def test_cron_omits_phantom_recyclarr_when_uninstalled(self) -> None:
        with mock.patch.object(cron_tasks, "BACKUP_SCRIPT", str(self.root / "missing_bak.sh")), \
             mock.patch.object(cron_tasks, "BACKUP_CRON_FILE", str(self.root / "missing_bak.cron")), \
             mock.patch.object(cron_tasks, "RECYCLARR_LOG_FILE", str(self.root / "missing_rc.log")), \
             mock.patch.object(cron_tasks, "IMMICH_ML_CRON_FILE", str(self.root / "missing_ml.cron")), \
             mock.patch("shutil.which", return_value=None), \
             mock.patch("subprocess.run", return_value=mock.Mock(returncode=1, stdout="", stderr="")):
            res = self.client.get("/api/cron/status", headers=self.headers).get_json()
            ids = [j["id"] for j in res["jobs"]]
            self.assertNotIn("recyclarr", ids)

    def test_system_prober_n100_and_amd_gpu_classification(self) -> None:
        from core.config_core import system_prober

        n100 = system_prober.probe_cpu_info(model_override="Intel(R) N100")
        self.assertFalse(n100["is_low_power"])
        haswell = system_prober.probe_cpu_info(model_override="Intel(R) Core(TM) i3-4010U CPU @ 1.70GHz")
        self.assertTrue(haswell["is_low_power"])

        dri = self.root / "dri"
        drm = self.root / "drm"
        dri.mkdir()
        (dri / "renderD128").write_text("", encoding="utf-8")
        card0_dev = drm / "card0" / "device"
        card0_dev.mkdir(parents=True)
        (card0_dev / "vendor").write_text("0x1002\n", encoding="utf-8")
        with mock.patch("shutil.which", return_value=None):
            hw = system_prober.probe_hardware_acceleration(dri_root=dri, drm_sys_root=drm)
            self.assertEqual(hw["vendor"], "amd")
            self.assertEqual(hw["recommended_mode"], "vaapi")
            self.assertIn("AMD VAAPI", hw["details"][0])
            self.assertNotIn("Intel", hw["details"][0])


if __name__ == "__main__":
    unittest.main()

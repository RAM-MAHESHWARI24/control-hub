"""Unit and API tests for Phase 3C Storage Analytics, Fill Forecast, Safe Cleanups, and SMART."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HUB_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HUB_DIR.parents[1]
if str(HUB_DIR) not in sys.path:
    sys.path.insert(0, str(HUB_DIR))

import server  # noqa: E402
from core import storage_sizes  # noqa: E402
from widgets import storage_hub  # noqa: E402


class TestStorageHub(unittest.TestCase):
    def setUp(self) -> None:
        self.app = server.create_app()
        self.token = self.app.config["CONTROL_HUB_TOKEN"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.client = self.app.test_client()

    def test_parse_size_bytes(self) -> None:
        self.assertEqual(storage_hub.parse_size_bytes("5.138GB (27%)"), 5138000000)
        self.assertEqual(storage_hub.parse_size_bytes("178.5 MB"), 178500000)
        self.assertEqual(storage_hub.parse_size_bytes("2 GiB"), 2 * (1024**3))
        self.assertEqual(storage_hub.parse_size_bytes("0B (0%)"), 0)

    def test_measure_all_tracks_subfolders_and_distinct_backups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hdd = root / "hdd"
            movies = hdd / "media" / "movies"
            tv = hdd / "media" / "tv"
            torrents = hdd / "torrents"
            photos = root / "photos"
            appdata = root / "appdata"
            p_bak = root / "photo-backups"
            m_bak = root / "media-backups"
            for folder in (movies, tv, torrents, photos, appdata, p_bak, m_bak):
                folder.mkdir(parents=True)

            (movies / "movie.bin").write_bytes(b"a" * 32768)
            (tv / "ep.bin").write_bytes(b"b" * 16384)
            (torrents / "seed.bin").write_bytes(b"c" * 8192)
            (photos / "img.jpg").write_bytes(b"d" * 512)
            (appdata / "cfg.db").write_bytes(b"e" * 256)
            (p_bak / "dump.sql.gz").write_bytes(b"f" * 128)
            (m_bak / "cfg.tar.zst").write_bytes(b"g" * 128)

            res = storage_sizes._measure_all(
                str(hdd), str(photos), str(appdata), str(p_bak), media_backup_path=str(m_bak)
            )
            self.assertTrue(res["measured"])
            # Linux `du -s -B1` includes directory block overhead; verify exact lower bounds and ordering.
            self.assertGreaterEqual(res["movies_bytes"], 32768)
            self.assertGreaterEqual(res["tv_bytes"], 16384)
            self.assertGreaterEqual(res["downloads_bytes"], 8192)
            self.assertGreater(res["movies_bytes"], res["tv_bytes"])
            self.assertGreater(res["tv_bytes"], res["downloads_bytes"])
            self.assertGreaterEqual(res["only_appdata_bytes"], 256)
            self.assertGreaterEqual(res["only_backups_bytes"], 256)
            self.assertGreater(res["appdata_bytes"], res["only_appdata_bytes"])

    def test_fill_forecast_history_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hist = str(Path(tmp) / "history.json")
            base_ts = 1_700_000_000.0
            total = 1000 * (1024**3)
            storage_sizes.record_storage_sample(hist, "/mnt/hdd/data", 800 * (1024**3), total, now_ts=base_ts)

            # Single recent sample cannot produce a multi-day trend yet
            early = storage_sizes.compute_fill_forecast(
                hist, "/mnt/hdd/data", 805 * (1024**3), total, now_ts=base_ts + 3600
            )
            self.assertFalse(early["ready"])

            # 10 days later with +5 GB/day -> 150 GB remaining -> ~30 days until full
            grown = storage_sizes.compute_fill_forecast(
                hist, "/mnt/hdd/data", 850 * (1024**3), total, now_ts=base_ts + 10 * 86400
            )
            self.assertTrue(grown["ready"])
            self.assertEqual(grown["trend"], "growing")
            self.assertAlmostEqual(grown["daily_delta_gb"], 5.0, places=1)
            self.assertAlmostEqual(grown["days_until_full"], 30.0, places=1)

            # Negative/zero delta reports steady state
            shrunk = storage_sizes.compute_fill_forecast(
                hist, "/mnt/hdd/data", 780 * (1024**3), total, now_ts=base_ts + 10 * 86400
            )
            self.assertTrue(shrunk["ready"])
            self.assertIsNone(shrunk["days_until_full"])

    def test_storage_overview_and_cleanup_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            qlogs = root / "qlogs"
            p_bak = root / "photo-backups"
            m_bak = root / "media-backups"
            qlogs.mkdir()
            p_bak.mkdir()
            m_bak.mkdir()

            # Active log MUST be kept; rotated .bak* must be cleaned
            (qlogs / "qbittorrent.log").write_text("active", encoding="utf-8")
            (qlogs / "qbittorrent.log.bak").write_bytes(b"x" * 1024)
            (qlogs / "qbittorrent.log.bak1").write_bytes(b"y" * 2048)

            # Keep newest 3 photo dumps; remove older 2
            for day in ("20261121", "20261122", "20261123", "20261124", "20261125"):
                (p_bak / f"immich_db_{day}_220001.sql.gz").write_bytes(b"z" * 1024)

            fake_sizes = {
                "measured": True, "measuring": False, "measured_at": 1700000000,
                "measured_by": "root-timer", "any_partial": False, "reason": None,
                "movies_gb": 500.0, "tv_gb": 250.0, "downloads_gb": 180.0,
                "photos_gb": 264.0, "only_backups_gb": 1.1, "only_appdata_gb": 4.2,
            }
            fake_smart = {
                "available": True, "smartctl_installed": True,
                "disks": [{"device": "sda", "model": "ST1000", "type": "HDD", "size_gb": 931.5, "passed": True, "temp_c": 34, "reallocated_sectors": 0}],
            }
            qbt_items = [
                {"hash": "abc123", "name": "DoneShow", "amount_left": 0, "progress": 1.0, "state": "pausedUP", "ratio": 2.1, "max_ratio": 2.0, "size": 2048},
                {"hash": "def456", "name": "StillSeeding", "amount_left": 0, "progress": 1.0, "state": "uploading", "ratio": 0.4, "max_ratio": 2.0, "seeding_time": 100, "max_seeding_time": -1, "size": 4096},
            ]

            def fake_qbt(method, endpoint, data=None):
                m = mock.Mock()
                m.status_code = 200
                if endpoint == "/api/v2/torrents/info":
                    m.json.return_value = qbt_items
                else:
                    m.json.return_value = {}
                return m

            docker_df = json.dumps({"Type": "Images", "Reclaimable": "2.5GB (20%)"}) + "\n"

            with mock.patch.object(storage_hub, "get_storage_sizes", return_value=fake_sizes), \
                 mock.patch.object(storage_hub, "QBITTORRENT_PASS", "pass123"), \
                 mock.patch.object(storage_hub, "_qbit_request", side_effect=fake_qbt), \
                 mock.patch.object(storage_hub, "QBIT_LOG_DIR", str(qlogs)), \
                 mock.patch.object(storage_hub, "BACKUP_DIR", str(p_bak)), \
                 mock.patch.object(storage_hub, "MEDIA_BACKUP_DIR", str(m_bak)), \
                 mock.patch.object(storage_hub, "STORAGE_OPS_HELPER", ""), \
                 mock.patch.object(storage_hub, "_probe_smart_health", return_value=fake_smart), \
                 mock.patch.object(storage_hub.subprocess, "run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=0, stdout=docker_df, stderr="")
                ov = self.client.get("/api/storage/overview", headers=self.headers)
                self.assertEqual(ov.status_code, 200)
                data = ov.get_json()
                self.assertEqual(len(data["folders"]["rows"]), 6)
                by_id = {c["id"]: c for c in data["cleanup"]}
                self.assertEqual(by_id["torrents_seeded"]["count"], 1)
                self.assertEqual(by_id["qbit_logs"]["count"], 2)
                self.assertEqual(by_id["old_dumps"]["count"], 2)
                self.assertGreater(by_id["docker_prune"]["size_bytes"], 2_000_000_000)

                # Clean rotated logs while keeping active qbittorrent.log
                c_logs = self.client.post("/api/storage/cleanup", headers=self.headers, json={"target": "qbit_logs"})
                self.assertEqual(c_logs.status_code, 200)
                self.assertTrue((qlogs / "qbittorrent.log").exists())
                self.assertFalse((qlogs / "qbittorrent.log.bak").exists())

                # Clean excess dumps while preserving newest 3
                c_dumps = self.client.post("/api/storage/cleanup", headers=self.headers, json={"target": "old_dumps"})
                self.assertEqual(c_dumps.status_code, 200)
                self.assertEqual(len(list(p_bak.glob("immich_db_*.sql.gz"))), 3)

                # Clean finished torrents
                c_tor = self.client.post("/api/storage/cleanup", headers=self.headers, json={"target": "torrents_seeded"})
                self.assertEqual(c_tor.status_code, 200)
                self.assertEqual(c_tor.get_json()["deleted_count"], 1)

                # Unknown cleanup target returns 400
                bad = self.client.post("/api/storage/cleanup", headers=self.headers, json={"target": "rm_root"})
                self.assertEqual(bad.status_code, 400)


if __name__ == "__main__":
    unittest.main()

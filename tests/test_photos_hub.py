"""Unit and API tests for Phase 3B Photos Hub, ML scheduler, XMP parser, and folder health."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

HUB_DIR = Path(__file__).resolve().parents[1]
if str(HUB_DIR) not in sys.path:
    sys.path.insert(0, str(HUB_DIR))

import server  # noqa: E402
from widgets import cron_tasks, photos_hub  # noqa: E402


class TestPhotosHub(unittest.TestCase):
    def setUp(self) -> None:
        self.app = server.create_app()
        self.token = self.app.config["CONTROL_HUB_TOKEN"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.client = self.app.test_client()

    def test_ml_cron_parse_write_and_disable_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cron_file = str(Path(tmp) / "immich-ml")
            photos_hub.write_ml_cron_file(cron_file, True, "06:15", "11:30")
            parsed = photos_hub.parse_ml_cron_file(cron_file)
            self.assertTrue(parsed["exists"])
            self.assertTrue(parsed["enabled"])
            self.assertEqual(parsed["start_time"], "06:15")
            self.assertEqual(parsed["stop_time"], "11:30")

            # Cron tasks widget reflects enabled schedule
            sched, _ = cron_tasks._parse_immich_ml_schedule(cron_file, "IST")
            self.assertIn("06:15 (Start)", sched)
            self.assertIn("11:30 (Stop)", sched)

            # Now pause the schedule and confirm DISABLED state propagates
            photos_hub.write_ml_cron_file(cron_file, False, "06:15", "11:30")
            paused = photos_hub.parse_ml_cron_file(cron_file)
            self.assertFalse(paused["enabled"])
            self.assertEqual(paused["start_time"], "06:15")
            self.assertEqual(paused["stop_time"], "11:30")

            sched_paused, _ = cron_tasks._parse_immich_ml_schedule(cron_file, "IST")
            self.assertIn("Disabled (was 06:15", sched_paused)

    def test_ml_cron_validation_rejects_bad_or_equal_times(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cron_file = str(Path(tmp) / "immich-ml")
            with mock.patch.object(photos_hub, "IMMICH_ML_CRON_FILE", cron_file):
                r1 = self.client.post(
                    "/api/photos/ml/schedule",
                    headers=self.headers,
                    json={"enabled": True, "start_time": "25:00", "stop_time": "10:00"},
                )
                self.assertEqual(r1.status_code, 400)

                r2 = self.client.post(
                    "/api/photos/ml/schedule",
                    headers=self.headers,
                    json={"enabled": True, "start_time": "06:00", "stop_time": "06:00"},
                )
                self.assertEqual(r2.status_code, 400)

                r3 = self.client.post(
                    "/api/photos/ml/schedule",
                    headers=self.headers,
                    json={"enabled": True, "start_time": "05:30", "stop_time": "09:45"},
                )
                self.assertEqual(r3.status_code, 200)
                body = r3.get_json()
                self.assertTrue(body["ok"])
                self.assertEqual(body["schedule"]["start_time"], "05:30")
                self.assertEqual(body["schedule"]["stop_time"], "09:45")

    def test_parse_face_export_status_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "backup.log"
            cache_file = Path(tmp) / "cache.json"
            cache_file.write_text(json.dumps({"a": ["Alice"], "b": ["Bob"]}), encoding="utf-8")

            log_file.write_text(
                "\n".join([
                    "Starting Immich Backup: Tue Nov 24 22:00:01 IST 2026",
                    "[1/4] Running Face-to-XMP Exporter...",
                    "Found 1200 assets with named faces.",
                    "Pending export: 14 assets (skipped 1186 cached).",
                    "Batch export completed successfully!",
                    "[2/4] Creating PostgreSQL database dump...",
                ]),
                encoding="utf-8",
            )
            res = photos_hub.parse_face_export_status(str(log_file), str(cache_file), "IST")
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["files_written"], 14)
            self.assertEqual(res["cached_skipped"], 1186)
            self.assertEqual(res["errors"], 0)
            self.assertIn("Tue Nov 24", res["last_run"])

            # Error/warning block overwrites previous status
            log_file.write_text(
                "\n".join([
                    "Starting Immich Backup: Wed Nov 25 22:00:01 IST 2026",
                    "[1/4] Running Face-to-XMP Exporter...",
                    "Found 1200 assets with named faces.",
                    "Pending export: 2 assets (skipped 1198 cached).",
                    "ExifTool had warnings/errors: permission denied",
                    "[2/4] Creating PostgreSQL database dump...",
                ]),
                encoding="utf-8",
            )
            err_res = photos_hub.parse_face_export_status(str(log_file), str(cache_file), "IST")
            self.assertEqual(err_res["status"], "warning")
            self.assertEqual(err_res["errors"], 1)
            self.assertIn("ExifTool had warnings/errors", err_res["error_detail"])

    def test_probe_folder_health_missing_and_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            upload_dir = Path(tmp) / "upload"
            upload_dir.mkdir()
            (upload_dir / "sample.jpg").write_bytes(b"img")

            ok = photos_hub.probe_folder_health(str(upload_dir), "Upload Folder", "upload")
            self.assertTrue(ok["exists"])
            self.assertTrue(ok["readable"])
            self.assertEqual(ok["status"], "healthy")
            self.assertEqual(ok["unreadable_count"], 0)
            self.assertGreater(ok["total_gb"], 0)

            missing = photos_hub.probe_folder_health(str(Path(tmp) / "missing"), "External", "external")
            self.assertFalse(missing["exists"])
            self.assertEqual(missing["status"], "missing")

    def test_photos_overview_and_ml_action_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            upload_dir = Path(tmp) / "upload"
            upload_dir.mkdir()
            cron_file = Path(tmp) / "immich-ml"
            photos_hub.write_ml_cron_file(str(cron_file), True, "06:05", "10:00")

            fake_meta = {
                "disk_size": "264.3 GB",
                "disk_partial": False,
                "disk_reason": None,
                "photos_free_gb": 512.0,
                "photos_total_gb": 1800.0,
                "assets": {
                    "total_assets": 35765,
                    "photos_count": 33400,
                    "videos_count": 2365,
                    "named_people": 12,
                    "unhidden_people": 18,
                    "assets_with_named_faces": 18904,
                    "total_face_instances": 42000,
                    "offline_assets": 0,
                    "pending_faces": 49,
                    "pending_metadata": 2,
                    "users": [
                        {"name": "Hemonesh", "assets": 35762, "used_bytes": 281570581686, "quota_bytes": None},
                    ],
                    "libraries": [
                        {"name": "Stills", "paths": [str(upload_dir)], "refreshed_at": "2026-11-25T07:30:00Z", "assets": 100, "offline_assets": 0},
                    ],
                },
            }
            fake_redis = {
                "available": True,
                "total_active": 1,
                "total_waiting": 4,
                "total_delayed": 0,
                "total_failed": 0,
                "queues": [{"id": "faceDetection", "label": "Face Detection", "waiting": 4, "active": 1, "delayed": 0, "failed": 0}],
            }

            with mock.patch.object(photos_hub, "fetch_immich_library_telemetry", return_value=fake_meta), \
                 mock.patch.object(photos_hub, "_query_redis_queues", return_value=fake_redis), \
                 mock.patch.object(photos_hub, "IMMICH_ML_CRON_FILE", str(cron_file)), \
                 mock.patch.object(photos_hub, "PHOTO_UPLOAD_DIR", str(upload_dir)), \
                 mock.patch.object(photos_hub, "HDD_MEMORIES", str(upload_dir)), \
                 mock.patch.object(photos_hub.subprocess, "run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=0, stdout="true\n", stderr="")
                resp = self.client.get("/api/photos/overview", headers=self.headers)
                self.assertEqual(resp.status_code, 200)
                data = resp.get_json()
                self.assertTrue(data["installed"])
                self.assertEqual(data["library"]["offline_assets"], 0)
                self.assertEqual(len(data["users"]), 1)
                self.assertEqual(data["ml"]["queue"]["active"], 1)
                self.assertEqual(data["ml"]["schedule"]["start_time"], "06:05")

                # Invalid ML action returns 400; valid start returns 200
                bad = self.client.post("/api/photos/ml/action", headers=self.headers, json={"action": "restart"})
                self.assertEqual(bad.status_code, 400)

                act = self.client.post("/api/photos/ml/action", headers=self.headers, json={"action": "start"})
                self.assertEqual(act.status_code, 200)
                self.assertTrue(act.get_json()["ok"])


if __name__ == "__main__":
    unittest.main()

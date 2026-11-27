"""Unit and API tests for Phase 3F Schedules (next run, clash warnings, and schedule updates)."""

import datetime
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HUB_DIR = Path(__file__).resolve().parents[1]
if str(HUB_DIR) not in sys.path:
    sys.path.insert(0, str(HUB_DIR))

from widgets import cron_tasks  # noqa: E402


class TestPhase3FSchedules(unittest.TestCase):
    def test_detect_schedule_clashes_flags_backup_inside_sleep_and_overlap(self) -> None:
        jobs = [
            {"id": "server_suspend", "name": "Nightly Sleep Suspend", "enabled": True, "time_hhmm": "00:00", "wake_hhmm": "06:00"},
            {"id": "immich_backup", "name": "Photo Cloud Backup", "enabled": True, "time_hhmm": "01:00"},
            {"id": "media_backup", "name": "Media Settings Backup", "enabled": True, "time_hhmm": "01:10"},
        ]
        clashes = cron_tasks.detect_schedule_clashes(jobs)
        msgs = [c["message"] for c in clashes]
        self.assertTrue(any("Sleep Suspend window" in m and "Photo Cloud Backup" in m for m in msgs))
        self.assertTrue(any("within 15 min" in m for m in msgs))

        clean_jobs = [
            {"id": "server_suspend", "name": "Nightly Sleep Suspend", "enabled": True, "time_hhmm": "00:00", "wake_hhmm": "06:00"},
            {"id": "immich_backup", "name": "Photo Cloud Backup", "enabled": True, "time_hhmm": "22:00"},
            {"id": "media_backup", "name": "Media Settings Backup", "enabled": True, "time_hhmm": "21:30"},
        ]
        self.assertEqual(cron_tasks.detect_schedule_clashes(clean_jobs), [])

    def test_format_next_daily_today_vs_tomorrow(self) -> None:
        now = datetime.datetime(2026, 11, 27, 21, 0, 0)
        self.assertEqual(cron_tasks._format_next_daily(22, 0, "IST", now=now), "Today 22:00 IST")
        self.assertEqual(cron_tasks._format_next_daily(20, 30, "IST", now=now), "Tomorrow 20:30 IST")

    def test_cron_schedule_preview_and_update_route(self) -> None:
        import server

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            backup_cron = tmp_path / "immich-backup"
            backup_cron.write_text(
                "GDRIVE_REMOTE=gdrive:\n0 22 * * * root /usr/local/sbin/immich_backup_gdrive.sh >> /tmp/b.log 2>&1\n",
                encoding="utf-8",
            )
            env = {
                "CONTROL_HUB_TOKEN": "phase3f-test-token",
                "CONTROL_HUB_DATA_DIR": tmp,
            }
            with mock.patch.dict(os.environ, env, clear=False):
                app = server.create_app()
            client = app.test_client()
            headers = {"Authorization": "Bearer phase3f-test-token"}

            fake_suspend_cfg = {"enabled": True, "sleep_time": "00:00", "wake_time": "06:00", "duration_hours": 6.0}
            with mock.patch.object(cron_tasks, "BACKUP_CRON_FILE", str(backup_cron)), \
                 mock.patch.object(cron_tasks, "sleep_module_installed", return_value=True), \
                 mock.patch.object(cron_tasks, "load_permanent_config", return_value=fake_suspend_cfg), \
                 mock.patch.object(cron_tasks, "load_tonight_override", return_value=None):
                prev_res = client.post(
                    "/api/cron/schedule/immich_backup",
                    json={"time": "01:30", "enabled": True, "preview_only": True},
                    headers=headers,
                )
                self.assertEqual(prev_res.status_code, 200)
                prev_data = prev_res.get_json()
                self.assertTrue(any("Sleep Suspend window" in c["message"] for c in prev_data["clashes"]))
                # Preview must not mutate file on disk.
                self.assertIn("0 22 * * *", backup_cron.read_text(encoding="utf-8"))

                save_res = client.post(
                    "/api/cron/schedule/immich_backup",
                    json={"time": "21:15", "enabled": True},
                    headers=headers,
                )
                self.assertEqual(save_res.status_code, 200)
                self.assertIn("15 21 * * * root", backup_cron.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

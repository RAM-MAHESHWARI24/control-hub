"""Phase 2A: backup health states, stale detection, next run and history from status.json."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import backup_health  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 22, 9, 0, tzinfo=IST)


def status(**kw):
    base = {"status": "synced", "stage": 4, "message": "ok", "started_at": "2026-11-21T22:00:01+05:30",
            "completed_at": "2026-11-21T22:06:01+05:30", "last_good_at": "2026-11-21T22:06:01+05:30", "history": []}
    base.update(kw)
    return base


class TestStates(unittest.TestCase):
    def summarize(self, st, running=False, now=NOW):
        return backup_health.summarize(st, running=running, now=now, schedule=(22, 0), tz_abbr="IST")

    def test_unknown_without_status(self):
        s = self.summarize(None)
        self.assertEqual(s["state"], "unknown")
        self.assertFalse(s["is_red"])
        self.assertEqual(s["message"], "No backup run recorded yet")

    def test_synced_recent(self):
        s = self.summarize(status())
        self.assertEqual(s["state"], "synced")
        self.assertFalse(s["is_red"])
        self.assertEqual(s["age"], "10 h ago")
        self.assertEqual(s["next_run"], "2026-11-22 22:00 IST")

    def test_stale_after_26_hours(self):
        s = self.summarize(status(), now=NOW + timedelta(hours=17))
        self.assertEqual(s["state"], "stale")
        self.assertTrue(s["is_red"])
        self.assertIn("missed", s["message"])

    def test_error_and_old_good_run(self):
        s = self.summarize(status(status="error", stage=0, message="Pre-flight: remote did not answer"))
        self.assertEqual(s["state"], "error")
        self.assertTrue(s["is_red"])
        self.assertEqual(s["message"], "Pre-flight: remote did not answer")
        self.assertEqual(s["last_good"], "2026-11-21 22:06 IST")

    def test_interrupted_when_no_process(self):
        s = self.summarize(status(status="syncing", stage=3))
        self.assertEqual(s["state"], "interrupted")
        self.assertTrue(s["is_red"])
        s = self.summarize(status(status="syncing", stage=3), running=True)
        self.assertEqual(s["state"], "syncing")
        self.assertEqual(s["stage"], 3)

    def test_history_is_trimmed_and_formatted(self):
        hist = [{"started_at": f"2026-11-{d:02d}T22:00:01+05:30", "outcome": "synced", "dump_bytes": 356271570,
                 "bytes": 2048, "files": 2, "duration_s": 300} for d in range(20, 10, -1)]
        s = self.summarize(status(history=hist, retention={"kept": 16, "delete": ["a", "b"], "next_delete": ["c"]}))
        self.assertEqual(len(s["history"]), backup_health.HISTORY_SHOWN)
        self.assertEqual(s["history"][0]["when"], "2026-11-20 22:00 IST")
        self.assertEqual(s["history"][0]["dump_size"], "339.8 MB")
        self.assertEqual(s["retention"], {"kept": 16, "deleted_last_run": 2, "next_delete": ["c"]})


class TestRestoreTest(unittest.TestCase):
    def test_restore_result_is_formatted_and_a_failure_is_red(self):
        ok = backup_health.summarize(status(restore_test={"ok": True, "completed_at": "2026-12-06T11:07:30+05:30",
                                                          "restored": 35765, "dump_file": "d.sql.gz"}),
                                     running=False, now=NOW, tz_abbr="IST")
        self.assertEqual(ok["restore_test"]["when"], "2026-12-06 11:07 IST")
        self.assertFalse(ok["is_red"])
        bad = backup_health.summarize(status(restore_test={"ok": False, "message": "gzip test failed"}),
                                      running=False, now=NOW, tz_abbr="IST")
        self.assertTrue(bad["is_red"])
        self.assertIsNone(backup_health.summarize(status(), running=False, now=NOW)["restore_test"])


class TestSchedule(unittest.TestCase):
    def test_cron_time_and_next_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            cron = Path(tmp) / "immich-backup"
            cron.write_text("GDRIVE_REMOTE=x:\n30 21 * * * root /usr/local/sbin/immich_backup_gdrive.sh >> /x 2>&1\n", encoding="utf-8")
            self.assertEqual(backup_health.cron_time(str(cron)), (21, 30))
            self.assertIsNone(backup_health.cron_time(str(cron), "media_config_backup.py"))
            media = Path(tmp) / "media-backup"
            media.write_text("30 21 * * * root /usr/bin/python3 /opt/x/scripts/media_config_backup.py >> /x 2>&1\n", encoding="utf-8")
            self.assertEqual(backup_health.cron_time(str(media), "media_config_backup.py"), (21, 30))
            self.assertIsNone(backup_health.cron_time(str(Path(tmp) / "missing")))
        after = datetime(2026, 11, 22, 23, 0, tzinfo=IST)
        self.assertEqual(backup_health.next_run((22, 0), after).day, 23)


if __name__ == "__main__":
    unittest.main()

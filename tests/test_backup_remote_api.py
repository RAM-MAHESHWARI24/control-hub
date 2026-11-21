"""/api/backup/remotes, /api/backup/remote/test and PUT /api/backup/remote (root helper behind sudo)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestBackupRemoteApi(unittest.TestCase):
    def setUp(self):
        self._old_token = os.environ.get("CONTROL_HUB_TOKEN")
        os.environ["CONTROL_HUB_TOKEN"] = "remote-api-test-token-123456789"
        import server
        from widgets import backup_sync
        self.tmp = tempfile.TemporaryDirectory()
        self.helper = Path(self.tmp.name) / "homelab-backup-remote"
        self.helper.write_text("#!/bin/sh\n", encoding="utf-8")
        self.calls = []

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["sudo", str(self.helper)]:
                self.calls.append(cmd[2:])
                answers = {
                    "list": {"remotes": [{"name": "gdrive", "type": "drive"}], "current": "gdrive:"},
                    "test": {"ok": True, "remote": "gdrive:x/", "folders": {"Memories": False}},
                    "set": {"ok": True, "remote": "gdrive:x/", "changed": ["/etc/cron.d/immich-backup"]},
                }
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(answers[cmd[2]]) + "\n", stderr="")
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

        self.patches = [
            mock.patch.object(backup_sync, "BACKUP_REMOTE_HELPER", str(self.helper)),
            mock.patch.object(backup_sync.subprocess, "run", side_effect=fake_run),
        ]
        for p in self.patches:
            p.start()
        self.backup_sync = backup_sync
        self.client = server.create_app().test_client()
        self.h = {"Authorization": "Bearer remote-api-test-token-123456789"}

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()
        if self._old_token is None:
            os.environ.pop("CONTROL_HUB_TOKEN", None)
        else:
            os.environ["CONTROL_HUB_TOKEN"] = self._old_token

    def test_list_test_and_set_pass_one_argument_to_the_helper(self):
        self.assertEqual(self.client.get("/api/backup/remotes", headers=self.h).get_json()["current"], "gdrive:")
        res = self.client.post("/api/backup/remote/test", headers=self.h, json={"remote": "gdrive:x; rm -rf /"})
        self.assertTrue(res.get_json()["ok"])
        res = self.client.put("/api/backup/remote", headers=self.h, json={"remote": "gdrive:x"})
        self.assertEqual(res.get_json()["remote"], "gdrive:x/")
        self.assertEqual(self.calls, [["list"], ["test", "gdrive:x; rm -rf /"], ["set", "gdrive:x"]],
                         "the value goes to the helper as a single argument; the helper validates it")
        self.assertEqual(self.client.put("/api/backup/remote", json={"remote": "a:"}).status_code, 401)

    def test_hidden_without_the_helper(self):
        with mock.patch.object(self.backup_sync, "BACKUP_REMOTE_HELPER", str(Path(self.tmp.name) / "missing")):
            res = self.client.get("/api/backup/remotes", headers=self.h)
        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()

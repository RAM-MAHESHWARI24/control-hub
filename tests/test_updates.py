"""
Phase 2C: Available Updates & Release Alerts tests.
Covers core/updates.py version parsing, classify(), source_for(), report(),
API routes (/api/updates, /api/updates/check + cooldown), and alerts.collect_updates().
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import config  # noqa: E402
from core import alerts, updates  # noqa: E402
import server  # noqa: E402
from widgets import alerts as alerts_widget  # noqa: E402
from widgets import updates as updates_widget  # noqa: E402


class TestUpdatesCore(unittest.TestCase):
    def test_split_image_and_source_mapping(self) -> None:
        self.assertEqual(updates.split_image("lscr.io/linuxserver/radarr:7.0.3.10918-ls328"), ("lscr.io/linuxserver/radarr", "7.0.3.10918-ls328"))
        self.assertEqual(updates.split_image("ghcr.io/immich-app/immich-server:v2.1.0@sha256:abc"), ("ghcr.io/immich-app/immich-server", "v2.1.0"))
        self.assertEqual(updates.split_image("localhost:5000/custom/app"), ("localhost:5000/custom/app", "latest"))

        self.assertEqual(updates.source_for("lscr.io/linuxserver/sonarr"), ("linuxserver/docker-sonarr", None))
        self.assertEqual(updates.source_for("ghcr.io/seerr-team/seerr"), ("seerr-team/seerr", None))
        self.assertEqual(updates.source_for("ghcr.io/open-noodle/gallery-server"), ("open-noodle/gallery", None))
        repo, reason = updates.source_for("ghcr.io/immich-app/postgres")
        self.assertIsNone(repo)
        self.assertIn("Database engine", reason)

    def test_version_classification(self) -> None:
        self.assertEqual(updates.classify("v2.1.1", "v2.1.1"), "up_to_date")
        self.assertEqual(updates.classify("7.0.3.10918-ls327", "7.0.3.10918-ls328"), "rebuild")
        self.assertEqual(updates.classify("v2.1.0", "v2.2.0"), "update")
        self.assertEqual(updates.classify("v1.9.4", "v2.0.0"), "major")
        self.assertEqual(updates.classify("v2.3.0", "v2.2.0"), "newer_than_release")
        self.assertEqual(updates.classify("edge", "v1.0.0"), "unknown")

    def test_report_flags_floating_tags_and_pending_counts(self) -> None:
        containers = [
            {
                "container": "radarr", "image": "lscr.io/linuxserver/radarr:5.10.0-ls1",
                "project": "mediaserver", "service": "radarr",
                "working_dir": "/srv/stacks/media", "env_file": None,
            },
            {
                "container": "jellyfin", "image": "lscr.io/linuxserver/jellyfin:latest",
                "project": "mediaserver", "service": "jellyfin",
                "working_dir": "/srv/stacks/media", "env_file": None,
            },
            {
                "container": "seerr", "image": "ghcr.io/seerr-team/seerr:v1.9.0",
                "project": "mediaserver", "service": "seerr",
                "working_dir": "/srv/stacks/media", "env_file": None,
            },
            {
                "container": "immich_postgres", "image": "ghcr.io/immich-app/postgres:16-vectorchord",
                "project": "noodle", "service": "database",
                "working_dir": "/srv/stacks/photos", "env_file": None,
            },
        ]
        cache = {
            "checked_at": 1700000000.0,
            "repos": {
                "linuxserver/docker-radarr": {"tag": "5.11.0-ls1", "published": "2026-11-20", "url": "https://example.invalid/radarr"},
                "linuxserver/docker-jellyfin": {"tag": "10.10.0-ls1", "published": "2026-11-20", "url": "https://example.invalid/jf"},
                "seerr-team/seerr": {"tag": "v2.0.0", "published": "2026-11-21", "url": "https://example.invalid/seerr"},
                "RAM-MAHESHWARI24/homelab-blueprint": {"tag": "v2.1.1", "published": "2026-11-22", "url": "https://example.invalid/bp"},
            },
        }
        self_row = updates.blueprint_row("v2.1.1", cache, "RAM-MAHESHWARI24/homelab-blueprint")
        rep = updates.report(containers, cache, self_row=self_row)
        self.assertEqual(rep["pending"], 2)
        self.assertEqual(rep["majors"], 1)
        by_name = {r["container"]: r for r in rep["rows"]}
        self.assertEqual(by_name["control-hub"]["kind"], "up_to_date")
        self.assertEqual(by_name["radarr"]["kind"], "update")
        self.assertEqual(by_name["seerr"]["kind"], "major")
        self.assertEqual(by_name["jellyfin"]["kind"], "not_tracked")
        self.assertIn("Floating tag", by_name["jellyfin"]["reason"])
        self.assertEqual(by_name["immich_postgres"]["kind"], "not_tracked")

    def test_collect_updates_notifies_once_and_marks_major_as_warning(self) -> None:
        rep = {
            "rows": [
                {"container": "radarr", "image_name": "lscr.io/linuxserver/radarr", "current": "5.10.0-ls1", "latest": "5.11.0-ls1", "kind": "update", "kind_text": "Update available", "published": "2026-11-20", "release_url": "https://example.invalid/r", "command": "docker compose up -d radarr"},
                {"container": "seerr", "image_name": "ghcr.io/seerr-team/seerr", "current": "v1.9.0", "latest": "v2.0.0", "kind": "major", "kind_text": "Major version", "published": "2026-11-21", "release_url": "https://example.invalid/s", "command": "docker compose up -d seerr"},
            ]
        }
        state = {}
        first = alerts.collect_updates(rep, state)
        self.assertEqual(len(first), 2)
        self.assertEqual(first[0].severity, "info")
        self.assertEqual(first[1].severity, "warning")
        self.assertIn("Major update available", first[1].title)
        self.assertTrue(first[0].event and first[1].event)
        # Re-evaluating the same versions must not re-fire
        self.assertEqual(alerts.collect_updates(rep, state), [])


class TestUpdatesApi(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._orig_token = os.environ.get("CONTROL_HUB_TOKEN")
        os.environ["CONTROL_HUB_TOKEN"] = "updates-test-token-789"
        self.cache_path = root / "updates_cache.json"
        self._patches = [
            mock.patch.object(config, "UPDATES_CACHE_FILE", str(self.cache_path)),
            mock.patch.object(updates_widget, "UPDATES_CACHE_FILE", str(self.cache_path)),
            mock.patch.object(updates_widget, "UPDATES_AUTO_CHECK", False),
            mock.patch.object(alerts_widget.engine, "config_path", root / "alerts.json"),
            mock.patch.object(alerts_widget.engine, "state_path", root / "alerts_state.json"),
        ]
        for p in self._patches:
            p.start()
        self.client = server.create_app().test_client()
        self.headers = {"Authorization": "Bearer updates-test-token-789"}

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        if self._orig_token is None:
            os.environ.pop("CONTROL_HUB_TOKEN", None)
        else:
            os.environ["CONTROL_HUB_TOKEN"] = self._orig_token
        self._tmp.cleanup()

    def test_get_and_force_check_updates_with_cooldown(self) -> None:
        sample_containers = [
            {"container": "sonarr", "image": "lscr.io/linuxserver/sonarr:4.0.0-ls1", "project": "mediaserver", "service": "sonarr", "working_dir": "/srv/stacks/media", "env_file": None}
        ]
        repos_map = {
            "linuxserver/docker-sonarr": {"tag": "4.0.2-ls1", "published": "2026-11-24", "url": "https://example.invalid/sonarr"},
            updates_widget.UPDATES_BLUEPRINT_REPO: {"tag": f"v{updates_widget.APP_VERSION}", "published": "2026-11-24", "url": "https://example.invalid/bp"},
        }
        with (
            mock.patch.object(updates, "running_containers", return_value=sample_containers),
            mock.patch.object(updates, "fetch_latest", side_effect=lambda repo: repos_map.get(repo, {"error": "404"})),
        ):
            res_init = self.client.get("/api/updates", headers=self.headers)
            self.assertEqual(res_init.status_code, 200)
            self.assertIsNone(res_init.get_json()["checked_at"])

            # Seed an expired cache (> MIN_MANUAL_INTERVAL) then trigger a forced check
            self.cache_path.write_text(json.dumps({"checked_at": time.time() - 700, "repos": {}}), encoding="utf-8")
            res_check = self.client.post("/api/updates/check", headers=self.headers).get_json()
            self.assertFalse(res_check["throttled"])
            self.assertEqual(res_check["pending"], 1)

            # Second immediate manual check hits MIN_MANUAL_INTERVAL cooldown honestly
            res_throttled = self.client.post("/api/updates/check", headers=self.headers).get_json()
            self.assertTrue(res_throttled["throttled"])
            self.assertGreater(res_throttled["cooldown_remaining_s"], 0)


if __name__ == "__main__":
    unittest.main()

"""API & unit tests for Phase 3A Media controls (per-torrent actions, speed limits, Jellyfin streams)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

CH_DIR = Path(__file__).resolve().parent.parent
if str(CH_DIR) not in sys.path:
    sys.path.insert(0, str(CH_DIR))

import server  # noqa: E402
from core import telemetry_sampler  # noqa: E402
from widgets import current_downloads  # noqa: E402


class TestTorrentsAndStreamsApi(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_token = os.environ.get("CONTROL_HUB_TOKEN")
        os.environ["CONTROL_HUB_TOKEN"] = "torrents-test-token-3a"
        self.client = server.create_app().test_client()
        self.headers = {"Authorization": "Bearer torrents-test-token-3a"}

    def tearDown(self) -> None:
        if self._orig_token is None:
            os.environ.pop("CONTROL_HUB_TOKEN", None)
        else:
            os.environ["CONTROL_HUB_TOKEN"] = self._orig_token

    def test_per_torrent_action_validation_delete_and_fallback(self) -> None:
        bad = self.client.post("/api/torrents/not-a-hash/action", json={"action": "pause"}, headers=self.headers)
        self.assertEqual(bad.status_code, 400)

        h = "a" * 40
        calls = []

        def fake_post(ep, data):
            calls.append((ep, data))
            # Simulate qBittorrent 4.x returning 404 on /stop then 200 on /pause
            if ep.endswith("/stop"):
                return mock.Mock(status_code=404)
            return mock.Mock(status_code=200)

        with mock.patch.object(current_downloads, "_post_qbit", side_effect=fake_post):
            res = self.client.post(f"/api/torrents/{h}/action", json={"action": "pause"}, headers=self.headers)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(calls, [("/api/v2/torrents/stop", {"hashes": h}), ("/api/v2/torrents/pause", {"hashes": h})])

            calls.clear()
            del_res = self.client.post(
                f"/api/torrents/{h}/action",
                json={"action": "delete", "delete_files": True},
                headers=self.headers,
            )
            self.assertEqual(del_res.status_code, 200)
            self.assertEqual(calls, [("/api/v2/torrents/delete", {"hashes": h, "deleteFiles": "true"})])

    def test_limits_get_and_post(self) -> None:
        def fake_req(method, ep, data=None):
            if ep == "/api/v2/app/preferences":
                return mock.Mock(
                    status_code=200,
                    json=lambda: {"dl_limit": 0, "up_limit": 1048576, "alt_dl_limit": 2097152, "scheduler_enabled": True, "schedule_from_hour": 19, "schedule_to_hour": 23},
                )
            if ep == "/api/v2/transfer/info":
                return mock.Mock(status_code=200, json=lambda: {"dl_rate_limit": 5242880, "up_rate_limit": 1048576})
            if ep == "/api/v2/transfer/speedLimitsMode":
                return mock.Mock(status_code=200, text="1")
            return mock.Mock(status_code=200)

        with mock.patch.object(current_downloads, "_qbit_request", side_effect=fake_req):
            got = self.client.get("/api/torrents/limits", headers=self.headers).get_json()
            self.assertTrue(got["success"])
            self.assertEqual(got["dl_limit_kbps"], 5120)
            self.assertTrue(got["alt_speed_enabled"])
            self.assertTrue(got["scheduler_enabled"])

            upd = self.client.post(
                "/api/torrents/limits",
                json={"dl_limit_kbps": 4096, "scheduler_enabled": True, "schedule_from_hour": 20},
                headers=self.headers,
            )
            self.assertEqual(upd.status_code, 200)

    def test_jellyfin_streams_reports_user_title_and_play_method(self) -> None:
        fake_sessions = [
            {
                "UserName": "Alex",
                "RemoteEndPoint": "192.168.1.50",
                "DeviceName": "Living Room TV",
                "NowPlayingItem": {"Name": "Pilot", "SeriesName": "Andor"},
                "PlayState": {"PlayMethod": "Transcode", "IsPaused": False},
            }
        ]
        with mock.patch.object(telemetry_sampler, "JELLYFIN_API_KEY", "test-jf-key"), \
             mock.patch.object(telemetry_sampler, "JELLYFIN_URL", "http://127.0.0.1:8096"), \
             mock.patch.object(telemetry_sampler.requests, "get", return_value=mock.Mock(status_code=200, json=lambda: fake_sessions)):
            streams = telemetry_sampler.get_jellyfin_streams()
        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0]["user"], "Alex")
        self.assertEqual(streams[0]["title"], "Andor — Pilot")
        self.assertEqual(streams[0]["play_method"], "Transcode")
        self.assertEqual(streams[0]["status"], "Playing")


if __name__ == "__main__":
    unittest.main()

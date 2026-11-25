"""API & unit tests for Phase 3A Slice 2 (Indexer Health, Seerr Requests, *Arr Calendar/Wanted, Jellyfin Scan)."""

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
from widgets import indexers, media_hub  # noqa: E402


class TestMediaHubAndIndexersHealth(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_token = os.environ.get("CONTROL_HUB_TOKEN")
        os.environ["CONTROL_HUB_TOKEN"] = "media-hub-token-3a"
        self.client = server.create_app().test_client()
        self.headers = {"Authorization": "Bearer media-hub-token-3a"}

    def tearDown(self) -> None:
        if self._orig_token is None:
            os.environ.pop("CONTROL_HUB_TOKEN", None)
        else:
            os.environ["CONTROL_HUB_TOKEN"] = self._orig_token

    def test_indexers_health_and_fix_hints(self) -> None:
        def fake_call(path, method="GET", data=None, timeout=20):
            if path == "indexer":
                return 200, [
                    {"id": 1, "name": "1337x", "protocol": "torrent", "privacy": "public", "enable": True},
                    {"id": 2, "name": "Nyaa", "protocol": "torrent", "privacy": "public", "enable": True},
                ]
            if path == "indexerstatus":
                return 200, [{"indexerId": 1, "disabledTill": "2026-11-26T00:00:00Z", "mostRecentFailure": "2026-11-25T20:00:00Z"}]
            if path == "indexer/testall":
                return 200, [{"id": 1, "isValid": False, "validationFailures": [{"errorMessage": "Cloudflare challenge"}]}]
            return 404, {}

        with mock.patch.object(indexers, "_api_key", return_value="prowlarr-key"), \
             mock.patch.object(indexers, "_call", side_effect=fake_call):
            h = self.client.get("/api/indexers/health", headers=self.headers).get_json()
            self.assertTrue(h["reachable"])
            self.assertEqual(h["failing"], 1)
            self.assertEqual(h["indexers"][0]["name"], "1337x")
            self.assertIn("Byparr", h["indexers"][0]["fix_hint"])

            tested = self.client.post("/api/indexers/test-all", headers=self.headers).get_json()
            self.assertEqual(tested["status"], "ok")
            self.assertFalse(tested["results"][0]["ok"])

    def test_media_overview_unconfigured_is_honest(self) -> None:
        with mock.patch.object(media_hub, "SEERR_API_KEY", ""), \
             mock.patch.object(media_hub, "RADARR_API_KEY", ""), \
             mock.patch.object(media_hub, "SONARR_API_KEY", ""), \
             mock.patch.object(media_hub, "JELLYFIN_API_KEY", ""):
            ov = self.client.get("/api/media/overview", headers=self.headers).get_json()
            self.assertFalse(ov["requests"]["configured"])
            self.assertFalse(ov["calendar"]["configured"])
            self.assertFalse(ov["library"]["jellyfin"]["configured"])
            self.assertEqual(self.client.post("/api/media/jellyfin/scan", headers=self.headers).status_code, 400)

    def test_media_overview_requests_calendar_wanted_and_scan_configured(self) -> None:
        def fake_get(url, headers=None, params=None, timeout=4.0):
            if "/api/v1/request" in url:
                return 200, {"results": [{"id": 42, "type": "movie", "status": 1, "media": {"title": "Dune"}, "requestedBy": {"displayName": "Alex"}}]}
            if "7878/api/v3/calendar" in url:
                return 200, [{"title": "Interstellar", "digitalRelease": "2026-11-26T00:00:00Z", "hasFile": False}]
            if "7878/api/v3/wanted/missing" in url:
                return 200, {"records": [{"title": "Inception"}]}
            if "8989/api/v3/calendar" in url:
                return 200, [{"title": "Ep1", "airDate": "2026-11-27", "seasonNumber": 1, "episodeNumber": 2, "series": {"title": "Andor"}, "hasFile": True}]
            if "8989/api/v3/wanted/missing" in url:
                return 200, {"records": [{"seasonNumber": 1, "episodeNumber": 3, "series": {"title": "Andor"}}]}
            if "/Items/Latest" in url:
                return 200, [{"Name": "Arrival", "Type": "Movie", "ProductionYear": 2016}]
            return 404, None

        with mock.patch.object(media_hub, "SEERR_API_KEY", "seerr-k"), \
             mock.patch.object(media_hub, "RADARR_API_KEY", "radarr-k"), \
             mock.patch.object(media_hub, "SONARR_API_KEY", "sonarr-k"), \
             mock.patch.object(media_hub, "JELLYFIN_API_KEY", "jf-k"), \
             mock.patch.object(media_hub, "_api_get", side_effect=fake_get), \
             mock.patch.object(media_hub, "_api_post", return_value=(204, None)) as post_mock:
            ov = self.client.get("/api/media/overview", headers=self.headers).get_json()
            self.assertEqual(ov["requests"]["items"][0]["title"], "Dune")
            self.assertEqual(len(ov["calendar"]["items"]), 2)
            self.assertEqual(len(ov["library"]["wanted"]), 2)
            self.assertEqual(ov["library"]["jellyfin"]["recent"][0]["name"], "Arrival")

            dec = self.client.post("/api/media/requests/42/approve", headers=self.headers)
            self.assertEqual(dec.status_code, 200)
            scan = self.client.post("/api/media/jellyfin/scan", headers=self.headers)
            self.assertEqual(scan.status_code, 200)
            self.assertEqual(post_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()

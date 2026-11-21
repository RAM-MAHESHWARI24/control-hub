"""PUT /api/tv-updater/devices/<id>/nickname: rename a TV from the dashboard."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestTvNicknameApi(unittest.TestCase):
    def setUp(self):
        self._old_token = os.environ.get("CONTROL_HUB_TOKEN")
        os.environ["CONTROL_HUB_TOKEN"] = "tv-names-test-token-1234567890"
        import server
        from widgets import tv_updater as widget

        self.saved = {}

        def set_nickname(device_id, nickname):
            if device_id != "living_room_tv":
                raise KeyError(device_id)
            name = " ".join(str(nickname).split())
            if len(name) > 40:
                raise ValueError("A name can have at most 40 characters.")
            self.saved[device_id] = name or None
            return name or None

        self.patches = [
            mock.patch.object(widget, "tv_module_installed", return_value=True),
            mock.patch.object(widget, "tv_updater", SimpleNamespace(set_nickname=set_nickname)),
        ]
        for p in self.patches:
            p.start()
        self.widget = widget
        self.client = server.create_app().test_client()
        self.h = {"Authorization": "Bearer tv-names-test-token-1234567890"}

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        if self._old_token is None:
            os.environ.pop("CONTROL_HUB_TOKEN", None)
        else:
            os.environ["CONTROL_HUB_TOKEN"] = self._old_token

    def url(self, device_id):
        return f"/api/tv-updater/devices/{device_id}/nickname"

    def test_rename_clear_and_errors(self):
        self.widget.telemetry_cache["last_fetched"] = 123
        res = self.client.put(self.url("living_room_tv"), headers=self.h, json={"nickname": " Living  room "})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["nickname"], "Living room")
        self.assertEqual(self.widget.telemetry_cache["last_fetched"], 0, "the next poll shows the new name")

        res = self.client.put(self.url("living_room_tv"), headers=self.h, json={"nickname": ""})
        self.assertIsNone(res.get_json()["nickname"])
        self.assertEqual(self.client.put(self.url("garage_tv"), headers=self.h, json={"nickname": "x"}).status_code, 404)
        self.assertEqual(self.client.put(self.url("living_room_tv"), headers=self.h, json={"nickname": "x" * 41}).status_code, 400)
        self.assertEqual(self.client.put(self.url("living_room_tv"), json={"nickname": "x"}).status_code, 401)

    def test_not_installed(self):
        with mock.patch.object(self.widget, "tv_module_installed", return_value=False):
            self.assertEqual(self.client.put(self.url("living_room_tv"), headers=self.h, json={"nickname": "x"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()

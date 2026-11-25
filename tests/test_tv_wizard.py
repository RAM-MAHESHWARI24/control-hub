"""API tests for Guided Add-a-TV wizard and TV profile CRUD endpoints (Phase 2D)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CH_DIR = Path(__file__).resolve().parent.parent
if str(CH_DIR) not in sys.path:
    sys.path.insert(0, str(CH_DIR))

import server  # noqa: E402
from widgets import tv_updater as tv_widget  # noqa: E402


class _FakeTvModule:
    def __init__(self) -> None:
        self.profiles = [
            {"id": "living_room_tv", "name": "Living Room TV", "default_ip": "192.168.1.34", "port": 5555, "paused": False}
        ]

    def scan_lan_adb_devices(self, port: int = 5555):
        return [
            {"ip": "192.168.1.34", "port": port, "already_added": True, "device_id": "living_room_tv", "name": "Living Room TV"},
            {"ip": "192.168.1.77", "port": port, "already_added": False, "device_id": None, "name": None},
        ]

    def connect_adb_tv(self, ip: str, port: int = 5555):
        if ip == "192.168.1.77":
            return {
                "ok": True,
                "connected": True,
                "needs_auth": False,
                "ip": ip,
                "port": port,
                "model": "BRAVIA 4K",
                "manufacturer": "Sony",
                "android": "12",
                "suggested_name": "Sony BRAVIA 4K",
                "apps": [{"id": "smarttube", "package": "org.smarttube.stable", "name": "SmartTube"}],
                "message": "Connected to Sony BRAVIA 4K (Android 12).",
            }
        return {"ok": False, "connected": False, "needs_auth": True, "ip": ip, "port": port, "message": "Look at your TV screen and choose 'Always allow'."}

    def add_tv_profile(self, name: str, ip: str, port: int = 5555, apps=None, probe=None):
        prof = {"id": "sony_bravia_4k", "name": name, "default_ip": ip, "port": port, "paused": False, "apps": apps or []}
        self.profiles.append(prof)
        return prof

    def update_tv_profile(self, device_id: str, **kwargs):
        p = next((x for x in self.profiles if x["id"] == device_id), None)
        if not p:
            raise KeyError(device_id)
        for k, v in kwargs.items():
            if v is not None:
                p[k] = v
        return p

    def test_tv_connection(self, device_id: str):
        p = next((x for x in self.profiles if x["id"] == device_id), None)
        if not p:
            raise KeyError(device_id)
        return {"ok": True, "connected": True, "needs_auth": False, "ip": p["default_ip"], "message": "Online"}

    def remove_tv_profile(self, device_id: str):
        before = len(self.profiles)
        self.profiles = [x for x in self.profiles if x["id"] != device_id]
        if len(self.profiles) == before:
            raise KeyError(device_id)


class TestTvWizardApi(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.fake_script = Path(self._tmp.name) / "tv_updater.py"
        self.fake_script.write_text("# stub\n", encoding="utf-8")
        self._orig_token = os.environ.get("CONTROL_HUB_TOKEN")
        os.environ["CONTROL_HUB_TOKEN"] = "tv-wizard-token-999"
        self.fake_mod = _FakeTvModule()
        self._patches = [
            mock.patch.object(tv_widget, "TV_UPDATER_PY", str(self.fake_script)),
            mock.patch.object(tv_widget, "tv_updater", self.fake_mod),
        ]
        for p in self._patches:
            p.start()
        self.client = server.create_app().test_client()
        self.headers = {"Authorization": "Bearer tv-wizard-token-999"}

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        if self._orig_token is None:
            os.environ.pop("CONTROL_HUB_TOKEN", None)
        else:
            os.environ["CONTROL_HUB_TOKEN"] = self._orig_token
        self._tmp.cleanup()

    def test_wizard_scan_connect_and_device_crud(self) -> None:
        scan = self.client.post("/api/tv-updater/scan-lan", json={}, headers=self.headers)
        self.assertEqual(scan.status_code, 200)
        self.assertEqual(len(scan.get_json()["candidates"]), 2)

        auth = self.client.post("/api/tv-updater/connect", json={"ip": "192.168.1.88"}, headers=self.headers)
        self.assertEqual(auth.status_code, 200)
        self.assertTrue(auth.get_json()["needs_auth"])

        conn = self.client.post("/api/tv-updater/connect", json={"ip": "192.168.1.77"}, headers=self.headers)
        self.assertEqual(conn.status_code, 200)
        self.assertEqual(conn.get_json()["suggested_name"], "Sony BRAVIA 4K")

        created = self.client.post(
            "/api/tv-updater/devices",
            json={"name": "Den TV", "ip": "192.168.1.77", "apps": ["org.smarttube.stable"]},
            headers=self.headers,
        )
        self.assertEqual(created.status_code, 201)
        dev_id = created.get_json()["device"]["id"]

        patched = self.client.patch(
            f"/api/tv-updater/devices/{dev_id}",
            json={"name": "Theater TV", "paused": True},
            headers=self.headers,
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.get_json()["device"]["name"], "Theater TV")
        self.assertTrue(patched.get_json()["device"]["paused"])

        tested = self.client.post(f"/api/tv-updater/devices/{dev_id}/test", headers=self.headers)
        self.assertEqual(tested.status_code, 200)
        self.assertTrue(tested.get_json()["ok"])

        removed = self.client.delete(f"/api/tv-updater/devices/{dev_id}", headers=self.headers)
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(self.client.delete(f"/api/tv-updater/devices/{dev_id}", headers=self.headers).status_code, 404)

    def test_wizard_endpoints_return_404_when_module_uninstalled(self) -> None:
        with mock.patch.object(tv_widget, "TV_UPDATER_PY", ""):
            self.assertEqual(self.client.post("/api/tv-updater/scan-lan", json={}, headers=self.headers).status_code, 404)
            self.assertEqual(self.client.post("/api/tv-updater/devices", json={}, headers=self.headers).status_code, 404)


if __name__ == "__main__":
    unittest.main()

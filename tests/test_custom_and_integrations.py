"""Tests for Phase 4E: Scoped API Tokens (`read` vs `full`), Home Assistant export, and NUT UPS probe."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CONTROL_HUB_ROOT = Path(__file__).resolve().parent.parent
if str(CONTROL_HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(CONTROL_HUB_ROOT))

import server as srv  # noqa: E402
from core import auth, sessions  # noqa: E402
from core.config_core import auth_password  # noqa: E402
from widgets import integrations  # noqa: E402


class TestPhase4CustomAndIntegrations(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        pw_path = Path(self._tmp.name) / "password"

        patch_pw = mock.patch.object(auth_password, "PASSWORD_FILE", pw_path)
        patch_pw.start()
        self.addCleanup(patch_pw.stop)

        orig_tok = os.environ.get("CONTROL_HUB_TOKEN")

        def restore_tok():
            if orig_tok is None:
                os.environ.pop("CONTROL_HUB_TOKEN", None)
            else:
                os.environ["CONTROL_HUB_TOKEN"] = orig_tok

        self.addCleanup(restore_tok)

        auth._failures.clear()
        self.owner_pw = "owner-tokens-alpha"
        auth_password.set_password(self.owner_pw, path=pw_path)
        os.environ["CONTROL_HUB_TOKEN"] = "phase4de-master-token"

        self.app = srv.create_app()
        self.app.config["CONTROL_HUB_TOKEN"] = "phase4de-master-token"
        self.client = self.app.test_client()
        self.master_hdrs = {"Authorization": f"Bearer {self.app.config['CONTROL_HUB_TOKEN']}"}

    def test_scoped_api_tokens_read_only_vs_full_and_revocation(self) -> None:
        # Create a read-only token and a full-access token
        r_ro = self.client.post(
            "/api/auth/tokens",
            headers=self.master_hdrs,
            json={"name": "Home Assistant Sensors", "scope": "read"},
        )
        self.assertEqual(r_ro.status_code, 201)
        ro_secret = r_ro.get_json()["token"]
        ro_id = r_ro.get_json()["record"]["id"]
        self.assertTrue(ro_secret.startswith("hub_ro_"))

        r_rw = self.client.post(
            "/api/auth/tokens",
            headers=self.master_hdrs,
            json={"name": "Nightly Automation", "scope": "full"},
        )
        self.assertEqual(r_rw.status_code, 201)
        rw_secret = r_rw.get_json()["token"]
        self.assertTrue(rw_secret.startswith("hub_rw_"))

        # Tokens are stored hashed (plaintext never persists)
        raw_disk = sessions.tokens_file().read_text(encoding="utf-8")
        self.assertNotIn(ro_secret, raw_disk)
        self.assertNotIn(rw_secret, raw_disk)

        ro_hdrs = {"Authorization": f"Bearer {ro_secret}"}
        rw_hdrs = {"Authorization": f"Bearer {rw_secret}"}

        # Read-only token can query read endpoints, reports scope=read, cannot inspect/mutate tokens or post
        st = self.client.get("/api/auth/status", headers=ro_hdrs).get_json()
        self.assertTrue(st["authenticated"])
        self.assertEqual(st["token_scope"], "read")
        self.assertEqual(self.client.get("/api/integrations/homeassistant", headers=ro_hdrs).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/tokens", headers=ro_hdrs).status_code, 403)
        post_denied = self.client.post("/api/sleep/toggle", headers=ro_hdrs, json={})
        self.assertEqual(post_denied.status_code, 403)
        self.assertEqual(post_denied.get_json()["error"], "insufficient_scope")

        # Full-access token can manage tokens
        self.assertEqual(self.client.get("/api/auth/tokens", headers=rw_hdrs).status_code, 200)

        # Revoking read-only token rejects subsequent requests cleanly
        self.assertEqual(self.client.delete(f"/api/auth/tokens/{ro_id}", headers=rw_hdrs).status_code, 200)
        self.assertEqual(self.client.get("/api/integrations/homeassistant", headers=ro_hdrs).status_code, 401)

    def test_nut_ups_honest_missing_and_low_battery_parse(self) -> None:
        with mock.patch("widgets.integrations.shutil.which", return_value=None):
            missing = integrations.probe_ups_nut()
        self.assertFalse(missing["installed"])
        self.assertEqual(missing["status"], "not_installed")

        upsc_list = mock.Mock(returncode=0, stdout="apc-bx1500\n", stderr="")
        upsc_data = mock.Mock(
            returncode=0,
            stdout=(
                "ups.model: Back-UPS BX1500M\n"
                "ups.status: OB DISCHRG LB\n"
                "battery.charge: 14\n"
                "battery.runtime: 240\n"
                "input.voltage: 0.0\n"
                "ups.load: 28\n"
            ),
            stderr="",
        )
        with mock.patch("widgets.integrations.shutil.which", return_value="/bin/upsc"), mock.patch(
            "widgets.integrations.subprocess.run", side_effect=[upsc_list, upsc_data]
        ):
            parsed = integrations.probe_ups_nut()
        self.assertTrue(parsed["installed"])
        self.assertTrue(parsed["on_battery"])
        self.assertTrue(parsed["low_battery"])
        self.assertEqual(parsed["status"], "low_battery")
        self.assertEqual(parsed["battery_charge"], 14.0)
        self.assertEqual(parsed["battery_runtime_s"], 240)
        self.assertIsNotNone(parsed["shutdown_action"])

    def test_home_assistant_route_exposes_sensors_and_yaml(self) -> None:
        self.assertEqual(self.client.get("/api/integrations/homeassistant").status_code, 401)
        res = self.client.get("/api/integrations/homeassistant", headers=self.master_hdrs)
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertIn("sensors", body)
        self.assertIn("disk_pool_pct", body["sensors"])
        self.assertIn("backup_state", body["sensors"])
        self.assertIn("sleep_skip_tonight", body["sensors"])
        self.assertIn("homelab_toggle_prevent_sleep", body["yaml_snippet"])


if __name__ == "__main__":
    unittest.main()

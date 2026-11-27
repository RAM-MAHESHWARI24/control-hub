"""Tests for Phase 4A (Tailscale Remote HTTPS & X-Forwarded-Proto) and Phase 4F (Troubleshoot runner)."""

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
from core import auth  # noqa: E402
from core.config_core import auth_password  # noqa: E402
from widgets import network_speed  # noqa: E402


class TestPhase4RemoteHelp(unittest.TestCase):
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

        self.owner_pw = "owner-demo-alpha"
        self.family_pw = "family-demo-beta"

        auth._failures.clear()
        auth_password.set_password(self.owner_pw, path=pw_path)
        os.environ["CONTROL_HUB_TOKEN"] = "phase4a4f-test-token"

        self.app = srv.create_app()
        self.app.config["CONTROL_HUB_TOKEN"] = "phase4a4f-test-token"
        self.client = self.app.test_client()
        self.owner_headers = {"Authorization": f"Bearer {self.app.config['CONTROL_HUB_TOKEN']}"}

    def test_x_forwarded_proto_sets_secure_session_cookie(self) -> None:
        r_http = self.client.post("/api/auth/login", json={"password": self.owner_pw})
        self.assertEqual(r_http.status_code, 200)
        cookie_http = "; ".join(r_http.headers.getlist("Set-Cookie"))
        self.assertIn("hub_session=", cookie_http)
        self.assertNotIn("Secure", cookie_http)

        r_https = self.client.post(
            "/api/auth/login",
            json={"password": self.owner_pw},
            headers={"X-Forwarded-Proto": "https"},
        )
        self.assertEqual(r_https.status_code, 200)
        cookie_https = "; ".join(r_https.headers.getlist("Set-Cookie"))
        self.assertIn("hub_session=", cookie_https)
        self.assertIn("Secure", cookie_https)

    def test_probe_tailscale_https_detects_serve_status(self) -> None:
        ts_data = {
            "installed": True,
            "connected": True,
            "dns_name": "mybox.tailnet.ts.net",
        }
        fake_serve = mock.Mock(
            returncode=0,
            stdout='{"TCP":{"443":{"HTTPS":true}},"Web":{"mybox.tailnet.ts.net:443":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:7575"}}}}}',
            stderr="",
        )
        with mock.patch("widgets.network_speed.shutil.which", return_value="/usr/bin/tailscale"), mock.patch(
            "widgets.network_speed.subprocess.run", return_value=fake_serve
        ):
            info = network_speed.probe_tailscale_https(ts_data, 7575)

        self.assertTrue(info["serve_active"])
        self.assertEqual(info["https_url"], "https://mybox.tailnet.ts.net")
        self.assertEqual(info["serve_cmd"], "sudo tailscale serve --bg 7575")
        self.assertEqual(info["cert_cmd"], "sudo tailscale cert mybox.tailnet.ts.net")
        self.assertIn("mybox.tailnet.ts.net:443", info["serve_targets"])

        disconn = network_speed.probe_tailscale_https({"installed": False, "connected": False}, 7575)
        self.assertFalse(disconn["serve_active"])
        self.assertIsNone(disconn["https_url"])

    def test_troubleshoot_endpoint_rbac_and_plain_word_checks(self) -> None:
        self.assertEqual(self.client.get("/api/troubleshoot").status_code, 401)

        r_acc = self.client.post(
            "/api/auth/access",
            headers=self.owner_headers,
            json={"family_enabled": True, "family_lan_open": False, "family_password": self.family_pw},
        )
        self.assertEqual(r_acc.status_code, 200)
        fam_client = self.app.test_client()
        self.assertEqual(fam_client.post("/api/auth/login", json={"password": self.family_pw}).status_code, 200)
        self.assertEqual(fam_client.get("/api/troubleshoot").status_code, 403)

        with mock.patch(
            "widgets.troubleshoot.network_speed.probe_network_interfaces",
            return_value={
                "interfaces": [
                    {
                        "name": "eth0",
                        "degraded": True,
                        "warning": "Running at 100 Mbps half duplex.",
                    }
                ]
            },
        ), mock.patch(
            "widgets.troubleshoot.network_speed.probe_tailscale_status",
            return_value={"installed": True, "connected": True, "dns_name": "box.ts.net"},
        ), mock.patch(
            "widgets.troubleshoot.network_speed.probe_tailscale_https",
            return_value={"serve_active": False},
        ), mock.patch(
            "widgets.troubleshoot.network_speed.build_port_map",
            return_value=([], []),
        ), mock.patch(
            "widgets.troubleshoot.indexers.indexers_health",
            return_value=self.app.response_class(
                response='{"installed":true,"reachable":true,"total":2,"failing":1}',
                mimetype="application/json",
            ),
        ):
            r = self.client.get("/api/troubleshoot", headers=self.owner_headers)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn(body["overall_status"], ("ok", "warn", "fail"))
        by_id = {c["id"]: c for c in body["checks"]}
        self.assertEqual(by_id["network_ports"]["status"], "warn")
        self.assertIn("half duplex", by_id["network_ports"]["summary"])
        self.assertEqual(by_id["prowlarr_indexers"]["status"], "warn")
        self.assertTrue(len(by_id["prowlarr_indexers"]["fix_steps"]) >= 1)
        self.assertIn("explanation", by_id["storage_capacity"])
        self.assertIn("hardlinks", by_id)


if __name__ == "__main__":
    unittest.main()

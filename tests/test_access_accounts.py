"""
Phase 3G Access & Accounts regression suite:
- Server-side per-device session store & individual / bulk revocation
- Read-only Family View (password mode, LAN-only mode, Tailscale/WAN isolation, 403 RBAC)
- Optional owner TOTP 2FA setup, challenge, recovery code consumption, and disable
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from werkzeug.test import Client
from werkzeug.wrappers import Response

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

_TMP_DIR = tempfile.mkdtemp(prefix="hub_access_test_")
_TEST_TOKEN = "local-unit-test-token"
os.environ["CONTROL_HUB_TOKEN"] = _TEST_TOKEN
os.environ["CONTROL_HUB_PASSWORD_FILE"] = str(Path(_TMP_DIR) / "password")

import server  # noqa: E402
from core import auth, sessions, totp  # noqa: E402
from core.config_core import auth_password  # noqa: E402


class FlaskClient(Client):
    def __init__(self, app, **kwargs):
        super().__init__(app, Response, **kwargs)


class TestPhase3GAccessAndAccounts(unittest.TestCase):
    def setUp(self):
        self.pw_dir = tempfile.mkdtemp(prefix="hub_pw_3g_")
        self.pw_file = Path(self.pw_dir) / "password"
        self.patcher = mock.patch.object(auth_password, "PASSWORD_FILE", self.pw_file)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

        self.owner_pw = "owner-demo-alpha"
        self.family_pw = "family-demo-beta"

        auth._failures.clear()
        auth_password.set_password(self.owner_pw, path=self.pw_file)
        self.app = server.create_app()
        self.app.config["CONTROL_HUB_TOKEN"] = _TEST_TOKEN

    def test_per_device_sessions_and_selective_revocation(self):
        dev1 = FlaskClient(self.app, use_cookies=True)
        dev2 = FlaskClient(self.app, use_cookies=True)

        r1 = dev1.post(
            "/api/auth/login",
            json={"password": self.owner_pw},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/125.0.0.0"},
        )
        r2 = dev2.post(
            "/api/auth/login",
            json={"password": self.owner_pw},
            headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/605.1"},
        )
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        sid2 = r2.get_json()["session_id"]

        listed = dev1.get("/api/auth/sessions")
        self.assertEqual(listed.status_code, 200)
        items = listed.get_json()["sessions"]
        self.assertEqual(len(items), 2)
        devices = {s["device"] for s in items}
        self.assertIn("Chrome on Windows", devices)
        self.assertIn("Safari on iPhone", devices)

        # Sign out device 2 individually; device 1 stays active
        rev = dev1.delete(f"/api/auth/sessions/{sid2}")
        self.assertEqual(rev.status_code, 200)
        self.assertEqual(dev2.get("/api/auth/check").status_code, 401)
        self.assertEqual(dev1.get("/api/auth/check").status_code, 200)

    def test_family_view_rbac_and_lan_ip_guard(self):
        owner = FlaskClient(self.app, use_cookies=True)
        self.assertEqual(owner.post("/api/auth/login", json={"password": self.owner_pw}).status_code, 200)

        # Configure family view with dedicated password
        res = owner.post("/api/auth/access", json={
            "family_enabled": True,
            "family_lan_open": False,
            "family_password": self.family_pw,
        })
        self.assertEqual(res.status_code, 200)

        fam = FlaskClient(self.app, use_cookies=True)
        login_res = fam.post("/api/auth/login", json={"password": self.family_pw})
        self.assertEqual(login_res.status_code, 200)
        self.assertEqual(login_res.get_json()["role"], "family")

        # Read-only status/media allowed; owner settings & mutations blocked 403
        self.assertEqual(fam.get("/api/auth/check").get_json()["role"], "family")
        self.assertEqual(fam.get("/api/system/vitals").status_code, 200)
        self.assertEqual(fam.get("/api/services/status").status_code, 200)
        self.assertEqual(fam.get("/api/media/overview").status_code, 200)
        self.assertEqual(fam.get("/api/config/current").status_code, 403)
        self.assertEqual(fam.get("/api/alerts").status_code, 403)
        self.assertEqual(fam.get("/api/auth/sessions").status_code, 403)
        self.assertEqual(fam.post("/api/services/restart/jellyfin").status_code, 403)
        self.assertEqual(fam.post("/api/media/requests/1/approve").status_code, 403)

        # Enable passwordless local LAN mode: RFC1918 & loopback allowed, Tailscale CGNAT & public WAN denied
        self.assertEqual(owner.post("/api/auth/access", json={"family_enabled": True, "family_lan_open": True}).status_code, 200)
        self.assertTrue(sessions.is_local_lan_ip("192.168.1.44"))
        self.assertTrue(sessions.is_local_lan_ip("10.0.0.15"))
        self.assertFalse(sessions.is_local_lan_ip("100.87.10.2"))
        self.assertFalse(sessions.is_local_lan_ip("203.0.113.9"))

        lan_client = FlaskClient(self.app)
        self.assertEqual(lan_client.get("/api/auth/status", environ_base={"REMOTE_ADDR": "192.168.1.44"}).get_json()["role"], "family")
        self.assertEqual(lan_client.get("/api/system/vitals", environ_base={"REMOTE_ADDR": "192.168.1.44"}).status_code, 200)
        self.assertEqual(lan_client.get("/api/config/current", environ_base={"REMOTE_ADDR": "192.168.1.44"}).status_code, 403)
        self.assertEqual(lan_client.get("/api/system/vitals", environ_base={"REMOTE_ADDR": "100.87.10.2"}).status_code, 401)
        self.assertEqual(lan_client.get("/api/system/vitals", environ_base={"REMOTE_ADDR": "203.0.113.9"}).status_code, 401)

    def test_optional_totp_setup_challenge_recovery_and_disable(self):
        owner = FlaskClient(self.app, use_cookies=True)
        self.assertEqual(owner.post("/api/auth/login", json={"password": self.owner_pw}).status_code, 200)

        setup_res = owner.post("/api/auth/totp/setup")
        self.assertEqual(setup_res.status_code, 200)
        secret = setup_res.get_json()["secret"]
        self.assertIn("otpauth://totp/", setup_res.get_json()["uri"])

        # Bad code fails activation
        self.assertEqual(owner.post("/api/auth/totp/enable", json={"code": "000000"}).status_code, 400)

        live_code = totp.totp_code(secret)
        enable_res = owner.post("/api/auth/totp/enable", json={"code": live_code})
        self.assertEqual(enable_res.status_code, 200)
        recovery_codes = enable_res.get_json()["recovery_codes"]
        self.assertEqual(len(recovery_codes), 6)

        # Password-only login now asks for TOTP
        fresh = FlaskClient(self.app, use_cookies=True)
        chal = fresh.post("/api/auth/login", json={"password": self.owner_pw})
        self.assertEqual(chal.status_code, 401)
        self.assertTrue(chal.get_json().get("totp_required"))

        # Valid live TOTP code succeeds
        ok_login = fresh.post("/api/auth/login", json={"password": self.owner_pw, "code": totp.totp_code(secret)})
        self.assertEqual(ok_login.status_code, 200)

        # One-time recovery code succeeds once and fails on replay
        rec_client = FlaskClient(self.app, use_cookies=True)
        self.assertEqual(rec_client.post("/api/auth/login", json={"password": self.owner_pw, "code": recovery_codes[0]}).status_code, 200)
        rec_replay = FlaskClient(self.app, use_cookies=True)
        self.assertEqual(rec_replay.post("/api/auth/login", json={"password": self.owner_pw, "code": recovery_codes[0]}).status_code, 401)

        # Wrong password cannot disable TOTP; right password disables it cleanly
        self.assertEqual(owner.post("/api/auth/totp/disable", json={"password": "wrong"}).status_code, 403)
        self.assertEqual(owner.post("/api/auth/totp/disable", json={"password": self.owner_pw}).status_code, 200)
        self.assertFalse(owner.get("/api/auth/status").get_json()["totp_enabled"])


if __name__ == "__main__":
    unittest.main()

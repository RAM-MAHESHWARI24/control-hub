"""Tests for Phase 4B (PWA manifest & Service Worker) and Phase 4C (History rollups & Monthly insights)."""

import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

CONTROL_HUB_ROOT = Path(__file__).resolve().parent.parent
if str(CONTROL_HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(CONTROL_HUB_ROOT))

import config  # noqa: E402
import server as srv  # noqa: E402
from core import auth, metrics_history  # noqa: E402
from core.config_core import auth_password  # noqa: E402


class TestHistoryAndPwa(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp_dir = Path(self._tmp.name)

        pw_path = tmp_dir / "password"
        hist_path = tmp_dir / "telemetry_history.json"

        patch_pw = mock.patch.object(auth_password, "PASSWORD_FILE", pw_path)
        patch_pw.start()
        self.addCleanup(patch_pw.stop)

        patch_hist = mock.patch.object(config, "TELEMETRY_HISTORY_FILE", str(hist_path))
        patch_hist.start()
        self.addCleanup(patch_hist.stop)

        orig_tok = os.environ.get("CONTROL_HUB_TOKEN")

        def restore_tok():
            metrics_history._reset_for_tests()
            if orig_tok is None:
                os.environ.pop("CONTROL_HUB_TOKEN", None)
            else:
                os.environ["CONTROL_HUB_TOKEN"] = orig_tok

        self.addCleanup(restore_tok)

        metrics_history._reset_for_tests()
        auth._failures.clear()
        self.owner_pw = "owner-history-pw"
        auth_password.set_password(self.owner_pw, path=pw_path)
        os.environ["CONTROL_HUB_TOKEN"] = "phase4bc-test-token"

        self.app = srv.create_app()
        self.app.config["CONTROL_HUB_TOKEN"] = "phase4bc-test-token"
        self.client = self.app.test_client()
        self.hdrs = {"Authorization": f"Bearer {self.app.config['CONTROL_HUB_TOKEN']}"}

    def test_pwa_manifest_and_service_worker_served(self) -> None:
        r_mf = self.client.get("/manifest.webmanifest")
        self.assertEqual(r_mf.status_code, 200)
        mf = r_mf.get_json(force=True)
        self.assertEqual(mf["display"], "standalone")
        self.assertIn("/#/overview", mf["start_url"])

        r_sw = self.client.get("/sw.js")
        self.assertEqual(r_sw.status_code, 200)
        self.assertEqual(r_sw.headers.get("Service-Worker-Allowed"), "/")
        sw_text = r_sw.get_data(as_text=True)
        self.assertIn("hub-shell-v2", sw_text)

        # Every URL listed in SHELL_ASSETS and manifest icons must serve HTTP 200 cleanly
        m_assets = re.search(r"const SHELL_ASSETS = \[(.*?)\];", sw_text, re.DOTALL)
        self.assertIsNotNone(m_assets)
        shell_urls = re.findall(r'"([^"]+)"', m_assets.group(1))
        self.assertGreaterEqual(len(shell_urls), 6)
        for asset_url in shell_urls:
            with self.client.get(asset_url) as resp:
                self.assertEqual(resp.status_code, 200, f"Service Worker shell asset returned {resp.status_code}: {asset_url}")

        for ico in mf.get("icons", []):
            with self.client.get(ico["src"]) as resp:
                self.assertEqual(resp.status_code, 200, f"Manifest icon returned {resp.status_code}: {ico['src']}")

    def test_metrics_history_throttle_ranges_and_downsampling(self) -> None:
        now = 1_750_000_000.0
        # 120 samples spanning 10 days (every 2 hours)
        for i in range(120):
            ts = now - (119 - i) * 7200
            recorded = metrics_history.record_sample(
                {
                    "cpu_pct": 10.0 + (i % 25),
                    "cpu_temp_c": 42.0 + (i % 8),
                    "ram_pct": 35.0 + (i % 10),
                    "lan_mbs": 5.0 + (i % 15),
                    "disk_io_mbs": 2.0 + (i % 6),
                    "pool_used_gb": 500.0 + i * 0.25,
                },
                now_ts=ts,
                min_interval_s=300,
            )
            self.assertTrue(recorded)

        # Throttled if within 300s of the last sample
        self.assertFalse(metrics_history.record_sample({"cpu_pct": 99.0}, now_ts=now + 60, min_interval_s=300))

        h24 = metrics_history.query_history("24h", now_ts=now + 60)
        h7d = metrics_history.query_history("7d", now_ts=now + 60)
        h30d = metrics_history.query_history("30d", now_ts=now + 60)

        self.assertLess(h24["raw_samples"], h7d["raw_samples"])
        self.assertLess(h7d["raw_samples"], h30d["raw_samples"])
        self.assertLessEqual(len(h30d["points"]), 96)
        self.assertAlmostEqual(h30d["stats"]["pool_delta_gb"], round(119 * 0.25, 2), places=1)

    def test_history_and_monthly_insights_api_routes(self) -> None:
        now = time.time()
        metrics_history.record_sample({"cpu_pct": 14.5, "ram_pct": 41.0, "lan_mbs": 3.2, "disk_io_mbs": 1.1}, now_ts=now - 3600)
        metrics_history.record_sample({"cpu_pct": 20.5, "ram_pct": 43.0, "lan_mbs": 7.5, "disk_io_mbs": 2.4}, now_ts=now)

        self.assertEqual(self.client.get("/api/history?range=24h").status_code, 401)
        r_hist = self.client.get("/api/history?range=7d", headers=self.hdrs)
        self.assertEqual(r_hist.status_code, 200)
        hbody = r_hist.get_json()
        self.assertEqual(hbody["range"], "7d")
        self.assertGreaterEqual(hbody["raw_samples"], 2)

        with mock.patch("core.metrics_history.sleep_guard.sleep_module_installed", return_value=True), mock.patch(
            "core.metrics_history.sleep_guard.load_permanent_config",
            return_value={"enabled": True, "sleep_time": "00:00", "wake_time": "06:00", "duration_hours": 6.0},
        ):
            r_ins = self.client.get("/api/insights/monthly", headers=self.hdrs)
        self.assertEqual(r_ins.status_code, 200)
        ins = r_ins.get_json()
        self.assertIn("monthly_report", ins)
        self.assertEqual(ins["power_savings"]["hours_per_day"], 6.0)
        self.assertGreater(ins["power_savings"]["monthly_kwh_saved"], 0.0)


if __name__ == "__main__":
    unittest.main()

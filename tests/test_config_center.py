"""Unit and API tests for Phase 3D Settings Centre (diff preview, undo, manifest, export/import, support bundle)."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HUB_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HUB_DIR.parents[1]
if str(HUB_DIR) not in sys.path:
    sys.path.insert(0, str(HUB_DIR))

import server  # noqa: E402
from widgets import config_center  # noqa: E402

HELPER_PATH = REPO_ROOT / "system" / "helpers" / "homelab-config-apply"


def _load_helper():
    loader = importlib.machinery.SourceFileLoader("homelab_config_apply", str(HELPER_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestConfigCenterPhase3D(unittest.TestCase):
    def setUp(self) -> None:
        self.app = server.create_app()
        self.token = self.app.config["CONTROL_HUB_TOKEN"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.client = self.app.test_client()

    @unittest.skipUnless(HELPER_PATH.is_file(), "monorepo helper absent in standalone module run")
    def test_helper_preview_apply_undo_and_sanitized_export(self) -> None:
        helper = _load_helper()
        with tempfile.TemporaryDirectory() as tmp:
            etc = Path(tmp) / "etc"
            etc.mkdir()
            cfg_file = etc / "config.json"
            bak_file = etc / "config.json.bak"
            initial = {
                "timezone": "UTC",
                "hdd_data": "/mnt/hdd/data",
                "hdd_memories": "/mnt/hdd/Memories",
                "puid": 1000,
                "pgid": 1000,
                "control_hub_port": 7575,
                "gdrive_remote": "gdrive:",
                "qbittorrent_pass": "TopSecretPass99",
                "control_hub_token": "SuperSecretTokenHex",
                "radarr_api_key": "RadarrKey123",
            }
            cfg_file.write_text(json.dumps(initial), encoding="utf-8")

            with mock.patch.object(helper, "CONFIG_JSON", cfg_file), \
                 mock.patch.object(helper, "BACKUP_JSON", bak_file), \
                 mock.patch.object(helper, "sync_all_blueprint_envs", return_value={"master_env": str(etc / "homelab.env")}):
                # Reject invalid port & relative path
                bad = helper.cmd_preview({"control_hub_port": 80, "hdd_data": "relative/path"})
                self.assertFalse(bad["valid"])
                self.assertGreaterEqual(len(bad["errors"]), 2)

                # Preview redacts secret values
                prev = helper.cmd_preview({"timezone": "Asia/Kolkata", "qbittorrent_pass": "NewSecret123"})
                self.assertTrue(prev["valid"])
                diff_by_field = {c["field"]: c for c in prev["changes"]}
                self.assertEqual(diff_by_field["timezone"]["new"], "Asia/Kolkata")
                self.assertEqual(diff_by_field["qbittorrent_pass"]["new"], "***updated***")
                self.assertNotIn("NewSecret123", json.dumps(prev))

                # Apply creates .bak and updates config
                applied = helper.cmd_apply({"timezone": "Asia/Kolkata", "control_hub_port": 7676})
                self.assertTrue(applied["ok"])
                self.assertTrue(applied["can_undo"])
                self.assertTrue(bak_file.is_file())
                saved = json.loads(cfg_file.read_text(encoding="utf-8"))
                self.assertEqual(saved["timezone"], "Asia/Kolkata")
                self.assertEqual(saved["control_hub_port"], 7676)

                # Export strips every secret
                exported = helper.cmd_export()
                self.assertTrue(exported["ok"])
                raw_export = json.dumps(exported["config"])
                self.assertNotIn("TopSecretPass99", raw_export)
                self.assertNotIn("SuperSecretTokenHex", raw_export)
                self.assertNotIn("RadarrKey123", raw_export)

                # Undo restores original config
                undone = helper.cmd_undo()
                self.assertTrue(undone["ok"])
                reverted = json.loads(cfg_file.read_text(encoding="utf-8"))
                self.assertEqual(reverted["timezone"], "UTC")
                self.assertEqual(reverted["control_hub_port"], 7575)

    def test_manifest_export_import_and_support_bundle_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_file = root / "installed.json"
            manifest_file.write_text(json.dumps({
                "manifest_version": 2,
                "blueprint_version": "2.1.1",
                "install_dir": "/opt/homelab-blueprint",
                "service_user": "homelab",
                "modules": ["media", "photos", "control_hub"],
                "units": ["control-hub.service"],
                "crons": ["/etc/cron.d/immich-backup"],
                "compose": [{"module": "mediaserver", "dir": "/srv/stacks/media"}],
            }), encoding="utf-8")

            backup_log = root / "backup.log"
            backup_log.write_text(
                "2026-11-26 starting job Authorization: Bearer super_secret_token_abc\n"
                "curl https://admin:my_secret_pw@example.invalid/test\n",
                encoding="utf-8",
            )

            with mock.patch.object(config_center, "MANIFEST_FILE_PATH", str(manifest_file)), \
                 mock.patch.object(config_center, "BACKUP_LOG_FILE", str(backup_log)), \
                 mock.patch.object(config_center, "CONFIG_APPLY_HELPER", ""):
                m_resp = self.client.get("/api/config/manifest", headers=self.headers)
                self.assertEqual(m_resp.status_code, 200)
                self.assertTrue(m_resp.get_json()["installed"])
                self.assertEqual(m_resp.get_json()["manifest"]["blueprint_version"], "2.1.1")

                # Export strips secrets
                ex_resp = self.client.get("/api/config/export?download=1", headers=self.headers)
                self.assertEqual(ex_resp.status_code, 200)
                self.assertIn("attachment; filename=\"homelab-settings-export.json\"", ex_resp.headers["Content-Disposition"])
                ex_data = json.loads(ex_resp.data.decode("utf-8"))
                self.assertTrue(ex_data["secrets_removed"])

                # Import preview strips any accidental secret keys before previewing
                imp_resp = self.client.post(
                    "/api/config/import",
                    headers=self.headers,
                    json={"config": {"timezone": "Europe/Berlin", "qbittorrent_pass": "LeakedSecret"}, "preview": True},
                )
                self.assertEqual(imp_resp.status_code, 200)
                imp_data = imp_resp.get_json()
                self.assertNotIn("qbittorrent_pass", imp_data["sanitized_config"])
                self.assertEqual(imp_data["sanitized_config"]["timezone"], "Europe/Berlin")

                # Support bundle scrubs secrets from logs
                sb_resp = self.client.get("/api/config/support-bundle?download=1", headers=self.headers)
                self.assertEqual(sb_resp.status_code, 200)
                self.assertIn("homelab-support-bundle.json", sb_resp.headers["Content-Disposition"])
                bundle_raw = sb_resp.data.decode("utf-8")
                self.assertNotIn("super_secret_token_abc", bundle_raw)
                self.assertNotIn("my_secret_pw", bundle_raw)
                self.assertIn("[REDACTED]", bundle_raw)

    def test_update_and_undo_use_audited_helper_when_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_helper = Path(tmp) / "homelab-config-apply"
            fake_helper.write_text("#!/bin/sh\n", encoding="utf-8")

            with mock.patch.object(config_center, "CONFIG_APPLY_HELPER", str(fake_helper)), \
                 mock.patch.object(config_center, "_run_config_apply") as mock_helper:
                mock_helper.side_effect = [
                    {"ok": True, "changes": [{"field": "timezone", "old": "UTC", "new": "Asia/Kolkata"}], "can_undo": True, "message": "Applied 1 change."},
                    {"ok": True, "message": "Reverted to previous configuration snapshot."},
                ]
                upd = self.client.post("/api/config/update", headers=self.headers, json={"timezone": "Asia/Kolkata"})
                self.assertEqual(upd.status_code, 200)
                self.assertTrue(upd.get_json()["can_undo"])

                undo = self.client.post("/api/config/undo", headers=self.headers, json={})
                self.assertEqual(undo.status_code, 200)
                self.assertEqual(undo.get_json()["status"], "success")


if __name__ == "__main__":
    unittest.main()

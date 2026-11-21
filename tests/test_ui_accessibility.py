"""
Phase 1E Playwright Viewport & WCAG 2.2 AA Accessibility Tests (axe-core).

Verifies:
- Phone (360x800), Tablet (820x1180), and Desktop (1366x900) render with
  zero horizontal overflow and zero clipped visible controls.
- Every visible interactive button/link meets the 44x44px minimum touch target.
- Modal keyboard flow (Enter opens, Tab stays inside dialog, Esc restores focus).
- axe-core WCAG 2.2 AA scan passes with zero critical or serious violations.

Skips only when playwright/axe are not installed locally unless
CI_REQUIRE_PLAYWRIGHT=1 is set.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

HAS_BROWSER_TOOLS = False
try:
    from playwright.sync_api import sync_playwright
    from axe_playwright_python.sync_playwright import Axe
    HAS_BROWSER_TOOLS = True
except ImportError:
    if os.getenv("CI_REQUIRE_PLAYWRIGHT") == "1":
        raise

import config  # noqa: E402
from core import storage_sizes  # noqa: E402
from core.config_core import auth_password  # noqa: E402
import server  # noqa: E402
from widgets import alerts as alerts_widget  # noqa: E402
from widgets import backup_sync, cron_tasks, network_speed, system_vitals, tv_updater  # noqa: E402

try:
    from werkzeug.serving import make_server
except ImportError:
    make_server = None


SAMPLE_SERVICES = [
    {
        "id": "jellyfin",
        "docker_id": "abc123def456",
        "name": "Jellyfin",
        "port": 8096,
        "description": "Media Streaming",
        "icon": "film",
        "category": "media",
        "state": "running",
        "status": "Up 2 hours",
        "is_up": True,
    },
    {
        "id": "qbittorrent",
        "docker_id": "def456ghi789",
        "name": "qBittorrent",
        "port": 8080,
        "description": "Torrent Client",
        "icon": "download",
        "category": "ingest",
        "state": "running",
        "status": "Up 2 hours",
        "is_up": True,
    },
    {
        "id": "prowlarr",
        "docker_id": "111222333444",
        "name": "Prowlarr",
        "port": 9696,
        "description": "Indexer Proxy",
        "icon": "search",
        "category": "ingest",
        "state": "running",
        "status": "Up 2 hours",
        "is_up": True,
    },
]


@unittest.skipUnless(
    HAS_BROWSER_TOOLS and make_server is not None,
    "playwright / axe-playwright-python / werkzeug not available",
)
class TestControlHubUiAccessibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        hub_dir = root / "state" / "control-hub"
        hub_dir.mkdir(parents=True, exist_ok=True)
        pw_file = hub_dir / "password"

        cls._orig_env = {
            k: os.environ.get(k)
            for k in ("HOMELAB_STATE_DIR", "CONTROL_HUB_PASSWORD_FILE", "CONTROL_HUB_TOKEN", "TZ")
        }
        os.environ["HOMELAB_STATE_DIR"] = str(root / "state")
        os.environ["CONTROL_HUB_PASSWORD_FILE"] = str(pw_file)
        os.environ["CONTROL_HUB_TOKEN"] = "ui-test-token-456"
        os.environ["TZ"] = "UTC"

        cls._patches = [
            mock.patch.object(auth_password, "PASSWORD_FILE", pw_file),
            mock.patch.object(config, "BACKUP_DIR", str(root / "backups")),
            mock.patch.object(config, "BACKUP_LOG_FILE", str(root / "backups" / "backup.log")),
            mock.patch.object(config, "BACKUP_STATUS_FILE", str(root / "backups" / "status.json")),
            mock.patch.object(config, "SPEEDTEST_CACHE_FILE", str(root / "speedtest_cache.json")),
            mock.patch.object(config, "STORAGE_SIZES_CACHE_FILE", str(root / "storage_sizes_cache.json")),
            mock.patch.object(backup_sync, "BACKUP_DIR", str(root / "backups")),
            mock.patch.object(backup_sync, "BACKUP_LOG_FILE", str(root / "backups" / "backup.log")),
            mock.patch.object(backup_sync, "BACKUP_STATUS_FILE", str(root / "backups" / "status.json")),
            mock.patch.object(backup_sync, "STORAGE_SIZES_CACHE_FILE", str(root / "storage_sizes_cache.json")),
            mock.patch.object(network_speed, "SPEEDTEST_CACHE_FILE", str(root / "speedtest_cache.json")),
            mock.patch.object(system_vitals, "STORAGE_SIZES_CACHE_FILE", str(root / "storage_sizes_cache.json")),
            mock.patch.object(cron_tasks, "BACKUP_LOG_FILE", str(root / "backups" / "backup.log")),
            mock.patch.object(cron_tasks, "BACKUP_STATUS_FILE", str(root / "backups" / "status.json")),
            mock.patch.object(tv_updater, "TV_UPDATER_PY", ""),
            mock.patch.object(tv_updater, "TV_UPDATER_STATE_FILE", ""),
            mock.patch.object(backup_sync, "MEDIA_BACKUP_STATUS_FILE", str(root / "media-backups" / "status.json")),
            mock.patch.object(backup_sync, "MEDIA_BACKUP_CRON_FILE", str(root / "media-backup.cron")),
            mock.patch.object(backup_sync, "SYSTEMD_UNIT_DIR", str(root / "units")),
            mock.patch.object(alerts_widget.engine, "config_path", root / "alerts.json"),
            mock.patch.object(alerts_widget.engine, "state_path", root / "alerts_state.json"),
        ]
        for p in cls._patches:
            p.start()

        # A failed pre-flight after one good run: the busiest state of the backup card.
        backups = root / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        (backups / "status.json").write_text(json.dumps({
            "status": "error", "stage": 0, "stage_label": "0. Pre-flight",
            "message": "Pre-flight: the remote gdrive: did not answer (token expired).",
            "started_at": "2026-11-22T22:00:01+05:30", "completed_at": "2026-11-22T22:00:09+05:30",
            "last_good_at": "2026-11-21T22:06:01+05:30", "remote": "gdrive:",
            "preflight": {"ok": False, "checks": [
                {"name": "remote", "ok": False, "detail": "gdrive: did not answer: token expired"}]},
            "retention": {"kept": 17, "delete": ["immich_db_20261001_220001.sql.gz"], "next_delete": ["immich_db_20261108_220001.sql.gz"]},
            "restore_test": {"ok": True, "message": "Restored", "completed_at": "2026-11-01T11:07:30+05:30",
                             "dump_file": "immich_db_20261031_220001.sql.gz", "restored": 35765, "expected": 35765},
            "history": [
                {"started_at": "2026-11-22T22:00:01+05:30", "outcome": "error", "message": "Pre-flight: the remote gdrive: did not answer (token expired).", "duration_s": 8},
                {"started_at": "2026-11-21T22:00:01+05:30", "outcome": "synced", "dump_file": "immich_db_20261121_220001.sql.gz",
                 "dump_bytes": 356271570, "files": 12, "bytes": 48000000, "duration_s": 360},
            ],
        }), encoding="utf-8")

        media_dir = root / "media-backups"
        media_dir.mkdir(parents=True, exist_ok=True)
        (media_dir / "status.json").write_text(json.dumps({
            "status": "synced", "stage": 4, "message": "Media settings backed up to gdrive:Media_Backup",
            "started_at": "2026-11-22T21:30:01+05:30", "completed_at": "2026-11-22T21:30:09+05:30",
            "last_good_at": "2026-11-22T21:30:09+05:30", "remote": "gdrive:",
            "dump_file": "media_config_20261122_213001.tar.zst", "dump_bytes": 19454318,
            "history": [{"started_at": "2026-11-22T21:30:01+05:30", "outcome": "synced", "duration_s": 8}],
        }), encoding="utf-8")

        (root / "units").mkdir(exist_ok=True)
        (root / "units" / "photo-restore-test.service").write_text("[Service]\n", encoding="utf-8")

        cls.password = "PlaywrightTestPass1!"
        auth_password.set_password(cls.password, path=pw_file)

        cls.app = server.create_app()

        # Override /api/services/status in test app so Service Matrix rows render realistically.
        def mock_services_status():
            from flask import jsonify
            return jsonify({
                "services": SAMPLE_SERVICES,
                "docker_available": True,
                "docker_error": None,
                "dozzle_installed": False,
                "cockpit_installed": False,
            })

        cls.app.view_functions["service_matrix.get_services_status"] = mock_services_status

        # Two TVs: one online with a nickname and a detected model, one never seen.
        def mock_tv_status():
            from flask import jsonify
            app_row = {"package": "org.smarttube.stable", "name": "SmartTube", "installed_code": 2470,
                       "installed_name": "32.80", "target_code": 2470, "target_name": "32.80", "is_installed": True,
                       "is_up_to_date": True, "status_code": "UP_TO_DATE", "status_text": "Up to date (vCode 2470)",
                       "is_foreground": False}
            return jsonify({
                "installed": True, "status": "synced", "all_up_to_date": True, "pending_updates_count": 0,
                "total_devices": 2, "online_devices": 1, "upstream_apps": {}, "schedule": "Every 15 min",
                "devices": [
                    {"id": "living_room_tv", "name": "Living room", "nickname": "Living room", "profile_name": "Living Room TV",
                     "ip": "192.168.1.34", "port": 5555, "model": "MIBOX4", "model_label": "Xiaomi MIBOX4",
                     "details": {"manufacturer": "Xiaomi", "model": "MIBOX4", "codename": "oneday", "android": "9",
                                 "sdk": "28", "device_name": "Mi Box", "last_seen": "2026-11-21 16:40"},
                     "is_online": True, "foreground_app_name": "Android TV Launcher", "is_media_playing": False, "apps": [app_row]},
                    {"id": "bedroom_tv", "name": "Bedroom TV", "nickname": None, "profile_name": "Bedroom TV",
                     "ip": "192.168.1.39", "port": 5555, "model": None, "model_label": None,
                     "details": {"last_seen": None}, "is_online": False, "apps": [dict(app_row, status_text="Up to date (vCode 2470) when last seen")]},
                ],
            })

        cls.app.view_functions["tv_updater.get_tv_updater_status"] = mock_tv_status

        cls.httpd = make_server("127.0.0.1", 0, cls.app)
        cls.port = cls.httpd.server_port
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

        cls._pw = sync_playwright().start()
        cls.browser = cls._pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.browser.close()
        except Exception:
            pass
        try:
            cls._pw.stop()
        except Exception:
            pass
        try:
            cls.httpd.shutdown()
            cls.httpd.server_close()
        except Exception:
            pass
        storage_sizes.wait_for_idle(timeout=5.0)
        for p in reversed(cls._patches):
            p.stop()
        for k, v in cls._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cls._tmp.cleanup()

    def _new_authenticated_page(self, width: int, height: int):
        context = self.browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()

        # Keep external font stylesheets from slowing/failing headless offline scans.
        page.route("https://fonts.googleapis.com/**", lambda route: route.abort())
        page.route("https://fonts.gstatic.com/**", lambda route: route.abort())

        console_errors = []
        page_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        # Sign in cleanly via API cookie before loading dashboard HTML.
        login_res = context.request.post(
            f"{self.base_url}/api/auth/login",
            data={"password": self.password},
        )
        self.assertEqual(login_res.status, 200)

        page.goto(self.base_url, wait_until="domcontentloaded")
        page.wait_for_selector("#sleep-guard-card")
        page.wait_for_selector(".service-row", state="attached", timeout=10000)
        page.wait_for_timeout(400)
        return context, page, console_errors, page_errors

    def _assert_layout_and_touch_targets(self, page, width: int) -> None:
        metrics = page.evaluate(
            """() => {
                const vw = window.innerWidth;
                const sw = document.documentElement.scrollWidth;
                const offenders = [];
                const clipped = [];
                const selector = 'button, a[href], summary, input:not([type="checkbox"]):not([type="radio"]), select';
                document.querySelectorAll(selector).forEach((el) => {
                    const st = window.getComputedStyle(el);
                    if (st.display === 'none' || st.visibility === 'hidden' || el.offsetParent === null) return;
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) return;
                    if (r.height < 43.5 || r.width < 43.5) {
                        offenders.push({
                            tag: el.tagName,
                            id: el.id,
                            cls: el.className,
                            text: (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 40),
                            w: Math.round(r.width),
                            h: Math.round(r.height),
                        });
                    }
                    if (r.right > vw + 1 || r.left < -1) {
                        clipped.push({
                            id: el.id,
                            cls: el.className,
                            left: Math.round(r.left),
                            right: Math.round(r.right),
                            vw,
                        });
                    }
                });
                return { vw, sw, offenders, clipped };
            }"""
        )
        self.assertLessEqual(
            metrics["sw"],
            metrics["vw"],
            f"Horizontal overflow at {width}px: scrollWidth={metrics['sw']} > innerWidth={metrics['vw']}",
        )
        self.assertEqual(
            metrics["clipped"],
            [],
            f"Clipped interactive controls at {width}px: {metrics['clipped']}",
        )
        self.assertEqual(
            metrics["offenders"],
            [],
            f"Interactive controls smaller than 44x44px at {width}px: {metrics['offenders']}",
        )

    def _assert_axe_wcag_aa(self, page, label: str) -> None:
        axe = Axe()
        results = axe.run(
            page,
            options={
                "runOnly": {
                    "type": "tag",
                    "values": ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"],
                }
            },
        )
        raw = getattr(results, "response", results)
        violations = raw.get("violations", []) if isinstance(raw, dict) else []
        bad = [v for v in violations if v.get("impact") in ("critical", "serious")]
        if bad:
            summary = [
                f"{v['id']} ({v['impact']}): {v['help']} -> {[n.get('target') for n in v.get('nodes', [])]}"
                for v in bad
            ]
            self.fail(f"WCAG 2.2 AA violations ({label}):\n" + "\n".join(summary))

    def test_responsive_viewports_touch_targets_and_axe(self) -> None:
        for width, height in ((360, 800), (820, 1180), (1366, 900)):
            context, page, console_errors, page_errors = self._new_authenticated_page(width, height)
            try:
                if width <= 599:
                    # Expand Service Matrix so rows and buttons inside it are also verified on mobile.
                    svc_btn = page.locator("#services-matrix .card-collapse-btn")
                    svc_btn.click()
                    page.wait_for_selector("#services-matrix:not(.is-collapsed) .service-row", timeout=5000)

                page.evaluate("() => { const d = document.getElementById('backup-history-wrap'); if (d) d.open = true; }")
                self._assert_layout_and_touch_targets(page, width)
                self._assert_axe_wcag_aa(page, f"dashboard@{width}x{height}")

                self.assertEqual(page_errors, [], f"Page errors at {width}px: {page_errors}")
                unexpected_console = [e for e in console_errors if "fonts.googleapis" not in e and "ERR_FAILED" not in e]
                self.assertEqual(unexpected_console, [], f"Console errors at {width}px: {unexpected_console}")
            finally:
                context.close()

    def test_backup_card_shows_failed_preflight_history_and_retention(self) -> None:
        context, page, _, page_errors = self._new_authenticated_page(360, 800)
        try:
            page.wait_for_function("() => document.getElementById('backup-history').children.length === 2", timeout=10000)
            if "is-collapsed" in (page.get_attribute("#backup-section", "class") or ""):
                page.click("#backup-section .card-collapse-btn")
            self.assertEqual(page.get_attribute("#backup-health", "data-state"), "error")
            self.assertIn("did not answer", page.inner_text("#backup-health-title"))
            self.assertIn("Last good backup", page.inner_text("#backup-health-detail"))
            self.assertIn("2026-11-21 22:06", page.inner_text("#backup-last-time"))
            self.assertIn("is-alert", page.get_attribute("#backup-section", "class"))
            self.assertEqual(page.inner_text("#backup-status-badge"), "Failed")
            self.assertTrue(page.is_visible("#backup-preflight .preflight-fail"))
            self.assertIsNone(page.get_attribute("#backup-preflight", "hidden"))
            page.click("#backup-history-wrap summary")
            runs = page.locator("#backup-history .backup-run")
            self.assertIn("Failed", runs.nth(0).inner_text())
            self.assertIn("339.8 MB", runs.nth(1).inner_text())
            self.assertIn("next run deletes immich_db_20261108_220001.sql.gz", page.inner_text("#backup-retention"))
            self.assertTrue(page.is_visible("#media-backup"))
            self.assertEqual(page.inner_text("#media-backup-badge"), "Verified")
            self.assertIn("18.6 MB", page.inner_text("#media-backup-line"))
            self.assertFalse(page.is_visible("#btn-media-backup-run"), "no button without the script")
            self.assertIn("passed 2026-11-01 11:07", page.inner_text("#restore-test-text"))
            self.assertIn("35,765 photos and videos", page.inner_text("#restore-test-text"))
            self.assertTrue(page.is_visible("#btn-restore-test-run"))
            self._assert_layout_and_touch_targets(page, 360)
            self._assert_axe_wcag_aa(page, "backup-card@360x800")
            self.assertEqual(page_errors, [])
        finally:
            context.close()

    def test_alerts_dialog_phone_layout_keyboard_and_axe(self) -> None:
        context, page, _, page_errors = self._new_authenticated_page(360, 800)
        try:
            self.assertEqual(page.inner_text("#alerts-count"), "off")
            if not page.is_visible("#btn-open-alerts"):
                page.click("#btn-header-menu")
            page.click("#btn-open-alerts")
            modal = page.locator("#alerts-modal")
            modal.wait_for(state="visible", timeout=5000)
            page.wait_for_selector("#alerts-channels fieldset[data-channel='ntfy']")
            self.assertEqual(page.locator("#alerts-rules [data-rule]").count(), 10)
            page.click("#alerts-channels fieldset[data-channel='ntfy'] button:has-text('New topic')")
            topic = page.input_value("#alerts-ntfy-topic")
            self.assertTrue(topic.startswith("homelab-") and len(topic) >= 20)
            for _ in range(8):
                page.keyboard.press("Tab")
                inside = page.evaluate("() => document.getElementById('alerts-modal').contains(document.activeElement)")
                self.assertTrue(inside, "Focus escaped the alerts dialog")
            self._assert_layout_and_touch_targets(page, 360)
            self._assert_axe_wcag_aa(page, "alerts-modal@360x800")
            page.keyboard.press("Escape")
            modal.wait_for(state="hidden", timeout=5000)
            self.assertEqual(page_errors, [])
        finally:
            context.close()

    def test_tv_name_shows_details_on_hover_and_click(self) -> None:
        context, page, _, page_errors = self._new_authenticated_page(360, 800)
        try:
            page.wait_for_selector("#tv-fleet-preview .tv-name-btn", state="attached", timeout=10000)
            if "is-collapsed" in (page.get_attribute("#tv-updater-section", "class") or ""):
                page.click("#tv-updater-section .card-collapse-btn")
            btn = page.locator("#tv-fleet-preview .tv-name-btn").first
            self.assertEqual(btn.inner_text(), "Living room")
            self.assertIn("Xiaomi MIBOX4 · Android 9 · 192.168.1.34:5555 · online", btn.get_attribute("title"))
            self.assertEqual(btn.get_attribute("aria-expanded"), "false")
            btn.click()
            panel = page.locator("#tv-info-card-living_room_tv")
            panel.wait_for(state="visible")
            self.assertEqual(btn.get_attribute("aria-expanded"), "true")
            self.assertFalse(page.is_visible("#tv-info-card-bedroom_tv"), "only the clicked TV opens")
            text = panel.inner_text()
            for expected in ("Xiaomi MIBOX4", "oneday", "9 (API 28)", "Mi Box", "192.168.1.34:5555"):
                self.assertIn(expected, text)
            self.assertEqual(page.input_value("#tv-nick-card-living_room_tv"), "Living room")
            never = page.locator("#tv-fleet-preview .tv-name-btn").nth(1)
            self.assertIn("Model not detected yet", never.get_attribute("title"))
            self._assert_layout_and_touch_targets(page, 360)
            self._assert_axe_wcag_aa(page, "tv-names@360x800")
            # A refresh re-renders the card (same path as the 15 s poll); the panel stays open.
            with page.expect_response(lambda r: "/api/tv-updater/status" in r.url):
                page.evaluate("() => document.getElementById('btn-refresh-now').click()")
            page.wait_for_timeout(300)
            self.assertTrue(page.is_visible("#tv-info-card-living_room_tv"))
            self.assertEqual(page_errors, [])
        finally:
            context.close()

    def test_modal_keyboard_focus_trap_escape_and_axe(self) -> None:
        context, page, _, page_errors = self._new_authenticated_page(1366, 900)
        try:
            open_btn = page.locator("#btn-open-config-center")
            open_btn.focus()
            page.keyboard.press("Enter")

            modal = page.locator("#config-center-modal")
            modal.wait_for(state="visible", timeout=5000)
            self.assertEqual(modal.get_attribute("role"), "dialog")
            self.assertEqual(modal.get_attribute("aria-modal"), "true")

            # Verify Tab focus stays trapped inside #config-center-modal
            for _ in range(12):
                page.keyboard.press("Tab")
                inside = page.evaluate(
                    "() => Boolean(document.activeElement && document.getElementById('config-center-modal').contains(document.activeElement))"
                )
                self.assertTrue(inside, "Focus escaped config-center-modal while tabbing")

            self._assert_axe_wcag_aa(page, "config-center-modal@1366x900")

            # Escape closes modal and restores focus to triggering button
            page.keyboard.press("Escape")
            modal.wait_for(state="hidden", timeout=5000)
            active_id = page.evaluate("() => document.activeElement && document.activeElement.id")
            self.assertEqual(active_id, "btn-open-config-center")
            self.assertEqual(page_errors, [])
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()

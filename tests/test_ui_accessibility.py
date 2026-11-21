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
        ]
        for p in cls._patches:
            p.start()

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
                const selector = 'button, a[href], input:not([type="checkbox"]):not([type="radio"]), select';
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

                self._assert_layout_and_touch_targets(page, width)
                self._assert_axe_wcag_aa(page, f"dashboard@{width}x{height}")

                self.assertEqual(page_errors, [], f"Page errors at {width}px: {page_errors}")
                unexpected_console = [e for e in console_errors if "fonts.googleapis" not in e and "ERR_FAILED" not in e]
                self.assertEqual(unexpected_console, [], f"Console errors at {width}px: {unexpected_console}")
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

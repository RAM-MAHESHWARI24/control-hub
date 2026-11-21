"""Phase 2B: alert rules, quiet hours, channels and the /api/alerts endpoints."""

from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import alerts  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
Usage = namedtuple("Usage", "total used free")


def cfg(**changes):
    c = copy.deepcopy(alerts.DEFAULT_CONFIG)
    c["quiet_hours"]["enabled"] = False
    c["channels"]["ntfy"]["enabled"] = True
    for path, value in changes.items():
        node = c
        keys = path.split("__")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    return c


def cond(key="disk_critical:/", rule="disk_critical", severity="critical", min_seconds=0, event=False):
    return alerts.Condition(key, rule, severity, f"T {key}", f"M {key}", min_seconds=min_seconds, event=event)


class TestConfig(unittest.TestCase):
    def test_masking_keeps_secret_and_validates(self):
        stored = alerts.apply_update(alerts.DEFAULT_CONFIG, {"channels": {"telegram": {"bot_token": "123:abc", "chat_id": "42"}}})
        shown = alerts.masked(stored)
        self.assertEqual(shown["channels"]["telegram"]["bot_token"], alerts.MASK)
        self.assertEqual(shown["channels"]["discord"]["webhook_url"], "")
        again = alerts.apply_update(stored, shown)  # the browser sends the mask back
        self.assertEqual(again["channels"]["telegram"]["bot_token"], "123:abc")

    def test_rejects_bad_values(self):
        for bad in (
            {"channels": {"ntfy": {"enabled": True, "topic": ""}}},
            {"channels": {"ntfy": {"topic": "short"}}},
            {"rules": {"disk_warning": {"percent": 120}}},
            {"rules": {"container_down": {"minutes": 0}}},
            {"quiet_hours": {"start": "25:00"}},
        ):
            with self.assertRaises(ValueError, msg=bad):
                alerts.apply_update(alerts.DEFAULT_CONFIG, bad)

    def test_unknown_keys_dropped_and_types_coerced(self):
        c = alerts.apply_update(alerts.DEFAULT_CONFIG, {"channels": {"email": {"port": "465", "evil": "x"}},
                                                         "rules": {"nope": {"enabled": False}, "cpu_temp": {"celsius": "75"}}})
        self.assertEqual(c["channels"]["email"]["port"], 465)
        self.assertNotIn("evil", c["channels"]["email"])
        self.assertNotIn("nope", c["rules"])
        self.assertEqual(c["rules"]["cpu_temp"]["celsius"], 75)


class TestEvaluate(unittest.TestCase):
    T0 = datetime(2026, 11, 22, 12, 0, tzinfo=IST)

    def test_fire_once_remind_and_resolve(self):
        c, state = cfg(), {}
        out = alerts.evaluate(c, state, [cond()], self.T0)
        self.assertEqual([m.title for m in out], ["T disk_critical:/"])
        self.assertEqual(alerts.evaluate(c, state, [cond()], self.T0 + timedelta(minutes=1)), [])
        out = alerts.evaluate(c, state, [cond()], self.T0 + timedelta(hours=25))
        self.assertTrue(out[0].title.startswith("Still:"))
        out = alerts.evaluate(c, state, [], self.T0 + timedelta(hours=26))
        self.assertTrue(out[0].resolved)
        self.assertTrue(out[0].title.startswith("Resolved:"))
        self.assertEqual(state["firing"], {})

    def test_minimum_duration(self):
        c, state = cfg(), {}
        down = cond("container:radarr", "container_down", "warning", min_seconds=300)
        self.assertEqual(alerts.evaluate(c, state, [down], self.T0), [])
        self.assertEqual(alerts.evaluate(c, state, [down], self.T0 + timedelta(minutes=4)), [])
        self.assertEqual(len(alerts.evaluate(c, state, [down], self.T0 + timedelta(minutes=5))), 1)
        # A blip that clears before the minimum never fires and never "resolves".
        state2 = {}
        alerts.evaluate(c, state2, [down], self.T0)
        self.assertEqual(alerts.evaluate(c, state2, [], self.T0 + timedelta(minutes=2)), [])

    def test_alerts_before_any_channel_are_sent_when_one_is_enabled(self):
        c, state = cfg(channels__ntfy__enabled=False), {}
        self.assertEqual(alerts.evaluate(c, state, [cond()], self.T0), [])
        self.assertTrue(state["firing"]["disk_critical:/"]["unsent"])
        self.assertTrue(state["history"][0]["unsent"])
        self.assertEqual(alerts.evaluate(c, state, [cond()], self.T0 + timedelta(minutes=1)), [])
        c["channels"]["ntfy"]["enabled"] = True
        out = alerts.evaluate(c, state, [cond()], self.T0 + timedelta(minutes=2))
        self.assertEqual([m.title for m in out], ["T disk_critical:/"])
        self.assertEqual(alerts.evaluate(c, state, [cond()], self.T0 + timedelta(minutes=3)), [])

    def test_disabled_rule_is_ignored(self):
        c = cfg(rules__disk_critical__enabled=False)
        self.assertEqual(alerts.evaluate(c, {}, [cond()], self.T0), [])

    def test_quiet_hours_queue_and_morning_digest(self):
        c = cfg(quiet_hours__enabled=True)
        state = {}
        night = datetime(2026, 11, 22, 2, 0, tzinfo=IST)
        warn = cond("disk_warning:/", "disk_warning", "warning")
        self.assertEqual(alerts.evaluate(c, state, [warn], night), [])
        self.assertEqual(len(state["queue"]), 1)
        # Critical alerts still go out at night.
        crit = cond()
        self.assertEqual(len(alerts.evaluate(c, state, [warn, crit], night + timedelta(minutes=1))), 1)
        out = alerts.evaluate(c, state, [warn, crit], datetime(2026, 11, 22, 7, 0, tzinfo=IST))
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].title.startswith("Overnight: 1"))
        self.assertEqual(state["queue"], [])

    def test_quiet_hours_window(self):
        c = cfg(quiet_hours__enabled=True)
        at = lambda h, m=0: datetime(2026, 11, 22, h, m, tzinfo=IST)  # noqa: E731
        self.assertTrue(alerts.in_quiet_hours(c, at(23, 30)))
        self.assertTrue(alerts.in_quiet_hours(c, at(6, 59)))
        self.assertFalse(alerts.in_quiet_hours(c, at(7, 0)))
        self.assertFalse(alerts.in_quiet_hours(c, at(12)))

    def test_events_and_daily_summary(self):
        c = cfg(daily_summary__enabled=True)
        state = {}
        ev = cond("tv_error:1", "tv_update_failed", "warning", event=True)
        out = alerts.evaluate(c, state, [ev], datetime(2026, 11, 22, 7, 0, tzinfo=IST))
        self.assertEqual(len(out), 1)
        self.assertNotIn("tv_error:1", state.get("firing", {}))
        out = alerts.evaluate(c, state, [], datetime(2026, 11, 22, 8, 0, tzinfo=IST))
        self.assertEqual([m.title for m in out], ["Daily summary: 0 open alert(s)"])
        self.assertEqual(alerts.evaluate(c, state, [], datetime(2026, 11, 22, 9, 0, tzinfo=IST)), [])


class TestCollectors(unittest.TestCase):
    def test_backup(self):
        summary = {"state": "error", "message": "Pre-flight: remote did not answer", "stale": False}
        st = {"preflight": {"checks": [{"name": "remote", "ok": False}]}}
        self.assertEqual([c.rule for c in alerts.collect_backup(st, summary)], ["drive_unreachable"])
        st = {"preflight": {"checks": [{"name": "remote", "ok": True}]}}
        self.assertEqual([c.rule for c in alerts.collect_backup(st, summary)], ["backup_failed"])
        summary = {"state": "stale", "message": "x", "stale": True, "last_good": "2026-11-20 22:06", "age": "2 days ago"}
        self.assertEqual([c.rule for c in alerts.collect_backup({"x": 1}, summary)], ["backup_stale"])
        self.assertEqual(alerts.collect_backup(None, None), [])

    def test_disks(self):
        gb = 1024**3
        usage = {"/": Usage(100 * gb, 50 * gb, 50 * gb), "/mnt/hdd/data": Usage(100 * gb, 90 * gb, 10 * gb),
                 "/mnt/hdd/Memories": Usage(100 * gb, 90 * gb, 10 * gb)}
        out = alerts.collect_disks(cfg(), list(usage), usage=lambda m: usage[m])
        self.assertEqual([c.key for c in out], ["disk_warning:/mnt/hdd/data"])  # same disk reported once
        usage["/"] = Usage(100 * gb, 96 * gb, 4 * gb)
        out = alerts.collect_disks(cfg(), ["/"], usage=lambda m: usage[m])
        self.assertEqual(out[0].severity, "critical")

    def test_containers(self):
        catalog = {"radarr": {"name": "Radarr"}, "jellyfin": {"name": "Jellyfin"}, "seerr": {"name": "Seerr"}}
        rows = [{"Names": "radarr", "State": "exited", "Status": "Exited (1) 3 minutes ago"},
                {"Names": "jellyfin", "State": "running", "Status": "Up 2 hours (unhealthy)"},
                {"Names": "seerr", "State": "running", "Status": "Up 2 hours (healthy)"},
                {"Names": "immich_machine_learning", "State": "exited", "Status": "Exited (0)"}]
        out = alerts.collect_containers(cfg(), rows, catalog)
        self.assertEqual(sorted(c.key for c in out), ["container:jellyfin", "container:radarr"])
        self.assertEqual(out[0].min_seconds, 300)
        out = alerts.collect_containers(cfg(rules__container_down__ignore=["radarr"]), rows, catalog)
        self.assertEqual([c.key for c in out], ["container:jellyfin"])

    def test_cpu_temp_and_signins(self):
        self.assertEqual(alerts.collect_cpu_temp(cfg(), 70.0), [])
        self.assertEqual(alerts.collect_cpu_temp(cfg(), None), [])
        self.assertEqual(alerts.collect_cpu_temp(cfg(), 85.5)[0].min_seconds, 120)
        self.assertEqual([c.key for c in alerts.collect_signins({"1.2.3.4": 10, "5.6.7.8": 2}, 10)], ["signin:1.2.3.4"])

    def test_tv_log_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "tv.log"
            log.write_text("2026 [INFO] start\n2026 [ERROR] old failure\n", encoding="utf-8")
            state = {}
            self.assertEqual(alerts.collect_tv_errors(str(log), state), [])  # first sight: start from the end
            with log.open("a", encoding="utf-8") as fh:
                fh.write("2026 [INFO] ok\n2026 [ERROR] Installation of a.apk on Mi Box failed\n")
            out = alerts.collect_tv_errors(str(log), state)
            self.assertEqual(len(out), 1)
            self.assertTrue(out[0].event)
            self.assertIn("Installation of a.apk", out[0].message)
            self.assertEqual(alerts.collect_tv_errors(str(log), state), [])
            self.assertEqual(alerts.collect_tv_errors(str(Path(tmp) / "missing.log"), state), [])


class TestDelivery(unittest.TestCase):
    def test_deliver_only_enabled_and_ready(self):
        sent = []
        senders = {name: (lambda c, m, n=name: (sent.append(n), (True, ""))[1]) for name in alerts.SENDERS}
        c = cfg(channels__ntfy__topic="homelab-abcdef123456", channels__discord__enabled=True)
        res = alerts.deliver(c, alerts.Outgoing("warning", "t", "m"), senders=senders)
        self.assertEqual(res, {"ntfy": "", "discord": "not configured"})
        self.assertEqual(sent, ["ntfy"])

    def test_sender_exception_is_reported(self):
        def boom(c, m):
            raise OSError("network down")
        c = cfg(channels__ntfy__enabled=True, channels__ntfy__topic="homelab-abcdef123456")
        res = alerts.deliver(c, alerts.Outgoing("warning", "t", "m"), senders={"ntfy": boom})
        self.assertEqual(res["ntfy"], "network down")

    def test_ntfy_request(self):
        resp = mock.Mock(ok=True, status_code=200, text="")
        with mock.patch.object(alerts.requests, "post", return_value=resp) as post:
            ok, _ = alerts.send_ntfy({"server": "https://ntfy.sh/", "topic": "homelab-abc123def456", "token": "tk"},
                                     alerts.Outgoing("critical", "Disk almost full", "96%"))
        self.assertTrue(ok)
        url = post.call_args.args[0]
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(url, "https://ntfy.sh/homelab-abc123def456")
        self.assertEqual(headers["Priority"], "5")
        self.assertEqual(headers["Authorization"], "Bearer tk")


class TestApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_token = os.environ.get("CONTROL_HUB_TOKEN")
        os.environ["CONTROL_HUB_TOKEN"] = "alerts-test-token-1234567890"
        import server
        from widgets import alerts as alerts_widget
        self.widget = alerts_widget
        root = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(alerts_widget.engine, "config_path", root / "alerts.json"),
            mock.patch.object(alerts_widget.engine, "state_path", root / "alerts_state.json"),
            mock.patch.object(alerts_widget.engine, "collect", lambda e, s: [cond()]),
        ]
        for p in self.patches:
            p.start()
        self.client = server.create_app().test_client()
        self.h = {"Authorization": "Bearer alerts-test-token-1234567890"}

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        if self._old_token is None:
            os.environ.pop("CONTROL_HUB_TOKEN", None)
        else:
            os.environ["CONTROL_HUB_TOKEN"] = self._old_token
        self.tmp.cleanup()

    def test_overview_update_test_and_check(self):
        data = self.client.get("/api/alerts", headers=self.h).get_json()
        self.assertFalse(data["any_channel"])
        self.assertIn("disk_critical", data["rules_info"])

        res = self.client.put("/api/alerts/config", headers=self.h, json={"channels": {"ntfy": {"enabled": True, "topic": "bad"}}})
        self.assertEqual(res.status_code, 400)
        res = self.client.put("/api/alerts/config", headers=self.h, json={
            "channels": {"ntfy": {"enabled": True, "topic": "homelab-abcdef123456", "token": "secret-token"}}})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["config"]["channels"]["ntfy"]["token"], alerts.MASK)
        if os.name != "nt":
            self.assertEqual(oct((Path(self.tmp.name) / "alerts.json").stat().st_mode & 0o777), oct(0o600))

        calls = []
        fake = lambda c, m: (calls.append((c["token"], m.title)), (True, ""))[1]  # noqa: E731
        with mock.patch.dict(alerts.SENDERS, {"ntfy": fake}):
            res = self.client.post("/api/alerts/test", headers=self.h, json={"channel": "ntfy", "channels": {"ntfy": {"token": alerts.MASK}}})
            self.assertTrue(res.get_json()["ok"])
            self.assertEqual(calls[-1], ("secret-token", "Control Hub test alert"))
            data = self.client.post("/api/alerts/check", headers=self.h).get_json()
        self.assertEqual(data["sent_now"][0]["title"], "T disk_critical:/")
        self.assertEqual(len(data["firing"]), 1)
        self.assertEqual(data["channel_status"]["ntfy"]["error"], "")
        self.assertEqual(self.client.post("/api/alerts/test", headers=self.h, json={"channel": "pager"}).status_code, 400)
        self.assertEqual(self.client.get("/api/alerts").status_code, 401)


if __name__ == "__main__":
    unittest.main()

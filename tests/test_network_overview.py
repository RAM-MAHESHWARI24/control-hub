"""Unit and API tests for Phase 3E Network (NIC link/duplex health, Tailscale status, port map & conflicts)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HUB_DIR = Path(__file__).resolve().parents[1]
if str(HUB_DIR) not in sys.path:
    sys.path.insert(0, str(HUB_DIR))

from core.config_core import netplan_manager  # noqa: E402
from widgets import network_speed  # noqa: E402


class TestPhase3ENetwork(unittest.TestCase):
    def test_probe_network_interfaces_flags_half_duplex_and_never_fabricates_speed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nic_bad = root / "enp3s0"
            nic_bad.mkdir()
            (nic_bad / "operstate").write_text("up\n", encoding="utf-8")
            (nic_bad / "speed").write_text("100\n", encoding="utf-8")
            (nic_bad / "duplex").write_text("half\n", encoding="utf-8")
            (nic_bad / "carrier").write_text("1\n", encoding="utf-8")
            (nic_bad / "address").write_text("aa:bb:cc:dd:ee:ff\n", encoding="utf-8")

            nic_missing = root / "eth9"
            nic_missing.mkdir()
            (nic_missing / "operstate").write_text("up\n", encoding="utf-8")

            res = netplan_manager.probe_network_interfaces(sys_net_root=str(root))
            by_name = {item["name"]: item for item in res["interfaces"]}

            self.assertTrue(by_name["enp3s0"]["degraded"])
            self.assertEqual(by_name["enp3s0"]["duplex"], "half")
            self.assertIn("half duplex", by_name["enp3s0"]["warning"])
            self.assertEqual(by_name["enp3s0"]["mac"], "aa:bb:cc:dd:ee:ff")

            self.assertIsNone(by_name["eth9"]["speed_mbps"])
            self.assertIsNone(by_name["eth9"]["duplex"])
            self.assertFalse(by_name["eth9"]["degraded"])

    def test_probe_tailscale_status_connected_and_missing_cli(self) -> None:
        sample_json = json.dumps({
            "BackendState": "Running",
            "Self": {
                "DNSName": "homelab.tailnet.ts.net.",
                "TailscaleIPs": ["100.64.0.10", "fd7a:115c:a1e0::10"],
                "PrimaryRoutes": ["192.168.1.0/24"],
                "AllowedIPs": ["100.64.0.10/32", "192.168.1.0/24"],
            },
            "Peer": {
                "p1": {"Online": True},
                "p2": {"Online": False},
            },
        })
        proc = subprocess.CompletedProcess(["tailscale", "status", "--json"], 0, stdout=sample_json, stderr="")
        with mock.patch.object(network_speed.shutil, "which", return_value="/usr/bin/tailscale"), \
             mock.patch.object(network_speed.subprocess, "run", return_value=proc), \
             mock.patch.object(network_speed, "_read_ip_forward", return_value=True):
            ts = network_speed.probe_tailscale_status()
        self.assertTrue(ts["installed"])
        self.assertTrue(ts["connected"])
        self.assertEqual(ts["tailnet_ip"], "100.64.0.10")
        self.assertEqual(ts["dns_name"], "homelab.tailnet.ts.net")
        self.assertTrue(ts["subnet_router"])
        self.assertEqual(ts["advertised_routes"], ["192.168.1.0/24"])
        self.assertTrue(ts["ip_forwarding"])
        self.assertEqual(ts["peer_count"], 1)

        with mock.patch.object(network_speed.shutil, "which", return_value=None):
            missing = network_speed.probe_tailscale_status()
        self.assertFalse(missing["installed"])
        self.assertFalse(missing["connected"])

    def test_build_port_map_flags_duplicate_port_conflicts(self) -> None:
        fake_catalog = {
            "control_hub": {"port": 7575, "name": "Control Hub Dashboard", "category": "system", "essential": True, "in_use": True, "available": False},
            "collision_app": {"port": 7575, "name": "Duplicate Test", "category": "media", "essential": False, "in_use": True, "available": False},
            "seerr": {"port": 5055, "name": "Seerr", "category": "media", "essential": True, "in_use": False, "available": True},
        }
        with mock.patch.object(network_speed, "get_default_ports", return_value=fake_catalog), \
             mock.patch.object(network_speed, "_running_docker_ports", return_value={}):
            rows, conflicts = network_speed.build_port_map()
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["port"], 7575)
        self.assertTrue(rows[0]["conflict"])
        self.assertFalse(rows[2]["conflict"])

    def test_network_overview_endpoint_returns_expected_contract(self) -> None:
        import server

        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "CONTROL_HUB_TOKEN": "phase3e-test-token",
                "CONTROL_HUB_DATA_DIR": tmp,
            }
            with mock.patch.dict(os.environ, env, clear=False):
                app = server.create_app()
            client = app.test_client()
            headers = {"Authorization": "Bearer phase3e-test-token"}
            with mock.patch.object(
                network_speed,
                "probe_network_interfaces",
                return_value={
                    "active_nic": "enp3s0",
                    "current_ip": "192.168.1.31",
                    "default_gateway": "192.168.1.1",
                    "dns_servers": ["1.1.1.1"],
                    "interfaces": [{"name": "enp3s0", "is_up": True, "speed_mbps": 1000, "duplex": "full", "degraded": False, "warning": None}],
                },
            ), mock.patch.object(
                network_speed,
                "probe_tailscale_status",
                return_value={"installed": True, "connected": True, "tailnet_ip": "100.64.0.10", "subnet_router": False, "advertised_routes": []},
            ), mock.patch.object(
                network_speed,
                "build_port_map",
                return_value=([{"key": "control_hub", "name": "Control Hub Dashboard", "port": 7575, "category": "system", "in_use": True, "conflict": False}], []),
            ):
                resp = client.get("/api/network/overview", headers=headers)
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["active_nic"], "enp3s0")
        self.assertTrue(payload["tailscale"]["connected"])
        self.assertEqual(payload["port_conflicts"], [])


if __name__ == "__main__":
    unittest.main()

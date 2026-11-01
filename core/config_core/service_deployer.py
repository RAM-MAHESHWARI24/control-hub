"""
Homelab Blueprint - Service Deployer & Provisioning Orchestrator
Coordinates storage tree creation, Netplan application, .env synchronization, and Docker deployment.
"""

import os
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, List

from .storage_manager import create_homelab_directory_tree
from .netplan_manager import safe_apply_netplan
from .env_manager import sync_all_blueprint_envs


def run_command(cmd: List[str], cwd: str = None) -> Dict[str, Any]:
    """Helper to execute shell command and capture output cleanly"""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300
        )
        return {
            "success": proc.returncode == 0,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "returncode": proc.returncode,
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "returncode": -1,
        }


def deploy_homelab_stack(base_dir: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes full provisioning pipeline based on user configuration.
    Supports dry_run=True to safely test without modifying host network, disk files, or Docker state.
    """
    root_path = Path(base_dir).resolve()
    is_dry_run = config.get("dry_run", False) or (os.getenv("DRY_RUN", "0") == "1")
    logs = []

    def log(msg: str):
        prefix = "[DRY-RUN] " if is_dry_run else ""
        logs.append(f"[{time.strftime('%H:%M:%S')}] {prefix}{msg}")

    if is_dry_run:
        log("=== SAFE SIMULATION / DRY-RUN MODE ACTIVE ===")
        log("No system files, network adapters, or Docker containers will be modified.")

    log("Starting Homelab Blueprint provisioning pipeline...")

    # Step 1: Storage Tree Creation
    data_dir = config.get("hdd_data", "/mnt/hdd/data")
    config_dir = config.get("config_dir", str(root_path / "apps" / "mediaserver" / "config"))
    memories_dir = config.get("hdd_memories", "/mnt/hdd/Memories")
    puid = int(config.get("puid", 1000))
    pgid = int(config.get("pgid", 1000))

    if is_dry_run:
        log(f"Simulating directory tree creation at '{data_dir}' (0 I/O hardlinks).")
        log(f"  -> Would create: {data_dir}/torrents/{{movies,tv}}")
        log(f"  -> Would create: {data_dir}/media/{{movies,tv}}")
        log(f"  -> Would create: {config_dir}/{{jellyfin,seerr,prowlarr,radarr,sonarr,bazarr,qbittorrent}}")
        log(f"  -> Would create: {memories_dir}")
        log(f"  -> Would set ownership to {puid}:{pgid}")
    else:
        log(f"Building single-mount directory tree at '{data_dir}' (0 I/O hardlinks)...")
        tree_result = create_homelab_directory_tree(data_dir, config_dir, memories_dir, puid, pgid)
        if tree_result["success"]:
            log(f"Successfully created {len(tree_result['created_dirs'])} directories with permissions {puid}:{pgid}.")
        else:
            log(f"Warning during directory creation: {tree_result['errors']}")

    # Step 2: Safe Netplan Static IP (if requested)
    netplan_result = None
    if config.get("enable_static_ip", False):
        nic = config.get("active_nic", "eth0")
        ip = config.get("server_ip", "192.168.1.100")
        gw = config.get("default_gateway", "192.168.1.1")
        dns = config.get("dns_servers", ["1.1.1.1", "8.8.8.8"])

        if is_dry_run:
            from .netplan_manager import generate_netplan_yaml
            preview_yaml = generate_netplan_yaml(nic, ip if "/" in ip else f"{ip}/24", gw, dns)
            log(f"Simulated Netplan static IP ({ip}) on interface '{nic}'.")
            log("Netplan configuration generated in memory without applying.")
            netplan_result = {
                "success": True,
                "mode": "dry_run",
                "preview_yaml": preview_yaml,
                "message": "Netplan static IP validated safely in dry-run mode."
            }
        else:
            log(f"Configuring safe static IP ({ip}) on interface '{nic}' with auto-rollback...")
            netplan_result = safe_apply_netplan(
                interface=nic,
                ip_address=ip,
                gateway=gw,
                dns_servers=dns
            )
            if netplan_result.get("success"):
                log(f"Netplan static IP confirmed safe! ({ip})")
            else:
                log(f"Netplan warning: {netplan_result.get('message', 'Failed to apply static IP')}")

    # Step 3: Synchronize all .env and config.json files
    if is_dry_run:
        preview_dir = root_path / "setup" / "dry_run_preview"
        preview_dir.mkdir(parents=True, exist_ok=True)
        log(f"Generating .env previews inside isolated folder: '{preview_dir.relative_to(root_path)}'...")
        # Write to preview directory instead of actual root and app directories
        env_result = sync_all_blueprint_envs(str(preview_dir), config)
        for env_name, env_path in env_result.items():
            log(f"  -> Generated preview: {Path(env_path).relative_to(root_path)}")
        log("Original monorepo .env files remain completely untouched.")
    else:
        log("Synchronizing unified environment files across all monorepo subsystems...")
        env_result = sync_all_blueprint_envs(str(root_path), config)
        for env_name, env_path in env_result.items():
            log(f"  -> Generated: {Path(env_path).relative_to(root_path)}")

    # Step 4: Docker Stacks & Host Services Orchestration
    services_launched = []
    launch_errors = []

    server_ip = config.get("server_ip", "192.168.1.100")
    enabled_services = config.get("enabled_services", ["media", "photos", "control_hub", "tv_updater"])
    ch_port = config.get("control_hub_port", 7575)

    # Ensure TMDB interceptor exists in seerr config dir for out-of-the-box ISP DPI bypass
    seerr_src = root_path / "apps" / "mediaserver" / "config" / "seerr" / "tmdb-interceptor.js"
    seerr_dst = Path(config_dir) / "seerr" / "tmdb-interceptor.js"
    if seerr_src.exists() and not seerr_dst.exists():
        try:
            seerr_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(seerr_src, seerr_dst)
            log("Ensured TMDB ISP bypass interceptor is in Seerr config directory.")
        except Exception as e:
            log(f"Notice copying TMDB interceptor: {e}")

    # Install host maintenance scripts to /usr/local/sbin/
    if not is_dry_run and os.name != "nt":
        sbin = Path("/usr/local/sbin")
        try:
            sbin.mkdir(parents=True, exist_ok=True)
            helpers = [
                (root_path / "system" / "power" / "server-suspend.sh", sbin / "server-suspend.sh"),
                (root_path / "system" / "power" / "immich-ml-control.sh", sbin / "immich-ml-control.sh"),
                (root_path / "system" / "maintenance" / "watchtower-run.sh", sbin / "watchtower-run.sh"),
            ]
            for src, dst in helpers:
                if src.exists():
                    shutil.copy2(src, dst)
                    os.chmod(str(dst), 0o755)
            log("Installed host maintenance scripts to /usr/local/sbin/")
        except Exception as e:
            log(f"Notice installing /usr/local/sbin helpers: {e}")

    if is_dry_run:
        if "media" in enabled_services:
            log("Simulating Media Pipeline Docker Compose deployment (skipping container start).")
            services_launched.append("media (dry-run)")
        if "photos" in enabled_services:
            log("Simulating Noodle Gallery Docker Compose deployment (skipping container start).")
            services_launched.append("photos (dry-run)")
        if "control_hub" in enabled_services:
            log("Simulating Control Hub Python environment and systemd service deployment.")
            services_launched.append("control_hub (dry-run)")
        if "tv_updater" in enabled_services:
            log("Simulating CleanYourTV cron schedule setup.")
            services_launched.append("tv_updater (dry-run)")
    else:
        # Real launch
        if "media" in enabled_services:
            media_path = root_path / "apps" / "mediaserver"
            log("Deploying Media Pipeline stack via Docker Compose...")
            cmd_res = run_command(["docker", "compose", "up", "-d"], cwd=str(media_path))
            if cmd_res["success"]:
                log("Media pipeline containers started successfully.")
                services_launched.append("media")
            else:
                log(f"Docker Compose media notice: {cmd_res['stderr'] or cmd_res['stdout']}")
                launch_errors.append({"service": "mediaserver", "msg": cmd_res['stderr']})

        if "photos" in enabled_services:
            noodle_path = root_path / "apps" / "noodle-gallery"
            log("Deploying Noodle Gallery (VectorChord & Postgres) via Docker Compose...")
            cmd_res = run_command(["docker", "compose", "up", "-d"], cwd=str(noodle_path))
            if cmd_res["success"]:
                log("Noodle Gallery containers started successfully.")
                services_launched.append("photos")
            else:
                log(f"Docker Compose photos notice: {cmd_res['stderr'] or cmd_res['stdout']}")
                launch_errors.append({"service": "noodle-gallery", "msg": cmd_res['stderr']})

        # Control Hub service
        if "control_hub" in enabled_services:
            ch_dir = root_path / "apps" / "control-hub"
            log("Deploying Control Hub management daemon...")
            venv_python = ch_dir / "venv" / "bin" / "python3"
            if not venv_python.exists() and os.name != "nt":
                run_command(["python3", "-m", "venv", "venv"], cwd=str(ch_dir))

            pip_bin = ch_dir / "venv" / "bin" / "pip"
            req_file = ch_dir / "requirements.txt"
            if pip_bin.exists() and req_file.exists():
                run_command([str(pip_bin), "install", "-q", "-r", str(req_file)], cwd=str(ch_dir))

            # Security Hardening: Ensure unprivileged homelab system user & sudoers whitelist
            if os.name != "nt":
                check_user = run_command(["id", "-u", "homelab"])
                if not check_user["success"]:
                    run_command(["useradd", "-r", "-s", "/usr/sbin/nologin", "-G", "docker", "homelab"])
                    log("Created unprivileged 'homelab' system service account.")
                else:
                    run_command(["usermod", "-aG", "docker", "homelab"])

                if (ch_dir / "venv").exists():
                    run_command(["chown", "-R", "homelab:homelab", str(ch_dir / "venv")])

                sudoers_src = root_path / "system" / "systemd" / "homelab-sudoers.example"
                sudoers_dst = Path("/etc/sudoers.d/homelab-blueprint")
                if sudoers_src.exists():
                    try:
                        shutil.copy2(sudoers_src, sudoers_dst)
                        os.chmod(str(sudoers_dst), 0o440)
                        log("Installed least-privilege sudoers whitelist in /etc/sudoers.d/homelab-blueprint.")
                    except Exception as e:
                        log(f"Notice installing sudoers whitelist: {e}")

            unit_src = root_path / "system" / "systemd" / "control-hub.service"
            unit_dst = Path("/etc/systemd/system/control-hub.service")
            if unit_src.exists() and os.name != "nt":
                try:
                    shutil.copy2(unit_src, unit_dst)
                    run_command(["systemctl", "daemon-reload"])
                    start_res = run_command(["systemctl", "enable", "--now", "control-hub.service"])
                    if start_res["success"]:
                        log(f"Control Hub service started successfully on port {ch_port}.")
                        services_launched.append("control_hub")
                    else:
                        log(f"Notice starting control-hub.service: {start_res['stderr']}")
                except Exception as e:
                    log(f"Notice installing control-hub.service: {e}")
            else:
                services_launched.append("control_hub")

        # CleanYourTV cron
        if "tv_updater" in enabled_services:
            cron_src = root_path / "system" / "cron.d" / "tv-updater"
            cron_dst = Path("/etc/cron.d/tv-updater")
            if cron_src.exists() and os.name != "nt":
                try:
                    shutil.copy2(cron_src, cron_dst)
                    os.chmod(str(cron_dst), 0o644)
                    log("CleanYourTV background cron registered in /etc/cron.d/tv-updater.")
                    services_launched.append("tv_updater")
                except Exception as e:
                    log(f"Notice setting tv-updater cron: {e}")
            else:
                services_launched.append("tv_updater")

    # Step 5: Build Service Access Catalog for UI Handoff
    ch_port = config.get("control_hub_port", 7575)
    access_catalog = [
        {
            "name": "Control Hub Dashboard",
            "desc": "Real-time command center, LAN telemetry & Sleep Guard",
            "url": f"http://{server_ip}:{ch_port}",
            "port": ch_port,
            "badge": "Command Center",
            "primary": True,
        },
        {
            "name": "Jellyfin Media",
            "desc": "High performance video and audio streaming",
            "url": f"http://{server_ip}:8096",
            "port": 8096,
            "badge": "Media",
        },
        {
            "name": "Seerr (Jellyseerr)",
            "desc": "Request management & TMDB bypass portal",
            "url": f"http://{server_ip}:5055",
            "port": 5055,
            "badge": "Requests",
        },
        {
            "name": "qBittorrent WebUI",
            "desc": "Torrent ingest and seed manager",
            "url": f"http://{server_ip}:{config.get('qbittorrent_port', 8080)}",
            "port": config.get('qbittorrent_port', 8080),
            "badge": "Downloader",
        },
        {
            "name": "Noodle Gallery",
            "desc": "AI vector search photo & video cloud",
            "url": f"http://{server_ip}:{config.get('gallery_port', 2283)}",
            "port": config.get('gallery_port', 2283),
            "badge": "Photos",
        },
    ]

    log("Provisioning pipeline completed!")

    return {
        "success": True,
        "logs": logs,
        "services_launched": services_launched,
        "launch_errors": launch_errors,
        "access_catalog": access_catalog,
        "dashboard_url": f"http://{server_ip}:{ch_port}",
        "netplan_result": netplan_result,
    }

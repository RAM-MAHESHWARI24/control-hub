"""
Widget: Unified Troubleshoot Health Runner (Phase 4F)
Runs read-only checks across Control Hub subsystems and explains any warnings
or failures in plain words with actionable next steps and target views.
"""

import datetime
import os
from pathlib import Path

from flask import Blueprint, jsonify

from config import BACKUP_DIR, BACKUP_STATUS_FILE, HDD_DATA, PORT
from core import backup_health
from core.telemetry_sampler import sampler_health
from widgets import cron_tasks, indexers, network_speed, service_matrix, sleep_guard, system_vitals

troubleshoot_bp = Blueprint("troubleshoot", __name__)


def _check_sampler() -> dict:
    try:
        health = sampler_health()
        stale = bool(health.get("stale"))
        started = bool(health.get("started"))
        if not started:
            return {
                "id": "telemetry_sampler",
                "title": "Background Telemetry Sampler",
                "category": "Core",
                "status": "warn",
                "summary": "Background sampler has not started yet.",
                "explanation": "CPU, speed, and temperature readings rely on the background sampler thread. Give it a few seconds after service startup or check journald logs.",
                "fix_steps": [
                    "Wait 10 seconds and click Refresh.",
                    "If it stays inactive, inspect `sudo journalctl -u control-hub.service -n 50`.",
                ],
                "action_view": "overview",
                "action_label": "Open Overview",
            }
        if stale:
            return {
                "id": "telemetry_sampler",
                "title": "Background Telemetry Sampler",
                "category": "Core",
                "status": "fail",
                "summary": f"Telemetry loop appears stale ({health.get('age_seconds')}s old).",
                "explanation": "Live vitals stopped updating, usually because a host probe hung or the Control Hub process needs a restart.",
                "fix_steps": [
                    "Run `sudo systemctl restart control-hub.service` via SSH.",
                    "Check `sudo journalctl -u control-hub.service -n 80` for stuck probes.",
                ],
                "action_view": "system",
                "action_label": "Open System",
            }
        return {
            "id": "telemetry_sampler",
            "title": "Background Telemetry Sampler",
            "category": "Core",
            "status": "ok",
            "summary": "Live telemetry thread is updating normally.",
            "explanation": "CPU load, temperatures, disk I/O, and LAN throughput are sampling on schedule.",
            "fix_steps": [],
            "action_view": "overview",
            "action_label": "Open Overview",
        }
    except Exception as exc:
        return {
            "id": "telemetry_sampler",
            "title": "Background Telemetry Sampler",
            "category": "Core",
            "status": "warn",
            "summary": f"Could not inspect sampler: {exc}",
            "explanation": "Telemetry health inspection hit an unexpected error.",
            "fix_steps": ["Check Control Hub service logs via SSH."],
            "action_view": "system",
            "action_label": "Open System",
        }


def _check_storage_and_hardlinks() -> list[dict]:
    checks: list[dict] = []
    vitals_data: dict = {}
    try:
        vitals_res = system_vitals.get_system_vitals()
        vitals_data = vitals_res.get_json(silent=True) or {}
    except Exception as exc:
        checks.append({
            "id": "storage_capacity",
            "title": "Storage Capacity",
            "category": "Storage",
            "status": "warn",
            "summary": f"Storage check failed: {exc}",
            "explanation": "Control Hub could not read filesystem headroom.",
            "fix_steps": ["Open System -> Storage Breakdown and press Refresh Storage."],
            "action_view": "system",
            "action_label": "Inspect Storage",
        })

    storage = vitals_data.get("storage") or {}
    ssd = storage.get("ssd") or {}
    hdd = storage.get("hdd") or {}

    if not hdd.get("available"):
        checks.append({
            "id": "storage_capacity",
            "title": "Media Pool Storage",
            "category": "Storage",
            "status": "warn",
            "summary": hdd.get("reason") or f"Data directory ({HDD_DATA}) not mounted.",
            "explanation": "When your media pool drive is unmounted or unconfigured, downloads and hardlinks cannot land cleanly on `/data`.",
            "fix_steps": [
                "Verify your drive is mounted and matches `HDD_DATA` in Server Config.",
                "Run `lsblk -f` and `df -h` via SSH if an external or internal HDD failed to mount.",
            ],
            "action_view": "system",
            "action_label": "Inspect Storage",
        })
    elif hdd.get("is_critical") or ssd.get("is_critical"):
        which = "Media Pool" if hdd.get("is_critical") else "OS Root"
        pct = hdd.get("percent") if hdd.get("is_critical") else ssd.get("percent")
        free = hdd.get("free_gb") if hdd.get("is_critical") else ssd.get("free_gb")
        checks.append({
            "id": "storage_capacity",
            "title": "Disk Space Headroom",
            "category": "Storage",
            "status": "fail",
            "summary": f"{which} is critically full ({pct}% used, {free} GB free).",
            "explanation": "A full disk stops Docker databases, stalls qBittorrent imports, and breaks nightly backups.",
            "fix_steps": [
                "Open System -> Safe Storage Cleanup to remove finished torrents or old logs.",
                "Verify backups succeeded before pruning old local snapshots.",
            ],
            "action_view": "system",
            "action_label": "Free Up Space",
        })
    elif hdd.get("is_warning") or ssd.get("is_warning"):
        pct = max(float(hdd.get("percent") or 0), float(ssd.get("percent") or 0))
        checks.append({
            "id": "storage_capacity",
            "title": "Disk Space Headroom",
            "category": "Storage",
            "status": "warn",
            "summary": f"Storage approaching warning threshold ({pct:.1f}% used).",
            "explanation": "Running near capacity leaves little room for large downloads or compressed photo/DB backups.",
            "fix_steps": [
                "Open System -> Storage Breakdown, Cleanup & Disk Health to reclaim space.",
            ],
            "action_view": "system",
            "action_label": "Inspect Storage",
        })
    else:
        checks.append({
            "id": "storage_capacity",
            "title": "Disk Space Headroom",
            "category": "Storage",
            "status": "ok",
            "summary": f"OS Root ({ssd.get('free_gb', '--')} GB free) and Media Pool ({hdd.get('free_gb', '--')} GB free) have healthy headroom.",
            "explanation": "Both OS and data filesystems are below your configured alert thresholds.",
            "fix_steps": [],
            "action_view": "system",
            "action_label": "Inspect Storage",
        })

    # Read-only atomic hardlink invariant check (same st_dev under ${HDD_DATA}).
    try:
        base = Path(HDD_DATA)
        torrents_dir = base / "torrents"
        media_dir = base / "media"
        if not base.exists():
            checks.append({
                "id": "hardlinks",
                "title": "Atomic Hardlinks (/data)",
                "category": "Storage",
                "status": "warn",
                "summary": f"{HDD_DATA} does not exist on this host yet.",
                "explanation": "Radarr and Sonarr need `/data/torrents` and `/data/media` on the same filesystem so completed downloads import instantly without copying.",
                "fix_steps": [
                    "Run the Setup Wizard or Config Center 'Verify Hardlink' check after mounting your storage pool.",
                ],
                "action_view": "system",
                "action_label": "Inspect Storage",
            })
        elif torrents_dir.exists() and media_dir.exists():
            same_dev = os.stat(torrents_dir).st_dev == os.stat(media_dir).st_dev
            if same_dev:
                checks.append({
                    "id": "hardlinks",
                    "title": "Atomic Hardlinks (/data)",
                    "category": "Storage",
                    "status": "ok",
                    "summary": "Torrents and Media share one filesystem device (0-I/O hardlinks supported).",
                    "explanation": "Imports from qBittorrent to Radarr/Sonarr create instant hardlinks instead of slow duplicate copies.",
                    "fix_steps": [],
                    "action_view": "apps",
                    "action_label": "Open Apps",
                })
            else:
                checks.append({
                    "id": "hardlinks",
                    "title": "Atomic Hardlinks (/data)",
                    "category": "Storage",
                    "status": "fail",
                    "summary": "Torrents and Media sit on different mount devices!",
                    "explanation": "Separate mounts force full cross-device file copies (EXDEV), burning disk I/O and doubling space usage while seeding.",
                    "fix_steps": [
                        "Mount one shared pool at `${HDD_DATA}:/data` with `torrents/` and `media/` subfolders on the same partition.",
                    ],
                    "action_view": "system",
                    "action_label": "Open Server Config",
                })
        else:
            checks.append({
                "id": "hardlinks",
                "title": "Atomic Hardlinks (/data)",
                "category": "Storage",
                "status": "ok",
                "summary": f"Storage root {HDD_DATA} is present (single-mount layout).",
                "explanation": "Single-mount storage pool path is present for downloads and library imports.",
                "fix_steps": [],
                "action_view": "system",
                "action_label": "Inspect Storage",
            })
    except OSError as exc:
        checks.append({
            "id": "hardlinks",
            "title": "Atomic Hardlinks (/data)",
            "category": "Storage",
            "status": "warn",
            "summary": f"Could not inspect {HDD_DATA}: {exc}",
            "explanation": "Filesystem metadata could not be read cleanly.",
            "fix_steps": ["Verify directory permissions for the `homelab` user on `/data`."],
            "action_view": "system",
            "action_label": "Inspect Storage",
        })

    return checks


def _check_docker_and_services() -> dict:
    try:
        res = service_matrix.get_services_status()
        payload = res.get_json(silent=True) or {}
        if payload.get("docker_available") is False:
            return {
                "id": "docker_services",
                "title": "Docker & Media Containers",
                "category": "Apps",
                "status": "fail",
                "summary": payload.get("docker_error") or "Docker daemon unavailable.",
                "explanation": "Control Hub cannot reach `/var/run/docker.sock` or Docker is stopped, so media and photo containers appear offline.",
                "fix_steps": [
                    "Run `sudo systemctl status docker` via SSH.",
                    "Confirm `homelab` belongs to the `docker` group cleanly.",
                ],
                "action_view": "apps",
                "action_label": "Open Apps",
            }
        services = payload.get("services") or []
        unhealthy = [
            s.get("name") or s.get("id")
            for s in services
            if s.get("state") in ("exited", "dead", "restarting") or s.get("health") == "unhealthy"
        ]
        if unhealthy:
            shown = ", ".join(unhealthy[:4])
            more = f" (+{len(unhealthy) - 4} more)" if len(unhealthy) > 4 else ""
            return {
                "id": "docker_services",
                "title": "Docker & Media Containers",
                "category": "Apps",
                "status": "fail",
                "summary": f"Containers need attention: {shown}{more}.",
                "explanation": "One or more containers are stopped, restarting, or failing their Docker healthcheck.",
                "fix_steps": [
                    "Open Apps -> Managed Containers, inspect inline logs for the affected app, and click Restart.",
                ],
                "action_view": "apps",
                "action_label": "Open Apps",
            }
        return {
            "id": "docker_services",
            "title": "Docker & Media Containers",
            "category": "Apps",
            "status": "ok",
            "summary": f"{len(services)} tracked container(s) running cleanly.",
            "explanation": "All detected containers report healthy or normal running status.",
            "fix_steps": [],
            "action_view": "apps",
            "action_label": "Open Apps",
        }
    except Exception as exc:
        return {
            "id": "docker_services",
            "title": "Docker & Media Containers",
            "category": "Apps",
            "status": "warn",
            "summary": f"Service probe error: {exc}",
            "explanation": "Could not evaluate Docker containers.",
            "fix_steps": ["Check the Apps view or Docker socket status."],
            "action_view": "apps",
            "action_label": "Open Apps",
        }


def _check_indexers() -> dict:
    try:
        res = indexers.indexers_health()
        payload = res.get_json(silent=True) or {}
        if not payload.get("installed"):
            return {
                "id": "prowlarr_indexers",
                "title": "Prowlarr Search Indexers",
                "category": "Media",
                "status": "ok",
                "summary": "Prowlarr key not configured on this host.",
                "explanation": "Indexer probing stays inactive until Prowlarr is installed and linked.",
                "fix_steps": [],
                "action_view": "apps",
                "action_label": "Open Apps",
            }
        if not payload.get("reachable"):
            return {
                "id": "prowlarr_indexers",
                "title": "Prowlarr Search Indexers",
                "category": "Media",
                "status": "fail",
                "summary": "Prowlarr API did not respond.",
                "explanation": "Radarr and Sonarr rely on Prowlarr for release searches; when Prowlarr is down or blocked, requests stall.",
                "fix_steps": [
                    "Open Apps and verify the `prowlarr` container is running and inspect its logs.",
                    "Confirm Prowlarr's API key matches `/etc/homelab/prowlarr.key`.",
                ],
                "action_view": "apps",
                "action_label": "Open Apps",
            }
        total = int(payload.get("total") or 0)
        failing = int(payload.get("failing") or 0)
        if total == 0:
            return {
                "id": "prowlarr_indexers",
                "title": "Prowlarr Search Indexers",
                "category": "Media",
                "status": "warn",
                "summary": "Prowlarr is running with 0 indexers configured.",
                "explanation": "Without at least one enabled indexer, Radarr and Sonarr cannot find media requested in Seerr.",
                "fix_steps": [
                    "Open Apps -> Media Pipeline & Indexer Health (or click Pick Indexers) to add an indexer.",
                ],
                "action_view": "apps",
                "action_label": "Open Indexers",
            }
        if failing > 0:
            return {
                "id": "prowlarr_indexers",
                "title": "Prowlarr Search Indexers",
                "category": "Media",
                "status": "warn",
                "summary": f"{failing} of {total} indexer(s) currently failing or backed off.",
                "explanation": "An indexer timed out, hit rate limits, or failed FlareSolverr checks.",
                "fix_steps": [
                    "Open Apps -> Media Pipeline & Indexer Health and click 'Test Indexers' to see per-indexer fix hints.",
                ],
                "action_view": "apps",
                "action_label": "Inspect Indexers",
            }
        return {
            "id": "prowlarr_indexers",
            "title": "Prowlarr Search Indexers",
            "category": "Media",
            "status": "ok",
            "summary": f"All {total} configured indexer(s) healthy.",
            "explanation": "Prowlarr responded cleanly and reported no disabled or failing indexers.",
            "fix_steps": [],
            "action_view": "apps",
            "action_label": "Open Indexers",
        }
    except Exception as exc:
        return {
            "id": "prowlarr_indexers",
            "title": "Prowlarr Search Indexers",
            "category": "Media",
            "status": "warn",
            "summary": f"Indexer check unavailable: {exc}",
            "explanation": "Could not query Prowlarr.",
            "fix_steps": ["Check the Apps view."],
            "action_view": "apps",
            "action_label": "Open Apps",
        }


def _check_backups() -> dict:
    try:
        snapshot = backup_health.read_status(BACKUP_STATUS_FILE)
        if not snapshot and not os.path.isdir(BACKUP_DIR):
            return {
                "id": "photo_backups",
                "title": "Photo Cloud Backup",
                "category": "Backups",
                "status": "ok",
                "summary": "Photo cloud backup module not active on this host.",
                "explanation": "Backups status appears once Photo Cloud Backup is configured.",
                "fix_steps": [],
                "action_view": "overview",
                "action_label": "Open Overview",
            }
        summary = backup_health.summarize(snapshot, running=False)
        state = summary.get("state") or "unknown"
        if state in ("error", "stale"):
            return {
                "id": "photo_backups",
                "title": "Photo Cloud Backup",
                "category": "Backups",
                "status": "fail" if state == "error" else "warn",
                "summary": summary.get("title") or f"Backup needs attention ({state}).",
                "explanation": summary.get("detail") or "The latest off-site cloud backup failed or is older than expected.",
                "fix_steps": [
                    "Open Backups and click 'Log' to read exact pre-flight or rclone messages.",
                    "If OAuth expired, re-authorize the remote with `rclone config reconnect` and verify with Test.",
                ],
                "action_view": "backups",
                "action_label": "Open Backups",
            }
        return {
            "id": "photo_backups",
            "title": "Photo Cloud Backup",
            "category": "Backups",
            "status": "ok" if state == "ok" else "warn",
            "summary": summary.get("title") or "Cloud backup telemetry healthy.",
            "explanation": summary.get("detail") or "Latest cloud photo sync passed pre-flight checks cleanly.",
            "fix_steps": [] if state == "ok" else ["Open Backups -> Run backup now to record an initial run."],
            "action_view": "backups",
            "action_label": "Open Backups",
        }
    except Exception as exc:
        return {
            "id": "photo_backups",
            "title": "Photo Cloud Backup",
            "category": "Backups",
            "status": "warn",
            "summary": f"Backup check error: {exc}",
            "explanation": "Could not inspect backup status file.",
            "fix_steps": ["Check the Backups view."],
            "action_view": "backups",
            "action_label": "Open Backups",
        }


def _check_network_and_remote() -> dict:
    try:
        net = network_speed.probe_network_interfaces()
        ts = network_speed.probe_tailscale_status()
        ts_https = network_speed.probe_tailscale_https(ts, PORT)
        _, conflicts = network_speed.build_port_map()
        degraded = [n for n in (net.get("interfaces") or []) if n.get("degraded")]

        if conflicts:
            first = conflicts[0]
            return {
                "id": "network_ports",
                "title": "Network Link, Tailscale & Ports",
                "category": "Network",
                "status": "fail",
                "summary": first.get("reason") or "Service port conflict detected.",
                "explanation": "Two configured services are assigned the same TCP port, which prevents one of them from binding.",
                "fix_steps": [
                    "Open System -> Network Ports, Tailscale & Port Map to review conflicting ports.",
                    "Update port assignments in Server Config and restart the affected stack.",
                ],
                "action_view": "system",
                "action_label": "Inspect Network",
            }
        if degraded:
            nic = degraded[0]
            return {
                "id": "network_ports",
                "title": "Network Link, Tailscale & Ports",
                "category": "Network",
                "status": "warn",
                "summary": f"{nic.get('name')}: {nic.get('warning')}",
                "explanation": "A slow 100 Mbps or half-duplex Ethernet link bottlenecks 4K streams and photo backups.",
                "fix_steps": [
                    "Inspect your Cat5e/Cat6 patch cable and switch port negotiation (`ethtool`).",
                ],
                "action_view": "system",
                "action_label": "Inspect Network",
            }
        https_note = "Tailscale Serve HTTPS active." if ts_https.get("serve_active") else (
            "Tailscale connected (HTTPS Serve ready)." if ts.get("connected") else "Local LAN healthy."
        )
        return {
            "id": "network_ports",
            "title": "Network Link, Tailscale & Ports",
            "category": "Network",
            "status": "ok",
            "summary": f"No port conflicts or degraded NICs. {https_note}",
            "explanation": "Network interfaces are negotiating cleanly and configured ports do not collide.",
            "fix_steps": [],
            "action_view": "system",
            "action_label": "Inspect Network",
        }
    except Exception as exc:
        return {
            "id": "network_ports",
            "title": "Network Link, Tailscale & Ports",
            "category": "Network",
            "status": "warn",
            "summary": f"Network check error: {exc}",
            "explanation": "Could not complete network interface inspection.",
            "fix_steps": ["Open System -> Network Ports, Tailscale & Port Map."],
            "action_view": "system",
            "action_label": "Inspect Network",
        }


def _check_sleep_and_schedules() -> dict:
    try:
        cron_res = cron_tasks.get_cron_tasks_status()
        cron_data = cron_res.get_json(silent=True) or {}
        clashes = cron_data.get("clashes") or []
        sleep_res = sleep_guard.get_sleep_status()
        sleep_data = sleep_res.get_json(silent=True) or {}

        if clashes:
            return {
                "id": "sleep_schedules",
                "title": "Sleep Guard & Automated Schedules",
                "category": "Power",
                "status": "warn",
                "summary": clashes[0].get("message") or "A scheduled job overlaps the nightly sleep window.",
                "explanation": "If a cron job starts while the server is suspended to RAM, the run is skipped until wakeup.",
                "fix_steps": [
                    "Open System -> Automated Tasks & Schedules and move the overlapping job earlier or after wake time.",
                ],
                "action_view": "system",
                "action_label": "Review Schedules",
            }
        if sleep_data.get("installed") and not sleep_data.get("enabled"):
            return {
                "id": "sleep_schedules",
                "title": "Sleep Guard & Automated Schedules",
                "category": "Power",
                "status": "warn",
                "summary": "Nightly ACPI S3 sleep schedule is currently disabled.",
                "explanation": "The server will stay powered on overnight unless Nightly Sleep is enabled.",
                "fix_steps": [
                    "Toggle Nightly Sleep on from System -> Sleep Guard when you want automated overnight suspend.",
                ],
                "action_view": "system",
                "action_label": "Open Sleep Guard",
            }
        return {
            "id": "sleep_schedules",
            "title": "Sleep Guard & Automated Schedules",
            "category": "Power",
            "status": "ok",
            "summary": "No cron schedule clashes detected with Sleep Guard.",
            "explanation": "Nightly backups, TV checks, and sleep windows are aligned without overlaps.",
            "fix_steps": [],
            "action_view": "system",
            "action_label": "Open System",
        }
    except Exception as exc:
        return {
            "id": "sleep_schedules",
            "title": "Sleep Guard & Automated Schedules",
            "category": "Power",
            "status": "warn",
            "summary": f"Schedule check error: {exc}",
            "explanation": "Could not evaluate cron or Sleep Guard status.",
            "fix_steps": ["Check System -> Automated Tasks & Schedules."],
            "action_view": "system",
            "action_label": "Open System",
        }


def run_troubleshoot_checks() -> dict:
    """Runs all safe read-only troubleshoot checks and builds a structured report."""
    checks: list[dict] = [
        _check_sampler(),
        *_check_storage_and_hardlinks(),
        _check_docker_and_services(),
        _check_indexers(),
        _check_backups(),
        _check_network_and_remote(),
        _check_sleep_and_schedules(),
    ]
    ok_count = sum(1 for c in checks if c["status"] == "ok")
    warn_count = sum(1 for c in checks if c["status"] == "warn")
    fail_count = sum(1 for c in checks if c["status"] == "fail")
    overall = "fail" if fail_count else ("warn" if warn_count else "ok")
    return {
        "status": "ok",
        "overall_status": overall,
        "ok_count": ok_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "checks": checks,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }


@troubleshoot_bp.route("/api/troubleshoot", methods=["GET"])
def api_troubleshoot():
    """Runs live health diagnostics and returns plain-English explanations and fix steps."""
    return jsonify(run_troubleshoot_checks())

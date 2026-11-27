# Control Hub 🚀

> High-performance, ultra-lightweight homelab command center and active node management daemon tailored for low-power hardware.  
> Runs on **< 25 MB RAM** and **< 0.2% CPU** with zero Node.js/npm dependencies.

[![CI](https://github.com/RAM-MAHESHWARI24/control-hub/actions/workflows/ci.yml/badge.svg)](https://github.com/RAM-MAHESHWARI24/control-hub/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/Release-v2.1.1-brightgreen.svg)](https://github.com/RAM-MAHESHWARI24/control-hub/releases)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![RAM Footprint](https://img.shields.io/badge/RAM-%3C25MB-success.svg)](#performance)
[![OpenAPI 3.1](https://img.shields.io/badge/OpenAPI-3.1-6BA539.svg)](docs/openapi.yaml)
[![Port: 7575](https://img.shields.io/badge/Port-7575-orange.svg)](#quickstart)

---

## 🌟 Why Control Hub?

Most homelab dashboards (Homarr, Homepage, Dashy) are heavy, static bookmark managers packaged in 200MB+ Docker images with continuous Node.js runtime overhead. 

**Control Hub** is an **active server management daemon** built with Python Flask and modular Vanilla ES6. It gives you a calm, 5-view Operations Console (`Overview`, `Apps & Media`, `Backups & Photos`, `TVs`, `System`) with Dark/Light/System themes, real-time hardware telemetry, active power control, searchable container logs, day-to-day node configuration, and an integrated AI copilot—all with zero external CDN requests while sipping resources on low-power hardware (such as 2-core mini-PCs or Intel N100s).

### 🧭 Workspace Views & Themes
* **5 Focused Hash-Routed Views:** `Overview` (`#/overview` — flush hairline Quick-Launch matrix, 4-cell Console KPI bench, adaptive Live Activity ledger, and `Host Record` trail), `Apps & Media` (`#/apps` — ruled desktop `service-ledger` table with search/custom container toggle + qBittorrent queue), `Backups & Photos` (`#/backups` — 4-cell verification header + `.trail` backup run timeline), `TVs` (`#/tvs` — ruled ADB Fleet & Package Matrix), and `System` (`#/system` — Compute & Storage bench, Disk I/O, HiDPI LAN oscilloscope + Speedtest, 24-hour Sleep Guard Pin Axis, Scheduled Automations, Node Administration).
* **Collapsible Icon-Rail Navigation (`>= 600px`):** Clicking inside `#main-content` automatically collapses the desktop sidebar to an icon-only rail showing module names on hover/focus, with a bottom arrow toggle (`←` / `→`) persisted in `localStorage`.
* **Adaptive Module Visibility:** Optional modules (`Backups`, `TVs`, `Sleep Guard`, `Prowlarr Indexers`) automatically hide their navigation links or display honest not-installed states when absent, and deep links redirect cleanly to `#/overview`.
* **Hallmark `Console` Theme System (`console: graphite` Dark + `console: paper` Light):** Uses self-hosted `Host Grotesk` + `Atkinson Hyperlegible Mono` fonts (`< 40 KB` total), OKLCH 1px hairline-divided surfaces, dual-semantic signals (**Amber** for operator actions vs **Cool Blue** for telemetry), and OS-following Auto mode persisted with zero FOUC, passing WCAG 2.2 AA contrast and >= 44px touch targets across phone, tablet, and desktop.

![Control Hub Header & Actions](docs/assets/hub_header_settings_ai.png)

---

## 📦 Complete Feature & Widget Catalog

Control Hub is organized into modular Python backend widgets (`widgets/`) and matching ES6 frontend controllers:

### 1. 🛌 Sleep Guard Power Automation (`widgets/sleep_guard.py`)
* **Real-Time Suspend Telemetry:** Displays tonight's configured suspend and RTC wake schedule in the host's local timezone (automatically hidden or marked not installed when Sleep Guard is absent).
* **1-Click Sleep Inhibition:** Toggle `/run/server-suspend.skip` directly from the UI to prevent sleep tonight without touching SSH.
* **Dynamic Time Shifting & Permanent Toggle:** Push tonight's sleep time back by **+1 Hour** or **+2 Hours** via `/run/server-suspend.override`, or disable/edit the recurring schedule in `/etc/server-suspend.conf`.
* **Process-Aware Deferral:** Automatically defers suspend while backups, restore tests, active LAN SMB shares, active qBittorrent downloads, or active Jellyfin playback are running.

### 2. ⚡ Live Network Telemetry (`widgets/network_speed.py`)
* Non-blocking background sampler computing true delta Rx/Tx bandwidth from `/sys/class/net/<active_nic>/statistics`.
* Cached Ookla Speedtest results (`speedtest_cache.json`) for ISP sanity checking.

### 3. 📥 qBittorrent Ingest Monitor (`widgets/current_downloads.py`)
* Live download speeds, remaining ETA, and completion percentages.
* 1-Click download queue pause and resume.

### 4. 📸 Immich & Noodle Backup Monitor (`widgets/backup_sync.py`)
* Reads only `status.json` from the backup script (no `sudo rclone`): last good run and its age, next run, Drive usage, the last 7 runs, and what retention kept and will delete next.
* Turns red when the last run failed, was interrupted, or the last good run is older than 26 hours (`BACKUP_STALE_HOURS`). A failed pre-flight lists each check and why it failed.
* "Run backup now" starts the same script as the nightly job and shows its log live.
* **Change remote**: pick another rclone remote (and optional folder), **Test** it (it must answer; the dialog says which backup folders it already has and warns when the whole photo library would be uploaded), then **Save**. Both backups switch from their next run. Needs the blueprint's root helper `homelab-backup-remote`; hidden otherwise.
* **Restore test**: the result of the monthly test that restores the newest remote dump into a throwaway database (photos counted against the dump), when it runs next, and **Run restore test now**. A failed test turns the card red and sends a critical alert.
* A **Media app settings** row shows the media module's nightly settings backup (databases and config of the media apps) with **Back up now** (`MEDIA_BACKUP_SCRIPT`, `MEDIA_BACKUP_STATUS_FILE`).
* Displays master photo and video library storage consumption.

### 4b. 🔔 Alerts (`widgets/alerts.py`, `core/alerts.py`)
* Sends a message when something needs attention: photo backup failed, interrupted or older than 26 hours; backup remote not reachable (Drive login expired); a disk over 85% or 95%; an app stopped or unhealthy for 5 minutes; CPU above 80 °C for 2 minutes; a TV app update failed; too many failed dashboard sign-ins.
* Channels: ntfy (phone app, no account; the dashboard can generate a private topic), Telegram, Discord and email (SMTP), each with a **Send test** button.
* Each alert is sent once, repeated after 24 hours if still open, and followed by "Resolved" when it clears. During quiet hours (default 23:00 to 07:00) only critical alerts go out; the rest arrive as one message when quiet hours end. An optional daily summary goes out at a set time.
* Setup for every channel: [Control Hub Alerts guide](https://github.com/RAM-MAHESHWARI24/homelab-blueprint/blob/develop/docs/CONTROL_HUB_ALERTS.md).
* Rules are checked every minute in one background thread. Settings and state live in `ALERTS_CONFIG_FILE` / `ALERTS_STATE_FILE` (0600, default the Control Hub state directory).

### 5. 📊 System Vitals & Hardware Gauges (`widgets/system_vitals.py`)
* Real-time CPU load, memory utilization, swap headroom, and thermal temperatures.
* **Universal Hardware Detection:** Dynamically probes host CPU model name, thread count, physical RAM, and storage mount headroom without hardcoded hardware assumptions.

### 6. 💾 Storage Operations & Hourly Directory Sizes (`widgets/storage_ops.py`, `core/storage_sizes.py`)
* Per-filesystem visual gauges for OS root storage and secondary media storage pools (deduplicated by filesystem `st_dev`, separating SSD appdata from HDD pools).
* Real-time read/write I/O throughput with dynamic block device resolution (NVMe, SATA/SAS, LVM/device-mapper, eMMC, virtio, RAID).
* Optional hourly `homelab-storage-sizes.timer` (root systemd oneshot outside Control Hub's cgroup) writes `0644` atomic JSON sizes for restricted photo directories; standalone mode gracefully surfaces partial-scan warnings when subdirectories are unreadable.

### 7. ⏰ Scheduled Cron Tasks (`widgets/cron_tasks.py`)
* Parses real installed schedules from `/etc/cron.d/*`, systemd timers, and Sleep Guard config, automatically hiding uninstalled modules.

### 8. 📜 Service Matrix & Container Logs (`widgets/service_matrix.py`)
* Lists installed containers (plus Cockpit when its socket is active) with real Docker healthcheck badges (`Healthy`, `Unhealthy`, `Starting`, `Scheduled Off`), dynamic published ports, client search, and an optional toggle to include non-blueprint Docker containers (`?include_other=true`).
* Start, stop, or restart containers (direct `docker` group access, no `sudo`, with streaming-aware confirmation prompts for guarded services) and inspect searchable, copyable logs inline. A Dozzle link appears only while a `dozzle` container is running.

### 9. 📺 Android TV Fleet Preview (`widgets/tv_updater.py`)
* Status and sync state of background ADB app updates for the TVs in the TV auto-updater profile. The online count and the device list come from the same data.

---

## ⚙️ Integrated Node Configuration Center (`widgets/config_center.py`)

Accessible via the header button **Config** (`btn-open-config-center`) or the `System -> Node Administration` panel, this 4-tab modal allows operators to inspect and reconfigure the homelab on the fly without editing `.env` files manually:

![Settings Hardlink Verification](docs/assets/hub_settings_hardlink_test.png)

### Tab 1: Storage & Identity
* Real-time `os.link` hardlink inode validation probe with millisecond latency measurement.
* Live directory path modification for Media Data Root (`HDD_DATA`), Photo Library Root (`HDD_MEMORIES`), container `PUID`/`PGID` auto-detection, and host IANA timezone (`TIMEZONE`).
* When managed by the blueprint installer (`/etc/homelab/config.json`), displays a read-only banner explaining how to apply path/secret updates via `sudo ./setup.sh --headless --config /etc/homelab/config.json` while keeping live hardlink probes, Port Matrix, and Netplan controls interactive.

### Tab 2: Port Matrix & Live Socket Prober
* Live socket-level prober testing all core homelab service ports simultaneously (`Bound` vs `Free`).
* Real-time status cards for Jellyfin (`8096`), Seerr (`5055`), Sonarr (`8989`), Radarr (`7878`), Prowlarr (`9696`), Bazarr (`6767`), qBittorrent (`8080`/`6881`), Immich (`2283`), Control Hub (`7575`), Cockpit (`9090`), and Dozzle (`8888`).

![Settings Port Matrix](docs/assets/hub_settings_port_matrix.png)

### Tab 3: API Secrets & Credentials
* 1-Click CSPRNG generator for high-entropy alphanumeric passwords and 32-character hex API keys for qBittorrent and all `*arr` services (stored values masked as `********`).

### Tab 4: Safe Netplan Static IP Manager
* Inspects active network interface, gateway, and DNS servers.
* Generates clean Ubuntu Netplan YAML for preview before applying.
* Applies the change with an armed 120s revert timer (`homelab-netplan-revert.timer`) and keeps it only after confirmation from the new address, so you never get locked out over SSH.

---

## 🤖 Built-in AI Copilot Modal

Accessible via the header button **🤖 AI Copilot** (`btn-open-ai-copilot`), this drawer empowers operators pairing with AI coding assistants (ChatGPT, Claude, Cursor, Antigravity):

![AI Copilot Drawer](docs/assets/hub_ai_copilot_diagnostics.png)

* **Hardware Intelligence Extraction:** Gathers host CPU model, core/thread count, physical memory, active IP, and `/dev/dri` GPU render node status.
* **1-Click Prompt Exporter:** Generates a dense, token-optimized context prompt (~300 tokens) ready to copy/paste into an LLM session.
* **Quick Reference Runbooks:** Direct links to offline technical markdown runbooks (`STORAGE_AND_HARDLINKS.md`, `POWER_MANAGEMENT_RTCWAKE.md`, etc.).

---

## 🔌 REST API Documentation

### Observability & Health Probing Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Standard service health status, version, and uptime |
| `GET` | `/api/livez` | Kubernetes-style liveness probe (checks event loop responsiveness) |
| `GET` | `/api/readyz` | Kubernetes-style readiness probe (checks storage and telemetry subsystems) |
| `GET` | `/api/docs` | Interactive Swagger UI API documentation portal |
| `GET` | `/api/openapi.yaml` | Raw OpenAPI 3.1.0 machine-readable contract |

### System & Telemetry Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/system/vitals` | Real-time CPU, RAM, Swap, and per-filesystem disk capacity metrics |
| `GET` | `/api/network/speed` | True Rx/Tx bandwidth deltas for the active NIC and cached Speedtest info |
| `GET` | `/api/storage/operations` | Real-time disk I/O throughput and SMB/Jellyfin client sessions |
| `GET` | `/api/storage/overview` | Per-folder usage, 30-day fill forecast, safe cleanup suggestions, and drive SMART health |
| `POST` | `/api/storage/cleanup` | Execute one safe cleanup (`torrents_seeded`, `qbit_logs`, `docker_prune`, or `old_dumps`) |
| `GET` | `/api/downloads/active` | Active qBittorrent downloads, speeds, status, priority, and ETAs |
| `POST` | `/api/torrents/toggle-all` | Pause/Stop or Resume/Start all torrents (qBittorrent 4.x & 5.x compatible) |
| `POST` | `/api/torrents/<hash>/action` | Per-torrent `pause`, `resume`, `delete` (with optional `delete_files`), or priority change |
| `GET` / `POST` | `/api/torrents/limits` | Read or update global DL/UL speed caps, alt-speed mode toggle, and evening schedule |
| `GET` | `/api/backup/status` | Photo & media cloud backup status, quota, and restore test telemetry |
| `GET` | `/api/photos/overview` | Per-user photo storage, ML schedule & job queue, Face-to-XMP export telemetry, and folder health |
| `POST` | `/api/photos/ml/schedule` | Update or pause `/etc/cron.d/immich-ml` start/stop times |
| `POST` | `/api/photos/ml/action` | Immediately `start` or `stop` the Immich Machine Learning container |
| `GET` | `/api/alerts` | Alert channels, rules, open alerts and recent history |
| `PUT` | `/api/alerts/config` | Save alert channels, rules and quiet hours |
| `POST` | `/api/alerts/test` | Send a test message to one channel |
| `POST` | `/api/alerts/check` | Check every alert rule now |
| `POST` | `/api/backup/media/run` | Back up the media apps' settings now |
| `POST` | `/api/backup/restore-test` | Start the photo backup restore test now |
| `GET` | `/api/backup/remotes` | rclone remotes on the server and the one in use |
| `POST` | `/api/backup/remote/test` | Test a remote (answers, space, existing folders) |
| `PUT` | `/api/backup/remote` | Switch both backups to another remote |
| `GET` | `/api/services/status` | Real Docker health, restart count, uptime, image version, published ports, and container IDs (`?include_other=true` supported) |
| `POST` | `/api/services/action/<service>` | Start, stop, or restart a Docker container (`{"action": "start\|stop\|restart"}`) |
| `GET` | `/api/services/logs/<service>?tail=150` | Direct Docker or Cockpit log stream |
| `POST` | `/api/indexers/add` | Adds selected Prowlarr indexers with optional credentials |
| `GET` | `/api/indexers/health` | Per-indexer Prowlarr health status, disabled state, and failure fix hints |
| `POST` | `/api/indexers/test-all` | Triggers Prowlarr connectivity test across all configured indexers |
| `GET` | `/api/media/overview` | Aggregates pending Seerr requests, 7-day Radarr/Sonarr calendar, missing items, and Jellyfin recent additions |
| `POST` | `/api/media/requests/<id>/<decision>` | Approves or declines a pending Seerr media request |
| `POST` | `/api/media/jellyfin/scan` | Triggers a Jellyfin library refresh scan |
| `GET` | `/api/network/overview` | Per-NIC link speed & duplex health warnings, Tailscale status/subnet-router state, and service port map with conflict flags |
| `GET` | `/api/updates` | Compares pinned container tags & Blueprint version against cached GitHub releases |
| `POST` | `/api/updates/check` | Checks upstream GitHub releases on demand (10-minute cooldown) |
| `POST` | `/api/updates/apply` | Applies one or all safe app updates via `homelab-update` with pre-update config backup & automatic health rollback |
| `POST` | `/api/updates/self-update` | Checks out a Blueprint release tag via `homelab-update` and re-applies setup (blueprint installs only) |
| `POST` | `/api/updates/policy` | Toggles optional automatic patch/rebuild updates (never majors or minors) |
| `GET` | `/api/updates/job` | Polls active or most recent app/blueprint update job status |
| `GET` | `/api/tv-updater/status` | Android TV fleet ADB update status |
| `PUT` | `/api/tv-updater/devices/<id>/nickname` | Give a TV a nickname (empty shows the detected model) |
| `POST` | `/api/tv-updater/scan-lan` | Scan the LAN subnet for open ADB TCP endpoints |
| `POST` | `/api/tv-updater/connect` | Pair ADB, detect model/Android version, or surface authorization prompt |
| `POST` | `/api/tv-updater/devices` | Add a managed TV profile to `/var/lib/homelab/tv-autoupdater/tv_profiles.json` |
| `PATCH` | `/api/tv-updater/devices/<id>` | Update TV name, IP/port, pause toggle, or selected apps |
| `POST` | `/api/tv-updater/devices/<id>/test` | Test live ADB connection for a TV |
| `DELETE` | `/api/tv-updater/devices/<id>` | Remove a TV profile from the fleet |

### Power Management Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/sleep/status` | Tonight's scheduled suspend, disabled/not-installed state, and RTC wake status |
| `POST` | `/api/sleep/toggle` | Creates/clears `/run/server-suspend.skip` to stay awake tonight |
| `POST` | `/api/sleep/shift-tonight` | Shifts tonight's suspend time by +1h, +2h, or custom window |
| `POST` | `/api/sleep/schedule-permanent` | Updates or disables the recurring nightly sleep schedule |
| `GET` | `/api/cron/status` | All installed timed jobs (`next_run`, `last_run`, `editable`) plus sleep/backup clash warnings |
| `POST` | `/api/cron/schedule/<job_id>` | Previews (`preview_only: true`) or updates a job's cron/Sleep Guard schedule and recalculates clashes |
| `GET` | `/api/auth/sessions` | Lists tracked browser sessions (device label, IP, role, last seen) for per-device sign-out (`DELETE /api/auth/sessions/<id>`) |
| `GET`/`POST` | `/api/auth/access` | Reads or updates read-only Family View (`family_enabled`, `family_lan_open`, `family_password`) |
| `POST` | `/api/auth/totp/{setup,enable,disable}` | Configures optional RFC 6238 TOTP two-factor authentication + recovery codes for owner logins |

### Configuration Center Endpoints (`widgets/config_center.py`)

| Method | Endpoint | Parameters / Body | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/config/current` | None | Returns active `.env` configuration dictionary, blueprint mode, and undo availability |
| `POST` | `/api/config/preview` | Proposed JSON config | Validates changes and previews a redacted field-by-field diff |
| `POST` | `/api/config/update` | JSON payload of env key-values | Saves snapshot and applies updates via `homelab-config-apply` (or directly when standalone) |
| `POST` | `/api/config/undo` | None | Reverts the last applied blueprint configuration snapshot |
| `GET` | `/api/config/manifest` | None | Returns `/var/lib/homelab/installed.json` modules, units, crons, and stacks |
| `GET` | `/api/config/export` | `?download=1` optional | Exports portable settings JSON with all secrets stripped |
| `POST` | `/api/config/import` | `{"config": {...}, "preview": true}` | Previews or applies imported settings safely with secrets stripped |
| `GET` | `/api/config/support-bundle` | `?download=1` optional | Downloads system vitals, container status, and secret-scrubbed logs |
| `POST` | `/api/config/verify-hardlink` | `{"path": "/mnt/hdd/data"}` | Executes live `os.link` probe and measures latency |
| `GET` | `/api/config/ports` | None | Probes all 13 services and returns active/inactive status |
| `POST` | `/api/config/generate-secrets` | None | Generates cryptographically secure passwords & API keys |
| `GET` | `/api/config/ai-diagnostics` | None | Returns hardware specs and ~300-token preformatted AI prompt |
| `POST` | `/api/config/netplan-preview` | `{"ip": "...", "gateway": "..."}` | Generates clean Netplan YAML configuration |
| `POST` | `/api/config/netplan-apply` | `{"interface": "...", "ip": ".../24", "gateway": "...", "dns": [...]}` | Applies with a revert timer; confirm with `POST /api/config/netplan-confirm`, inspect with `GET /api/config/netplan-status` |

---

> This repository is a read-only mirror of a folder in [homelab-blueprint](https://github.com/RAM-MAHESHWARI24/homelab-blueprint), published on every release. Please open issues and pull requests there.

## 🚀 Quickstart & Standalone Deployment

Control Hub ships with the [homelab-blueprint](https://github.com/RAM-MAHESHWARI24/homelab-blueprint) installer. To run it on its own, next to an existing setup:

```bash
git clone https://github.com/RAM-MAHESHWARI24/control-hub.git
cd control-hub
./install.sh            # creates .env with a new access token and a Python venv
./run.sh                # starts the dashboard on port 7575
```

Or in Docker:

```bash
./install.sh --docker   # same .env, then docker compose up -d --build
```

The script prints the dashboard link with the token. Anyone holding the token controls the host, so keep it private. Then edit `.env`:

- `QBITTORRENT_URL`, `QBITTORRENT_USER`, `QBITTORRENT_PASS` for the downloads card. In Docker the default `http://host.docker.internal:8080` reaches a qBittorrent on the host.
- `BACKUP_DIR` for the backup card, where your photo backups land.
- `TV_UPDATER_DIR` and `TV_UPDATER_PY` only if you also run [tv-autoupdater](https://github.com/RAM-MAHESHWARI24/tv-autoupdater). Without them the TV card stays hidden.

---

## 🔧 Systemd Service Deployment

To run Control Hub as a hardened, unprivileged background daemon on Ubuntu:

```ini
# /etc/systemd/system/control-hub.service
[Unit]
Description=Control Hub (Custom Dashboard & API Engine)
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
User=homelab
Group=homelab
SupplementaryGroups=docker
WorkingDirectory=/opt/homelab-blueprint/apps/control-hub
EnvironmentFile=-/opt/homelab-blueprint/apps/control-hub/.env
ExecStart=/opt/homelab-blueprint/apps/control-hub/venv/bin/python3 /opt/homelab-blueprint/apps/control-hub/server.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

# Low-power resource bounds
CPUQuota=20%
MemoryMax=100M

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now control-hub.service
```

---

## 📄 License
MIT License. Part of the [Homelab Blueprint](https://github.com/RAM-MAHESHWARI24/homelab-blueprint) ecosystem.

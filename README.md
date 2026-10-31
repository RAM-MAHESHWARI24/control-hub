# Control Hub 🚀

> High-performance, ultra-lightweight homelab command center and active node management daemon tailored for low-power hardware.  
> Runs on **< 25 MB RAM** and **< 0.2% CPU** with zero Node.js/npm dependencies.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![RAM Footprint](https://img.shields.io/badge/RAM-%3C25MB-success.svg)](#performance)
[![Zero-NPM](https://img.shields.io/badge/Frontend-Vanilla%20ES6%20%2B%20CSS-success.svg)](#architecture)
[![Port: 7575](https://img.shields.io/badge/Port-7575-orange.svg)](#quickstart)

---

## 🌟 Why Control Hub?

Most homelab dashboards (Homarr, Homepage, Dashy) are heavy, static bookmark managers packaged in 200MB+ Docker images with continuous Node.js runtime overhead. 

**Control Hub** is an **active server management daemon** built with Python Flask and modular Vanilla ES6. It gives you real-time hardware telemetry, active power control, live container logs, day-to-day node configuration, and an integrated AI copilot while sipping resources on low-power hardware (such as 2-core Haswell mini-PCs or Intel N100s).

![Control Hub Header & Actions](../../docs/assets/control-hub/hub_header_settings_ai.png)

---

## 📦 Complete Feature & Widget Catalog

Control Hub is organized into modular Python backend widgets (`widgets/`) and matching ES6 frontend controllers:

### 1. 🛌 Sleep Guard Hero Card (`widgets/sleep_guard.py`)
* **Real-Time Suspend Telemetry:** Displays tonight's scheduled suspend time (default 00:00 IST) and hardware RTC wake alarm (06:00 IST).
* **1-Click Sleep Inhibition:** Toggle `/run/server-suspend.skip` directly from the UI to prevent sleep tonight without touching SSH.
* **Dynamic Time Shifting:** Push tonight's sleep time back by **+1 Hour** or **+2 Hours** on the fly via `/run/server-suspend.override`.
* **Process-Aware Deferral:** Automatically monitors background backup jobs (`immich_backup_gdrive.sh`, `rclone`, `pg_dumpall`) and defers sleep until completion.

### 2. ⚡ Live Network Telemetry (`widgets/network_speed.py`)
* Non-blocking background sampler computing true delta Rx/Tx bandwidth from `/sys/class/net/<active_nic>/statistics`.
* Cached Ookla Speedtest results (`speedtest_cache.json`) for ISP sanity checking.

### 3. 📥 qBittorrent Ingest Monitor (`widgets/current_downloads.py`)
* Live download speeds, remaining ETA, and completion percentages.
* 1-Click download queue pause and resume.

### 4. 📸 Immich & Noodle Backup Monitor (`widgets/backup_sync.py`)
* Monitors nightly PostgreSQL database dumps and Google Drive cloud mirror progress.
* Displays master photo and video library storage consumption.

### 5. 📊 System Vitals & Hardware Gauges (`widgets/system_vitals.py`)
* Real-time CPU load, memory utilization, swap headroom, and thermal temperatures.
* **Universal Hardware Detection:** Dynamically probes host CPU model name, thread count, physical RAM, and storage mount headroom without hardcoded hardware assumptions.

### 6. 💾 Storage Operations & Inodes (`widgets/storage_ops.py`)
* Visual gauges for primary root storage (NVMe/SSD) and secondary storage pool (HDD/SATA).
* Real-time read/write I/O throughput with dynamic block device resolution (`/dev/nvme*`, `/dev/sd*`, `/dev/vd*`).

### 7. ⏰ Scheduled Cron Tasks (`widgets/cron_tasks.py`)
* Visual inspection of system cron jobs (nightly ML scheduler, daily Recyclarr sync, weekly Watchtower updates).

### 8. 📜 Service Matrix & Container Logs (`widgets/service_matrix.py`)
* Instant launcher for all running services.
* Integrated container log streaming via Dozzle using dynamic 12-character hex Docker IDs (`/container/<docker_id>`).

### 9. 📺 Android TV Fleet Preview (`widgets/tv_updater.py`)
* Status and sync state of background ADB app updates across living room and bedroom smart TVs.

---

## ⚙️ Integrated Node Configuration Center (`widgets/config_center.py`)

Accessible via the header button **⚙️ Settings** (`btn-open-config-center`), this 5-tab modal allows operators to inspect and reconfigure the homelab on the fly without editing `.env` files manually:

![Settings Hardlink Verification](../../docs/assets/control-hub/hub_settings_hardlink_test.png)

### Tab 1: Storage & Atomic Hardlinks
* Real-time `os.link` hardlink inode validation probe with millisecond latency measurement.
* Live directory path modification for Media Root (`DATA_ROOT_HOST`), Photo Storage (`MEMORIES_ROOT_HOST`), and App Configs (`CONFIG_ROOT_HOST`).

### Tab 2: 13-Service Port Matrix & Connectivity Prober
* Live socket-level prober testing all 13 core homelab ports simultaneously.
* Real-time badges (`ACTIVE` in green, `INACTIVE` in amber) for Jellyfin (8096), Seerr (5055), Sonarr (8989), Radarr (7878), Prowlarr (9696), Bazarr (6767), qBittorrent (8080/6881), Immich (2283), Control Hub (7575), Cockpit (9090), and Dozzle (8888).

![Settings Port Matrix](../../docs/assets/control-hub/hub_settings_port_matrix.png)

### Tab 3: Security & Secrets Generator
* 1-Click CSPRNG generator for high-entropy alphanumeric passwords and 32-character hex API keys for all *arr services and PostgreSQL.

### Tab 4: Safe Netplan Static IP Manager
* Inspects active network interface, gateway, and DNS servers.
* Generates clean Ubuntu Netplan YAML.
* Executes safe rollback validation (`netplan try --timeout 45`) so you never get locked out over SSH.

### Tab 5: Setup Wizard Fast Launcher
* 1-Click button to launch the zero-dependency Onboarding Setup Wizard on port `8000` for full cluster re-provisioning.

---

## 🤖 Built-in AI Copilot Modal

Accessible via the header button **🤖 AI Copilot** (`btn-open-ai-copilot`), this drawer empowers operators pairing with AI coding assistants (ChatGPT, Claude, Cursor, Antigravity):

![AI Copilot Drawer](../../docs/assets/control-hub/hub_ai_copilot_diagnostics.png)

* **Hardware Intelligence Extraction:** Gathers host CPU model, core/thread count, physical memory, active IP, and `/dev/dri` GPU render node status.
* **1-Click Prompt Exporter:** Generates a dense, token-optimized context prompt (~300 tokens) ready to copy/paste into an LLM session.
* **Quick Reference Runbooks:** Direct links to offline technical markdown runbooks (`STORAGE_AND_HARDLINKS.md`, `POWER_MANAGEMENT_RTCWAKE.md`, etc.).

---

## 🔌 REST API Documentation

### System & Telemetry Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/system/vitals` | Real-time CPU, RAM, Swap, and disk capacity metrics |
| `GET` | `/api/network/speed` | True Rx/Tx bandwidth deltas for `ACTIVE_NIC` |
| `GET` | `/api/storage/ops` | Real-time disk I/O throughput |
| `GET` | `/api/downloads/status` | Active qBittorrent downloads, speeds, and ETAs |
| `GET` | `/api/backup/status` | Immich backup and Google Drive sync status |
| `GET` | `/api/services/status` | Health status and container IDs for all services |
| `GET` | `/api/services/logs/<service>?tail=50` | Direct Docker log stream |
| `GET` | `/api/tv/status` | Android TV fleet ADB update status |

### Power Management Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/power/sleep-status` | Tonight's scheduled suspend and RTC wake status |
| `POST` | `/api/power/skip-sleep` | Creates `/run/server-suspend.skip` to prevent sleep tonight |
| `POST` | `/api/power/shift-sleep` | Shifting tonight's suspend time by +1h or +2h |

### Configuration Center Endpoints (`widgets/config_center.py`)

| Method | Endpoint | Parameters / Body | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/config/current` | None | Returns active `.env` configuration dictionary |
| `POST` | `/api/config/update` | JSON payload of env key-values | Atomically writes updated settings to `.env` |
| `POST` | `/api/config/verify-hardlink` | `{"path": "/mnt/hdd/data"}` | Executes live `os.link` probe and measures latency |
| `GET` | `/api/config/ports` | None | Probes all 13 services and returns active/inactive status |
| `POST` | `/api/config/generate-secrets` | None | Generates cryptographically secure passwords & API keys |
| `GET` | `/api/config/ai-diagnostics` | None | Returns hardware specs and ~300-token preformatted AI prompt |
| `POST` | `/api/config/netplan-preview` | `{"ip": "...", "gateway": "..."}` | Generates clean Netplan YAML configuration |
| `POST` | `/api/config/netplan-apply` | `{"config_yaml": "..."}` | Runs safe `netplan try --timeout 45` with auto-rollback |

---

## 🚀 Quickstart

### 1. Requirements
* Python 3.10+
* Linux host (Ubuntu 24.04 / 26.04 LTS recommended)
* Optional: Docker (for container logs and service matrix)

### 2. Manual Installation
```bash
cd apps/control-hub
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Running
```bash
python3 server.py
```
Open `http://<your-server-ip>:7575` in your browser.

---

## 🔧 Systemd Service Deployment

To run Control Hub as an auto-starting system daemon on Ubuntu:

```ini
# /etc/systemd/system/control-hub.service
[Unit]
Description=Control Hub Homelab Management Daemon
After=network.target

[Service]
Type=simple
User=server_ff
WorkingDirectory=/opt/homelab-blueprint/apps/control-hub
ExecStart=/opt/homelab-blueprint/apps/control-hub/venv/bin/python3 /opt/homelab-blueprint/apps/control-hub/server.py
Restart=always
RestartSec=5
EnvironmentFile=-/opt/homelab-blueprint/.env

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
MIT License. Part of the [Homelab Blueprint](../../README.md) monorepo.

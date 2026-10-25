# Control Hub 🚀

> High-performance, ultra-lightweight homelab dashboard and server management daemon tailored for low-power hardware.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![RAM Footprint](https://img.shields.io/badge/RAM-%3C25MB-success.svg)](#performance)

---

## 🌟 Overview

Most homelab dashboards (Homarr, Homepage, Dashy) are static bookmark managers with high RAM footprints. **Control Hub** is an active server management daemon built in Python Flask and Vanilla ES6 modules. It runs with **< 25 MB RAM** and **< 0.2% CPU** while providing active management controls, live docker logs, and hardware telemetry.

### Key Capabilities

* **🛌 Sleep Guard Hero Card:** Quick-toggle sleep inhibition (`/run/server-suspend.skip`), one-off shift buttons (`+1h`, `+2h`), and recurring midnight sleep scheduling.
* **⚡ Live LAN Telemetry:** Non-blocking background sampler calculating true Rx/Tx bandwidth against network interfaces with Ookla Speedtest cache integration.
* **📥 qBittorrent Ingest Monitor:** Displays active torrent downloads, speeds, ETAs, and 1-click download queue pause.
* **📸 Immich Backup & Sync Monitor:** Tracks nightly PostgreSQL database snapshots, cloud sync status, and storage utilization.
* **📊 System Vitals & Storage Ops:** Instant CPU, RAM, SSD, and HDD headroom gauges with real-time disk I/O throughput.
* **📜 Service Matrix & Dozzle Log Streamer:** Service launcher with integrated 12-char hexadecimal Docker ID log streaming.
* **📺 Android TV Fleet Preview:** Status of background ADB app updates across living room and bedroom smart TVs.

---

## 🚀 Quickstart

### 1. Requirements
* Python 3.10+
* Docker (optional, for Dozzle and container metrics)
* Linux host (Ubuntu/Debian recommended)

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/your-username/control-hub.git /opt/control-hub
cd /opt/control-hub

# Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configuration
Copy `.env.example` to `.env` or set environment variables:
```bash
cp .env.example .env
nano .env
```

| Variable | Default | Description |
| :--- | :--- | :--- |
| `CONTROL_HUB_PORT` | `7575` | Dashboard HTTP listening port |
| `ACTIVE_NIC` | `eth0` | Network interface for real-time throughput |
| `LINK_SPEED_MBPS` | `1000` | Max LAN link speed |
| `QBITTORRENT_URL` | `http://127.0.0.1:8080` | qBittorrent WebUI address |
| `QBITTORRENT_USER` | `admin` | qBittorrent username |
| `QBITTORRENT_PASS` | `adminadmin` | qBittorrent password |

### 4. Running
```bash
python3 server.py
```
Open `http://<your-server-ip>:7575` in your browser.

---

## 🔧 Systemd Service Deployment

To run Control Hub as an auto-starting background daemon on Linux:

```ini
# /etc/systemd/system/control-hub.service
[Unit]
Description=Control Hub Homelab Dashboard
After=network.target

[Service]
Type=simple
User=homelab_user
WorkingDirectory=/opt/control-hub
ExecStart=/opt/control-hub/venv/bin/python3 /opt/control-hub/server.py
Restart=always
RestartSec=5
EnvironmentFile=-/opt/control-hub/.env

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
MIT License. Feel free to use and modify for your homelab!

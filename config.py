"""
Control Hub - Centralized Configuration Template
Copy this file to config.py or set environment variables in a .env file.
"""

import os
from pathlib import Path

# Directory Anchors
BASE_DIR = Path(__file__).resolve().parent
APPS_DIR = BASE_DIR.parent


def _load_env_file(path: Path) -> None:
    """Loads KEY=VALUE lines into the environment without overriding existing values."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    except OSError:
        pass


# Configuration sources, first match wins per key:
#   1. real environment (systemd EnvironmentFile=/etc/homelab/control-hub.env)
#   2. ./.env next to this file (standalone / docker usage; the installer symlinks it)
#   3. /etc/homelab/control-hub.env directly (when run by hand on an installed host)
for _candidate in (BASE_DIR / ".env", Path(os.getenv("HOMELAB_ETC_DIR", "/etc/homelab")) / "control-hub.env"):
    if _candidate.exists():
        _load_env_file(_candidate)

# Server Binding
HOST = os.getenv("CONTROL_HUB_HOST", "0.0.0.0")
PORT = int(os.getenv("CONTROL_HUB_PORT", 7575))

# File & Directory Paths
SUSPEND_SKIP_FILE = os.getenv("SUSPEND_SKIP_FILE", "/run/server-suspend.skip")
SUSPEND_OVERRIDE_FILE = os.getenv("SUSPEND_OVERRIDE_FILE", "/run/server-suspend.override")
SUSPEND_CONFIG_FILE = os.getenv("SUSPEND_CONFIG_FILE", "/etc/server-suspend.conf")
SUSPEND_CRON_FILE = os.getenv("SUSPEND_CRON_FILE", "/etc/cron.d/server-suspend")
BACKUP_LOG_FILE = os.getenv("BACKUP_LOG_FILE", "/opt/immich/backups/backup.log")
BACKUP_DIR = os.getenv("BACKUP_DIR", "/opt/immich/backups")
WATCHTOWER_LOG_DIR = os.getenv("WATCHTOWER_LOG_DIR", "/var/log/watchtower")
SPEEDTEST_CACHE_FILE = os.getenv("SPEEDTEST_CACHE_FILE", str(BASE_DIR / "speedtest_cache.json"))
SPEEDTEST_BIN = os.getenv("SPEEDTEST_BIN", "/usr/local/bin/speedtest")
RECYCLARR_LOG_FILE = os.getenv("RECYCLARR_LOG_FILE", "/var/log/recyclarr.log")
IMMICH_ML_LOG_FILE = os.getenv("IMMICH_ML_LOG_FILE", "/var/log/immich-ml.log")
SERVER_SUSPEND_LOG_FILE = os.getenv("SERVER_SUSPEND_LOG_FILE", "/var/log/server-suspend.log")

# Android TV Updater Integration (Dynamically resolves to sibling apps/tv-updater)
TV_UPDATER_DIR = os.getenv("TV_UPDATER_DIR", str(APPS_DIR / "tv-updater"))
TV_UPDATER_PY = os.getenv("TV_UPDATER_PY", str(APPS_DIR / "tv-updater" / "tv_updater.py"))
TV_UPDATER_LOG_FILE = os.getenv("TV_UPDATER_LOG_FILE", "/var/log/tv-updater.log")
TV_UPDATER_LOCAL_LOG_FILE = os.getenv("TV_UPDATER_LOCAL_LOG_FILE", str(APPS_DIR / "tv-updater" / "tv_updater.log"))
TV_UPDATER_STATE_FILE = os.getenv("TV_UPDATER_STATE_FILE", str(APPS_DIR / "tv-updater" / "state.json"))
TV_UPDATER_INCOMING_DIR = os.getenv("TV_UPDATER_INCOMING_DIR", str(APPS_DIR / "tv-updater" / "incoming_apks"))

# Network interface for LAN sampling. Empty = auto-detect the default-route NIC
# (see core.telemetry_sampler.detect_active_nic). Never assume "eth0".
ACTIVE_NIC = os.getenv("ACTIVE_NIC", "")
LINK_SPEED_MBPS = int(os.getenv("LINK_SPEED_MBPS", 1000))

# qBittorrent Configuration (no default password is shipped)
QBITTORRENT_URL = os.getenv("QBITTORRENT_URL", "http://127.0.0.1:8080")
QBITTORRENT_USER = os.getenv("QBITTORRENT_USER", "admin")
QBITTORRENT_PASS = os.getenv("QBITTORRENT_PASS", "")

# Prowlarr (indexer picker). The installer writes the API key to PROWLARR_KEY_FILE
# (0640 root:homelab); PROWLARR_API_KEY in the environment takes precedence.
PROWLARR_URL = os.getenv("PROWLARR_URL", "http://127.0.0.1:9696")
PROWLARR_KEY_FILE = os.getenv("PROWLARR_KEY_FILE", str(Path(os.getenv("HOMELAB_ETC_DIR", "/etc/homelab")) / "prowlarr.key"))

# Services Catalog for Service Matrix
SERVICES_CATALOG = {
    "jellyfin": {"name": "Jellyfin", "port": 8096, "desc": "Media Streaming Server", "icon": "film", "category": "media"},
    "seerr": {"name": "Seerr", "port": 5055, "desc": "Media Discovery & Requests", "icon": "search", "category": "media"},
    "immich_server": {"name": "Immich", "port": 2283, "desc": "Photo & Video Cloud", "icon": "image", "category": "media"},
    "sonarr": {"name": "Sonarr", "port": 8989, "desc": "TV Series Automation", "icon": "tv", "category": "ingest"},
    "radarr": {"name": "Radarr", "port": 7878, "desc": "Movie Automation", "icon": "video", "category": "ingest"},
    "prowlarr": {"name": "Prowlarr", "port": 9696, "desc": "Indexer Proxy & Scrapers", "icon": "rss", "category": "ingest"},
    "bazarr": {"name": "Bazarr", "port": 6767, "desc": "Subtitles Manager", "icon": "file-text", "category": "ingest"},
    "qbittorrent": {"name": "qBittorrent", "port": 8080, "desc": "BitTorrent Downloader", "icon": "download", "category": "system"},
    "dozzle": {"name": "Dozzle", "port": 8888, "desc": "Live Docker Log Streamer", "icon": "terminal", "category": "system"},
    "byparr": {"name": "Byparr", "port": 8191, "desc": "Cloudflare Challenge Solver", "icon": "shield", "category": "system"}
}

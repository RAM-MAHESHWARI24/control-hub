"""
Control Hub - Centralized Configuration
Reads values from process environment, ./.env, or /etc/homelab/control-hub.env.
"""

import datetime
import os
import tempfile
from pathlib import Path

# Directory Anchors
BASE_DIR = Path(__file__).resolve().parent


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

STATE_DIR = Path(os.getenv("HOMELAB_STATE_DIR", "/var/lib/homelab"))
APPDATA_DIR = os.getenv("HOMELAB_APPDATA_DIR", "/srv/homelab/appdata")


def _default_hub_cache_dir() -> Path:
    """Returns a writable directory for Control Hub runtime caches."""
    hub_state = STATE_DIR / "control-hub"
    if "HOMELAB_STATE_DIR" in os.environ or (hub_state.is_dir() and os.access(hub_state, os.W_OK)):
        return hub_state
    if os.access(BASE_DIR, os.W_OK):
        return BASE_DIR
    return Path(tempfile.gettempdir()) / "control-hub"


HUB_CACHE_DIR = _default_hub_cache_dir()

# Server Binding
HOST = os.getenv("CONTROL_HUB_HOST", "0.0.0.0")
PORT = int(os.getenv("CONTROL_HUB_PORT", 7575))

# File & Directory Paths
SUSPEND_SKIP_FILE = os.getenv("SUSPEND_SKIP_FILE", "/run/server-suspend.skip")
SUSPEND_OVERRIDE_FILE = os.getenv("SUSPEND_OVERRIDE_FILE", "/run/server-suspend.override")
SUSPEND_CONFIG_FILE = os.getenv("SUSPEND_CONFIG_FILE", "/etc/server-suspend.conf")
SUSPEND_CRON_FILE = os.getenv("SUSPEND_CRON_FILE", "/etc/cron.d/server-suspend")
SUSPEND_SCRIPT = os.getenv("SUSPEND_SCRIPT", "/usr/local/sbin/server-suspend.sh")

BACKUP_DIR = os.getenv("BACKUP_DIR", str(STATE_DIR / "photo-backups"))
BACKUP_LOG_FILE = os.getenv("BACKUP_LOG_FILE", os.path.join(BACKUP_DIR, "backup.log"))
BACKUP_STATUS_FILE = os.getenv("BACKUP_STATUS_FILE", os.path.join(BACKUP_DIR, "status.json"))
# The nightly schedule (and the settings "Run backup now" uses) live in this cron file.
BACKUP_CRON_FILE = os.getenv("BACKUP_CRON_FILE", "/etc/cron.d/immich-backup")
BACKUP_SCRIPT = os.getenv("BACKUP_SCRIPT", "/usr/local/sbin/immich_backup_gdrive.sh")
BACKUP_STALE_HOURS = float(os.getenv("BACKUP_STALE_HOURS", "26"))
# Media apps' settings backup (the media module's media_config_backup.py), when installed.
MEDIA_BACKUP_DIR = os.getenv("MEDIA_BACKUP_DIR", str(STATE_DIR / "media-backups"))
MEDIA_BACKUP_STATUS_FILE = os.getenv("MEDIA_BACKUP_STATUS_FILE", os.path.join(MEDIA_BACKUP_DIR, "status.json"))
MEDIA_BACKUP_LOG_FILE = os.getenv("MEDIA_BACKUP_LOG_FILE", os.path.join(MEDIA_BACKUP_DIR, "backup.log"))
MEDIA_BACKUP_CRON_FILE = os.getenv("MEDIA_BACKUP_CRON_FILE", "/etc/cron.d/media-backup")
MEDIA_BACKUP_SCRIPT = os.getenv("MEDIA_BACKUP_SCRIPT", "")
# Monthly restore test of the photo database backup (systemd service + timer of that name).
RESTORE_TEST_UNIT = os.getenv("RESTORE_TEST_UNIT", "photo-restore-test")
# Root helper that lists, tests and switches the backup remote (blueprint installs only).
BACKUP_REMOTE_HELPER = os.getenv("BACKUP_REMOTE_HELPER", "/usr/local/sbin/homelab-backup-remote")
SYSTEMD_UNIT_DIR = os.getenv("SYSTEMD_UNIT_DIR", "/etc/systemd/system")
HDD_DATA = os.getenv("HDD_DATA", "/mnt/hdd/data")
HDD_MEMORIES = os.getenv("HDD_MEMORIES", "/mnt/hdd/Memories")
PHOTO_UPLOAD_DIR = os.getenv("PHOTO_UPLOAD_DIR", "")
GDRIVE_REMOTE = os.getenv("GDRIVE_REMOTE", "")

# Immich / Noodle Gallery database settings (overridable for custom installs)
IMMICH_DB_CONTAINER = os.getenv("IMMICH_DB_CONTAINER", "immich_postgres")
IMMICH_DB_USER = os.getenv("IMMICH_DB_USER", "postgres")
IMMICH_DB_NAME = os.getenv("IMMICH_DB_NAME", "immich")
IMMICH_ML_CRON_FILE = os.getenv("IMMICH_ML_CRON_FILE", "/etc/cron.d/immich-ml")
TV_UPDATER_CRON_FILE = os.getenv("TV_UPDATER_CRON_FILE", "/etc/cron.d/tv-autoupdater")

# Optional Jellyfin API settings (enables verified NowPlaying playback detection)
JELLYFIN_URL = os.getenv("JELLYFIN_URL", "http://127.0.0.1:8096")
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY", "")

SPEEDTEST_CACHE_FILE = os.getenv("SPEEDTEST_CACHE_FILE", str(HUB_CACHE_DIR / "speedtest_cache.json"))
STORAGE_SIZES_CACHE_FILE = os.getenv("STORAGE_SIZES_CACHE_FILE", str(HUB_CACHE_DIR / "storage_sizes_cache.json"))
UPDATES_CACHE_FILE = os.getenv("UPDATES_CACHE_FILE", str(HUB_CACHE_DIR / "updates_cache.json"))
UPDATES_POLICY_FILE = os.getenv("UPDATES_POLICY_FILE", str(HUB_CACHE_DIR / "updates_policy.json"))
UPDATES_BLUEPRINT_REPO = os.getenv("UPDATES_BLUEPRINT_REPO", "RAM-MAHESHWARI24/homelab-blueprint")
UPDATES_AUTO_CHECK = os.getenv("UPDATES_AUTO_CHECK", "1").strip().lower() not in ("0", "false", "no")
# Root helper that updates pinned containers safely (with rollback) & self-updates blueprint installs.
UPDATE_HELPER = os.getenv("HOMELAB_UPDATE_HELPER", "/usr/local/sbin/homelab-update")
# Alert channels/rules (may hold a bot token or SMTP password: written 0600) and alert state.
ALERTS_CONFIG_FILE = Path(os.getenv("ALERTS_CONFIG_FILE", str(HUB_CACHE_DIR / "alerts.json")))
ALERTS_STATE_FILE = Path(os.getenv("ALERTS_STATE_FILE", str(HUB_CACHE_DIR / "alerts_state.json")))
SPEEDTEST_BIN = os.getenv("SPEEDTEST_BIN", "/usr/local/bin/speedtest")
RECYCLARR_LOG_FILE = os.getenv("RECYCLARR_LOG_FILE", "/var/log/recyclarr.log")
IMMICH_ML_LOG_FILE = os.getenv("IMMICH_ML_LOG_FILE", "/var/log/immich-ml.log")
SERVER_SUSPEND_LOG_FILE = os.getenv("SERVER_SUSPEND_LOG_FILE", "/var/log/server-suspend.log")

# Android TV auto-updater integration (optional). Unset means the TV widget reports
# "not installed" and the dashboard hides it. The blueprint installer sets both when
# the tv_autoupdater module is enabled; standalone users point them at their checkout.
TV_UPDATER_DIR = os.getenv("TV_UPDATER_DIR", "")
TV_UPDATER_PY = os.getenv("TV_UPDATER_PY", "")
TV_UPDATER_LOG_FILE = os.getenv("TV_UPDATER_LOG_FILE", "/var/log/tv-updater.log")
TV_UPDATER_LOCAL_LOG_FILE = os.getenv("TV_UPDATER_LOCAL_LOG_FILE", os.path.join(TV_UPDATER_DIR, "tv_updater.log") if TV_UPDATER_DIR else "")
TV_UPDATER_STATE_FILE = os.getenv("TV_UPDATER_STATE_FILE", os.path.join(TV_UPDATER_DIR, "state.json") if TV_UPDATER_DIR else "")
TV_UPDATER_INCOMING_DIR = os.getenv("TV_UPDATER_INCOMING_DIR", os.path.join(TV_UPDATER_DIR, "incoming_apks") if TV_UPDATER_DIR else "")

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


def get_host_timezone() -> str:
    """Returns the configured host IANA timezone name or local tzname."""
    tz = (os.getenv("TZ") or os.getenv("TIMEZONE") or "").strip()
    if tz:
        return tz
    tz_file = Path("/etc/timezone")
    if tz_file.exists():
        try:
            val = tz_file.read_text(encoding="utf-8").strip()
            if val:
                return val
        except OSError:
            pass
    localtime = Path("/etc/localtime")
    if localtime.is_symlink():
        try:
            target = os.readlink(str(localtime))
            if "zoneinfo/" in target:
                return target.split("zoneinfo/", 1)[1]
        except OSError:
            pass
    return datetime.datetime.now().astimezone().tzname() or "UTC"


def get_tz_abbr() -> str:
    """Returns the short local timezone label (e.g., UTC, CET, IST)."""
    tz_env = (os.getenv("TZ") or "").strip()
    if tz_env and "/" not in tz_env and len(tz_env) <= 6:
        return tz_env
    try:
        abbr = datetime.datetime.now().astimezone().tzname()
        if abbr:
            return abbr
    except Exception:
        pass
    return get_host_timezone()


# Services Catalog for Service Matrix
SERVICES_CATALOG = {
    "jellyfin": {"name": "Jellyfin", "port": 8096, "desc": "Media Streaming Server", "icon": "film", "category": "media", "has_web_ui": True},
    "seerr": {"name": "Seerr", "port": 5055, "desc": "Media Discovery & Requests", "icon": "search", "category": "media", "has_web_ui": True},
    "immich_server": {"name": "Immich", "port": 2283, "desc": "Photo & Video Cloud", "icon": "image", "category": "media", "optional": True, "has_web_ui": True},
    "sonarr": {"name": "Sonarr", "port": 8989, "desc": "TV Series Automation", "icon": "tv", "category": "ingest", "has_web_ui": True},
    "radarr": {"name": "Radarr", "port": 7878, "desc": "Movie Automation", "icon": "video", "category": "ingest", "has_web_ui": True},
    "prowlarr": {"name": "Prowlarr", "port": 9696, "desc": "Indexer Proxy & Scrapers", "icon": "rss", "category": "ingest", "has_web_ui": True},
    "bazarr": {"name": "Bazarr", "port": 6767, "desc": "Subtitles Manager", "icon": "file-text", "category": "ingest", "has_web_ui": True},
    "qbittorrent": {"name": "qBittorrent", "port": 8080, "desc": "BitTorrent Downloader", "icon": "download", "category": "system", "has_web_ui": True},
    "dozzle": {"name": "Dozzle", "port": 8888, "desc": "Live Docker Log Streamer", "icon": "terminal", "category": "system", "optional": True, "has_web_ui": True},
    "byparr": {"name": "Byparr", "port": 8191, "desc": "Cloudflare Challenge Solver", "icon": "shield", "category": "system", "optional": True, "has_web_ui": False},
    "immich_postgres": {"name": "Photo Database", "port": None, "desc": "PostgreSQL + Vector Engine", "icon": "database", "category": "system", "optional": True, "has_web_ui": False},
    "immich_redis": {"name": "Photo Cache", "port": None, "desc": "Valkey / Redis Cache", "icon": "database", "category": "system", "optional": True, "has_web_ui": False},
    "immich_machine_learning": {"name": "Photo ML Engine", "port": None, "desc": "Scheduled Face & CLIP AI", "icon": "cpu", "category": "system", "optional": True, "has_web_ui": False, "scheduled": True},
}

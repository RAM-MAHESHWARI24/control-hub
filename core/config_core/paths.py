"""
Canonical host paths for a Homelab Blueprint installation.

Code lives in the git checkout (replaceable); everything the installer
generates lives outside it so a re-clone, `git clean` or teardown of the
checkout never destroys configuration or state.

    /etc/homelab/            rendered .env files, config.json, API token (root-owned, 0600/0640)
    /var/lib/homelab/        install manifest, module state, caches
    /srv/homelab/appdata/    container config directories and databases

Every path can be overridden with an environment variable so tests, dry
runs and non-root development on Windows or macOS work without touching
the real filesystem.
"""

import os
from pathlib import Path

ETC_DIR = Path(os.getenv("HOMELAB_ETC_DIR", "/etc/homelab"))
STATE_DIR = Path(os.getenv("HOMELAB_STATE_DIR", "/var/lib/homelab"))
APPDATA_DIR = Path(os.getenv("HOMELAB_APPDATA_DIR", "/srv/homelab/appdata"))

CONFIG_FILE = ETC_DIR / "config.json"
MANIFEST_FILE = STATE_DIR / "installed.json"
CONTROL_HUB_TOKEN_FILE = ETC_DIR / "control-hub.token"

# Unprivileged system account that runs the Control Hub daemon and module cron jobs.
SERVICE_USER = os.getenv("HOMELAB_SERVICE_USER", "homelab")


def module_env_file(module_id: str) -> Path:
    """Path of the rendered environment file for a module (e.g. mediaserver.env)."""
    return ETC_DIR / f"{module_id}.env"


def module_appdata_dir(module_id: str) -> Path:
    """Default appdata (CONFIG_DIR) location for a module's containers."""
    return APPDATA_DIR / module_id


def is_linux_host() -> bool:
    """True when running on a Linux host where system paths and tools exist."""
    return os.name != "nt" and Path("/etc").is_dir()

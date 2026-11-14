"""
Bearer-token authentication shared by the Setup Wizard and the Control Hub.

Both daemons expose privileged operations (deploying stacks, applying
Netplan, restarting containers, suspending the host) on the LAN. A single
random token is the security boundary:

* The wizard generates a token per run and prints a URL carrying it.
* The Control Hub reads a persistent token from CONTROL_HUB_TOKEN or from
  /etc/homelab/control-hub.token, created by the installer.

Clients send it as `Authorization: Bearer <token>` or `X-Homelab-Token`.
Comparison is constant-time.
"""

import hmac
import os
import secrets
import stat
from pathlib import Path
from typing import Optional

from .paths import CONTROL_HUB_TOKEN_FILE

TOKEN_ENV_VAR = "CONTROL_HUB_TOKEN"
HEADER_NAME = "X-Homelab-Token"


def generate_token(nbytes: int = 32) -> str:
    """Returns a URL-safe random token (43 characters for 32 bytes)."""
    return secrets.token_urlsafe(nbytes)


def write_token_file(token: str, path: Path = CONTROL_HUB_TOKEN_FILE, group: Optional[str] = None) -> Path:
    """
    Writes the token with restrictive permissions. When `group` is given the
    file is root:<group> 0640 so the unprivileged daemon can read it; otherwise 0600.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(token.strip() + "\n")
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    tmp.replace(path)

    if group and hasattr(os, "chown"):
        try:
            import grp  # POSIX only

            gid = grp.getgrnam(group).gr_gid
            os.chown(path, 0, gid)
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
        except (KeyError, PermissionError, ImportError):
            pass
    return path


def read_token_file(path: Path = CONTROL_HUB_TOKEN_FILE) -> Optional[str]:
    """Returns the stored token, or None when the file is missing or empty."""
    try:
        value = path.read_text(encoding="utf-8").strip()
        return value or None
    except (FileNotFoundError, PermissionError, OSError):
        return None


def load_control_hub_token() -> Optional[str]:
    """Environment variable wins over the token file."""
    env_value = os.getenv(TOKEN_ENV_VAR, "").strip()
    if env_value:
        return env_value
    return read_token_file()


def extract_token(headers) -> Optional[str]:
    """
    Pulls a token from request headers. Accepts `Authorization: Bearer x`
    and `X-Homelab-Token: x`. `headers` is any mapping with .get().
    """
    auth = headers.get("Authorization") or headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        candidate = auth[7:].strip()
        if candidate:
            return candidate
    custom = headers.get(HEADER_NAME) or headers.get(HEADER_NAME.lower()) or ""
    return custom.strip() or None


def token_matches(presented: Optional[str], expected: Optional[str]) -> bool:
    """Constant-time comparison. Always False when either side is missing."""
    if not presented or not expected:
        return False
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))

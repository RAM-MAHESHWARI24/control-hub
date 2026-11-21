"""
Password login for the Control Hub dashboard.

People sign in with one password (by default the master password chosen in
the Setup Wizard). A browser that signs in gets a long-lived HttpOnly cookie,
so each device asks once. The bearer token stays for scripts and CI.

The password is stored only as a salted PBKDF2-SHA256 hash in
/var/lib/homelab/control-hub/password, owned by the service user so the
dashboard can change it. The session cookie is an HMAC of that hash keyed
with the Control Hub token: changing the password, or rotating the token,
signs every browser out.
"""

import base64
import hashlib
import hmac
import os
import secrets
import stat
from pathlib import Path
from typing import Optional

from .paths import STATE_DIR

PASSWORD_FILE = Path(os.getenv("CONTROL_HUB_PASSWORD_FILE", str(STATE_DIR / "control-hub" / "password")))
MIN_PASSWORD_LENGTH = 8
_ITERATIONS = 310_000
_SCHEME = "pbkdf2_sha256"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, iterations: int = _ITERATIONS) -> str:
    """Returns 'pbkdf2_sha256$<iterations>$<salt>$<digest>'."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_SCHEME}${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: Optional[str]) -> bool:
    """Constant-time check of `password` against a stored hash."""
    if not password or not stored:
        return False
    try:
        scheme, iterations, salt, digest = stored.strip().split("$")
        if scheme != _SCHEME:
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _unb64(salt), int(iterations))
        return hmac.compare_digest(candidate, _unb64(digest))
    except (ValueError, TypeError):
        return False


def read_password_hash(path: Optional[Path] = None) -> Optional[str]:
    """Returns the stored hash, or None when no password is set."""
    try:
        value = (path or PASSWORD_FILE).read_text(encoding="utf-8").strip()
        return value or None
    except OSError:
        return None


def write_password_hash(stored: str, path: Optional[Path] = None, owner: Optional[str] = None) -> Path:
    """Writes the hash 0600 (directory 0700). `owner` chowns both to that user when run as root."""
    target = path or PASSWORD_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(stored.strip() + "\n")
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    if owner and hasattr(os, "chown"):
        try:
            import pwd  # POSIX only

            entry = pwd.getpwnam(owner)
            for p in (target.parent, tmp):
                os.chown(p, entry.pw_uid, entry.pw_gid)
            os.chmod(target.parent, stat.S_IRWXU)
        except (KeyError, PermissionError, ImportError):
            pass
    tmp.replace(target)
    return target


def set_password(password: str, path: Optional[Path] = None, owner: Optional[str] = None) -> Path:
    """Validates and stores a new password."""
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise ValueError(f"the password must have at least {MIN_PASSWORD_LENGTH} characters")
    return write_password_hash(hash_password(password), path, owner)


def session_value(token: str, stored_hash: str) -> str:
    """Cookie value for a signed-in browser; changes when the password or token changes."""
    return hmac.new(token.encode("utf-8"), ("hub-session-v1:" + stored_hash).encode("utf-8"), hashlib.sha256).hexdigest()

"""
Server-side session store, parsed device metadata, TOTP state, and read-only Family access settings.

All persistent auth state lives beside auth_password.PASSWORD_FILE (by default
/var/lib/homelab/control-hub/), written atomically with mode 0600 so isolated
unit tests that patch auth_password.PASSWORD_FILE automatically isolate
sessions.json and access.json too.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import stat
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.config_core import auth_password
from core.totp import (
    consume_recovery_code,
    format_secret_groups,
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_code,
    totp_uri,
    verify_totp_code,
)

SESSION_MAX_AGE = 400 * 24 * 3600
_MAX_STORED_SESSIONS = 50
_LAST_SEEN_TOUCH_INTERVAL = 60

_sessions_lock = threading.Lock()
_access_lock = threading.Lock()


def _auth_dir() -> Path:
    return Path(auth_password.PASSWORD_FILE).parent


def sessions_file() -> Path:
    return _auth_dir() / "sessions.json"


def access_file() -> Path:
    return _auth_dir() / "access.json"


def _atomic_write_json(target: Path, payload: Dict[str, Any]) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    os.replace(tmp, target)
    return target


def _read_json(target: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not target.exists():
        return json.loads(json.dumps(default))
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else json.loads(json.dumps(default))
    except (OSError, ValueError):
        return json.loads(json.dumps(default))


def parse_user_agent(user_agent: str) -> str:
    """Derives a clean 'Browser on OS' label from a User-Agent string."""
    ua = (user_agent or "").strip()
    if not ua:
        return "Browser session"

    low = ua.lower()
    if "iphone" in low:
        os_name = "iPhone"
    elif "ipad" in low:
        os_name = "iPad"
    elif "android" in low:
        os_name = "Android"
    elif "windows" in low:
        os_name = "Windows"
    elif "macintosh" in low or "mac os x" in low:
        os_name = "macOS"
    elif "cros" in low:
        os_name = "ChromeOS"
    elif "linux" in low:
        os_name = "Linux"
    else:
        os_name = ""

    if "edg/" in low:
        browser = "Edge"
    elif "opr/" in low or "opera" in low:
        browser = "Opera"
    elif "firefox/" in low:
        browser = "Firefox"
    elif "chrome/" in low or "chromium" in low or "crios/" in low:
        browser = "Chrome"
    elif "safari/" in low and "chrome" not in low:
        browser = "Safari"
    elif "curl/" in low:
        return "curl CLI"
    elif "python" in low:
        return "Python client"
    elif "playwright" in low or "headless" in low:
        browser = "Browser"
    else:
        browser = "Browser"

    return f"{browser} on {os_name}" if os_name else browser


_LOCAL_LAN_V4 = (
    ipaddress.IPv4Network("127.0.0.0/8"),
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("169.254.0.0/16"),
)
_LOCAL_LAN_V6 = (
    ipaddress.IPv6Network("::1/128"),
    ipaddress.IPv6Network("fc00::/7"),
    ipaddress.IPv6Network("fe80::/10"),
)


def is_local_lan_ip(addr: str) -> bool:
    """True strictly for loopback, RFC1918, link-local, or IPv6 ULA; False for Tailscale (100.64/10) & WAN."""
    raw = (addr or "").split("%")[0].strip()
    if not raw:
        return False
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if isinstance(ip, ipaddress.IPv4Address):
        return any(ip in net for net in _LOCAL_LAN_V4)
    return any(ip in net for net in _LOCAL_LAN_V6)


def _session_signature(token: str, sid: str, role: str) -> str:
    msg = f"hub-sid-v2:{sid}:{role}".encode("utf-8")
    return hmac.new(token.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _prune_sessions(sessions: Dict[str, Any], now: float) -> Dict[str, Any]:
    active = {
        sid: rec
        for sid, rec in sessions.items()
        if isinstance(rec, dict) and (now - float(rec.get("last_seen", 0))) <= SESSION_MAX_AGE
    }
    if len(active) <= _MAX_STORED_SESSIONS:
        return active
    ordered = sorted(active.items(), key=lambda kv: float(kv[1].get("last_seen", 0)), reverse=True)
    return dict(ordered[:_MAX_STORED_SESSIONS])


def create_session(token: str, role: str, user_agent: str, ip: str) -> Tuple[str, str]:
    """Creates and persists a per-device session, returning (session_id, cookie_value)."""
    sid = secrets.token_hex(12)
    now = time.time()
    clean_role = "family" if role == "family" else "owner"
    record = {
        "id": sid,
        "role": clean_role,
        "device": parse_user_agent(user_agent),
        "user_agent": (user_agent or "")[:240],
        "ip": (ip or "?")[:64],
        "created_at": now,
        "last_seen": now,
    }
    with _sessions_lock:
        path = sessions_file()
        data = _read_json(path, {"sessions": {}})
        sessions = data.get("sessions") if isinstance(data.get("sessions"), dict) else {}
        sessions[sid] = record
        data["sessions"] = _prune_sessions(sessions, now)
        _atomic_write_json(path, data)
    return sid, f"{sid}.{_session_signature(token, sid, clean_role)}"


def verify_session_cookie(token: str, cookie: str) -> Optional[Dict[str, Any]]:
    """Validates signed cookie format and active server-side session entry."""
    raw = (cookie or "").strip()
    if "." not in raw:
        return None
    sid, sig = raw.split(".", 1)
    if not sid or not sig:
        return None
    with _sessions_lock:
        data = _read_json(sessions_file(), {"sessions": {}})
        sessions = data.get("sessions") if isinstance(data.get("sessions"), dict) else {}
        rec = sessions.get(sid)
        if not isinstance(rec, dict):
            return None
        role = "family" if rec.get("role") == "family" else "owner"
        expected = _session_signature(token, sid, role)
        if not hmac.compare_digest(sig, expected):
            return None
        now = time.time()
        if (now - float(rec.get("last_seen", 0))) > SESSION_MAX_AGE:
            return None
        return dict(rec)


def touch_session(sid: str, ip: str = "", user_agent: str = "") -> None:
    """Updates last_seen (throttled to reduce flash writes during 2.5s polling)."""
    if not sid:
        return
    now = time.time()
    with _sessions_lock:
        path = sessions_file()
        data = _read_json(path, {"sessions": {}})
        sessions = data.get("sessions") if isinstance(data.get("sessions"), dict) else {}
        rec = sessions.get(sid)
        if not isinstance(rec, dict):
            return
        last_seen = float(rec.get("last_seen", 0))
        if (now - last_seen) < _LAST_SEEN_TOUCH_INTERVAL:
            return
        rec["last_seen"] = now
        if ip:
            rec["ip"] = ip[:64]
        if user_agent:
            rec["user_agent"] = user_agent[:240]
            rec["device"] = parse_user_agent(user_agent)
        sessions[sid] = rec
        data["sessions"] = sessions
        _atomic_write_json(path, data)


def list_sessions(current_sid: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists active device sessions sorted newest activity first."""
    now = time.time()
    with _sessions_lock:
        data = _read_json(sessions_file(), {"sessions": {}})
        sessions = data.get("sessions") if isinstance(data.get("sessions"), dict) else {}
        items: List[Dict[str, Any]] = []
        for sid, rec in sessions.items():
            if not isinstance(rec, dict):
                continue
            if (now - float(rec.get("last_seen", 0))) > SESSION_MAX_AGE:
                continue
            items.append(
                {
                    "id": sid,
                    "role": "family" if rec.get("role") == "family" else "owner",
                    "device": str(rec.get("device") or "Browser session"),
                    "ip": str(rec.get("ip") or "?"),
                    "created_at": float(rec.get("created_at", 0)),
                    "last_seen": float(rec.get("last_seen", 0)),
                    "is_current": bool(current_sid and sid == current_sid),
                }
            )
    items.sort(key=lambda r: (1 if r["is_current"] else 0, r["last_seen"]), reverse=True)
    return items


def revoke_session(sid: str) -> bool:
    """Revokes a single session by ID. Returns True if it existed."""
    if not sid:
        return False
    with _sessions_lock:
        path = sessions_file()
        data = _read_json(path, {"sessions": {}})
        sessions = data.get("sessions") if isinstance(data.get("sessions"), dict) else {}
        if sid not in sessions:
            return False
        sessions.pop(sid, None)
        data["sessions"] = sessions
        _atomic_write_json(path, data)
        return True


def revoke_other_sessions(keep_sid: Optional[str] = None, role: Optional[str] = None) -> int:
    """Revokes sessions (optionally filtered by role), preserving `keep_sid` if provided."""
    with _sessions_lock:
        path = sessions_file()
        data = _read_json(path, {"sessions": {}})
        sessions = data.get("sessions") if isinstance(data.get("sessions"), dict) else {}
        kept: Dict[str, Any] = {}
        removed = 0
        for sid, rec in sessions.items():
            rec_role = rec.get("role", "owner") if isinstance(rec, dict) else "owner"
            if keep_sid and sid == keep_sid:
                kept[sid] = rec
            elif role is not None and rec_role != role:
                kept[sid] = rec
            else:
                removed += 1
        if removed:
            data["sessions"] = kept
            _atomic_write_json(path, data)
        return removed


# ---------------------------------------------------------------------------
# Family View & Owner TOTP Access Settings
# ---------------------------------------------------------------------------

_DEFAULT_ACCESS: Dict[str, Any] = {
    "family": {
        "enabled": False,
        "lan_open": False,
        "password_hash": None,
    },
    "totp": {
        "enabled": False,
        "secret": None,
        "recovery_hashes": [],
    },
    "pending_totp": None,
}


def read_access_config() -> Dict[str, Any]:
    with _access_lock:
        data = _read_json(access_file(), _DEFAULT_ACCESS)
        for section, defaults in _DEFAULT_ACCESS.items():
            if section == "pending_totp":
                continue
            if not isinstance(data.get(section), dict):
                data[section] = dict(defaults)
            else:
                for k, v in defaults.items():
                    data[section].setdefault(k, v)
        return data


def _save_access_config(data: Dict[str, Any]) -> None:
    _atomic_write_json(access_file(), data)


def get_family_status() -> Dict[str, Any]:
    cfg = read_access_config()["family"]
    return {
        "enabled": bool(cfg.get("enabled")),
        "lan_open": bool(cfg.get("lan_open")),
        "password_set": bool(cfg.get("password_hash")),
    }


def set_family_config(
    enabled: bool,
    lan_open: bool,
    password: Optional[str] = None,
) -> Dict[str, Any]:
    """Updates read-only Family view settings. Raises ValueError on invalid input."""
    with _access_lock:
        cfg = _read_json(access_file(), _DEFAULT_ACCESS)
        fam = dict(cfg.get("family") or _DEFAULT_ACCESS["family"])
        pw_changed = False
        if password is not None and password != "":
            if len(password) < auth_password.MIN_PASSWORD_LENGTH:
                raise ValueError(f"Family password must have at least {auth_password.MIN_PASSWORD_LENGTH} characters.")
            fam["password_hash"] = auth_password.hash_password(password)
            pw_changed = True
        if bool(enabled) and not bool(lan_open) and not fam.get("password_hash"):
            raise ValueError("Set a family password (at least 8 characters) or allow passwordless LAN access.")
        fam["enabled"] = bool(enabled)
        fam["lan_open"] = bool(lan_open)
        cfg["family"] = fam
        _save_access_config(cfg)

    if not enabled or pw_changed:
        revoke_other_sessions(keep_sid=None, role="family")
    return get_family_status()


def verify_family_login(password: str) -> bool:
    """Verifies candidate against enabled Family view password."""
    cfg = read_access_config()["family"]
    if not cfg.get("enabled"):
        return False
    stored = cfg.get("password_hash")
    return bool(stored and auth_password.verify_password(password, stored))


def get_totp_status() -> Dict[str, Any]:
    cfg = read_access_config()["totp"]
    return {
        "enabled": bool(cfg.get("enabled") and cfg.get("secret")),
        "recovery_remaining": len(cfg.get("recovery_hashes") or []),
    }


def start_totp_setup(issuer: str = "Homelab Control Hub", account: str = "owner") -> Dict[str, str]:
    """Creates a pending TOTP secret until the user confirms one valid 6-digit code."""
    secret = generate_totp_secret()
    with _access_lock:
        cfg = _read_json(access_file(), _DEFAULT_ACCESS)
        cfg["pending_totp"] = secret
        _save_access_config(cfg)
    return {
        "secret": secret,
        "formatted_secret": format_secret_groups(secret),
        "uri": totp_uri(secret, issuer=issuer, account=account),
    }


def enable_totp(code: str) -> Tuple[bool, Any]:
    """Activates pending TOTP if code matches, returning (True, recovery_codes) or (False, error)."""
    with _access_lock:
        cfg = _read_json(access_file(), _DEFAULT_ACCESS)
        secret = cfg.get("pending_totp") or (cfg.get("totp") or {}).get("secret")
        if not secret:
            return False, "Generate a 2FA setup key first."
        if not verify_totp_code(str(secret), code):
            return False, "That 6-digit code did not match. Check your device clock and try again."
        recovery_codes = generate_recovery_codes()
        cfg["totp"] = {
            "enabled": True,
            "secret": str(secret),
            "recovery_hashes": [hash_recovery_code(c) for c in recovery_codes],
        }
        cfg["pending_totp"] = None
        _save_access_config(cfg)
        return True, recovery_codes


def verify_owner_second_factor(code: str) -> bool:
    """Verifies a TOTP code or consumes a one-time recovery code if owner 2FA is enabled."""
    with _access_lock:
        cfg = _read_json(access_file(), _DEFAULT_ACCESS)
        totp = cfg.get("totp") or {}
        if not (totp.get("enabled") and totp.get("secret")):
            return True
        if verify_totp_code(str(totp["secret"]), code):
            return True
        ok, remaining = consume_recovery_code(code, totp.get("recovery_hashes") or [])
        if ok:
            totp["recovery_hashes"] = remaining
            cfg["totp"] = totp
            _save_access_config(cfg)
            return True
        return False


def disable_totp() -> None:
    """Disables owner TOTP and clears stored secret/recovery codes."""
    with _access_lock:
        cfg = _read_json(access_file(), _DEFAULT_ACCESS)
        cfg["totp"] = {"enabled": False, "secret": None, "recovery_hashes": []}
        cfg["pending_totp"] = None
        _save_access_config(cfg)

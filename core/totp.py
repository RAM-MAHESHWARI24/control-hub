"""
RFC 6238 TOTP & recovery-code helpers for optional owner two-factor authentication.
Pure Python standard library only.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse
from typing import Iterable, List, Optional, Tuple

_TOTP_STEP_SECONDS = 30
_TOTP_DIGITS = 6
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_totp_secret(num_bytes: int = 20) -> str:
    """Returns a random unpadded uppercase base32 secret (160-bit default)."""
    raw = secrets.token_bytes(num_bytes)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def format_secret_groups(secret: str, group_size: int = 4) -> str:
    """Formats a base32 secret into readable chunks for manual entry."""
    clean = "".join(ch for ch in (secret or "").upper() if ch.isalnum())
    return " ".join(clean[i : i + group_size] for i in range(0, len(clean), group_size))


def _decode_base32(secret: str) -> Optional[bytes]:
    clean = "".join(ch for ch in (secret or "").upper() if ch.isalnum())
    if not clean:
        return None
    pad = "=" * (-len(clean) % 8)
    try:
        return base64.b32decode(clean + pad, casefold=True)
    except (ValueError, TypeError):
        return None


def totp_code(
    secret: str,
    counter: Optional[int] = None,
    for_time: Optional[float] = None,
    step: int = _TOTP_STEP_SECONDS,
    digits: int = _TOTP_DIGITS,
) -> str:
    """Computes a 6-digit RFC 6238 TOTP code for the given counter or UNIX time."""
    key = _decode_base32(secret)
    if not key:
        raise ValueError("Invalid base32 TOTP secret")
    if counter is None:
        ts = time.time() if for_time is None else float(for_time)
        counter = int(ts // step)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** digits)).zfill(digits)


def verify_totp_code(
    secret: str,
    candidate: str,
    window: int = 1,
    for_time: Optional[float] = None,
) -> bool:
    """Verifies a 6-digit TOTP code allowing +-window 30s intervals."""
    normalized = "".join(ch for ch in str(candidate or "") if ch.isdigit())
    if len(normalized) != _TOTP_DIGITS:
        return False
    if _decode_base32(secret) is None:
        return False
    ts = time.time() if for_time is None else float(for_time)
    base_counter = int(ts // _TOTP_STEP_SECONDS)
    for delta in range(-window, window + 1):
        expected = totp_code(secret, counter=max(0, base_counter + delta))
        if hmac.compare_digest(normalized, expected):
            return True
    return False


def totp_uri(secret: str, issuer: str = "Homelab Control Hub", account: str = "owner") -> str:
    """Builds a standard otpauth:// URI compatible with authenticator apps."""
    label = urllib.parse.quote(f"{issuer}:{account}")
    params = urllib.parse.urlencode(
        {
            "secret": "".join(ch for ch in secret.upper() if ch.isalnum()),
            "issuer": issuer,
            "digits": str(_TOTP_DIGITS),
            "period": str(_TOTP_STEP_SECONDS),
        }
    )
    return f"otpauth://totp/{label}?{params}"


def generate_recovery_codes(count: int = 6) -> List[str]:
    """Generates one-time XXXX-XXXX recovery codes without ambiguous characters."""
    codes: List[str] = []
    for _ in range(count):
        left = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(4))
        right = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(4))
        codes.append(f"{left}-{right}")
    return codes


def hash_recovery_code(code: str) -> str:
    """Returns SHA-256 digest of a normalized uppercase recovery code."""
    clean = "".join(ch for ch in str(code or "").upper() if ch.isalnum())
    return hashlib.sha256(("hub-recovery-v1:" + clean).encode("utf-8")).hexdigest()


def consume_recovery_code(candidate: str, stored_hashes: Iterable[str]) -> Tuple[bool, List[str]]:
    """Checks candidate against stored recovery hashes and removes it if matched."""
    clean = "".join(ch for ch in str(candidate or "").upper() if ch.isalnum())
    hashes = list(stored_hashes or [])
    if len(clean) < 8 or not hashes:
        return False, hashes
    cand_hash = hash_recovery_code(clean)
    matched = False
    remaining: List[str] = []
    for item in hashes:
        if not matched and hmac.compare_digest(cand_hash, str(item)):
            matched = True
            continue
        remaining.append(str(item))
    return matched, remaining

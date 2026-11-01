"""
Secrets and Credentials Generator
Generates high-entropy cryptographic passwords and API keys.
"""

import secrets
import string


def generate_password(length: int = 24, alphanumeric_only: bool = True) -> str:
    """
    Generate a cryptographically secure random password.
    Defaults to alphanumeric characters [A-Za-z0-9] to prevent issues
    with PostgreSQL connection strings, Docker env parsing, and shell interpolation.
    """
    if alphanumeric_only:
        alphabet = string.ascii_letters + string.digits
    else:
        # Avoid problematic shell characters like $, ", `, \, \n
        safe_symbols = "!@#%^&*()-_=+"
        alphabet = string.ascii_letters + string.digits + safe_symbols

    # Ensure at least one uppercase, lowercase, and digit
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        has_upper = any(c.isupper() for c in pwd)
        has_lower = any(c.islower() for c in pwd)
        has_digit = any(c.isdigit() for c in pwd)
        if has_upper and has_lower and has_digit:
            return pwd


def generate_api_key(length: int = 32) -> str:
    """Generate a hex API key formatted like Radarr / Sonarr / Prowlarr native keys"""
    return secrets.token_hex(length // 2)


def generate_all_secrets() -> dict:
    """Generate a complete set of strong defaults for all monorepo services"""
    return {
        "qbittorrent_user": "admin",
        "qbittorrent_pass": generate_password(18, alphanumeric_only=True),
        "postgres_password": generate_password(24, alphanumeric_only=True),
        "radarr_api_key": generate_api_key(32),
        "sonarr_api_key": generate_api_key(32),
        "prowlarr_api_key": generate_api_key(32),
    }

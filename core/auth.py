"""
Bearer-token guard for the Control Hub API.

Every /api/* route except the public health/liveness/readiness probes and the
OpenAPI documents requires `Authorization: Bearer <token>` (or the
X-Homelab-Token header). The token comes from CONTROL_HUB_TOKEN or
/etc/homelab/control-hub.token (written by the installer). When neither is
present, a random token is generated for this process and printed at startup
so a standalone `python server.py` is never left wide open.
"""

from typing import Tuple

from flask import Flask, jsonify, request

from core.config_core.auth_token import (
    extract_token,
    generate_token,
    load_control_hub_token,
    token_matches,
)

PUBLIC_API_PATHS = {
    "/api/health",
    "/api/livez",
    "/api/readyz",
    "/api/openapi.yaml",
    "/api/docs",
}


def install_auth(app: Flask) -> Tuple[str, bool]:
    """Registers the guard. Returns (token, was_generated)."""
    token = load_control_hub_token()
    generated = False
    if not token:
        token = generate_token()
        generated = True
    app.config["CONTROL_HUB_TOKEN"] = token

    @app.before_request
    def _require_token():
        path = request.path
        if not path.startswith("/api/") or path in PUBLIC_API_PATHS:
            return None
        if token_matches(extract_token(request.headers), app.config["CONTROL_HUB_TOKEN"]):
            return None
        return jsonify({"status": "error", "error": "unauthorized", "hint": "Send Authorization: Bearer <token>. Run './setup.sh token' on the server to see it."}), 401

    @app.route("/api/auth/check")
    def _auth_check():
        # Reaching this handler means the before_request guard accepted the token.
        return jsonify({"status": "ok", "authenticated": True})

    return token, generated

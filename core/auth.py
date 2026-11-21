"""
Access guard for the Control Hub API.

Every /api/* route except the public probes, the OpenAPI documents and the
login endpoint needs one of:

* the session cookie a browser gets by signing in with the dashboard password
  (POST /api/auth/login), so each device signs in once; or
* `Authorization: Bearer <token>` (or X-Homelab-Token), for scripts and CI.

The token comes from CONTROL_HUB_TOKEN or /etc/homelab/control-hub.token
(written by the installer). When neither is present, a random token is
generated for this process and printed at startup, so a standalone
`python server.py` is never left wide open. The password hash lives in
/var/lib/homelab/control-hub/password (see core.config_core.auth_password).
"""

import threading
import time
from collections import defaultdict, deque
from typing import Tuple

from flask import Flask, jsonify, request

from core.config_core.auth_password import (
    MIN_PASSWORD_LENGTH,
    read_password_hash,
    session_value,
    set_password,
    verify_password,
)
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
    "/api/auth/login",
    "/api/auth/status",
}

SESSION_COOKIE = "hub_session"
SESSION_MAX_AGE = 400 * 24 * 3600  # browsers cap cookie lifetime at about 400 days
LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_FAILURES = 10

_failures = defaultdict(deque)
_failures_lock = threading.Lock()


def _too_many_failures(ip: str) -> bool:
    now = time.monotonic()
    with _failures_lock:
        q = _failures[ip]
        while q and now - q[0] > LOGIN_WINDOW_SECONDS:
            q.popleft()
        return len(q) >= LOGIN_MAX_FAILURES


def failure_counts() -> dict:
    """Failed sign-ins per address within the lockout window (read by alerts)."""
    now = time.monotonic()
    with _failures_lock:
        return {ip: sum(1 for t in q if now - t <= LOGIN_WINDOW_SECONDS) for ip, q in _failures.items() if q}


def _record_failure(ip: str) -> None:
    with _failures_lock:
        _failures[ip].append(time.monotonic())


def _set_session(response, token: str, stored_hash: str):
    response.set_cookie(
        SESSION_COOKIE,
        session_value(token, stored_hash),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="Strict",
        secure=request.is_secure,
        path="/",
    )
    return response


def install_auth(app: Flask) -> Tuple[str, bool]:
    """Registers the guard and the /api/auth/* routes. Returns (token, was_generated)."""
    token = load_control_hub_token()
    generated = False
    if not token:
        token = generate_token()
        generated = True
    app.config["CONTROL_HUB_TOKEN"] = token

    def has_valid_session() -> bool:
        stored = read_password_hash()
        cookie = request.cookies.get(SESSION_COOKIE, "")
        if not stored or not cookie:
            return False
        return token_matches(cookie, session_value(app.config["CONTROL_HUB_TOKEN"], stored))

    def is_authenticated() -> bool:
        return token_matches(extract_token(request.headers), app.config["CONTROL_HUB_TOKEN"]) or has_valid_session()

    @app.before_request
    def _require_auth():
        path = request.path
        if not path.startswith("/api/") or path in PUBLIC_API_PATHS:
            return None
        if is_authenticated():
            return None
        return jsonify({"status": "error", "error": "unauthorized", "hint": "Sign in with the dashboard password, or send Authorization: Bearer <token>."}), 401

    @app.route("/api/auth/check")
    def _auth_check():
        # Reaching this handler means the guard accepted the request.
        return jsonify({"status": "ok", "authenticated": True})

    @app.route("/api/auth/status")
    def _auth_status():
        return jsonify({"authenticated": is_authenticated(), "password_set": bool(read_password_hash())})

    @app.route("/api/auth/login", methods=["POST"])
    def _auth_login():
        ip = request.remote_addr or "?"
        if _too_many_failures(ip):
            return jsonify({"status": "error", "error": "Too many wrong attempts. Wait a few minutes and try again."}), 429
        data = request.get_json(silent=True) or {}
        secret = str(data.get("password") or "")
        stored = read_password_hash()
        if not stored:
            return jsonify({"status": "error", "error": "No dashboard password is set. On the server run: sudo ./setup.sh password"}), 409
        # The access token is accepted here too, so an old bookmark or note still works.
        if verify_password(secret, stored) or token_matches(secret, app.config["CONTROL_HUB_TOKEN"]):
            return _set_session(jsonify({"status": "ok"}), app.config["CONTROL_HUB_TOKEN"], stored)
        _record_failure(ip)
        return jsonify({"status": "error", "error": "Wrong password."}), 401

    @app.route("/api/auth/logout", methods=["POST"])
    def _auth_logout():
        response = jsonify({"status": "ok"})
        response.delete_cookie(SESSION_COOKIE, path="/", samesite="Strict")
        return response

    @app.route("/api/auth/password", methods=["POST"])
    def _auth_change_password():
        data = request.get_json(silent=True) or {}
        current, new = str(data.get("current") or ""), str(data.get("new") or "")
        stored = read_password_hash()
        if stored and not verify_password(current, stored):
            _record_failure(request.remote_addr or "?")
            return jsonify({"status": "error", "error": "The current password is wrong."}), 403
        if len(new) < MIN_PASSWORD_LENGTH:
            return jsonify({"status": "error", "error": f"Use at least {MIN_PASSWORD_LENGTH} characters."}), 400
        try:
            set_password(new)
        except OSError as exc:
            return jsonify({"status": "error", "error": f"Could not save the password: {exc}"}), 500
        # Other browsers are signed out (their cookie no longer matches); this one stays in.
        return _set_session(jsonify({"status": "ok", "message": "Password changed. Other devices must sign in again."}),
                            app.config["CONTROL_HUB_TOKEN"], read_password_hash() or "")

    return token, generated

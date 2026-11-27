"""
Access guard, per-device session store, read-only Family View RBAC, and optional owner TOTP.

Every /api/* route except the public probes, the OpenAPI documents and the
login/status endpoints requires one of:

* a per-device server-tracked `hub_session` cookie (role "owner" or "family"),
* automatic local-LAN read-only Family access when explicitly enabled by the owner, or
* `Authorization: Bearer <token>` (or X-Homelab-Token), for scripts and CI.
"""

from collections import defaultdict, deque
import socket
import threading
import time
from typing import Optional, Tuple

from flask import Flask, g, jsonify, request

from core.config_core.auth_password import (
    MIN_PASSWORD_LENGTH,
    read_password_hash,
    set_password,
    verify_password,
)
from core.config_core.auth_token import (
    extract_token,
    generate_token,
    load_control_hub_token,
    token_matches,
)
from core.sessions import (
    SESSION_MAX_AGE,
    create_session,
    disable_totp,
    enable_totp,
    get_family_status,
    get_totp_status,
    is_local_lan_ip,
    list_sessions,
    read_access_config,
    revoke_other_sessions,
    revoke_session,
    set_family_config,
    start_totp_setup,
    touch_session,
    verify_family_login,
    verify_owner_second_factor,
    verify_session_cookie,
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

FAMILY_ALLOWED_GET_PATHS = {
    "/api/health",
    "/api/livez",
    "/api/readyz",
    "/api/auth/check",
    "/api/auth/status",
    "/api/system/vitals",
    "/api/network/speed",
    "/api/downloads/active",
    "/api/storage/operations",
    "/api/services/status",
    "/api/media/overview",
    "/api/sleep/status",
}

FAMILY_ALLOWED_POST_PATHS = {
    "/api/auth/login",
    "/api/auth/logout",
}

SESSION_COOKIE = "hub_session"
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


def _is_https_request() -> bool:
    """Returns True when served directly over TLS or behind an HTTPS reverse proxy (e.g. Tailscale Serve)."""
    if request.is_secure:
        return True
    fwd_proto = request.headers.get("X-Forwarded-Proto", "")
    first = fwd_proto.split(",")[0].strip().lower()
    return first == "https"


def _set_session_cookie(response, cookie_val: str):
    response.set_cookie(
        SESSION_COOKIE,
        cookie_val,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="Strict",
        secure=_is_https_request(),
        path="/",
    )
    return response


def _require_owner():
    if getattr(g, "auth_role", "") != "owner":
        return jsonify({
            "status": "error",
            "error": "forbidden",
            "hint": "Owner sign-in is required to view or change account and server settings.",
        }), 403
    return None


def install_auth(app: Flask) -> Tuple[str, bool]:
    """Registers the guard, RBAC filter, and /api/auth/* routes. Returns (token, was_generated)."""
    token = load_control_hub_token()
    generated = False
    if not token:
        token = generate_token()
        generated = True
    app.config["CONTROL_HUB_TOKEN"] = token

    def resolve_auth() -> Tuple[bool, str, Optional[str], str]:
        if token_matches(extract_token(request.headers), app.config["CONTROL_HUB_TOKEN"]):
            return True, "owner", None, "token"

        stored = read_password_hash()
        cookie = request.cookies.get(SESSION_COOKIE, "")
        if stored and cookie:
            rec = verify_session_cookie(app.config["CONTROL_HUB_TOKEN"], cookie)
            if rec:
                role = "family" if rec.get("role") == "family" else "owner"
                if role == "family" and not get_family_status().get("enabled"):
                    return False, "", None, "none"
                touch_session(
                    rec["id"],
                    ip=request.remote_addr or "",
                    user_agent=request.headers.get("User-Agent", ""),
                )
                return True, role, rec["id"], "session"

        if stored:
            fam = read_access_config().get("family") or {}
            if fam.get("enabled") and fam.get("lan_open") and is_local_lan_ip(request.remote_addr or ""):
                return True, "family", None, "lan_family"

        return False, "", None, "none"

    @app.before_request
    def _require_auth():
        path = request.path
        if not path.startswith("/api/"):
            return None
        authed, role, sid, via = resolve_auth()
        g.authenticated = authed
        g.auth_role = role
        g.session_id = sid
        g.auth_via = via

        if path in PUBLIC_API_PATHS:
            return None
        if not authed:
            return jsonify({
                "status": "error",
                "error": "unauthorized",
                "hint": "Sign in with the dashboard password, or send Authorization: Bearer <token>.",
            }), 401
        if role == "family":
            if request.method == "GET" and path in FAMILY_ALLOWED_GET_PATHS:
                return None
            if request.method == "POST" and path in FAMILY_ALLOWED_POST_PATHS:
                return None
            return jsonify({
                "status": "error",
                "error": "forbidden",
                "hint": "Read-only family access cannot view settings or change server controls.",
            }), 403
        return None

    @app.route("/api/auth/check")
    def _auth_check():
        return jsonify({
            "status": "ok",
            "authenticated": True,
            "role": getattr(g, "auth_role", "owner"),
            "session_id": getattr(g, "session_id", None),
        })

    @app.route("/api/auth/status")
    def _auth_status():
        fam = get_family_status()
        totp = get_totp_status()
        authed = bool(getattr(g, "authenticated", False))
        return jsonify({
            "authenticated": authed,
            "password_set": bool(read_password_hash()),
            "role": getattr(g, "auth_role", "") if authed else None,
            "auth_via": getattr(g, "auth_via", "none") if authed else "none",
            "session_id": getattr(g, "session_id", None) if authed else None,
            "family_enabled": fam["enabled"],
            "family_lan_open": fam["lan_open"],
            "family_password_set": fam["password_set"],
            "totp_enabled": totp["enabled"],
        })

    @app.route("/api/auth/login", methods=["POST"])
    def _auth_login():
        ip = request.remote_addr or "?"
        if _too_many_failures(ip):
            return jsonify({"status": "error", "error": "Too many wrong attempts. Wait a few minutes and try again."}), 429
        data = request.get_json(silent=True) or {}
        secret = str(data.get("password") or "")
        code = str(data.get("code") or data.get("totp") or "").strip()
        mode = str(data.get("mode") or "auto").strip().lower()
        stored = read_password_hash()
        if not stored:
            return jsonify({"status": "error", "error": "No dashboard password is set. On the server run: sudo ./setup.sh password"}), 409

        is_token_login = token_matches(secret, app.config["CONTROL_HUB_TOKEN"])
        is_owner_pw = (mode != "family") and verify_password(secret, stored)

        if is_token_login or is_owner_pw:
            if is_owner_pw and not is_token_login and get_totp_status()["enabled"]:
                if not code:
                    return jsonify({
                        "status": "error",
                        "totp_required": True,
                        "error": "Enter your 6-digit authenticator or recovery code.",
                    }), 401
                if not verify_owner_second_factor(code):
                    _record_failure(ip)
                    return jsonify({
                        "status": "error",
                        "totp_required": True,
                        "error": "Invalid authenticator or recovery code.",
                    }), 401

            sid, cookie_val = create_session(
                app.config["CONTROL_HUB_TOKEN"],
                "owner",
                request.headers.get("User-Agent", ""),
                ip,
            )
            return _set_session_cookie(
                jsonify({"status": "ok", "role": "owner", "session_id": sid}),
                cookie_val,
            )

        if mode != "owner" and verify_family_login(secret):
            sid, cookie_val = create_session(
                app.config["CONTROL_HUB_TOKEN"],
                "family",
                request.headers.get("User-Agent", ""),
                ip,
            )
            return _set_session_cookie(
                jsonify({"status": "ok", "role": "family", "session_id": sid}),
                cookie_val,
            )

        _record_failure(ip)
        return jsonify({"status": "error", "error": "Wrong password."}), 401

    @app.route("/api/auth/logout", methods=["POST"])
    def _auth_logout():
        sid = getattr(g, "session_id", None)
        if sid:
            revoke_session(sid)
        response = jsonify({"status": "ok"})
        response.delete_cookie(SESSION_COOKIE, path="/", samesite="Strict")
        return response

    @app.route("/api/auth/password", methods=["POST"])
    def _auth_change_password():
        denied = _require_owner()
        if denied:
            return denied
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
        current_sid = getattr(g, "session_id", None)
        revoke_other_sessions(keep_sid=current_sid)
        return jsonify({
            "status": "ok",
            "message": "Password changed. Other devices must sign in again.",
        })

    @app.route("/api/auth/sessions", methods=["GET"])
    def _auth_sessions_list():
        denied = _require_owner()
        if denied:
            return denied
        current_sid = getattr(g, "session_id", None)
        return jsonify({
            "status": "ok",
            "current_session_id": current_sid,
            "sessions": list_sessions(current_sid=current_sid),
        })

    @app.route("/api/auth/sessions/<session_id>", methods=["DELETE"])
    def _auth_session_revoke(session_id: str):
        denied = _require_owner()
        if denied:
            return denied
        removed = revoke_session(session_id)
        if not removed:
            return jsonify({"status": "error", "error": "Session not found."}), 404
        response = jsonify({"status": "ok", "revoked": session_id})
        if session_id == getattr(g, "session_id", None):
            response.delete_cookie(SESSION_COOKIE, path="/", samesite="Strict")
        return response

    @app.route("/api/auth/sessions/revoke-others", methods=["POST"])
    def _auth_sessions_revoke_others():
        denied = _require_owner()
        if denied:
            return denied
        count = revoke_other_sessions(keep_sid=getattr(g, "session_id", None))
        return jsonify({"status": "ok", "revoked_count": count})

    @app.route("/api/auth/access", methods=["GET"])
    def _auth_access_get():
        denied = _require_owner()
        if denied:
            return denied
        return jsonify({
            "status": "ok",
            "family": get_family_status(),
            "totp": get_totp_status(),
        })

    @app.route("/api/auth/access", methods=["POST"])
    def _auth_access_update():
        denied = _require_owner()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        enabled = bool(data.get("family_enabled"))
        lan_open = bool(data.get("family_lan_open"))
        password = data.get("family_password")
        try:
            fam = set_family_config(
                enabled=enabled,
                lan_open=lan_open,
                password=str(password) if password is not None else None,
            )
        except ValueError as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400
        except OSError as exc:
            return jsonify({"status": "error", "error": f"Could not save access settings: {exc}"}), 500
        return jsonify({
            "status": "ok",
            "family": fam,
            "message": "Family view settings updated.",
        })

    @app.route("/api/auth/totp/setup", methods=["POST"])
    def _auth_totp_setup():
        denied = _require_owner()
        if denied:
            return denied
        host_label = socket.gethostname() or "homelab"
        payload = start_totp_setup(account=f"owner@{host_label}")
        return jsonify({"status": "ok", **payload})

    @app.route("/api/auth/totp/enable", methods=["POST"])
    def _auth_totp_enable():
        denied = _require_owner()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        code = str(data.get("code") or "").strip()
        ok, result = enable_totp(code)
        if not ok:
            return jsonify({"status": "error", "error": str(result)}), 400
        return jsonify({
            "status": "ok",
            "enabled": True,
            "recovery_codes": result,
            "message": "Two-factor authentication enabled. Save your recovery codes offline.",
        })

    @app.route("/api/auth/totp/disable", methods=["POST"])
    def _auth_totp_disable():
        denied = _require_owner()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        password = str(data.get("password") or "")
        stored = read_password_hash()
        if stored and not verify_password(password, stored):
            _record_failure(request.remote_addr or "?")
            return jsonify({"status": "error", "error": "The owner password is wrong."}), 403
        disable_totp()
        return jsonify({"status": "ok", "enabled": False, "message": "Two-factor authentication turned off."})

    return token, generated

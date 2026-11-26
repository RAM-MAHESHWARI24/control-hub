"""
Widget: Configuration & Node Control Center

Environment settings, atomic hardlink testing, port status matrix,
credential generation, AI Copilot diagnostics and static-IP changes.

Static IP changes run through core/netplan_cli.py under sudo (the daemon is
unprivileged); the change is applied with an armed revert timer and must be
confirmed from the new address within the timeout.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from flask import Blueprint, Response, jsonify, request

HUB_ROOT = Path(__file__).resolve().parent.parent
if str(HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(HUB_ROOT))

from config import (  # noqa: E402
    BACKUP_LOG_FILE,
    CONFIG_APPLY_HELPER,
    IMMICH_ML_LOG_FILE,
    MANIFEST_FILE_PATH,
    MEDIA_BACKUP_LOG_FILE,
    PHOTO_UPLOAD_DIR,
    PORT,
    SERVER_SUSPEND_LOG_FILE,
    TV_UPDATER_LOG_FILE,
)
from core.config_core import (  # noqa: E402
    ETC_DIR,
    generate_all_secrets,
    generate_ai_context_dump,
    generate_netplan_yaml,
    get_default_ports,
    get_disk_partitions,
    get_system_snapshot,
    load_env_file,
    netplan_change_status,
    probe_network_interfaces,
    sync_all_blueprint_envs,
    test_atomic_hardlink,
)

# Monorepo root when running inside the blueprint, otherwise the hub itself (standalone).
REPO_ROOT = HUB_ROOT.parent.parent if (HUB_ROOT.parent.parent / "apps" / "control-hub").exists() else HUB_ROOT
NETPLAN_CLI = HUB_ROOT / "core" / "netplan_cli.py"
SECRET_MASK = "********"
SECRET_CONFIG_KEYS = {
    "radarr_api_key": "RADARR_API_KEY",
    "sonarr_api_key": "SONARR_API_KEY",
    "prowlarr_api_key": "PROWLARR_API_KEY",
    "qbittorrent_pass": "QBITTORRENT_PASS",
}
_LOG_SECRET_RE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._~+/=-]+|(?:password|passwd|pass|token|api[_-]?key|secret)\s*[:=]\s*[^\s,;\"']+|://[^:\s/]+:[^@\s/]+@)"
)

config_center_bp = Blueprint("config_center", __name__)


def _config_apply_available() -> bool:
    return bool(CONFIG_APPLY_HELPER and os.path.isfile(CONFIG_APPLY_HELPER))


def _run_config_apply(action: str, payload: dict | None = None, timeout: int = 20) -> dict | None:
    if not _config_apply_available():
        return None
    cmd = ["sudo", "-n", CONFIG_APPLY_HELPER, action]
    if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() == 0:
        cmd = [CONFIG_APPLY_HELPER, action]
    try:
        proc = subprocess.run(
            cmd,
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.stdout.strip():
            return json.loads(proc.stdout.strip())
    except Exception:
        pass
    return None


def _blueprint_env_path() -> Path:
    """First readable blueprint or hub env file; falls back to control-hub.env when homelab.env is 0600 root."""
    for candidate in (
        ETC_DIR / "homelab.env",
        ETC_DIR / "control-hub.env",
        REPO_ROOT / ".env",
        HUB_ROOT / ".env",
        REPO_ROOT / ".env.example",
    ):
        if candidate.exists() and os.access(candidate, os.R_OK):
            return candidate
    return REPO_ROOT / ".env.example"


def _is_env_read_only() -> bool:
    """True when /etc/homelab is root-owned and the audited config-apply helper is absent."""
    return bool(ETC_DIR.exists() and not os.access(ETC_DIR, os.W_OK) and not _config_apply_available())


def _redact_log_line(line: str) -> str:
    return _LOG_SECRET_RE.sub(lambda m: m.group(0).split(":", 1)[0] + ": [REDACTED]" if ":" in m.group(0) and "://" not in m.group(0) else "[REDACTED]", line)


def _run_privileged_netplan(args):
    """Runs the audited netplan helper via sudo (or directly when already root)."""
    cmd = [sys.executable, str(NETPLAN_CLI), *args]
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        cmd = ["sudo", "-n", *cmd]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    try:
        payload = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        payload = {"success": False, "error": proc.stdout.strip() or proc.stderr.strip()}
    if proc.returncode != 0 and "error" not in payload:
        payload["error"] = proc.stderr.strip() or f"exit code {proc.returncode}"
        payload.setdefault("success", False)
    return payload


@config_center_bp.route("/api/config/current", methods=["GET"])
def get_current_config():
    """Returns current environment values (secrets masked), system vitals, mounts and network interfaces."""
    try:
        env_path = _blueprint_env_path()
        env_vars = load_env_file(str(env_path))
        snapshot = get_system_snapshot()
        interfaces = probe_network_interfaces()
        read_only = _is_env_read_only()

        def _mask(key: str) -> str:
            val = env_vars.get(key, "")
            return SECRET_MASK if val else ""

        config = {
            "host_user": env_vars.get("HOST_USER", ""),
            "puid": env_vars.get("PUID", "1000"),
            "pgid": env_vars.get("PGID", "1000"),
            "server_ip": env_vars.get("SERVER_IP", interfaces.get("current_ip", "")),
            "timezone": env_vars.get("TIMEZONE") or env_vars.get("TZ") or snapshot.get("timezone", "UTC"),
            "ssd_root": env_vars.get("SSD_ROOT", "/"),
            "hdd_data": env_vars.get("HDD_DATA", "/mnt/hdd/data"),
            "hdd_memories": env_vars.get("HDD_MEMORIES", "/mnt/hdd/Memories"),
            "radarr_api_key": _mask("RADARR_API_KEY"),
            "sonarr_api_key": _mask("SONARR_API_KEY"),
            "prowlarr_api_key": _mask("PROWLARR_API_KEY"),
            "control_hub_port": env_vars.get("CONTROL_HUB_PORT", str(PORT)),
            "active_nic": env_vars.get("ACTIVE_NIC") or interfaces.get("active_nic", ""),
            "link_speed_mbps": env_vars.get("LINK_SPEED_MBPS", ""),
            "qbittorrent_user": env_vars.get("QBITTORRENT_USER", "admin"),
            "qbittorrent_pass": _mask("QBITTORRENT_PASS"),
            "gdrive_remote": env_vars.get("GDRIVE_REMOTE", ""),
            "photo_upload_dir": env_vars.get("PHOTO_UPLOAD_DIR", PHOTO_UPLOAD_DIR),
        }

        helper_avail = _config_apply_available()
        helper_stat = _run_config_apply("status") if helper_avail else None
        manifest_exists = bool(MANIFEST_FILE_PATH and os.path.isfile(MANIFEST_FILE_PATH))
        blueprint_mode = bool((helper_stat or {}).get("blueprint_mode") or manifest_exists or (ETC_DIR.exists() and REPO_ROOT != HUB_ROOT))
        can_undo = bool((helper_stat or {}).get("can_undo"))

        return jsonify({
            "status": "success",
            "config": config,
            "system": snapshot,
            "mounts": get_disk_partitions(),
            "interfaces": interfaces,
            "env_path": str(env_path),
            "is_example_fallback": env_path.name == ".env.example",
            "read_only": read_only,
            "helper_available": helper_avail,
            "blueprint_mode": blueprint_mode,
            "can_undo": can_undo,
            "apply_hint": (
                f"{ETC_DIR} is root-owned. Edit {ETC_DIR}/config.json and run "
                f"'sudo ./setup.sh --headless --config {ETC_DIR}/config.json' to apply changes."
            ) if read_only else None,
            "netplan_pending": netplan_change_status(),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/preview", methods=["POST"])
def preview_config():
    """Returns validation results and a redacted diff before applying configuration changes."""
    try:
        data = request.get_json() or {}
        if not data:
            return jsonify({"status": "error", "message": "No configuration payload provided"}), 400

        helper_res = _run_config_apply("preview", payload=data)
        if isinstance(helper_res, dict):
            code = 200 if helper_res.get("ok") else 400
            return jsonify({"status": "success" if helper_res.get("ok") else "error", **helper_res}), code

        # Standalone / dev fallback diff against current env
        env_vars = load_env_file(str(_blueprint_env_path()))
        current_map = {
            "timezone": (env_vars.get("TIMEZONE") or env_vars.get("TZ") or "UTC", "Timezone"),
            "hdd_data": (env_vars.get("HDD_DATA", "/mnt/hdd/data"), "Media Data Root (HDD_DATA)"),
            "hdd_memories": (env_vars.get("HDD_MEMORIES", "/mnt/hdd/Memories"), "Photo Library Root (HDD_MEMORIES)"),
            "photo_upload_dir": (env_vars.get("PHOTO_UPLOAD_DIR", PHOTO_UPLOAD_DIR), "Photo Upload Folder"),
            "puid": (env_vars.get("PUID", "1000"), "Container PUID"),
            "pgid": (env_vars.get("PGID", "1000"), "Container PGID"),
            "control_hub_port": (env_vars.get("CONTROL_HUB_PORT", str(PORT)), "Control Hub Port"),
            "gdrive_remote": (env_vars.get("GDRIVE_REMOTE", ""), "Backup Remote"),
        }
        changes = []
        for field, (old_val, label) in current_map.items():
            if field in data and str(data[field]) != str(old_val):
                changes.append({"field": field, "label": label, "old": old_val, "new": data[field]})
        for s_key, env_key in SECRET_CONFIG_KEYS.items():
            raw_s = str(data.get(s_key) or "").strip()
            if raw_s and raw_s != SECRET_MASK and raw_s != env_vars.get(env_key, ""):
                changes.append({"field": s_key, "label": s_key, "old": SECRET_MASK, "new": "***updated***"})
        return jsonify({"status": "success", "ok": True, "valid": True, "changes": changes, "errors": []})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/update", methods=["POST"])
def update_config():
    """Applies configuration changes via audited helper (blueprint) or directly (standalone)."""
    try:
        data = request.get_json() or {}
        if not data:
            return jsonify({"status": "error", "message": "No configuration payload provided"}), 400

        if _config_apply_available():
            helper_res = _run_config_apply("apply", payload=data, timeout=30)
            if isinstance(helper_res, dict):
                if helper_res.get("ok"):
                    return jsonify({
                        "status": "success",
                        "message": helper_res.get("message") or "Configuration saved.",
                        "updated_files": helper_res.get("updated_files") or {},
                        "changes": helper_res.get("changes") or [],
                        "can_undo": bool(helper_res.get("can_undo")),
                    })
                return jsonify({
                    "status": "error",
                    "message": helper_res.get("error") or "Configuration rejected by validator.",
                    "errors": helper_res.get("errors") or [],
                }), 400

        # Preserve existing stored secrets if the browser echoes the mask back unchanged.
        env_vars = load_env_file(str(_blueprint_env_path()))
        merged = dict(data)
        for field_key, env_key in SECRET_CONFIG_KEYS.items():
            if merged.get(field_key) == SECRET_MASK:
                merged[field_key] = env_vars.get(env_key, "")

        env_dir = str(ETC_DIR) if ETC_DIR.exists() else None
        try:
            results = sync_all_blueprint_envs(str(REPO_ROOT), merged, env_dir=env_dir)
        except PermissionError:
            return jsonify({
                "status": "error",
                "message": (
                    f"{ETC_DIR} is root-owned. Edit {ETC_DIR}/config.json and re-run "
                    "'sudo ./setup.sh --headless --config /etc/homelab/config.json' to apply changes."
                ),
            }), 403
        return jsonify({"status": "success", "message": "Configuration saved.", "updated_files": results, "can_undo": False})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/undo", methods=["POST"])
def undo_config():
    """Reverts the last audited blueprint configuration change."""
    if not _config_apply_available():
        return jsonify({"status": "error", "message": "Undo requires the homelab-config-apply blueprint helper."}), 404
    res = _run_config_apply("undo", timeout=30)
    if isinstance(res, dict) and res.get("ok"):
        return jsonify({"status": "success", "message": res.get("message"), "updated_files": res.get("updated_files")})
    err = (res or {}).get("error") or "Could not restore previous configuration snapshot."
    return jsonify({"status": "error", "message": err}), 400


@config_center_bp.route("/api/config/manifest", methods=["GET"])
def get_install_manifest():
    """Returns /var/lib/homelab/installed.json for blueprint installs."""
    if not MANIFEST_FILE_PATH or not os.path.isfile(MANIFEST_FILE_PATH):
        return jsonify({"installed": False, "manifest": None, "path": MANIFEST_FILE_PATH})
    try:
        data = json.loads(Path(MANIFEST_FILE_PATH).read_text(encoding="utf-8"))
        return jsonify({"installed": True, "manifest": data, "path": MANIFEST_FILE_PATH})
    except (OSError, json.JSONDecodeError) as exc:
        return jsonify({"installed": False, "manifest": None, "error": str(exc)[:160], "path": MANIFEST_FILE_PATH}), 500


@config_center_bp.route("/api/config/export", methods=["GET"])
def export_settings():
    """Exports sanitized settings (zero secrets) for migrating onto a new server."""
    helper_res = _run_config_apply("export")
    if isinstance(helper_res, dict) and helper_res.get("ok"):
        export_cfg = helper_res.get("config") or {}
    else:
        env_vars = load_env_file(str(_blueprint_env_path()))
        export_cfg = {
            "host_user": env_vars.get("HOST_USER", "homelab"),
            "puid": env_vars.get("PUID", "1000"),
            "pgid": env_vars.get("PGID", "1000"),
            "timezone": env_vars.get("TIMEZONE") or env_vars.get("TZ") or "UTC",
            "hdd_data": env_vars.get("HDD_DATA", "/mnt/hdd/data"),
            "hdd_memories": env_vars.get("HDD_MEMORIES", "/mnt/hdd/Memories"),
            "photo_upload_dir": env_vars.get("PHOTO_UPLOAD_DIR", PHOTO_UPLOAD_DIR),
            "control_hub_port": int(env_vars.get("CONTROL_HUB_PORT", PORT) or PORT),
            "gdrive_remote": env_vars.get("GDRIVE_REMOTE", ""),
        }

    bundle = {"schema_version": 2, "secrets_removed": True, "config": export_cfg}
    if request.args.get("download") in ("1", "true"):
        return Response(
            json.dumps(bundle, indent=2) + "\n",
            mimetype="application/json",
            headers={"Content-Disposition": 'attachment; filename="homelab-settings-export.json"'},
        )
    return jsonify({"status": "success", **bundle})


@config_center_bp.route("/api/config/import", methods=["POST"])
def import_settings():
    """Validates imported settings (secrets stripped) and returns a preview or applies changes."""
    body = request.get_json(silent=True) or {}
    raw_cfg = body.get("config") if isinstance(body.get("config"), dict) else body
    if not isinstance(raw_cfg, dict) or not raw_cfg:
        return jsonify({"status": "error", "message": "Expected a JSON settings object."}), 400

    # Strip any secret-looking keys on import for defense in depth
    sanitized = {
        k: v for k, v in raw_cfg.items()
        if not any(tok in k.lower() for tok in ("password", "pass", "token", "secret", "api_key", "_key"))
    }
    if not sanitized:
        return jsonify({"status": "error", "message": "No editable non-secret fields found in import payload."}), 400

    dry_preview = bool(body.get("preview", True))
    if dry_preview:
        helper_res = _run_config_apply("preview", payload=sanitized)
        if isinstance(helper_res, dict):
            code = 200 if helper_res.get("ok") else 400
            return jsonify({"status": "success" if helper_res.get("ok") else "error", "sanitized_config": sanitized, **helper_res}), code
        return jsonify({"status": "success", "ok": True, "valid": True, "sanitized_config": sanitized, "changes": [{"field": k, "label": k, "old": "(current)", "new": v} for k, v in sanitized.items()], "errors": []})

    helper_res = _run_config_apply("apply", payload=sanitized, timeout=30)
    if isinstance(helper_res, dict):
        code = 200 if helper_res.get("ok") else 400
        return jsonify({"status": "success" if helper_res.get("ok") else "error", **helper_res}), code

    env_dir = str(ETC_DIR) if ETC_DIR.exists() else None
    try:
        updated = sync_all_blueprint_envs(str(REPO_ROOT), sanitized, env_dir=env_dir)
        return jsonify({"status": "success", "ok": True, "message": "Imported settings applied.", "updated_files": updated})
    except PermissionError:
        return jsonify({"status": "error", "message": f"{ETC_DIR} is root-owned; import preview only without helper."}), 403


@config_center_bp.route("/api/config/support-bundle", methods=["GET"])
def download_support_bundle():
    """Builds a secret-free diagnostic bundle (versions, health summary, redacted recent logs)."""
    snapshot = get_system_snapshot()
    manifest_data = None
    if MANIFEST_FILE_PATH and os.path.isfile(MANIFEST_FILE_PATH):
        try:
            manifest_data = json.loads(Path(MANIFEST_FILE_PATH).read_text(encoding="utf-8"))
        except Exception:
            manifest_data = None

    containers = []
    try:
        proc = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) == 3:
                    containers.append({"name": parts[0], "image": parts[1], "status": parts[2]})
    except Exception:
        pass

    logs = {}
    for label, path_str in (
        ("photo_backup", BACKUP_LOG_FILE),
        ("media_backup", MEDIA_BACKUP_LOG_FILE),
        ("immich_ml", IMMICH_ML_LOG_FILE),
        ("tv_updater", TV_UPDATER_LOG_FILE),
        ("sleep_guard", SERVER_SUSPEND_LOG_FILE),
    ):
        if path_str and os.path.isfile(path_str):
            try:
                lines = Path(path_str).read_text(encoding="utf-8", errors="replace").splitlines()[-50:]
                logs[label] = [_redact_log_line(ln) for ln in lines]
            except OSError as exc:
                logs[label] = [f"Unreadable: {exc}"]

    bundle = {
        "schema_version": 1,
        "secrets_redacted": True,
        "system": snapshot,
        "manifest": manifest_data,
        "containers": containers,
        "logs": logs,
    }
    if request.args.get("download") in ("1", "true"):
        return Response(
            json.dumps(bundle, indent=2) + "\n",
            mimetype="application/json",
            headers={"Content-Disposition": 'attachment; filename="homelab-support-bundle.json"'},
        )
    return jsonify({"status": "success", **bundle})


@config_center_bp.route("/api/config/verify-hardlink", methods=["POST"])
def verify_hardlink():
    try:
        data = request.get_json() or {}
        return jsonify({"status": "success", "result": test_atomic_hardlink(data.get("path", "/mnt/hdd/data"))})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/ports", methods=["GET"])
def get_ports_status():
    try:
        overrides = {"control_hub": PORT}
        return jsonify({"status": "success", "ports": get_default_ports(overrides=overrides)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/generate-secrets", methods=["POST"])
def generate_secrets():
    try:
        return jsonify({"status": "success", "secrets": generate_all_secrets()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/ai-diagnostics", methods=["GET"])
def get_ai_diagnostics():
    try:
        notes = request.args.get("notes", "").strip()
        snapshot = get_system_snapshot()
        ai_prompt = generate_ai_context_dump(snapshot)
        if notes:
            ai_prompt += f"\n## Custom Administrator Notes:\n{notes}\n"
        return jsonify({"status": "success", "snapshot": snapshot, "ai_prompt": ai_prompt})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def _netplan_params(data):
    net = probe_network_interfaces()
    interface = data.get("interface") or net["active_nic"]
    ip = data.get("ip") or net["current_ip"]
    gateway = data.get("gateway") or net["default_gateway"]
    dns = data.get("dns") or net["dns_servers"]
    return interface, (ip if "/" in ip else f"{ip}/24"), gateway, dns


@config_center_bp.route("/api/config/netplan-preview", methods=["POST"])
def netplan_preview():
    try:
        interface, ip_cidr, gateway, dns = _netplan_params(request.get_json() or {})
        return jsonify({"status": "success", "yaml": generate_netplan_yaml(interface, ip_cidr, gateway, dns), "ip": ip_cidr, "valid": True})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/netplan-apply", methods=["POST"])
def netplan_apply():
    """Applies a static IP with an armed revert timer (confirm via /api/config/netplan-confirm)."""
    try:
        data = request.get_json() or {}
        interface, ip_cidr, gateway, dns = _netplan_params(data)
        timeout = int(data.get("timeout", 120))
        args = ["apply", "--interface", interface, "--ip", ip_cidr, "--gateway", gateway, "--timeout", str(timeout)]
        for server in dns:
            args += ["--dns", server]
        result = _run_privileged_netplan(args)
        status = "success" if result.get("success") else "error"
        return jsonify({"status": status, "result": result}), (200 if status == "success" else 500)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/netplan-confirm", methods=["POST"])
def netplan_confirm():
    try:
        result = _run_privileged_netplan(["confirm"])
        return jsonify({"status": "success" if result.get("success") else "error", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@config_center_bp.route("/api/config/netplan-status", methods=["GET"])
def netplan_status():
    return jsonify({"status": "success", "result": netplan_change_status()})

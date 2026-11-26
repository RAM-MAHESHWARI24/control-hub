"""
.env rendering for every module, from the wizard/headless configuration.

Rendered files are written with 0600 permissions because they hold database
passwords and API keys. On a real install they live in /etc/homelab/ and a
symlink is placed next to each module's docker-compose.yml so a plain
`docker compose up -d` in that directory keeps working. In dry-run or
standalone mode (no env_dir given) they are written next to the module.
"""

import json
import os
import stat
from pathlib import Path
from typing import Dict, Any, Optional

from .secrets_generator import generate_password, generate_api_key
from .paths import APPDATA_DIR as _APPDATA_DIR
from .paths import STATE_DIR as _STATE_DIR

PLACEHOLDER_SECRETS = {"adminadmin", "postgres", "postgres_pass", "postgres_secure_pass", "changeme", "password"}


def load_env_file(filepath: str) -> Dict[str, str]:
    """Parses a .env file into a dictionary of key-value pairs."""
    p = Path(filepath)
    if not p.exists():
        return {}

    env_vars: Dict[str, str] = {}
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                env_vars[k.strip()] = v.strip().strip("'\"")
    return env_vars


def update_env_variables(template_content: str, updates: Dict[str, Any]) -> str:
    """
    Updates values in template .env text while preserving comments and order.
    Variables not present in the template are appended at the bottom.
    """
    lines = template_content.splitlines()
    updated_lines = []
    seen_keys = set()

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _ = stripped.split("=", 1)
            key = key.strip()
            seen_keys.add(key)
            if key in updates:
                updated_lines.append(f"{key}={updates[key]}")
                continue
        updated_lines.append(line)

    unseen_keys = [k for k in updates if k not in seen_keys]
    if unseen_keys:
        updated_lines.append("\n# --- Additional Configured Settings ---")
        for k in unseen_keys:
            updated_lines.append(f"{k}={updates[k]}")

    return "\n".join(updated_lines) + "\n"


def write_env_file(target_path: str, content: str, mode: int = 0o600) -> None:
    """Atomically writes a secrets-bearing file with restrictive permissions."""
    p = Path(target_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    temp_file = p.with_name(p.name + ".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(content)
    try:
        os.chmod(temp_file, mode)
    except OSError:
        pass
    temp_file.replace(p)


def _link_into_module(env_path: Path, module_dir: Path, link_name: str = ".env") -> None:
    """Creates module_dir/<link_name> -> env_path so standalone compose usage keeps working."""
    if os.name == "nt":
        return
    link = module_dir / link_name
    try:
        if link.is_symlink():
            if os.readlink(link) == str(env_path):
                return
            link.unlink()
        elif link.exists():
            link.unlink()
        module_dir.mkdir(parents=True, exist_ok=True)
        os.symlink(str(env_path), str(link))
    except OSError:
        pass


def _ensure_secret(config: Dict[str, Any], key: str, generator) -> str:
    """Returns config[key], generating and storing a value when it is empty or a placeholder."""
    value = str(config.get(key) or "").strip()
    if not value or value.upper().startswith("YOUR_") or value.lower() in PLACEHOLDER_SECRETS:
        value = generator()
        config[key] = value
    return value


def _external_mount_path(config: Dict[str, Any]) -> str:
    """Container path for the photo external library; an unusable value falls back to /mnt/media."""
    path = str(config.get("photo_external_mount_path") or "/mnt/media").strip().rstrip("/")
    if not path.startswith("/") or ":" in path or any(c.isspace() for c in path) or path in ("", "/data"):
        return "/mnt/media"
    return path


def sync_all_blueprint_envs(base_dir: str, config: Dict[str, Any], env_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Renders every module's environment file from its .env.example template.

    base_dir: repository root (or dry-run preview root) holding apps/<module>/.env.example
    env_dir:  where to write the rendered files (e.g. /etc/homelab). When None the
              files are written beside each module (dry-run / standalone behaviour).

    Secrets that are missing or still placeholders are generated here so no
    install ever ships default credentials. Generated values are written back
    into `config` so the caller can show them to the operator once.
    """
    root_path = Path(base_dir)
    out_dir = Path(env_dir) if env_dir else None
    results: Dict[str, Any] = {}

    tz = config.get("timezone") or "UTC"
    puid = config.get("puid", 1000)
    pgid = config.get("pgid", 1000)
    data_dir = config.get("hdd_data", "/mnt/hdd/data")
    memories_dir = config.get("hdd_memories", "/mnt/hdd/Memories")
    active_nic = config.get("active_nic") or ""
    server_ip = config.get("server_ip", "")
    qbit_port = config.get("qbittorrent_port", 8080)

    qbit_user = config.get("qbittorrent_user") or "admin"
    qbit_pass = _ensure_secret(config, "qbittorrent_pass", lambda: generate_password(18))
    pg_pass = _ensure_secret(config, "postgres_password", lambda: generate_password(24))
    radarr_key = _ensure_secret(config, "radarr_api_key", lambda: generate_api_key(32))
    sonarr_key = _ensure_secret(config, "sonarr_api_key", lambda: generate_api_key(32))
    prowlarr_key = _ensure_secret(config, "prowlarr_api_key", lambda: generate_api_key(32))
    hub_token = _ensure_secret(config, "control_hub_token", lambda: generate_api_key(48))
    # Jellyfin / Seerr admin password; defaults to the qBittorrent password so Express mode has one "master" password
    if not str(config.get("media_admin_pass") or "").strip():
        config["media_admin_pass"] = qbit_pass
    media_admin_pass = config["media_admin_pass"]

    tv_enabled = any(str(m) in ("tv_autoupdater", "tv_updater", "tv-updater") for m in (config.get("enabled_services") or []))
    services = [str(m) for m in (config.get("enabled_services") or ["media", "photos", "control_hub"])]
    media_backup_enabled = (
        any(m in ("media", "mediaserver") for m in services)
        and any(m in ("photo_backup", "immich_backup") for m in services)
        and bool(config.get("gdrive_remote"))
        and config.get("media_backup", True) is not False
    )

    def render(module_id: str, module_dir: Path, updates: Dict[str, Any]) -> Path:
        template = module_dir / ".env.example"
        template_content = template.read_text(encoding="utf-8") if template.exists() else ""
        content = update_env_variables(template_content, updates)
        target = (out_dir / f"{module_id}.env") if out_dir else (module_dir / ".env")
        write_env_file(str(target), content)
        if out_dir and module_dir.exists():
            _link_into_module(target, module_dir)
        return target

    # 1. Blueprint-wide values (root .env)
    results["master_env"] = str(
        render(
            "homelab",
            root_path,
            {
                "HOST_USER": config.get("host_user", "homelab"),
                "PUID": puid,
                "PGID": pgid,
                "SERVER_IP": server_ip,
                "TIMEZONE": tz,
                "SSD_ROOT": config.get("ssd_root", "/"),
                "HDD_DATA": data_dir,
                "HDD_MEMORIES": memories_dir,
                "RADARR_API_KEY": radarr_key,
                "SONARR_API_KEY": sonarr_key,
                "PROWLARR_API_KEY": prowlarr_key,
                "CONTROL_HUB_PORT": config.get("control_hub_port", 7575),
                "ACTIVE_NIC": active_nic,
                "LINK_SPEED_MBPS": config.get("link_speed_mbps", 1000),
                "QBITTORRENT_URL": f"http://127.0.0.1:{qbit_port}",
                "QBITTORRENT_USER": qbit_user,
                "QBITTORRENT_PASS": qbit_pass,
                "GDRIVE_REMOTE": config.get("gdrive_remote", ""),
            },
        )
    )

    # 2. Media pipeline
    results["mediaserver_env"] = str(
        render(
            "mediaserver",
            root_path / "apps" / "mediaserver",
            {
                "PUID": puid,
                "PGID": pgid,
                "TZ": tz,
                "CONFIG_DIR": config.get("config_dir", "./config"),
                "DATA_DIR": data_dir,
                "RADARR_API_KEY": radarr_key,
                "SONARR_API_KEY": sonarr_key,
                "PROWLARR_API_KEY": prowlarr_key,
                "QBITTORRENT_USER": qbit_user,
                "QBITTORRENT_PASS": qbit_pass,
                "ENABLE_TMDB_BYPASS": "true" if config.get("enable_tmdb_bypass") else "false",
                "SEERR_NODE_OPTIONS": (
                    "--dns-result-order=ipv4first --require /app/config/tmdb-interceptor.js"
                    if config.get("enable_tmdb_bypass") else "--dns-result-order=ipv4first"
                ),
                "COMPOSE_PROFILES": "byparr" if config.get("enable_byparr") else "",
                "DNS_OVERRIDE": "true" if config.get("dns_override") else "",
                "DNS_PRIMARY": (config.get("dns_servers") or ["1.1.1.1"])[0],
                "DNS_SECONDARY": (config.get("dns_servers") or ["1.1.1.1", "8.8.8.8"])[-1],
                "MEDIA_ADMIN_USER": config.get("media_admin_user", "admin"),
                "MEDIA_ADMIN_PASS": media_admin_pass,
            },
        )
    )

    # 3. Photo cloud
    # Installed: photo DB, thumbnails and transcodes live under appdata, not in the
    # replaceable checkout. Standalone (no env_dir): beside the module, as before.
    photo_state = f"{_APPDATA_DIR}/noodle-gallery" if out_dir else "./data"
    results["noodle_gallery_env"] = str(
        render(
            "noodle-gallery",
            root_path / "apps" / "noodle-gallery",
            {
                "UPLOAD_LOCATION": config.get("photo_upload_dir", f"{memories_dir.rstrip('/')}/uploads"),
                "DB_DATA_LOCATION": config.get("photo_db_dir", f"{photo_state}/postgres"),
                "THUMBS_LOCATION": config.get("photo_thumbs_dir", f"{photo_state}/thumbs"),
                "ENCODED_VIDEO_LOCATION": config.get("photo_video_dir", f"{photo_state}/encoded-video"),
                "EXTERNAL_LIBRARY_LOCATION": memories_dir,
                "EXTERNAL_LIBRARY_MOUNT_PATH": _external_mount_path(config),
                "EXTERNAL_LIBRARY_MOUNT_MODE": "rw" if str(config.get("photo_external_mount_mode", "ro")).strip() == "rw" else "ro",
                "GALLERY_PORT": config.get("gallery_port", 2283),
                "TZ": tz,
                "DB_PASSWORD": pg_pass,
                "DB_USERNAME": config.get("postgres_user", "postgres"),
                "DB_DATABASE_NAME": config.get("postgres_db", "immich"),
            },
        )
    )

    # 4. Control Hub
    results["control_hub_env"] = str(
        render(
            "control-hub",
            root_path / "apps" / "control-hub",
            {
                "CONTROL_HUB_HOST": config.get("control_hub_host", "0.0.0.0"),
                "CONTROL_HUB_PORT": config.get("control_hub_port", 7575),
                "CONTROL_HUB_TOKEN": hub_token,
                "ACTIVE_NIC": active_nic,
                "LINK_SPEED_MBPS": config.get("link_speed_mbps", 1000),
                "QBITTORRENT_URL": f"http://127.0.0.1:{qbit_port}",
                "QBITTORRENT_USER": qbit_user,
                "QBITTORRENT_PASS": qbit_pass,
                "HDD_DATA": data_dir,
                "HDD_MEMORIES": memories_dir,
                "PHOTO_UPLOAD_DIR": config.get("photo_upload_dir", f"{memories_dir.rstrip('/')}/uploads"),
                "GDRIVE_REMOTE": config.get("gdrive_remote", ""),
                "IMMICH_DB_USER": config.get("postgres_user", "postgres"),
                "IMMICH_DB_NAME": config.get("postgres_db", "immich"),
                "TZ": tz,
                # Set only when the TV module is part of this install; empty hides the TV card.
                # "Back up now" for the media apps' settings; empty hides the button.
                "MEDIA_BACKUP_SCRIPT": str(root_path / "apps" / "mediaserver" / "scripts" / "media_config_backup.py") if media_backup_enabled else "",
                "TV_UPDATER_DIR": str(root_path / "apps" / "tv-autoupdater") if tv_enabled else "",
                "TV_UPDATER_PY": str(root_path / "apps" / "tv-autoupdater" / "tv_updater.py") if tv_enabled else "",
                "TV_UPDATER_STATE_FILE": str(_STATE_DIR / "tv-autoupdater" / "state.json"),
                # Where the photo-backup cron (apps/immich-face-xmp-exporter/host/cron/immich-backup) writes
                "BACKUP_DIR": str(_STATE_DIR / "photo-backups"),
                "BACKUP_LOG_FILE": str(_STATE_DIR / "photo-backups" / "backup.log"),
                "TV_UPDATER_INCOMING_DIR": str(_STATE_DIR / "tv-autoupdater" / "incoming_apks"),
                "TV_UPDATER_LOG_FILE": str(_STATE_DIR / "tv-autoupdater" / "tv-autoupdater.log"),
            },
        )
    )

    # 5. TV auto-updater (JSON config rather than .env)
    tv_dir = next(
        (root_path / "apps" / name for name in ("tv-autoupdater", "tv-updater") if (root_path / "apps" / name).exists()),
        None,
    )
    if tv_dir is not None:
        tv_template_file = tv_dir / "config.example.json"
        tv_data: Dict[str, Any] = {}
        if tv_template_file.exists():
            try:
                tv_data = json.loads(tv_template_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                tv_data = {}

        tv_ips = config.get("tv_ips", [])
        if tv_ips:
            tv_data["target_profiles"] = [
                {
                    "id": f"tv_{idx + 1}",
                    "name": f"Smart TV {idx + 1}",
                    "match_models": ["android_tv", "mibox", "bravia", "chromecast"],
                    "default_ip": ip.strip(),
                    "port": 5555,
                }
                for idx, ip in enumerate(tv_ips)
            ]

        tv_target = (out_dir / "tv-autoupdater.json") if out_dir else (tv_dir / "config.json")
        write_env_file(str(tv_target), json.dumps(tv_data, indent=2) + "\n", mode=stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
        if out_dir:
            _link_into_module(tv_target, tv_dir, "config.json")
        results["tv_autoupdater_config"] = str(tv_target)

    return results

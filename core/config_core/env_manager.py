"""
Environment Configuration (.env) File Parser & Synchronizer
Safely reads, updates, and writes .env files while preserving structure and comments.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, List, Tuple


def load_env_file(filepath: str) -> Dict[str, str]:
    """Parses a .env file into a dictionary of key-value pairs"""
    p = Path(filepath)
    if not p.exists():
        return {}

    env_vars = {}
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                env_vars[k] = v
    return env_vars


def update_env_variables(template_content: str, updates: Dict[str, Any]) -> str:
    """
    Updates variable values in template .env text while preserving comments and order.
    Appends any new variables not present in the template at the bottom.
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
                val = updates[key]
                # Format value cleanly
                val_str = str(val)
                updated_lines.append(f"{key}={val_str}")
                continue
        updated_lines.append(line)

    # Append any updates that were not in the template
    unseen_keys = [k for k in updates.keys() if k not in seen_keys]
    if unseen_keys:
        updated_lines.append("\n# --- Additional Configured Settings ---")
        for k in unseen_keys:
            updated_lines.append(f"{k}={updates[k]}")

    return "\n".join(updated_lines) + "\n"


def write_env_file(target_path: str, content: str) -> None:
    """Atomically writes content to target file via temporary file to prevent corruption"""
    p = Path(target_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    temp_file = p.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(content)
    temp_file.replace(p)


def sync_all_blueprint_envs(base_dir: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Synchronizes unified settings across all 5 monorepo component configs.
    Uses .env.example templates if destination .env does not exist.
    """
    root_path = Path(base_dir)
    results = {}

    # 1. Master Root .env
    master_template_file = root_path / ".env.example"
    master_env_file = root_path / ".env"
    template_content = master_template_file.read_text(encoding="utf-8") if master_template_file.exists() else ""

    master_updates = {
        "HOST_USER": config.get("host_user", "homelab_user"),
        "PUID": config.get("puid", 1000),
        "PGID": config.get("pgid", 1000),
        "SERVER_IP": config.get("server_ip", "192.168.1.100"),
        "TIMEZONE": config.get("timezone", "Asia/Kolkata"),
        "SSD_ROOT": config.get("ssd_root", "/"),
        "HDD_DATA": config.get("hdd_data", "/mnt/hdd/data"),
        "HDD_MEMORIES": config.get("hdd_memories", "/mnt/hdd/Memories"),
        "RADARR_API_KEY": config.get("radarr_api_key", ""),
        "SONARR_API_KEY": config.get("sonarr_api_key", ""),
        "PROWLARR_API_KEY": config.get("prowlarr_api_key", ""),
        "CONTROL_HUB_PORT": config.get("control_hub_port", 7575),
        "ACTIVE_NIC": config.get("active_nic", "eth0"),
        "LINK_SPEED_MBPS": config.get("link_speed_mbps", 1000),
        "QBITTORRENT_URL": f"http://127.0.0.1:{config.get('qbittorrent_port', 8080)}",
        "QBITTORRENT_USER": config.get("qbittorrent_user", "admin"),
        "QBITTORRENT_PASS": config.get("qbittorrent_pass", "adminadmin"),
        "GDRIVE_REMOTE": config.get("gdrive_remote", "gdrive:"),
    }
    master_content = update_env_variables(template_content, master_updates)
    write_env_file(str(master_env_file), master_content)
    results["master_env"] = str(master_env_file)

    # 2. Mediaserver Pipeline (apps/mediaserver/.env)
    media_dir = root_path / "apps" / "mediaserver"
    media_template = media_dir / ".env.example"
    media_env = media_dir / ".env"
    media_template_content = media_template.read_text(encoding="utf-8") if media_template.exists() else ""

    media_updates = {
        "PUID": config.get("puid", 1000),
        "PGID": config.get("pgid", 1000),
        "TZ": config.get("timezone", "Asia/Kolkata"),
        "CONFIG_DIR": config.get("config_dir", "./config"),
        "DATA_DIR": config.get("hdd_data", "/mnt/hdd/data"),
        "RADARR_API_KEY": config.get("radarr_api_key", ""),
        "SONARR_API_KEY": config.get("sonarr_api_key", ""),
        "PROWLARR_API_KEY": config.get("prowlarr_api_key", ""),
    }
    media_content = update_env_variables(media_template_content, media_updates)
    write_env_file(str(media_env), media_content)
    results["mediaserver_env"] = str(media_env)

    # 3. Noodle Photo Cloud (apps/noodle-gallery/.env)
    noodle_dir = root_path / "apps" / "noodle-gallery"
    noodle_template = noodle_dir / ".env.example"
    noodle_env = noodle_dir / ".env"
    noodle_template_content = noodle_template.read_text(encoding="utf-8") if noodle_template.exists() else ""

    noodle_updates = {
        "UPLOAD_LOCATION": config.get("photo_upload_dir", "/mnt/hdd/immich"),
        "DB_DATA_LOCATION": config.get("photo_db_dir", "./data/postgres"),
        "THUMBS_LOCATION": config.get("photo_thumbs_dir", "./data/thumbs"),
        "ENCODED_VIDEO_LOCATION": config.get("photo_video_dir", "./data/encoded-video"),
        "EXTERNAL_LIBRARY_LOCATION": config.get("hdd_memories", "/mnt/hdd/Memories"),
        "GALLERY_PORT": config.get("gallery_port", 2283),
        "TZ": config.get("timezone", "Asia/Kolkata"),
        "DB_PASSWORD": config.get("postgres_password", "postgres_secure_pass"),
        "DB_USERNAME": config.get("postgres_user", "postgres"),
        "DB_DATABASE_NAME": config.get("postgres_db", "immich"),
    }
    noodle_content = update_env_variables(noodle_template_content, noodle_updates)
    write_env_file(str(noodle_env), noodle_content)
    results["noodle_gallery_env"] = str(noodle_env)

    # 4. Control Hub Dashboard (apps/control-hub/.env)
    ch_dir = root_path / "apps" / "control-hub"
    ch_template = ch_dir / ".env.example"
    ch_env = ch_dir / ".env"
    ch_template_content = ch_template.read_text(encoding="utf-8") if ch_template.exists() else ""

    ch_updates = {
        "CONTROL_HUB_PORT": config.get("control_hub_port", 7575),
        "ACTIVE_NIC": config.get("active_nic", "eth0"),
        "LINK_SPEED_MBPS": config.get("link_speed_mbps", 1000),
        "QBITTORRENT_URL": f"http://127.0.0.1:{config.get('qbittorrent_port', 8080)}",
        "QBITTORRENT_USER": config.get("qbittorrent_user", "admin"),
        "QBITTORRENT_PASS": config.get("qbittorrent_pass", "adminadmin"),
    }
    ch_content = update_env_variables(ch_template_content, ch_updates)
    write_env_file(str(ch_env), ch_content)
    results["control_hub_env"] = str(ch_env)

    # 5. CleanYourTV (apps/tv-updater/config.json)
    tv_dir = root_path / "apps" / "tv-updater"
    tv_config_file = tv_dir / "config.json"
    tv_template_file = tv_dir / "config.example.json"

    tv_data = {}
    if tv_template_file.exists():
        try:
            tv_data = json.loads(tv_template_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    tv_ips = config.get("tv_ips", [])
    if tv_ips:
        # Update target profile default IPs
        target_profiles = []
        for idx, ip in enumerate(tv_ips):
            target_profiles.append({
                "id": f"tv_{idx + 1}",
                "name": f"Smart TV {idx + 1}",
                "match_models": ["android_tv", "mibox", "bravia", "chromecast"],
                "default_ip": ip.strip(),
                "port": 5555,
            })
        tv_data["target_profiles"] = target_profiles
    tv_config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(tv_config_file, "w", encoding="utf-8") as f:
        json.dump(tv_data, f, indent=2)
    results["tv_updater_config"] = str(tv_config_file)

    return results

"""
Updates available: what each app runs versus its newest stable release.

The running version comes from Docker itself (the pinned image tag of each container
started by docker compose), so this works for any stack without reading other
modules' files. The newest version comes from the project's latest GitHub release:

    lscr.io/linuxserver/<app>      -> linuxserver/docker-<app>   (release name = image tag)
    ghcr.io/<owner>/<image>        -> <owner>/<image>
    ghcr.io/open-noodle/gallery-*  -> open-noodle/gallery
    the photo database (Postgres)  -> not compared: update it by hand with its app

Results are cached on disk and refreshed at most once a day (GitHub allows 60
anonymous requests an hour; GITHUB_TOKEN raises that). Nothing is ever updated here:
the list says what is new, how big the step is, and the exact command to apply it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

CHECK_EVERY_SECONDS = 24 * 3600
AUTO_PATCH_INTERVAL = 24 * 3600
MIN_MANUAL_INTERVAL = 600
USER_AGENT = "homelab-blueprint-control-hub"

_lock = threading.Lock()

# Images whose repository name differs from the image name, or that must not be compared.
REPO_OVERRIDES = {
    "ghcr.io/open-noodle/gallery-server": "open-noodle/gallery",
    "ghcr.io/open-noodle/gallery-ml": "open-noodle/gallery",
}
MANUAL = {
    "ghcr.io/immich-app/postgres": "Database engine: update it by hand, together with the photo app, after reading its release notes.",
}
MIGRATION_MAJOR_HINTS = {
    "open-noodle/gallery": "Major photo-app release requires a manual database migration check — read release notes first.",
    "linuxserver/docker-sonarr": "Major Sonarr release includes database schema changes — review release notes before upgrading.",
}


def split_image(image: str) -> Tuple[str, str]:
    """('lscr.io/linuxserver/radarr', '7.0.3.10918-ls328') from an image reference (digest dropped)."""
    ref = image.split("@", 1)[0]
    name, _, tag = ref.rpartition(":")
    if not name or "/" in tag:  # no tag (a port in the registry host, or none at all)
        return ref, "latest"
    return name, tag


def source_for(name: str) -> Tuple[Optional[str], Optional[str]]:
    """(github_repo, reason_if_not_tracked)."""
    if name in MANUAL:
        return None, MANUAL[name]
    if name in REPO_OVERRIDES:
        return REPO_OVERRIDES[name], None
    m = re.match(r"^lscr\.io/linuxserver/([a-z0-9-]+)$", name) or re.match(r"^(?:docker\.io/|ghcr\.io/)?linuxserver/([a-z0-9-]+)$", name)
    if m:
        return f"linuxserver/docker-{m.group(1)}", None
    m = re.match(r"^ghcr\.io/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)$", name)
    if m:
        return f"{m.group(1)}/{m.group(2)}", None
    return None, "No release source known for this image."


def parse_version(tag: str) -> Tuple[Tuple[int, ...], int]:
    """(numbers of the app version, linuxserver build) — '7.0.3.10918-ls328' -> ((7,0,3,10918), 328)."""
    tag = tag.strip().lstrip("vV")
    build = 0
    m = re.search(r"-ls(\d+)$", tag)
    if m:
        build = int(m.group(1))
        tag = tag[: m.start()]
    return tuple(int(n) for n in re.findall(r"\d+", tag)), build


def classify(current: str, latest: str) -> str:
    """up_to_date | rebuild (same app, new image build) | update | major | newer_than_release | unknown."""
    if current.lstrip("vV") == latest.lstrip("vV"):
        return "up_to_date"
    (cur, cur_b), (new, new_b) = parse_version(current), parse_version(latest)
    if not cur or not new:
        return "unknown"
    if cur == new:
        if new_b > cur_b:
            return "rebuild"
        return "up_to_date" if new_b == cur_b else "newer_than_release"
    if new < cur:
        return "newer_than_release"
    return "major" if new[0] != cur[0] else "update"


def is_patch_update(current: str, latest: str) -> bool:
    """True only for image rebuilds or patch-level bumps (same major.minor; never major/minor)."""
    kind = classify(current, latest)
    if kind == "rebuild":
        return True
    if kind != "update":
        return False
    (cur, _), (new, _) = parse_version(current), parse_version(latest)
    return len(cur) >= 2 and len(new) >= 2 and cur[:2] == new[:2]


KIND_TEXT = {
    "up_to_date": "Up to date",
    "rebuild": "New image build (same app version)",
    "update": "Update available",
    "major": "Major version: read the release notes first",
    "newer_than_release": "Running a newer version than the latest release",
    "unknown": "Versions cannot be compared",
    "not_tracked": "Not tracked",
    "error": "Could not check",
}


# ---------------------------------------------------------------- sources

def running_containers() -> Optional[List[Dict]]:
    """Containers started by docker compose, with image and compose labels."""
    try:
        ids = subprocess.run(["docker", "ps", "-aq"], capture_output=True, text=True, timeout=10)
        if ids.returncode != 0:
            return None
        id_list = ids.stdout.split()
        if not id_list:
            return []
        res = subprocess.run(["docker", "inspect", *id_list], capture_output=True, text=True, timeout=20)
        data = json.loads(res.stdout or "[]")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    out = []
    for c in data:
        labels = (c.get("Config") or {}).get("Labels") or {}
        project = labels.get("com.docker.compose.project")
        if not project:
            continue  # started by hand, not part of a stack: nothing to update through compose
        out.append({
            "container": (c.get("Name") or "").lstrip("/"),
            "image": (c.get("Config") or {}).get("Image") or "",
            "project": project,
            "service": labels.get("com.docker.compose.service"),
            "working_dir": labels.get("com.docker.compose.project.working_dir"),
            "env_file": labels.get("com.docker.compose.project.environment_file"),
        })
    return sorted(out, key=lambda x: (x["project"], x["container"]))


def fetch_latest(repo: str, timeout: int = 10) -> Dict:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/releases/latest", headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        return {"error": str(exc)[:160]}
    if r.status_code != 200:
        msg = "rate limited by GitHub, try later" if r.status_code in (403, 429) else f"HTTP {r.status_code}"
        return {"error": msg}
    d = r.json()
    return {"tag": d.get("tag_name"), "published": (d.get("published_at") or "")[:10], "url": d.get("html_url")}


# ---------------------------------------------------------------- cache + report

def load_cache(path: Path) -> Dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(path: Path, data: Dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def refresh(cache_path: Path, containers: List[Dict], extra_repos: List[str], fetch=None, now: Optional[float] = None) -> Dict:
    """Fetches the newest release of every repo the running images map to."""
    fetcher = fetch or fetch_latest
    repos = sorted({r for c in containers if (r := source_for(split_image(c["image"])[0])[0])} | set(extra_repos))
    data = {"checked_at": now or time.time(), "repos": {repo: fetcher(repo) for repo in repos}}
    save_cache(cache_path, data)
    return data


def refresh_if_due(cache_path: Path, containers: List[Dict], extra_repos: List[str], force: bool = False) -> Dict:
    with _lock:
        cache = load_cache(cache_path)
        age = time.time() - float(cache.get("checked_at") or 0)
        if (force and age >= MIN_MANUAL_INTERVAL) or age >= CHECK_EVERY_SECONDS:
            cache = refresh(cache_path, containers, extra_repos)
        return cache


def update_command(c: Dict) -> Optional[str]:
    if not (c.get("working_dir") and c.get("service")):
        return None
    env = f" --env-file {c['env_file']}" if c.get("env_file") else ""
    return f"cd {c['working_dir']} && sudo docker compose{env} up -d {c['service']}"


def report(containers: List[Dict], cache: Dict, self_row: Optional[Dict] = None) -> Dict:
    rows = []
    for c in containers:
        name, tag = split_image(c["image"])
        repo, why = source_for(name)
        row = {**c, "image_name": name, "current": tag, "repo": repo, "latest": None, "published": None,
               "release_url": None, "kind": "not_tracked", "reason": why, "command": update_command(c),
               "patch_safe": False, "one_click_allowed": False}
        if repo:
            got = (cache.get("repos") or {}).get(repo)
            if not got:
                row.update(kind="unknown", reason="Not checked yet")
            elif got.get("error"):
                row.update(kind="error", reason=got["error"])
            else:
                kind = classify(tag, got["tag"] or "")
                reason = None
                if kind == "major":
                    reason = MIGRATION_MAJOR_HINTS.get(
                        repo, "Major release requires manual review — check release notes before updating."
                    )
                row.update(
                    latest=got["tag"],
                    published=got.get("published"),
                    release_url=got.get("url"),
                    kind=kind,
                    reason=reason,
                    patch_safe=bool(got.get("tag") and is_patch_update(tag, got["tag"])),
                    one_click_allowed=bool(kind in ("update", "rebuild") and got.get("tag") and c.get("service")),
                )
        if tag in ("latest", "release", "main"):
            row.update(kind="not_tracked", patch_safe=False, one_click_allowed=False,
                       reason=f"Floating tag '{tag}': the version cannot be known from the tag.")
        row["kind_text"] = KIND_TEXT.get(row["kind"], row["kind"])
        rows.append(row)
    if self_row:
        rows.insert(0, self_row)
    pending = [r for r in rows if r["kind"] in ("rebuild", "update", "major")]
    return {"checked_at": cache.get("checked_at"), "rows": rows, "pending": len(pending),
            "majors": sum(1 for r in pending if r["kind"] == "major"),
            "safe_pending": sum(1 for r in rows if r.get("one_click_allowed"))}


def load_policy(path: Path) -> Dict:
    default = {"auto_patch": False, "last_auto_run": None, "last_auto_summary": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            default["auto_patch"] = bool(data.get("auto_patch", False))
            default["last_auto_run"] = data.get("last_auto_run")
            default["last_auto_summary"] = data.get("last_auto_summary")
    except (OSError, ValueError):
        pass
    return default


def save_policy(path: Path, policy: Dict) -> Dict:
    clean = {
        "auto_patch": bool(policy.get("auto_patch", False)),
        "last_auto_run": policy.get("last_auto_run"),
        "last_auto_summary": policy.get("last_auto_summary"),
    }
    save_cache(path, clean)
    return clean


def blueprint_row(version: str, cache: Dict, repo: str) -> Dict:
    got = (cache.get("repos") or {}).get(repo) or {}
    row = {"container": "control-hub", "project": "homelab-blueprint", "service": None, "image": None,
           "image_name": "Homelab Blueprint (Control Hub and installer)", "current": version, "repo": repo,
           "latest": got.get("tag"), "published": got.get("published"), "release_url": got.get("url"),
           "command": "cd /opt/homelab-blueprint && git pull, then re-run setup (see docs/RELEASING.md)"}
    if got.get("error"):
        row.update(kind="error", reason=got["error"])
    elif got.get("tag"):
        row.update(kind=classify(version, got["tag"]), reason=None)
    else:
        row.update(kind="unknown", reason="Not checked yet")
    row["kind_text"] = KIND_TEXT.get(row["kind"], row["kind"])
    return row


def new_since_notified(rep: Dict, notified: Dict[str, str]) -> List[Dict]:
    """Pending updates whose newest version has not been announced yet (updates `notified`)."""
    fresh = []
    for r in rep["rows"]:
        if r["kind"] in ("rebuild", "update", "major") and r.get("latest"):
            key = r.get("image_name") or r["container"]
            if notified.get(key) != r["latest"]:
                notified[key] = r["latest"]
                fresh.append(r)
    return fresh

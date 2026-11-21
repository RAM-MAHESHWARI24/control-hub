"""
Alerts: watch the server and send a message when something needs attention.

    collectors  ->  conditions (what is wrong right now)  ->  engine  ->  channels

* A collector reads one source (backup status.json, disk usage, docker, CPU
  temperature, the TV updater log, sign-in failures) and returns Condition objects.
* The engine compares them with what was already firing: a new condition fires
  once it has lasted its rule's minimum duration, a firing one is repeated every
  REMIND_HOURS, and one that clears sends "Resolved".
* During quiet hours only critical alerts go out; the rest wait in a queue that is
  sent as one digest when quiet hours end. An optional daily summary goes out at
  a fixed time.
* Channels: ntfy (default, no account), Telegram, Discord and email (SMTP).

Settings live in alerts.json and state in alerts_state.json under the Control
Hub's state directory (both 0600, owned by the service user). Runs in one daemon
thread with a 60 s tick, well inside the service's CPU and memory limits.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import smtplib
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import requests

TICK_SECONDS = 60
REMIND_HOURS = 24
HISTORY_LIMIT = 100
SEVERITIES = ("critical", "warning", "info")
SECRET_FIELDS = {"ntfy": ["token"], "telegram": ["bot_token"], "discord": ["webhook_url"], "email": ["password"]}
MASK = "********"

DEFAULT_CONFIG: Dict = {
    "channels": {
        "ntfy": {"enabled": False, "server": "https://ntfy.sh", "topic": "", "token": ""},
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
        "discord": {"enabled": False, "webhook_url": ""},
        "email": {"enabled": False, "host": "", "port": 587, "starttls": True, "username": "",
                  "password": "", "sender": "", "recipient": ""},
    },
    "rules": {
        "backup_failed": {"enabled": True},
        "backup_stale": {"enabled": True},
        "drive_unreachable": {"enabled": True},
        "restore_test_failed": {"enabled": True},
        "disk_warning": {"enabled": True, "percent": 85},
        "disk_critical": {"enabled": True, "percent": 95},
        "container_down": {"enabled": True, "minutes": 5, "ignore": []},
        "cpu_temp": {"enabled": True, "celsius": 80, "minutes": 2},
        "tv_update_failed": {"enabled": True},
        "signin_failures": {"enabled": True},
    },
    "quiet_hours": {"enabled": True, "start": "23:00", "end": "07:00"},
    "daily_summary": {"enabled": False, "time": "08:00"},
}

RULE_INFO = {
    "backup_failed": ("Backup failed or was interrupted (photos, media settings)", "critical"),
    "backup_stale": ("No good backup for more than 26 hours (photos, media settings)", "warning"),
    "drive_unreachable": ("Backup remote not reachable (Drive login expired or remote renamed)", "critical"),
    "restore_test_failed": ("Photo backup restore test failed", "critical"),
    "disk_warning": ("Disk filling up", "warning"),
    "disk_critical": ("Disk almost full", "critical"),
    "container_down": ("App stopped or unhealthy", "warning"),
    "cpu_temp": ("CPU temperature high", "warning"),
    "tv_update_failed": ("TV app update failed", "warning"),
    "signin_failures": ("Too many failed dashboard sign-ins", "warning"),
}


@dataclass
class Condition:
    key: str            # stable id, e.g. "disk_critical:/mnt/hdd"
    rule: str           # rule name in config["rules"]
    severity: str
    title: str
    message: str
    min_seconds: int = 0  # must hold this long before firing
    event: bool = False   # one-off (log line): sent once, never "resolved"


@dataclass
class Outgoing:
    severity: str
    title: str
    message: str
    resolved: bool = False
    tags: List[str] = field(default_factory=list)


# ---------------------------------------------------------------- config

def _merge(defaults, value):
    """Stored values over defaults; keys the defaults do not know are dropped."""
    if isinstance(defaults, dict) and isinstance(value, dict):
        return {k: _merge(v, value.get(k, v)) for k, v in defaults.items()}
    return value if value is not None else defaults


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return copy.deepcopy(default)


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def load_config(path: Path) -> Dict:
    return _merge(DEFAULT_CONFIG, load_json(path, {}))


def masked(config: Dict) -> Dict:
    """Config for the browser: secrets replaced by MASK (empty stays empty)."""
    out = copy.deepcopy(config)
    for channel, fields in SECRET_FIELDS.items():
        for f in fields:
            if out["channels"][channel].get(f):
                out["channels"][channel][f] = MASK
    return out


def _hhmm(value: str) -> str:
    h, m = str(value).split(":")
    h, m = int(h), int(m)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"invalid time {value!r}")
    return f"{h:02d}:{m:02d}"


def apply_update(current: Dict, update: Dict) -> Dict:
    """Validates an update from the browser. MASK keeps the stored secret."""
    new = _merge(DEFAULT_CONFIG, copy.deepcopy(current))
    for channel, fields in (update.get("channels") or {}).items():
        if channel not in new["channels"] or not isinstance(fields, dict):
            continue
        for key, value in fields.items():
            if key not in new["channels"][channel]:
                continue
            if value == MASK:
                continue
            default = DEFAULT_CONFIG["channels"][channel][key]
            if isinstance(default, bool):
                value = bool(value)
            elif isinstance(default, int):
                value = int(value)
            else:
                value = str(value).strip()
            new["channels"][channel][key] = value
    for rule, fields in (update.get("rules") or {}).items():
        if rule not in new["rules"] or not isinstance(fields, dict):
            continue
        for key, value in fields.items():
            if key == "enabled":
                new["rules"][rule]["enabled"] = bool(value)
            elif key == "ignore" and isinstance(value, list):
                new["rules"][rule]["ignore"] = [str(v).strip() for v in value if str(v).strip()]
            elif key in new["rules"][rule]:
                number = float(value)
                if number <= 0:
                    raise ValueError(f"{rule}.{key} must be positive")
                if key == "percent" and number >= 100:
                    raise ValueError(f"{rule}.percent must be below 100")
                new["rules"][rule][key] = int(number) if float(number).is_integer() else number
    for block in ("quiet_hours", "daily_summary"):
        for key, value in (update.get(block) or {}).items():
            if key == "enabled":
                new[block]["enabled"] = bool(value)
            elif key in ("start", "end", "time") and key in new[block]:
                new[block][key] = _hhmm(value)
    ntfy = new["channels"]["ntfy"]
    if ntfy["enabled"] and not ntfy["topic"]:
        raise ValueError("ntfy needs a topic")
    if ntfy["topic"] and (len(ntfy["topic"]) < 12 or not ntfy["topic"].replace("-", "").replace("_", "").isalnum()):
        raise ValueError("ntfy topic: at least 12 letters, digits, - or _ (anyone who knows it can read the alerts)")
    return new


# ---------------------------------------------------------------- channels

PRIORITY = {"critical": "5", "warning": "4", "info": "3"}
TAGS = {"critical": "rotating_light", "warning": "warning", "info": "information_source"}


def send_ntfy(cfg: Dict, msg: Outgoing, timeout: int = 10) -> Tuple[bool, str]:
    url = f"{cfg['server'].rstrip('/')}/{cfg['topic']}"
    headers = {"Title": msg.title.encode("utf-8").decode("latin-1", "replace"),
               "Priority": "2" if msg.resolved else PRIORITY.get(msg.severity, "3"),
               "Tags": "white_check_mark" if msg.resolved else TAGS.get(msg.severity, "bell")}
    if cfg.get("token"):
        headers["Authorization"] = f"Bearer {cfg['token']}"
    r = requests.post(url, data=msg.message.encode("utf-8"), headers=headers, timeout=timeout)
    return r.ok, "" if r.ok else f"HTTP {r.status_code}: {r.text[:120]}"


def send_telegram(cfg: Dict, msg: Outgoing, timeout: int = 10) -> Tuple[bool, str]:
    r = requests.post(f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage",
                      json={"chat_id": cfg["chat_id"], "text": f"{msg.title}\n{msg.message}"}, timeout=timeout)
    return r.ok, "" if r.ok else f"HTTP {r.status_code}: {r.text[:120]}"


def send_discord(cfg: Dict, msg: Outgoing, timeout: int = 10) -> Tuple[bool, str]:
    r = requests.post(cfg["webhook_url"], json={"content": f"**{msg.title}**\n{msg.message}"[:1900]}, timeout=timeout)
    return r.ok, "" if r.ok else f"HTTP {r.status_code}: {r.text[:120]}"


def send_email(cfg: Dict, msg: Outgoing, timeout: int = 15) -> Tuple[bool, str]:
    em = EmailMessage()
    em["Subject"] = msg.title
    em["From"] = cfg["sender"] or cfg["username"]
    em["To"] = cfg["recipient"]
    em.set_content(msg.message)
    with smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=timeout) as smtp:
        if cfg.get("starttls", True):
            smtp.starttls()
        if cfg.get("username"):
            smtp.login(cfg["username"], cfg["password"])
        smtp.send_message(em)
    return True, ""


SENDERS: Dict[str, Callable[[Dict, Outgoing], Tuple[bool, str]]] = {
    "ntfy": send_ntfy, "telegram": send_telegram, "discord": send_discord, "email": send_email,
}

REQUIRED = {"ntfy": ["server", "topic"], "telegram": ["bot_token", "chat_id"], "discord": ["webhook_url"],
            "email": ["host", "port", "recipient"]}


def channel_ready(name: str, cfg: Dict) -> bool:
    return all(cfg.get(f) for f in REQUIRED[name])


def deliver(config: Dict, msg: Outgoing, only: Optional[str] = None, senders=None) -> Dict[str, str]:
    """Sends to every enabled channel (or just `only`). Returns {channel: "" or error}."""
    senders = senders or SENDERS
    results = {}
    for name, cfg in config["channels"].items():
        if only and name != only:
            continue
        if not only and not cfg.get("enabled"):
            continue
        if not channel_ready(name, cfg):
            results[name] = "not configured"
            continue
        try:
            ok, err = senders[name](cfg, msg)
            results[name] = "" if ok else (err or "failed")
        except Exception as exc:  # network, SMTP, DNS...
            results[name] = str(exc)[:200]
    return results


# ---------------------------------------------------------------- engine

def in_quiet_hours(config: Dict, now: datetime) -> bool:
    q = config["quiet_hours"]
    if not q.get("enabled"):
        return False
    start, end, cur = q["start"], q["end"], now.strftime("%H:%M")
    return (start <= cur < end) if start < end else (cur >= start or cur < end)


def evaluate(config: Dict, state: Dict, conditions: List[Condition], now: datetime) -> List[Outgoing]:
    """
    Updates `state` in place and returns the messages to send now. Pure: no I/O.
    state keys: pending {key: first_seen}, firing {key: {...}}, queue [..], history [..]
    """
    ts = now.timestamp()
    pending = state.setdefault("pending", {})
    firing = state.setdefault("firing", {})
    queue = state.setdefault("queue", [])
    history = state.setdefault("history", [])
    quiet = in_quiet_hours(config, now)
    # With no channel switched on nothing can be delivered: alerts are still listed in the
    # dashboard, and the open ones are sent as soon as a channel is turned on.
    can_send = any(ch.get("enabled") for ch in config["channels"].values())
    out: List[Outgoing] = []

    def emit(msg: Outgoing, key: str):
        history.insert(0, {"at": now.isoformat(timespec="seconds"), "key": key, "severity": msg.severity,
                           "title": msg.title, "message": msg.message, "resolved": msg.resolved,
                           "queued": can_send and quiet and msg.severity != "critical", "unsent": not can_send})
        del history[HISTORY_LIMIT:]
        if not can_send:
            return
        if quiet and msg.severity != "critical":
            queue.append({"severity": msg.severity, "title": msg.title, "message": msg.message,
                          "resolved": msg.resolved, "at": now.strftime("%H:%M")})
        else:
            out.append(msg)

    active = {}
    for c in conditions:
        if config["rules"].get(c.rule, {}).get("enabled", True):
            active[c.key] = c

    for key, c in active.items():
        if c.event:
            emit(Outgoing(c.severity, c.title, c.message), key)
            continue
        first = pending.setdefault(key, ts)
        if key in firing:
            f = firing[key]
            f["message"] = c.message
            if f.get("unsent") and can_send:
                f["unsent"] = False
                f["last_sent"] = ts
                emit(Outgoing(c.severity, c.title, c.message), key)
            elif ts - f["last_sent"] >= REMIND_HOURS * 3600:
                f["last_sent"] = ts
                emit(Outgoing(c.severity, f"Still: {c.title}", c.message), key)
        elif ts - first >= c.min_seconds:
            firing[key] = {"since": ts, "last_sent": ts, "title": c.title, "message": c.message,
                           "severity": c.severity, "rule": c.rule, "unsent": not can_send}
            emit(Outgoing(c.severity, c.title, c.message), key)

    for key in [k for k in pending if k not in active]:
        del pending[key]
    for key in [k for k in firing if k not in active]:
        f = firing.pop(key)
        emit(Outgoing("info", f"Resolved: {f['title']}", f"{f['message']}\nCleared at {now.strftime('%H:%M')}.", resolved=True), key)

    # Quiet hours over: send what waited, as one message.
    if not quiet and queue:
        lines = [f"{q['at']}  {'OK ' if q['resolved'] else ''}{q['title']}: {q['message'].splitlines()[0]}" for q in queue]
        worst = "warning" if any(q["severity"] == "warning" and not q["resolved"] for q in queue) else "info"
        out.append(Outgoing(worst, f"Overnight: {len(queue)} alert(s)", "\n".join(lines)))
        queue.clear()

    # Optional daily summary at a fixed time (once per day).
    summary = config["daily_summary"]
    today = now.strftime("%Y-%m-%d")
    if summary.get("enabled") and now.strftime("%H:%M") >= summary["time"] and state.get("summary_sent") != today:
        state["summary_sent"] = today
        body = "\n".join(f"- {f['title']}: {f['message'].splitlines()[0]}" for f in firing.values()) or "Nothing needs attention."
        out.append(Outgoing("info", f"Daily summary: {len(firing)} open alert(s)", body))
    return out


# ---------------------------------------------------------------- collectors

BACKUP_LABELS = {"photo": "Photo backup", "media": "Media settings backup"}


def collect_backup(status: Optional[Dict], summary: Optional[Dict], what: str = "photo") -> List[Condition]:
    """Alerts for one backup job; `what` names it in the message ("photo" keeps the original keys)."""
    if not status or not summary:
        return []
    label = BACKUP_LABELS.get(what, f"{what.capitalize()} backup")
    suffix = "" if what == "photo" else f":{what}"
    out = []
    pre = status.get("preflight") or {}
    remote_failed = any(c.get("name") == "remote" and not c.get("ok") for c in pre.get("checks") or [])
    title, sev = RULE_INFO["drive_unreachable"]
    if summary["state"] == "error" and remote_failed:
        out.append(Condition(f"drive_unreachable{suffix}", "drive_unreachable", sev, f"{label}: {title}", summary["message"]))
    elif summary["state"] in ("error", "interrupted"):
        out.append(Condition(f"backup_failed{suffix}", "backup_failed", "critical",
                             f"{label} failed or was interrupted", summary["message"]))
    if summary.get("stale"):
        out.append(Condition(f"backup_stale{suffix}", "backup_stale", "warning",
                             f"{label}: no good run for more than {int(summary.get('stale_after_hours') or 26)} hours",
                             f"Last good run: {summary.get('last_good') or 'never'} ({summary.get('age') or 'unknown'})."))
    return out


def collect_restore_test(status: Optional[Dict]) -> List[Condition]:
    """The last monthly restore test failed: the newest remote dump may not be restorable."""
    test = (status or {}).get("restore_test")
    if not isinstance(test, dict) or test.get("ok") is not False:
        return []
    title, sev = RULE_INFO["restore_test_failed"]
    return [Condition("restore_test", "restore_test_failed", sev, title, test.get("message") or "See the restore test log.")]


def collect_disks(config: Dict, mounts: List[str], usage=shutil.disk_usage) -> List[Condition]:
    out = []
    warn = config["rules"]["disk_warning"]["percent"]
    crit = config["rules"]["disk_critical"]["percent"]
    seen = set()
    for mount in mounts:
        try:
            u = usage(mount)
        except OSError:
            continue
        ident = (u.total, u.used)
        if ident in seen:
            continue
        seen.add(ident)
        pct = round(u.used / u.total * 100, 1) if u.total else 0
        free_gb = round(u.free / 1024**3, 1)
        if pct >= crit:
            t, s = RULE_INFO["disk_critical"]
            out.append(Condition(f"disk_critical:{mount}", "disk_critical", s, f"{t}: {mount}", f"{mount} is {pct}% full ({free_gb} GB free)."))
        elif pct >= warn:
            t, s = RULE_INFO["disk_warning"]
            out.append(Condition(f"disk_warning:{mount}", "disk_warning", s, f"{t}: {mount}", f"{mount} is {pct}% full ({free_gb} GB free)."))
    return out


def collect_containers(config: Dict, containers: List[Dict], catalog: Dict) -> List[Condition]:
    rule = config["rules"]["container_down"]
    ignore = set(rule.get("ignore") or [])
    title, sev = RULE_INFO["container_down"]
    out = []
    for c in containers:
        name = (c.get("Names") or "").strip()
        if name not in catalog or name in ignore:
            continue
        state, status = c.get("State", ""), c.get("Status", "")
        if state != "running" or "(unhealthy)" in status:
            label = catalog[name].get("name", name)
            why = "unhealthy" if state == "running" else (state or "stopped")
            out.append(Condition(f"container:{name}", "container_down", sev, f"{title}: {label}",
                                 f"{label} ({name}) is {why}: {status or 'no status'}.", min_seconds=int(rule["minutes"] * 60)))
    return out


def collect_cpu_temp(config: Dict, temp_c: Optional[float]) -> List[Condition]:
    rule = config["rules"]["cpu_temp"]
    if temp_c is None or temp_c < rule["celsius"]:
        return []
    title, sev = RULE_INFO["cpu_temp"]
    return [Condition("cpu_temp", "cpu_temp", sev, title, f"CPU at {temp_c} °C (limit {rule['celsius']} °C).",
                      min_seconds=int(rule["minutes"] * 60))]


def collect_tv_errors(log_path: str, state: Dict) -> List[Condition]:
    """New `[ERROR]` lines in the TV updater log since the last tick (one event per tick)."""
    try:
        st = os.stat(log_path)
    except OSError:
        return []
    mark = state.setdefault("tv_log", {})
    if mark.get("ino") != st.st_ino or mark.get("offset", 0) > st.st_size:
        mark.update(ino=st.st_ino, offset=st.st_size)  # first sight or rotated: start from the end
        return []
    with open(log_path, "rb") as fh:
        fh.seek(mark["offset"])
        chunk = fh.read(min(st.st_size - mark["offset"], 256 * 1024)).decode("utf-8", "replace")
    mark["offset"] = st.st_size
    errors = [ln.split("[ERROR]", 1)[1].strip() for ln in chunk.splitlines() if "[ERROR]" in ln]
    if not errors:
        return []
    title, sev = RULE_INFO["tv_update_failed"]
    more = f"\n(+{len(errors) - 3} more in the TV log)" if len(errors) > 3 else ""
    return [Condition(f"tv_error:{int(time.time())}", "tv_update_failed", sev, title, "\n".join(errors[:3]) + more, event=True)]


def collect_signins(failures: Dict[str, int], limit: int) -> List[Condition]:
    title, sev = RULE_INFO["signin_failures"]
    return [Condition(f"signin:{ip}", "signin_failures", sev, title,
                      f"{count} failed sign-ins from {ip} in the last 5 minutes; that address is locked out for now.")
            for ip, count in failures.items() if count >= limit]


def read_cpu_temp() -> Optional[float]:
    for zone in ("/sys/class/thermal/thermal_zone0/temp", "/sys/class/thermal/thermal_zone1/temp"):
        try:
            raw = int(Path(zone).read_text().strip())
            if raw > 1000:
                return round(raw / 1000.0, 1)
        except (OSError, ValueError):
            continue
    return None


def docker_containers() -> Optional[List[Dict]]:
    try:
        proc = subprocess.run(["docker", "ps", "-a", "--format", "{{json .}}"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    rows = []
    for line in proc.stdout.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


class AlertEngine:
    """Owns config/state files and the background thread."""

    def __init__(self, config_path: Path, state_path: Path, collect: Callable[["AlertEngine", Dict], List[Condition]]):
        self.config_path = config_path
        self.state_path = state_path
        self.collect = collect
        self.lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None
        self.last_tick: Optional[float] = None
        self.last_results: Dict[str, str] = {}

    def config(self) -> Dict:
        return load_config(self.config_path)

    def state(self) -> Dict:
        return load_json(self.state_path, {})

    def save_config(self, config: Dict) -> None:
        with self.lock:
            save_json(self.config_path, config)

    def tick(self, now: Optional[datetime] = None) -> List[Outgoing]:
        now = now or datetime.now().astimezone()
        config = self.config()
        with self.lock:
            state = self.state()
            try:
                conditions = self.collect(self, state)
            except Exception as exc:  # a broken collector must not stop the others next time
                conditions = []
                state["collector_error"] = str(exc)[:200]
            outgoing = evaluate(config, state, conditions, now)
            channels = state.setdefault("channels", {})
            for msg in outgoing:
                for name, err in deliver(config, msg).items():
                    channels[name] = {"at": now.isoformat(timespec="seconds"), "error": err}
            save_json(self.state_path, state)
        self.last_tick = time.time()
        return outgoing

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return

        def loop():
            time.sleep(30)  # let the rest of the hub start first
            while True:
                try:
                    self.tick()
                except Exception:
                    pass
                time.sleep(TICK_SECONDS)

        self.thread = threading.Thread(target=loop, name="alerts", daemon=True)
        self.thread.start()


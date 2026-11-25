"""
Widget: Indexer picker (Prowlarr)

Lets the operator choose indexers from Prowlarr's own definition list after
install. The blueprint ships no tracker list and pre-selects nothing: the
list comes live from the user's Prowlarr, and the user's picks are added
through Prowlarr's API. Which indexers to use, and whether they are lawful
where the server runs, is the operator's responsibility.

Routes (bearer-protected like the rest of /api):
  GET  /api/indexers/status      installed? reachable? how many configured?
  GET  /api/indexers/available   Prowlarr's definition list (name, protocol, privacy, fields)
  POST /api/indexers/add         {"indexers": [{"name": ..., "fields": {...}}], "force": false}

The Prowlarr API key is read from PROWLARR_API_KEY or the key file the
installer writes (/etc/homelab/prowlarr.key, 0640 root:homelab). When neither
exists the module reports installed=false and the dashboard hides the picker.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request

from config import PROWLARR_KEY_FILE, PROWLARR_URL

indexers_bp = Blueprint("indexers", __name__)

# Field types a person has to fill in for a private tracker (schema fields with an empty value).
CREDENTIAL_FIELD_TYPES = {"textbox", "password"}
# Never shown in the picker, whatever the schema says.
HIDDEN_FIELD_NAMES = {"definitionFile", "baseUrl", "baseSettings.limitsUnit"}


def _api_key() -> str:
    key = (os.getenv("PROWLARR_API_KEY") or "").strip()
    if key:
        return key
    try:
        return Path(PROWLARR_KEY_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _call(path: str, method: str = "GET", data: Any = None, timeout: int = 20) -> Tuple[int, Any]:
    key = _api_key()
    url = f"{PROWLARR_URL.rstrip('/')}/api/v1/{path.lstrip('/')}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={"X-Api-Key": key, "Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(text)
        except json.JSONDecodeError:
            return e.code, {"message": text[:400]}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, {"message": str(e)}


def _credential_fields(schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fields the user must supply: visible text/password inputs with no default."""
    out = []
    for f in schema.get("fields", []) or []:
        name = f.get("name", "")
        if name in HIDDEN_FIELD_NAMES or f.get("hidden") or f.get("advanced"):
            continue
        if f.get("type") not in CREDENTIAL_FIELD_TYPES:
            continue
        if f.get("value") not in (None, ""):
            continue
        out.append({"name": name, "label": f.get("label") or name, "type": f.get("type"), "help": f.get("helpText") or ""})
    return out


def _slim(schema: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": schema.get("name"),
        "definition": schema.get("definitionName") or schema.get("implementationName") or schema.get("implementation"),
        "protocol": schema.get("protocol"),
        "privacy": schema.get("privacy"),
        "language": schema.get("language"),
        "description": (schema.get("description") or "")[:160],
        "fields": _credential_fields(schema),
    }


def _configured_names() -> Optional[List[str]]:
    st, existing = _call("indexer")
    if st != 200 or not isinstance(existing, list):
        return None
    return [i.get("name", "") for i in existing]


@indexers_bp.route("/api/indexers/status", methods=["GET"])
def indexers_status():
    key = _api_key()
    if not key:
        return jsonify({"status": "ok", "installed": False, "reachable": False, "configured": 0, "configured_names": []})
    names = _configured_names()
    return jsonify({
        "status": "ok",
        "installed": True,
        "reachable": names is not None,
        "configured": len(names or []),
        "configured_names": names or [],
        "prowlarr_url": PROWLARR_URL,
    })


@indexers_bp.route("/api/indexers/available", methods=["GET"])
def indexers_available():
    if not _api_key():
        return jsonify({"status": "error", "error": "indexer module not installed (no Prowlarr API key)"}), 404
    st, schemas = _call("indexer/schema", timeout=60)
    if st != 200 or not isinstance(schemas, list):
        return jsonify({"status": "error", "error": f"Prowlarr schema request failed (HTTP {st})", "detail": schemas}), 502
    configured = set(_configured_names() or [])
    items = [_slim(s) for s in schemas if s.get("name")]
    items.sort(key=lambda i: (i["privacy"] != "public", (i["name"] or "").lower()))
    return jsonify({"status": "ok", "count": len(items), "configured": sorted(configured), "indexers": items})


@indexers_bp.route("/api/indexers/add", methods=["POST"])
def indexers_add():
    if not _api_key():
        return jsonify({"status": "error", "error": "indexer module not installed (no Prowlarr API key)"}), 404
    payload = request.get_json(silent=True) or {}
    wanted = payload.get("indexers") or []
    force = bool(payload.get("force", False))
    if not isinstance(wanted, list) or not wanted:
        return jsonify({"status": "error", "error": "body must be {\"indexers\": [{\"name\": ..., \"fields\": {...}}]}"}), 400

    st, schemas = _call("indexer/schema", timeout=60)
    if st != 200 or not isinstance(schemas, list):
        return jsonify({"status": "error", "error": f"Prowlarr schema request failed (HTTP {st})"}), 502
    by_name = {s.get("name"): s for s in schemas if s.get("name")}
    configured = set(_configured_names() or [])

    results = []
    for item in wanted[:50]:
        name = str(item.get("name", "")).strip() if isinstance(item, dict) else ""
        values = item.get("fields") or {} if isinstance(item, dict) else {}
        if not name or name not in by_name:
            results.append({"name": name, "ok": False, "detail": "unknown indexer"})
            continue
        if name in configured:
            results.append({"name": name, "ok": True, "detail": "already configured"})
            continue
        schema = json.loads(json.dumps(by_name[name]))  # deep copy
        schema.update({"name": name, "enable": True, "priority": schema.get("priority") or 25, "tags": schema.get("tags") or []})
        schema.setdefault("appProfileId", 1)
        for f in schema.get("fields", []) or []:
            if f.get("name") in values:
                f["value"] = values[f["name"]]
        path = "indexer?forceSave=true" if force else "indexer"
        st, resp = _call(path, "POST", schema, timeout=90)
        if st in (200, 201):
            results.append({"name": name, "ok": True, "detail": "added"})
            configured.add(name)
        else:
            detail = resp
            if isinstance(resp, list) and resp and isinstance(resp[0], dict):
                detail = "; ".join(str(r.get("errorMessage") or r) for r in resp)
            elif isinstance(resp, dict):
                detail = resp.get("message") or resp.get("errorMessage") or json.dumps(resp)[:300]
            results.append({"name": name, "ok": False, "detail": f"HTTP {st}: {str(detail)[:300]}"})

    added = sum(1 for r in results if r["ok"] and r["detail"] == "added")
    return jsonify({"status": "ok", "added": added, "configured": len(configured), "results": results})


def _indexer_fix_hint(disabled_till: Optional[str], enabled: bool) -> Optional[str]:
    if not enabled:
        return "Disabled in Prowlarr; re-enable or test connectivity."
    if disabled_till:
        return "Blocked or failing challenge check; ensure Byparr solver / proxy tag is attached, then click Test All."
    return None


@indexers_bp.route("/api/indexers/health", methods=["GET"])
def indexers_health():
    """Returns health, recent failure status, and fix hints for every configured Prowlarr indexer."""
    if not _api_key():
        return jsonify({"status": "ok", "installed": False, "reachable": False, "indexers": []})

    st_list, indexers = _call("indexer")
    if st_list != 200 or not isinstance(indexers, list):
        return jsonify({"status": "ok", "installed": True, "reachable": False, "indexers": []})

    st_stat, statuses = _call("indexerstatus")
    status_by_id = {}
    if st_stat == 200 and isinstance(statuses, list):
        for s in statuses:
            if isinstance(s, dict) and s.get("indexerId") is not None:
                status_by_id[s["indexerId"]] = s

    rows = []
    failing = 0
    for ix in indexers:
        if not isinstance(ix, dict):
            continue
        iid = ix.get("id")
        st_info = status_by_id.get(iid) or {}
        disabled_till = st_info.get("disabledTill")
        most_recent = st_info.get("mostRecentFailure")
        enabled = bool(ix.get("enable", True))
        healthy = enabled and not disabled_till and not most_recent
        if not healthy:
            failing += 1
        rows.append({
            "id": iid,
            "name": ix.get("name") or "Unknown",
            "protocol": ix.get("protocol") or "",
            "privacy": ix.get("privacy") or "",
            "enabled": enabled,
            "healthy": healthy,
            "disabled_till": disabled_till,
            "last_failure": most_recent,
            "fix_hint": _indexer_fix_hint(disabled_till, enabled) if not healthy else None,
        })
    rows.sort(key=lambda r: (r["healthy"], (r["name"] or "").lower()))
    return jsonify({
        "status": "ok",
        "installed": True,
        "reachable": True,
        "total": len(rows),
        "failing": failing,
        "indexers": rows,
    })


@indexers_bp.route("/api/indexers/test-all", methods=["POST"])
def indexers_test_all():
    """Runs Prowlarr's connectivity test across all configured indexers."""
    if not _api_key():
        return jsonify({"status": "error", "error": "indexer module not installed"}), 404
    st, resp = _call("indexer/testall", method="POST", data={}, timeout=90)
    if st not in (200, 201, 204):
        return jsonify({"status": "error", "error": f"Prowlarr testall failed (HTTP {st})"}), 502
    results = []
    if isinstance(resp, list):
        for r in resp:
            if isinstance(r, dict):
                results.append({
                    "id": r.get("id"),
                    "ok": bool(r.get("isValid", True)),
                    "failures": [str(f.get("errorMessage") or f) for f in (r.get("validationFailures") or [])][:3],
                })
    return jsonify({"status": "ok", "results": results})

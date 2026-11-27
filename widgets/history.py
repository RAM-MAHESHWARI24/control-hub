"""
Widget: Telemetry History & Monthly Insights (Phase 4C)
Exposes 24h / 7d / 30d hardware telemetry curves, monthly availability/backup/space report,
and Sleep Guard kWh / CO2 savings estimates.
"""

from flask import Blueprint, jsonify, request

from core.metrics_history import compute_monthly_insights, query_history

history_bp = Blueprint("history", __name__)


@history_bp.route("/api/history", methods=["GET"])
def api_get_history():
    """Returns time-series telemetry points and stats for range=24h|7d|30d."""
    range_key = (request.args.get("range") or "24h").strip().lower()
    if range_key not in ("24h", "7d", "30d"):
        range_key = "24h"
    return jsonify(query_history(range_key))


@history_bp.route("/api/insights/monthly", methods=["GET"])
def api_get_monthly_insights():
    """Returns 30-day uptime/backup/update/storage summary and Sleep Guard power savings."""
    return jsonify(compute_monthly_insights())

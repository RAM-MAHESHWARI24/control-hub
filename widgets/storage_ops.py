"""
Widget: Server Read/Write Operations (Disk Throughput & Media Streams)
Provides endpoints for real-time disk read/write throughput in MB/s and Mbps,
active SMB client connections, and active Jellyfin video playback streams.
"""

from flask import Blueprint, jsonify
from core.telemetry_sampler import telemetry_lock, telemetry_state

storage_ops_bp = Blueprint("storage_ops", __name__)

@storage_ops_bp.route("/api/storage/operations", methods=["GET"])
def get_storage_operations():
    """Returns real-time disk read/write throughput, SMB shares, and Jellyfin streams"""
    with telemetry_lock:
        return jsonify(telemetry_state["storage_ops"])

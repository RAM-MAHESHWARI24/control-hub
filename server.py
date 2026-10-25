#!/usr/bin/env python3
"""
ServerFF Control Hub - Modular Backend API Daemon
High-Performance Dashboard Engine for serverff (Ubuntu 26.04 / Haswell i3-4005U)
"""

from flask import Flask, send_from_directory

from config import HOST, PORT
from core.telemetry_sampler import start_telemetry_sampler

# Import all visual widget blueprints
from widgets.sleep_guard import sleep_guard_bp
from widgets.network_speed import network_speed_bp
from widgets.current_downloads import current_downloads_bp
from widgets.backup_sync import backup_sync_bp
from widgets.system_vitals import system_vitals_bp
from widgets.storage_ops import storage_ops_bp
from widgets.cron_tasks import cron_tasks_bp
from widgets.service_matrix import service_matrix_bp
from widgets.tv_updater import tv_updater_bp
from widgets.config_center import config_center_bp


def create_app():
    """Application factory registering all modular widget blueprints"""
    app = Flask(__name__, static_folder="static")

    # Root & static proxy routes
    @app.route("/")
    def index():
        return send_from_directory("static", "index.html")

    @app.route("/<path:path>")
    def static_proxy(path):
        return send_from_directory("static", path)

    # Register all modular widget blueprints
    app.register_blueprint(sleep_guard_bp)
    app.register_blueprint(network_speed_bp)
    app.register_blueprint(current_downloads_bp)
    app.register_blueprint(backup_sync_bp)
    app.register_blueprint(system_vitals_bp)
    app.register_blueprint(storage_ops_bp)
    app.register_blueprint(cron_tasks_bp)
    app.register_blueprint(service_matrix_bp)
    app.register_blueprint(tv_updater_bp)
    app.register_blueprint(config_center_bp)

    return app


app = create_app()

if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Launch real-time background telemetry sampler
    start_telemetry_sampler()

    try:
        print(f"🚀 ServerFF Control Hub listening on http://{HOST}:{PORT}")
    except UnicodeEncodeError:
        print(f"[+] ServerFF Control Hub listening on http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)

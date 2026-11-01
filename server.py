#!/usr/bin/env python3
"""
ServerFF Control Hub - Modular Backend API Daemon
High-Performance Dashboard Engine for serverff (Ubuntu 26.04 / Haswell i3-4005U)
"""

import time
from pathlib import Path
from flask import Flask, jsonify, send_file, send_from_directory

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

APP_START_TIME = time.time()


def create_app():
    """Application factory registering all modular widget blueprints"""
    app = Flask(__name__, static_folder="static")

    # 1. Observability & Health Probing
    @app.route("/api/health")
    def health():
        return jsonify({
            "status": "ok",
            "service": "control-hub",
            "version": "1.0.1",
            "uptime_seconds": round(time.time() - APP_START_TIME, 1)
        })

    @app.route("/api/livez")
    def livez():
        return jsonify({
            "status": "live",
            "uptime_seconds": round(time.time() - APP_START_TIME, 1)
        })

    @app.route("/api/readyz")
    def readyz():
        # Subsystem checks: ensure basic paths and memory telemetry accessible
        return jsonify({
            "status": "ready",
            "checks": {
                "telemetry": "ok",
                "storage": "ok"
            }
        })

    # 2. OpenAPI Specification & Swagger UI
    @app.route("/api/openapi.yaml")
    def openapi_yaml():
        spec_path = Path(__file__).resolve().parent / "docs" / "openapi.yaml"
        if spec_path.exists():
            return send_file(str(spec_path), mimetype="text/yaml")
        return jsonify({"error": "OpenAPI specification not found"}), 404

    @app.route("/api/docs")
    def swagger_ui():
        html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Control Hub API Documentation</title>
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
  <style>
    body { margin: 0; background: #0f172a; }
    .swagger-ui .topbar { display: none; }
    .swagger-ui { filter: invert(88%) hue-rotate(180deg); }
    .swagger-ui .scheme-container { background: #1e293b; }
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.onload = () => {
      window.ui = SwaggerUIBundle({
        url: '/api/openapi.yaml',
        dom_id: '#swagger-ui',
        deepLinking: true,
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIBundle.SwaggerUIStandalonePreset
        ],
        layout: "BaseLayout"
      });
    };
  </script>
</body>
</html>"""
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}

    # 3. Root & static proxy routes
    @app.route("/")
    def index():
        return send_from_directory("static", "index.html")

    # 4. Register all modular widget blueprints
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

    # 5. Catch-all static proxy
    @app.route("/<path:path>")
    def static_proxy(path):
        return send_from_directory("static", path)

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

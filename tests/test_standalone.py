"""
Control Hub - Standalone Smoke & Endpoint Verification Suite
Validates that the dashboard microservice functions independently without any monorepo dependencies.
"""

import os
import sys
import unittest
from pathlib import Path

# Add control hub root to sys.path
HUB_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HUB_ROOT))

TEST_TOKEN = "standalone-test-token-0123456789"
os.environ["CONTROL_HUB_TOKEN"] = TEST_TOKEN

from flask.testing import FlaskClient
from server import create_app


class AuthClient(FlaskClient):
    """Sends the bearer token on every request."""

    def open(self, *args, **kwargs):
        headers = dict(kwargs.pop("headers", None) or {})
        headers.setdefault("Authorization", f"Bearer {TEST_TOKEN}")
        kwargs["headers"] = headers
        return super().open(*args, **kwargs)


class TestControlHubStandalone(unittest.TestCase):
    """Smoke tests for independent execution of Control Hub"""

    def setUp(self):
        self.app = create_app()
        self.app.test_client_class = AuthClient
        self.client = self.app.test_client()

    def test_token_required_for_api(self):
        """Protected endpoints answer 401 without a token; health stays public"""
        anon = FlaskClient(self.app)
        self.assertEqual(anon.get("/api/health").status_code, 200)
        self.assertEqual(anon.get("/api/system/vitals").status_code, 401)
        self.assertEqual(anon.get("/api/system/vitals", headers={"Authorization": "Bearer nope"}).status_code, 401)
        self.assertEqual(self.client.get("/api/auth/check").status_code, 200)

    def test_indexer_picker_hidden_without_prowlarr_key(self):
        """The indexer picker reports installed=false (and hides itself) when no Prowlarr key exists"""
        res = self.client.get("/api/indexers/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("installed", data)
        self.assertIsInstance(data["installed"], bool)
        if not data["installed"]:
            self.assertEqual(self.client.get("/api/indexers/available").status_code, 404)

    def test_observability_endpoints(self):
        """Verify /api/health, /api/livez, and /api/readyz probes"""
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("service"), "control-hub")

        res = self.client.get("/api/livez")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json().get("status"), "live")

        res = self.client.get("/api/readyz")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json().get("status"), "ready")

    def test_openapi_contract_and_swagger(self):
        """Verify OpenAPI 3.1 YAML contract and Swagger UI HTML"""
        res = self.client.get("/api/openapi.yaml")
        self.assertEqual(res.status_code, 200)
        yaml_content = res.get_data(as_text=True)
        res.close()
        self.assertIn("openapi: 3.1.0", yaml_content)

        res = self.client.get("/api/docs")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        res.close()
        self.assertIn("SwaggerUIBundle", html)

    def test_system_vitals_telemetry(self):
        """Verify hardware telemetry endpoints function dynamically"""
        res = self.client.get("/api/system/vitals")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("cpu", data)
        self.assertIn("memory", data)
        self.assertIn("storage", data)

    def test_web_dashboard_rendering(self):
        """Verify main HTML HUD interface renders properly"""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        res.close()
        self.assertIn("Control Hub", html)


if __name__ == "__main__":
    unittest.main()


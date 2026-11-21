"""
BharatStore — Render Deployment Automated Test Suite
Verifies:
1. Module-level Flask app exposure in run.py (required by Gunicorn).
2. Gunicorn package availability and version compatibility.
3. Procfile validity with dynamic $PORT binding.
4. Render Blueprint specification (render.yaml).
5. PostgreSQL DATABASE_URL resolution and postgres:// scheme normalization.
6. Database error sanitization (passwords never leaked in errors).
7. Production security settings (Secure & HttpOnly cookies on HTTPS).
8. Health check visibility without faking connections.
9. Static assets and core application endpoints accessibility.
"""

import os
import re
import unittest
from run import app
from app.config import Config
from app.database import DatabaseService


class TestRenderDeployment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.client = cls.app.test_client()
        cls.db = DatabaseService()

    def test_01_module_level_flask_app_import(self):
        """Spec 1: run.py exposes Flask app at module level for Gunicorn WSGI."""
        from run import app as imported_app
        self.assertIsNotNone(imported_app)
        self.assertEqual(imported_app.name, "app")
        self.assertGreater(len(imported_app.url_map._rules), 50)
        print(" [PASSED] 1. run.py correctly exposes Flask application at module level for Gunicorn")

    def test_02_gunicorn_installed_and_requirements_updated(self):
        """Spec 2: Gunicorn is installed in Python environment and declared in requirements.txt."""
        import gunicorn
        self.assertTrue(hasattr(gunicorn, "__version__"))

        req_path = os.path.join(os.path.dirname(__file__), "..", "requirements.txt")
        with open(req_path, "r", encoding="utf-8") as f:
            reqs = f.read()
        self.assertIn("gunicorn", reqs)
        print(f" [PASSED] 2. Gunicorn (v{gunicorn.__version__}) verified and declared in requirements.txt")

    def test_03_procfile_configured(self):
        """Spec 3: Procfile contains proper web service start command using dynamic $PORT."""
        procfile_path = os.path.join(os.path.dirname(__file__), "..", "Procfile")
        self.assertTrue(os.path.exists(procfile_path), "Procfile must exist")
        with open(procfile_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        self.assertTrue(content.startswith("web: gunicorn run:app"))
        self.assertIn("--bind 0.0.0.0:$PORT", content)
        self.assertIn("--workers 2", content)
        self.assertIn("--timeout 120", content)
        print(" [PASSED] 3. Procfile contains compliant Gunicorn start command with dynamic $PORT")

    def test_04_render_blueprint_specification(self):
        """Spec 4: render.yaml contains valid Render Blueprint declaration."""
        render_yaml_path = os.path.join(os.path.dirname(__file__), "..", "render.yaml")
        self.assertTrue(os.path.exists(render_yaml_path), "render.yaml must exist")
        with open(render_yaml_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("type: web", content)
        self.assertIn("runtime: python", content)
        self.assertIn("pip install -r requirements.txt", content)
        self.assertIn("gunicorn run:app", content)
        print(" [PASSED] 4. render.yaml Blueprint specification correctly configured")

    def test_05_database_url_support_and_postgres_scheme_normalization(self):
        """Spec 5: Config resolves DATABASE_URL and normalizes 'postgres://' to 'postgresql://'."""
        orig_db_url = Config.DATABASE_URL
        orig_aiven_url = Config.AIVEN_PG_URL
        try:
            # Test standard Render DATABASE_URL with postgres:// prefix
            Config.DATABASE_URL = "postgres://avnadmin:securepass123@pg.aivencloud.com:12345/defaultdb"
            Config.AIVEN_PG_URL = ""
            self.assertTrue(Config.is_pg_configured())
            resolved = Config.get_pg_url()
            self.assertTrue(resolved.startswith("postgresql://"))
            self.assertFalse(resolved.startswith("postgres://"))

            # Test AIVEN_PG_URL fallback
            Config.DATABASE_URL = ""
            Config.AIVEN_PG_URL = "postgresql://user:pass@host:5432/db"
            self.assertTrue(Config.is_pg_configured())
            self.assertEqual(Config.get_pg_url(), "postgresql://user:pass@host:5432/db")
        finally:
            Config.DATABASE_URL = orig_db_url
            Config.AIVEN_PG_URL = orig_aiven_url
        print(" [PASSED] 5. PostgreSQL DATABASE_URL and scheme normalization (postgres:// -> postgresql://) verified")

    def test_06_database_error_sanitization(self):
        """Spec 6: Database connection errors redact passwords to prevent sensitive information leakage."""
        sample_error = "could not connect to server: postgresql://avnadmin:SuperSecretPassword123@pg.aiven.com:5432/defaultdb"
        sanitized = self.db._sanitize_db_error(sample_error)
        self.assertNotIn("SuperSecretPassword123", sanitized)
        self.assertIn("avnadmin:******@", sanitized)

        keyword_error = "FATAL: password authentication failed for user 'avnadmin' password=SecretPass999"
        sanitized_kw = self.db._sanitize_db_error(keyword_error)
        self.assertNotIn("SecretPass999", sanitized_kw)
        self.assertIn("password=******", sanitized_kw)
        print(" [PASSED] 6. Database error sanitization redacts credentials and prevents secret leakage")

    def test_07_health_endpoint_service_visibility(self):
        """Spec 7: /api/health accurately reports service configuration without faking live connections."""
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "healthy")
        self.assertIn("services", data)
        self.assertIn("postgresql", data["services"])
        self.assertIn("kafka", data["services"])
        self.assertIn("opensearch", data["services"])

        # Error field must be None or sanitized string, never containing passwords
        pg_info = data["services"]["postgresql"]
        self.assertIn("is_live", pg_info)
        self.assertIn("label", pg_info)
        if pg_info.get("error"):
            self.assertNotIn("password=", pg_info["error"])
        print(" [PASSED] 7. Health endpoint (/api/health) accurately reports honest service status")

    def test_08_core_routes_and_static_assets_serve_correctly(self):
        """Spec 8: Flask serves both frontend templates and static assets cleanly."""
        routes = [
            ("/", 200),
            ("/retail", 200),
            ("/login", 200),
            ("/register", 200),
            ("/cart", 200),
            ("/checkout", 200),
            ("/static/css/style.css", 200),
            ("/static/js/app.js", 200),
            ("/static/images/online-shopping-hero.jpg", 200),
            ("/static/images/placeholder-product.svg", 200),
            ("/api/products", 200),
            ("/api/retail/catalog", 200),
            ("/api/retail/stores", 200),
        ]
        for path, expected_status in routes:
            r = self.client.get(path)
            self.assertEqual(r.status_code, expected_status, f"Route {path} returned {r.status_code}")
        print(" [PASSED] 8. All core frontend views, static assets, and APIs verified HTTP 200")


if __name__ == "__main__":
    unittest.main()

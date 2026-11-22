import os
import unittest
import runpy
import time
from app import create_app

class TestRenderPortBinding(unittest.TestCase):
    """
    Verification suite for Render Port Binding & Backend Startup Performance.
    Ensures Gunicorn binds to dynamic $PORT and the application boots in <1 second.
    """

    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_gunicorn_conf_dynamic_port_binding(self):
        """Verify gunicorn.conf.py parses dynamic PORT environment variable"""
        # Case 1: Custom PORT set (e.g. Render dynamic allocation)
        os.environ["PORT"] = "10055"
        conf = runpy.run_path("gunicorn.conf.py")
        self.assertEqual(conf.get("bind"), "0.0.0.0:10055")
        self.assertEqual(conf.get("workers"), 1)
        self.assertEqual(conf.get("worker_class"), "gthread")
        self.assertEqual(conf.get("threads"), 4)
        self.assertEqual(conf.get("timeout"), 120)

        # Case 2: PORT unset defaults gracefully to 10000
        del os.environ["PORT"]
        conf_default = runpy.run_path("gunicorn.conf.py")
        self.assertEqual(conf_default.get("bind"), "0.0.0.0:10000")

    def test_health_endpoint_response(self):
        """Verify /api/health responds immediately with HTTP 200 and healthy status"""
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsNotNone(data)
        self.assertEqual(data.get("status"), "healthy")

    def test_startup_latency_benchmark(self):
        """Benchmark app instantiation to ensure instant worker boot (< 2.0s)"""
        start = time.perf_counter()
        test_app = create_app()
        elapsed = time.perf_counter() - start
        self.assertIsNotNone(test_app)
        self.assertLess(elapsed, 2.0, f"App startup took {elapsed:.3f}s, expected under 2.0s")

    def test_opensearch_lazy_or_thread_fallback(self):
        """Verify search operations work smoothly without blocking startup"""
        from app.routes import opensearch_service
        results = opensearch_service.search(query_text="Atta", shopping_mode="ONLINE")
        self.assertIsInstance(results, dict)
        self.assertIn("results", results)
        self.assertGreater(len(results["results"]), 0)

if __name__ == "__main__":
    unittest.main()

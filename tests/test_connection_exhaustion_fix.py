"""
Tests for BharatStore PostgreSQL Connection Exhaustion Fix.
Verifies:
1. BoundedConnectionPool strictly enforces maxconn hard ceiling.
2. Connection reuse without socket churn (LIFO reuse).
3. Pre-ping liveness probe detects and purges broken connections.
4. Connection recycling (pool_recycle) retires stale connections.
5. Pool status reporting thread-safety and metrics accuracy.
6. Flask app context teardown safely cleans up request-scoped connections.
7. DB diagnostics API (/api/admin/db-diagnostics) non-destructive execution.
8. Health endpoint (/api/health) exposes pool metrics.
9. Gunicorn configuration enforces worker=1 and thread-based concurrency.
10. Config limits strictly bounded for Aiven PostgreSQL capacity (17 usable slots).
"""

import os
import time
import queue
import runpy
import unittest
import threading
from unittest.mock import MagicMock, patch

from run import app
from app.config import Config
from app.database import BoundedConnectionPool, PooledConnectionProxy, DatabaseService


class MockRawConnection:
    """Mock raw psycopg2 connection simulating socket and transaction status."""
    def __init__(self, conn_id: int):
        self.conn_id = conn_id
        self.closed = False
        self.autocommit = False
        self.status = 0 # STATUS_READY in psycopg2
        self.cursor_mock = MagicMock()

    def cursor(self, *args, **kwargs):
        return self.cursor_mock

    def rollback(self):
        self.status = 0

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class TestPostgresConnectionExhaustionFix(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = self.app.test_client()

    def test_01_config_pool_limits(self):
        """Verify conservative pool limits tailored for Aiven free tier (17 usable slots)."""
        self.assertEqual(Config.PG_POOL_MIN, 1)
        self.assertEqual(Config.PG_POOL_MAX, 3)
        self.assertGreaterEqual(Config.PG_POOL_TIMEOUT, 5.0)
        self.assertGreaterEqual(Config.PG_POOL_RECYCLE, 300.0)

    def test_02_bounded_pool_hard_ceiling(self):
        """Verify pool strictly never exceeds maxconn connections."""
        created_conns = []

        def mock_connect():
            c = MockRawConnection(len(created_conns) + 1)
            created_conns.append(c)
            return c

        pool = BoundedConnectionPool(
            minconn=1,
            maxconn=3,
            timeout=0.2,
            recycle=1800.0,
            connect_fn=mock_connect
        )

        c1 = pool.getconn()
        c2 = pool.getconn()
        c3 = pool.getconn()

        self.assertEqual(len(created_conns), 3)
        self.assertEqual(pool._created_count, 3)

        # 4th checkout should timeout because maxconn=3 is reached
        start = time.perf_counter()
        with self.assertRaises(TimeoutError) as ctx:
            pool.getconn(timeout=0.1)
        elapsed = time.perf_counter() - start
        self.assertGreaterEqual(elapsed, 0.08)
        self.assertIn("timed out", str(ctx.exception).lower())

        # Return c1 and verify 4th checkout succeeds immediately
        pool.putconn(c1)
        c4 = pool.getconn(timeout=0.2)
        self.assertIs(c4, c1)
        self.assertEqual(len(created_conns), 3)  # No extra connection created!

        pool.putconn(c2)
        pool.putconn(c3)
        pool.putconn(c4)
        pool.closeall()

    def test_03_bounded_pool_reuse_and_lifo(self):
        """Verify connections are returned and reused rather than destroyed."""
        conn_seq = []
        def mock_connect():
            c = MockRawConnection(len(conn_seq) + 1)
            conn_seq.append(c)
            return c

        pool = BoundedConnectionPool(minconn=1, maxconn=3, timeout=1.0, connect_fn=mock_connect)

        c1 = pool.getconn()
        self.assertEqual(c1.conn_id, 1)
        pool.putconn(c1)
        self.assertFalse(c1.closed, "Returned connection must remain open for reuse!")

        # Subsequent checkout should reuse c1
        c1_reused = pool.getconn()
        self.assertIs(c1, c1_reused)
        self.assertEqual(len(conn_seq), 1)

        pool.putconn(c1_reused)
        pool.closeall()
        self.assertTrue(c1.closed, "closeall must terminate connections")

    def test_04_pre_ping_purges_dead_connection(self):
        """Verify pre-ping detects dead socket and replaces with healthy connection."""
        conn_seq = []
        def mock_connect():
            c = MockRawConnection(len(conn_seq) + 1)
            conn_seq.append(c)
            return c

        pool = BoundedConnectionPool(minconn=1, maxconn=2, timeout=1.0, connect_fn=mock_connect)

        c1 = pool.getconn()
        pool.putconn(c1)

        # Simulate socket drop / broken connection
        c1.closed = True

        # Next getconn should discard c1 and create healthy c2
        c2 = pool.getconn()
        self.assertEqual(c2.conn_id, 2)
        self.assertFalse(c2.closed)

        pool.putconn(c2)
        pool.closeall()

    def test_05_pool_recycle_refreshes_stale_connections(self):
        """Verify connections older than recycle interval are transparently replaced."""
        conn_seq = []
        def mock_connect():
            c = MockRawConnection(len(conn_seq) + 1)
            conn_seq.append(c)
            return c

        # Set recycle to 0.1s
        pool = BoundedConnectionPool(minconn=1, maxconn=2, timeout=1.0, recycle=0.1, connect_fn=mock_connect)

        c1 = pool.getconn()
        self.assertEqual(c1.conn_id, 1)
        pool.putconn(c1)

        # Wait past recycle threshold
        time.sleep(0.15)

        # Should be recycled and a fresh connection created
        c2 = pool.getconn()
        self.assertEqual(c2.conn_id, 2)
        self.assertTrue(c1.closed, "Stale connection must be closed upon recycle")

        pool.putconn(c2)
        pool.closeall()

    def test_06_pool_status_metrics(self):
        """Verify thread-safe pool metrics are accurate."""
        pool = BoundedConnectionPool(minconn=1, maxconn=3, timeout=5.0, recycle=1800.0, connect_fn=lambda: MockRawConnection(1))
        c1 = pool.getconn()

        status = pool.get_status()
        self.assertEqual(status["minconn"], 1)
        self.assertEqual(status["maxconn"], 3)
        self.assertEqual(status["created_connections"], 1)
        self.assertEqual(status["checked_out_connections"], 1)
        self.assertEqual(status["idle_connections"], 0)

        pool.putconn(c1)
        status_after = pool.get_status()
        self.assertEqual(status_after["created_connections"], 1)
        self.assertEqual(status_after["checked_out_connections"], 0)
        self.assertEqual(status_after["idle_connections"], 1)

        pool.closeall()

    def test_07_pooled_connection_proxy(self):
        """Verify PooledConnectionProxy delegates methods and returns to pool on close."""
        pool = BoundedConnectionPool(minconn=1, maxconn=2, timeout=1.0, connect_fn=lambda: MockRawConnection(1))
        raw = pool.getconn()
        proxy = PooledConnectionProxy(pool, raw)

        # Context manager usage
        with proxy as conn:
            self.assertIsNotNone(conn)
        self.assertEqual(pool.get_status()["idle_connections"], 1)

        # Double close safety
        proxy.close()
        self.assertEqual(pool.get_status()["idle_connections"], 1)

        pool.closeall()

    def test_08_flask_teardown_appcontext_cleanup(self):
        """Verify request-scoped g.db_conn is closed on appcontext teardown."""
        from flask import g
        mock_conn = MagicMock()

        with self.app.app_context():
            g.db_conn = mock_conn

        # Context exit must trigger cleanup_request_db_resources
        mock_conn.close.assert_called_once()

    def test_09_db_diagnostics_endpoint(self):
        """Verify /api/admin/db-diagnostics returns HTTP 200 with non-destructive diagnostic report."""
        resp = self.client.get("/api/admin/db-diagnostics")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("diagnostics", data)
        diag = data["diagnostics"]
        self.assertIn("engine", diag)

    def test_10_health_endpoint_includes_pool(self):
        """Verify /api/health includes PostgreSQL pool metrics."""
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        pg_svc = data["services"]["postgresql"]
        self.assertIn("pool", pg_svc)
        self.assertEqual(pg_svc["pool"]["maxconn"], 3)

    def test_11_gunicorn_conf_concurrency_guards(self):
        """Verify gunicorn.conf.py restricts workers to 1 and uses gthread concurrency."""
        os.environ["PORT"] = "10000"
        conf = runpy.run_path("gunicorn.conf.py")
        self.assertEqual(conf.get("workers"), 1, "Must run 1 worker to prevent connection pool multiplication")
        self.assertEqual(conf.get("worker_class"), "gthread")
        self.assertEqual(conf.get("threads"), 4)

    def test_12_multi_thread_bounded_concurrency(self):
        """Verify concurrent multi-threaded checkouts do not leak or exceed pool ceiling."""
        conn_counter = 0
        counter_lock = threading.Lock()

        def mock_connect():
            nonlocal conn_counter
            with counter_lock:
                conn_counter += 1
                return MockRawConnection(conn_counter)

        pool = BoundedConnectionPool(minconn=1, maxconn=3, timeout=2.0, connect_fn=mock_connect)
        errors = []

        def worker_task():
            try:
                for _ in range(5):
                    c = pool.getconn()
                    time.sleep(0.01)
                    pool.putconn(c)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker_task) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Encountered unexpected worker errors: {errors}")
        self.assertLessEqual(conn_counter, 3, "Total connections created must never exceed maxconn=3")
        pool.closeall()


if __name__ == "__main__":
    unittest.main()

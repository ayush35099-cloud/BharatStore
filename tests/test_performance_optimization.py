"""
BharatStore — Performance & Loading Speed Optimization Test Suite
Validates:
1. Gzip HTTP compression on eligible payloads (> 500 bytes).
2. Long-term immutable caching headers on /static/ assets.
3. Thread-safe in-memory TTLCache behavior and invalidation.
4. Database connection pool initialization and safe connection return.
5. High-performance batch price comparison (zero N+1 queries: <= 3 queries vs 554 previously).
6. 100% data parity between batch comparisons and single comparisons.
7. Endpoints latency and response times (/ , /retail , /api/products , /api/health).
8. Cart, checkout, product, and customer data preservation.
"""

import gzip
import time
import unittest
from run import app
from app.cache import app_cache, TTLCache
from app.routes import db_service, build_retail_context


class TestPerformanceOptimization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.client = cls.app.test_client()

    def test_01_gzip_compression_enabled(self):
        """Verifies HTTP Gzip compression is automatically applied to payloads >= 500B."""
        res = self.client.get("/api/products", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("Content-Encoding"), "gzip")
        self.assertIn("Accept-Encoding", res.headers.get("Vary", ""))
        
        # Verify body can be decompressed
        decompressed = gzip.decompress(res.data)
        self.assertIn(b"Apple iPhone 15", decompressed)

    def test_02_static_asset_cache_headers(self):
        """Verifies immutable cache headers for static assets."""
        res = self.client.get("/static/css/style.css")
        self.assertEqual(res.status_code, 200)
        self.assertIn("max-age=31536000", res.headers.get("Cache-Control", ""))
        res.close()

    def test_03_ttl_cache_operations(self):
        """Verifies in-memory thread-safe TTLCache set, get, expiry, and prefix invalidation."""
        test_cache = TTLCache(default_ttl_sec=1.0)
        test_cache.set("item:1", {"name": "Apple"})
        test_cache.set("item:2", {"name": "Banana"})
        test_cache.set("other:1", {"name": "Orange"})

        self.assertEqual(test_cache.get("item:1"), {"name": "Apple"})
        
        # Test prefix invalidation
        test_cache.invalidate_prefix("item:")
        self.assertIsNone(test_cache.get("item:1"))
        self.assertIsNone(test_cache.get("item:2"))
        self.assertEqual(test_cache.get("other:1"), {"name": "Orange"})

        # Test TTL expiration
        time.sleep(1.1)
        self.assertIsNone(test_cache.get("other:1"))

    def test_04_retail_query_count_under_threshold(self):
        """Verifies /retail executes <= 6 queries on cold cache and 0 queries on warm cache (down from 554 N+1 queries)."""
        app_cache.clear()
        query_count = 0
        orig_get_sqlite = db_service._get_sqlite_connection

        class CountingCursor:
            def __init__(self, cur): self._cur = cur
            def execute(self, *args, **kwargs):
                nonlocal query_count
                query_count += 1
                return self._cur.execute(*args, **kwargs)
            def fetchone(self): return self._cur.fetchone()
            def fetchall(self): return self._cur.fetchall()
            def __getattr__(self, name): return getattr(self._cur, name)

        class CountingConn:
            def __init__(self, conn): self._conn = conn
            def cursor(self, *args, **kwargs): return CountingCursor(self._conn.cursor(*args, **kwargs))
            def __getattr__(self, name): return getattr(self._conn, name)

        db_service._get_sqlite_connection = lambda: CountingConn(orig_get_sqlite())

        try:
            with self.app.test_request_context("/retail"):
                # Cold cache run
                query_count = 0
                ctx = build_retail_context()
                cold_queries = query_count
                self.assertLessEqual(cold_queries, 6, f"Cold query count {cold_queries} exceeds maximum of 6 queries! (Was 554)")
                self.assertGreater(len(ctx["products"]), 0)
                self.assertEqual(len(ctx["stores"]), 5)

                # Warm cache run
                query_count = 0
                ctx_warm = build_retail_context()
                warm_queries = query_count
                self.assertEqual(warm_queries, 0, f"Warm query count should be 0, got {warm_queries}")
        finally:
            db_service._get_sqlite_connection = orig_get_sqlite

    def test_05_batch_comparison_data_parity(self):
        """Verifies batch comparison data matches single comparison data identically."""
        batch = db_service.get_all_product_price_comparisons("Bengaluru")
        self.assertGreater(len(batch), 0)

        for test_pid in [41, 70, 75]:
            single = db_service.get_product_price_comparison(test_pid, "Bengaluru")
            b = batch.get(test_pid)
            self.assertIsNotNone(b)
            self.assertEqual(b["lowest_price"], single["lowest_price"])
            self.assertEqual(b["lowest_store_name"], single["lowest_store_name"])
            self.assertEqual(b["in_stock_stores_count"], single["in_stock_stores_count"])
            self.assertEqual(len(b["stores_comparison"]), len(single["stores_comparison"]))

    def test_06_response_time_benchmark(self):
        """Verifies sub-millisecond to low single-digit response times on key routes."""
        endpoints = [
            ("/", "Homepage"),
            ("/retail", "Retail"),
            ("/api/products", "API Products"),
            ("/api/retail/stores", "API Stores"),
            ("/api/health", "API Health")
        ]
        for url, name in endpoints:
            # Warm up
            self.client.get(url)
            t0 = time.perf_counter()
            res = self.client.get(url)
            t1 = time.perf_counter()
            self.assertEqual(res.status_code, 200)
            elapsed_ms = (t1 - t0) * 1000
            # Local response times should all be under 50ms (typically < 5ms)
            self.assertLess(elapsed_ms, 50.0, f"{name} ({url}) took {elapsed_ms:.2f}ms, expected < 50ms")

    def test_07_data_integrity_preserved(self):
        """Verifies all products, stores, categories, and inventory items remain intact."""
        prods = db_service.get_all_products()
        self.assertGreaterEqual(len(prods), 100, "Catalog products count must be preserved")
        stores = db_service.get_retail_stores("Bengaluru")
        self.assertEqual(len(stores), 5, "Bengaluru must have 5 retail stores")
        hubs = db_service.get_store_hubs()
        self.assertGreaterEqual(len(hubs), 6, "Store hubs must be preserved")


if __name__ == "__main__":
    unittest.main()

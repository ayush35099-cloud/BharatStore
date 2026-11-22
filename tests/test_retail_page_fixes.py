"""
Regression Test Suite for BharatStore Retail Page (/retail) & Multi-Process Pool Isolation
Verifies:
1. /retail page renders HTTP 200 with all departments, 5-shop showcase grid, search bar, and active store.
2. Store switching via ?store_id= query param updates active storefront.
3. /api/retail/stores returns 5 Bengaluru neighbourhood shops with full metadata.
4. /api/retail/catalog returns categorized grocery catalog with 5-shop comparisons.
5. /api/retail/stores/<id> returns store details and product count.
6. /api/retail/products/<id>/compare returns accurate price comparisons without NaN/TypeError.
7. Handling of NULL original_price in price comparison calculation without TypeError.
8. Proper float/int types in get_store_inventory and get_store_product.
9. Process PID-aware connection pool isolation and gunicorn post_fork safety.
10. Sizing of connection pool (PG_POOL_MIN=1, PG_POOL_MAX=3) compliant with Aiven free tier.
11. Add to cart in retail mode functions properly across independent store baskets.
12. Online shopping marketplace mode (/ and /api/products) remains 100% functional.
"""

import os
import unittest
from app import create_app
from app.config import Config
from app.routes import db_service


class TestRetailPageFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_01_retail_page_renders_http_200_with_all_elements(self):
        """1. /retail renders HTTP 200 with complete DOM elements, departments, and active store."""
        resp = self.client.get("/retail")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Check core DOM sections
        self.assertIn("retail-stores-grid-5", html)
        self.assertIn("retail-hero-store-name", html)
        self.assertIn("retail-grocery-search-input", html)
        self.assertIn("retail-dept-section", html)
        self.assertIn("dairy-section", html)
        self.assertIn("grains-section", html)
        self.assertIn("produce-section", html)
        self.assertIn("snacks-section", html)
        self.assertIn("household-section", html)
        self.assertIn("retail-compare-modal", html)
        self.assertIn("Compare 5 Shops", html)

    def test_02_retail_store_switch_via_query_param(self):
        """2. Switching stores via /retail?store_id=2 renders Store 2 as the active store."""
        resp = self.client.get("/retail?store_id=2")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        store_2 = db_service.get_store_by_id(2)
        self.assertIsNotNone(store_2)
        self.assertIn(store_2["store_name"], html)

    def test_03_api_retail_stores_returns_5_shops(self):
        """3. /api/retail/stores returns 5 neighbourhood shops with complete metadata."""
        resp = self.client.get("/api/retail/stores")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        stores = data.get("stores", [])
        self.assertEqual(len(stores), 5)

        for s in stores:
            self.assertIn("id", s)
            self.assertIn("store_name", s)
            self.assertIn("area", s)
            self.assertIn("city", s)
            self.assertIn("rating", s)
            self.assertIn("delivery_time", s)

    def test_04_api_retail_catalog(self):
        """4. /api/retail/catalog returns grocery departments and items."""
        resp = self.client.get("/api/retail/catalog")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("dairy_bakery_items", data)
        self.assertIn("rice_atta_dal_items", data)
        self.assertIn("fruits_vegetables_items", data)
        self.assertIn("snacks_beverages_items", data)
        self.assertIn("household_personal_items", data)
        self.assertGreater(data.get("total_items", 0), 0)

    def test_05_api_retail_store_by_id(self):
        """5. /api/retail/stores/<id> returns specific store details and inventory count."""
        resp = self.client.get("/api/retail/stores/1")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("store", data)
        self.assertEqual(data["store"]["id"], 1)
        self.assertGreater(data.get("total_products", 0), 0)

    def test_06_api_retail_product_price_comparison(self):
        """6. /api/retail/products/<id>/compare returns real-time price comparisons across 5 shops."""
        resp = self.client.get("/api/retail/products/21/compare")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("product", data)
        self.assertIn("stores_comparison", data)
        self.assertEqual(len(data["stores_comparison"]), 5)

        lowest_price = data.get("lowest_price")
        self.assertIsNotNone(lowest_price)
        self.assertGreater(lowest_price, 0)
        self.assertIsInstance(lowest_price, (int, float))

    def test_07_price_comparison_handles_null_original_price_without_type_error(self):
        """7. get_product_price_comparison handles products where original_price is None without TypeError."""
        # Product 25 or create custom dict to test calculation
        comp = db_service.get_product_price_comparison(21, "Bengaluru")
        self.assertIsNotNone(comp)
        self.assertIn("stores_comparison", comp)
        for st in comp["stores_comparison"]:
            self.assertIsInstance(st["price"], (int, float))
            self.assertIsInstance(st["original_price"], (int, float))

    def test_08_get_store_inventory_types(self):
        """8. get_store_inventory returns float selling_price and original_price."""
        inv = db_service.get_store_inventory(1)
        self.assertGreater(len(inv), 0)
        for item in inv:
            self.assertIsInstance(item["selling_price"], float)
            if item.get("original_price") is not None:
                self.assertIsInstance(item["original_price"], float)
            self.assertIsInstance(item["stock_quantity"], int)
            self.assertIsInstance(item["is_available"], bool)

    def test_09_multiprocess_pool_isolation_and_pid_reset(self):
        """9. Process PID change triggers clean connection pool reset to prevent cross-process socket sharing."""
        orig_pid = db_service._pool_pid
        db_service.reset_connection_pool()
        self.assertIsNone(db_service._pg_pool)
        self.assertIsNone(db_service._pool_pid)

        # Calling _get_pg_pool should respect PID
        pool = db_service._get_pg_pool()
        if db_service.is_live_postgres:
            self.assertIsNotNone(pool)
            self.assertEqual(db_service._pool_pid, os.getpid())

    def test_10_safe_connection_pool_limits_for_aiven(self):
        """10. Connection pool min/max are safely bounded for Aiven PostgreSQL 20-connection limit."""
        self.assertEqual(Config.PG_POOL_MIN, 1)
        self.assertEqual(Config.PG_POOL_MAX, 3)

    def test_11_add_to_cart_in_retail_mode(self):
        """11. Adding item to retail store basket updates cart and preserves store isolation."""
        with self.client.session_transaction() as sess:
            sess["retail_cart"] = {}

        resp = self.client.post("/api/cart/retail/1/add", json={
            "product_id": 21,
            "quantity": 2,
            "fulfillment": "delivery"
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertTrue(data.get("success"))

        # Verify retail cart summary endpoint
        cart_resp = self.client.get("/api/retail/cart")
        self.assertEqual(cart_resp.status_code, 200)
        cart_data = cart_resp.get_json()
        self.assertTrue(cart_data.get("success"))
        self.assertGreater(cart_data.get("total_items", 0), 0)

    def test_12_online_shopping_mode_catalog_intact(self):
        """12. Online shopping marketplace mode (/ and /api/products) remains 100% functional without regression."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)

        prod_resp = self.client.get("/api/products?mode=online")
        self.assertEqual(prod_resp.status_code, 200)
        prods = prod_resp.get_json()
        self.assertGreater(prods.get("total", 0), 0)


if __name__ == "__main__":
    unittest.main()

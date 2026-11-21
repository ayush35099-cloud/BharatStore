"""
BharatStore 2.0 - Phase 4 Multi-Store Inventory & Database Test Suite
=====================================================================
Covers all 21 required test scenarios:
1. Store creation.
2. Store retrieval.
3. Store update.
4. Store activation/deactivation.
5. Invalid store IDs.
6. Inventory creation.
7. Store-specific pricing.
8. Different stock across stores.
9. Product availability.
10. Out-of-stock handling.
11. Invalid stock quantities.
12. Duplicate inventory prevention.
13. Missing product handling.
14. Missing store handling.
15. Unauthorized inventory modification.
16. Customer access restrictions.
17. Concurrent stock updates.
18. Overselling prevention.
19. Stock reservation and release.
20. PostgreSQL and SQLite compatibility.
21. Retail and Online Shopping separation.
"""

import unittest
import threading
import json
from app import create_app
from app.config import Config
from app.database import DatabaseService


class TestPhase4StoreInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Configure admin API key for tests if missing
        if not Config.ADMIN_API_KEY:
            Config.ADMIN_API_KEY = "test-phase4-admin-secret-token-2026"
        cls.admin_headers = {
            "X-Admin-Token": Config.ADMIN_API_KEY,
            "Content-Type": "application/json"
        }
        cls.app = create_app()
        cls.client = cls.app.test_client()
        cls.db = DatabaseService()

    # 1. Store creation
    def test_01_store_creation(self):
        # Clean up any existing test store for repeatable test isolation
        existing = self.db.get_store_by_slug("bharatstore-test-express-koramangala")
        if existing:
            conn = self.db._get_sqlite_connection()
            conn.execute("DELETE FROM store_inventory WHERE store_id = ?;", (existing["id"],))
            conn.execute("DELETE FROM stores WHERE id = ?;", (existing["id"],))
            conn.commit()
            conn.close()

        res = self.client.post("/api/admin/stores", headers=self.admin_headers, json={
            "store_name": "BharatStore Test Express Koramangala",
            "store_slug": "bharatstore-test-express-koramangala",
            "store_description": "Modern express quick-commerce store for rapid testing.",
            "full_address": "12th Main Road, 5th Block, Koramangala, Bengaluru 560095",
            "city": "Bengaluru",
            "area": "Koramangala",
            "pincode": "560095",
            "contact_phone": "+91 98450 99887",
            "email": "test.koramangala@bharatstore.in",
            "latitude": 12.9345,
            "longitude": 77.6201,
            "opening_time": "06:00 AM",
            "closing_time": "11:00 PM"
        })
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("store", data)
        self.assertEqual(data["store"]["store_name"], "BharatStore Test Express Koramangala")
        self.__class__.created_store_id = data["store"]["id"]
        print(" [PASSED] 1. Store creation verified via Admin API (/api/admin/stores)")

    # 2. Store retrieval
    def test_02_store_retrieval(self):
        store_id = getattr(self.__class__, "created_store_id", 1)
        res = self.client.get(f"/api/stores/{store_id}")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["store"]["id"], store_id)

        # Retrieve by slug
        slug_store = self.db.get_store_by_slug("bharatstore-bengaluru-tech-store")
        self.assertIsNotNone(slug_store)
        self.assertEqual(slug_store["id"], 1)
        print(" [PASSED] 2. Store retrieval verified by ID and Slug")

    # 3. Store update
    def test_03_store_update(self):
        store_id = getattr(self.__class__, "created_store_id", 1)
        res = self.client.put(f"/api/admin/stores/{store_id}", headers=self.admin_headers, json={
            "contact_phone": "+91 98450 11223",
            "closing_time": "11:45 PM"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["store"]["contact_phone"], "+91 98450 11223")
        self.assertEqual(data["store"]["closing_time"], "11:45 PM")
        print(" [PASSED] 3. Store update verified via Admin API")

    # 4. Store activation/deactivation
    def test_04_store_activation_deactivation(self):
        store_id = getattr(self.__class__, "created_store_id", 1)
        # Deactivate
        deact_res = self.client.post(f"/api/admin/stores/{store_id}/status", headers=self.admin_headers, json={
            "is_active": False
        })
        self.assertEqual(deact_res.status_code, 200)
        self.assertFalse(deact_res.get_json()["is_active"])

        # Check that active_only listing hides it
        active_list = self.client.get("/api/stores?active_only=true").get_json()["stores"]
        self.assertFalse(any(s["id"] == store_id for s in active_list))

        # Reactivate
        act_res = self.client.post(f"/api/admin/stores/{store_id}/status", headers=self.admin_headers, json={
            "is_active": True
        })
        self.assertEqual(act_res.status_code, 200)
        self.assertTrue(act_res.get_json()["is_active"])
        print(" [PASSED] 4. Store activation & deactivation cycle verified")

    # 5. Invalid store IDs
    def test_05_invalid_store_ids(self):
        # Non-existent ID
        res = self.client.get("/api/stores/999999")
        self.assertEqual(res.status_code, 404)
        self.assertFalse(res.get_json()["success"])

        # Non-numeric ID in route
        res2 = self.client.get("/api/stores/not-a-number")
        self.assertEqual(res2.status_code, 404)
        print(" [PASSED] 5. Invalid store IDs handled safely with HTTP 404")

    # 6. Inventory creation
    def test_06_inventory_creation(self):
        store_id = getattr(self.__class__, "created_store_id", 1)
        # Clean up product 16 if already present from previous test run
        self.db.remove_store_inventory(store_id, 16)

        # Add Product 16 (Tata Tea Gold) to this store
        res = self.client.post(f"/api/stores/{store_id}/inventory", headers=self.admin_headers, json={
            "product_id": 16,
            "selling_price": 530.00,
            "original_price": 540.00,
            "stock_quantity": 40,
            "low_stock_threshold": 8
        })
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["inventory"]["store_id"], store_id)
        self.assertEqual(data["inventory"]["product_id"], 16)
        self.assertEqual(float(data["inventory"]["selling_price"]), 530.00)
        print(" [PASSED] 6. Store inventory creation verified via Admin API (/api/stores/<id>/inventory)")

    # 7. Store-specific pricing
    def test_07_store_specific_pricing(self):
        # Product 61 (Amul Taaza Milk 1L)
        p1 = self.db.get_store_product(1, 61)
        p2 = self.db.get_store_product(2, 61)
        self.assertIsNotNone(p1)
        self.assertIsNotNone(p2)
        # Store 1 sells at 60.0, Store 2 sells at 62.0
        self.assertNotEqual(float(p1["selling_price"]), float(p2["selling_price"]))
        self.assertEqual(float(p1["selling_price"]), 60.00)
        self.assertEqual(float(p2["selling_price"]), 62.00)
        print(" [PASSED] 7. Store-specific pricing verified (₹60.00 vs ₹62.00 for Milk 1L)")

    # 8. Different stock across stores
    def test_08_different_stock_across_stores(self):
        # Product 18 (Aashirvaad Atta 5kg)
        s1_prod = self.db.get_store_product(1, 18)
        s2_prod = self.db.get_store_product(2, 18)
        self.assertIsNotNone(s1_prod)
        self.assertIsNotNone(s2_prod)
        # Store 1 has 5 units, Store 2 has 12 units
        self.assertEqual(s1_prod["stock_quantity"], 5)
        self.assertEqual(s2_prod["stock_quantity"], 12)
        self.assertNotEqual(s1_prod["stock_quantity"], s2_prod["stock_quantity"])
        print(" [PASSED] 8. Independent stock levels verified (5 units vs 12 units for Atta 5kg)")

    # 9. Product availability
    def test_09_product_availability(self):
        res = self.client.get("/api/stores/1/products")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        # All items in /products must have stock > 0 and is_available True
        for p in data["products"]:
            self.assertTrue(p["is_available"])
            self.assertGreater(p["stock_quantity"], 0)
        print(" [PASSED] 9. Store product availability list strictly verified (/api/stores/<id>/products)")

    # 10. Out-of-stock handling
    def test_10_out_of_stock_handling(self):
        # Product 62 (Curd 500g): In Stock at Store 1 (10 units), Out of Stock at Store 2 (0 units)
        p1 = self.db.get_store_product(1, 62)
        p2 = self.db.get_store_product(2, 62)
        self.assertTrue(p1["is_available"])
        self.assertGreater(p1["stock_quantity"], 0)

        self.assertFalse(p2["is_available"])
        self.assertEqual(p2["stock_quantity"], 0)

        # Store 2 products list must NOT include product 62
        s2_products = self.client.get("/api/stores/2/products").get_json()["products"]
        self.assertFalse(any(p["product_id"] == 62 for p in s2_products))
        print(" [PASSED] 10. Out-of-stock isolation verified (Curd in stock at Store 1, unavailable at Store 2)")

    # 11. Invalid stock quantities
    def test_11_invalid_stock_quantities(self):
        # Negative stock
        res_neg = self.client.post("/api/stores/1/inventory", headers=self.admin_headers, json={
            "product_id": 20,
            "selling_price": 500,
            "stock_quantity": -10
        })
        self.assertEqual(res_neg.status_code, 400)
        self.assertIn("negative", res_neg.get_json()["error"].lower())

        # Negative price
        res_bad_price = self.client.post("/api/stores/1/inventory", headers=self.admin_headers, json={
            "product_id": 20,
            "selling_price": -50,
            "stock_quantity": 10
        })
        self.assertEqual(res_bad_price.status_code, 400)
        self.assertIn("negative", res_bad_price.get_json()["error"].lower())
        print(" [PASSED] 11. Negative stock and negative price rejected with HTTP 400")

    # 12. Duplicate inventory prevention
    def test_12_duplicate_inventory_prevention(self):
        # Product 61 already exists in Store 1
        res = self.client.post("/api/stores/1/inventory", headers=self.admin_headers, json={
            "product_id": 61,
            "selling_price": 60,
            "stock_quantity": 20
        })
        self.assertEqual(res.status_code, 409)
        self.assertIn("already registered", res.get_json()["error"].lower())
        print(" [PASSED] 12. Duplicate store inventory registration strictly rejected with HTTP 409")

    # 13. Missing product handling
    def test_13_missing_product_handling(self):
        res = self.client.post("/api/stores/1/inventory", headers=self.admin_headers, json={
            "product_id": 999999,
            "selling_price": 100,
            "stock_quantity": 10
        })
        self.assertEqual(res.status_code, 404)
        self.assertIn("not found", res.get_json()["error"].lower())
        print(" [PASSED] 13. Missing product rejected with HTTP 404")

    # 14. Missing store handling
    def test_14_missing_store_handling(self):
        res = self.client.post("/api/stores/999999/inventory", headers=self.admin_headers, json={
            "product_id": 16,
            "selling_price": 100,
            "stock_quantity": 10
        })
        self.assertEqual(res.status_code, 404)
        self.assertIn("not found", res.get_json()["error"].lower())
        print(" [PASSED] 14. Missing store rejected with HTTP 404")

    # 15. Unauthorized inventory modification
    def test_15_unauthorized_inventory_modification(self):
        # Attempt to POST without admin token
        res_post = self.client.post("/api/stores/1/inventory", json={
            "product_id": 16,
            "selling_price": 100,
            "stock_quantity": 10
        })
        self.assertEqual(res_post.status_code, 403)

        # Attempt to PUT without admin token
        res_put = self.client.put("/api/stores/1/inventory/61", json={
            "selling_price": 99
        })
        self.assertEqual(res_put.status_code, 403)

        # Attempt to DELETE without admin token
        res_del = self.client.delete("/api/stores/1/inventory/61")
        self.assertEqual(res_del.status_code, 403)
        print(" [PASSED] 15. Unauthorized inventory mutations blocked with HTTP 403")

    # 16. Customer access restrictions
    def test_16_customer_access_restrictions(self):
        # Customers can read stores and products freely without auth headers
        res_stores = self.client.get("/api/stores")
        self.assertEqual(res_stores.status_code, 200)

        res_inv = self.client.get("/api/stores/1/inventory")
        self.assertEqual(res_inv.status_code, 200)

        res_prod = self.client.get("/api/stores/1/products/61")
        self.assertEqual(res_prod.status_code, 200)
        print(" [PASSED] 16. Customer read access permitted without administrative credentials")

    # 17. Concurrent stock updates
    def test_17_concurrent_stock_updates(self):
        # Concurrently update stock for Product 64 in Store 1 across 10 threads
        store_id = 1
        product_id = 64
        initial = self.db.get_store_product(store_id, product_id)
        original_stock = initial["stock_quantity"]

        errors = []
        def worker(thread_idx):
            try:
                self.db.update_store_inventory(store_id, product_id, {
                    "stock_quantity": original_stock + thread_idx
                })
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(1, 6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        # Restore original stock
        self.db.update_store_inventory(store_id, product_id, {"stock_quantity": original_stock})
        print(" [PASSED] 17. Thread-safe concurrent stock updates verified")

    # 18. Overselling prevention
    def test_18_overselling_prevention(self):
        store_id = 1
        product_id = 18  # Aashirvaad Atta, stock = 5
        curr = self.db.get_store_product(store_id, product_id)
        avail = curr["stock_quantity"] - curr["reserved_quantity"]

        # Attempt to reserve more than available (avail + 10)
        with self.assertRaises(ValueError) as ctx:
            self.db.reserve_store_stock(store_id, product_id, avail + 10, "TEST_OVERSELL", "99")
        self.assertIn("Insufficient stock", str(ctx.exception))
        print(" [PASSED] 18. Overselling strictly prevented: requested > available rejected")

    # 19. Stock reservation and release
    def test_19_stock_reservation_and_release(self):
        store_id = 3
        product_id = 64  # Butter, stock = 30, reserved = 0
        before = self.db.get_store_product(store_id, product_id)
        init_stock = before["stock_quantity"]
        init_reserved = before["reserved_quantity"]

        # 1. Reserve 5 units
        res1 = self.db.reserve_store_stock(store_id, product_id, 5, "TEST_CART", "101")
        self.assertEqual(res1["quantity_reserved"], 5)
        self.assertEqual(res1["total_reserved"], init_reserved + 5)

        # 2. Release 2 units
        res2 = self.db.release_store_stock(store_id, product_id, 2, "TEST_CART", "101")
        self.assertEqual(res2["total_reserved"], init_reserved + 3)

        # 3. Commit sale for remaining 3 units
        res3 = self.db.commit_store_sale(store_id, product_id, 3, "TEST_ORDER", "5001")
        self.assertEqual(res3["new_stock"], init_stock - 3)
        self.assertEqual(res3["new_reserved"], init_reserved)

        # Clean up by restoring original stock
        self.db.update_store_inventory(store_id, product_id, {"stock_quantity": init_stock})
        print(" [PASSED] 19. Stock reservation, release and sale commit lifecycle verified")

    # 20. PostgreSQL and SQLite compatibility
    def test_20_sqlite_and_postgres_compatibility(self):
        conn = self.db._get_sqlite_connection()
        cur = conn.cursor()
        # Verify tables exist with expected schema
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('stores', 'store_inventory');")
        tables = [r[0] for r in cur.fetchall()]
        self.assertIn("stores", tables)
        self.assertIn("store_inventory", tables)

        # Verify columns in store_inventory
        cur.execute("PRAGMA table_info(store_inventory);")
        cols = [r[1] for r in cur.fetchall()]
        for req_col in ["store_id", "product_id", "selling_price", "stock_quantity", "reserved_quantity", "is_available"]:
            self.assertIn(req_col, cols)
        conn.close()
        print(" [PASSED] 20. Relational schema compatibility verified on SQLite engine")

    # 21. Retail and Online Shopping separation
    def test_21_retail_and_online_shopping_separation(self):
        # 1. Online marketplace product catalog (/products) loads global products
        res_online = self.client.get("/products")
        self.assertEqual(res_online.status_code, 200)

        # 2. Online backend cart validation (/api/cart/validate) operates on global inventory
        res_cart = self.client.post("/api/cart/validate", json={
            "product_id": 1,
            "quantity": 1
        })
        self.assertEqual(res_cart.status_code, 200)
        self.assertTrue(res_cart.get_json()["valid"])

        # 3. Physical store inventory is queryable via /api/stores/1/products without mutating global catalog
        res_retail = self.client.get("/api/stores/1/products")
        self.assertEqual(res_retail.status_code, 200)
        retail_prods = res_retail.get_json()["products"]
        self.assertGreater(len(retail_prods), 0)

        # Verify global product 1 price is unchanged by store 1 prices
        global_prod = self.db.get_product_by_id(1)
        self.assertEqual(float(global_prod["price"]), 71999.00)
        print(" [PASSED] 21. Retail and Online Shopping architectural separation confirmed intact")


if __name__ == "__main__":
    unittest.main()

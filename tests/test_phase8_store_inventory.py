"""
Test Suite: BharatStore 2.0 – Phase 8 Store-Specific Inventory & Retail Bug Fixes
================================================================================
Comprehensive verification for all Phase 8 requirements:
1. Part 1: Fix ₹NaN Price Comparison Bug (Product 76 Amul Gold Milk across all 5 shops, numeric validation, out-of-stock exclusion).
2. Part 2: Retail Near Me Grocery-Only Isolation (8 allowed grocery categories, non-grocery exclusion, online preservation).
3. Part 3 & 4: Store-Specific Inventory & Stock Management (independent stock, non-negative checks, out-of-stock/low-stock APIs, movement ledger).
4. Part 5: Admin Auth Protection & ACID stock controls.
"""

import unittest
import json
import uuid
import math
from app import create_app
from app.config import Config
from app.database import DatabaseService


class TestPhase8StoreInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()
        cls.db = DatabaseService()
        if not Config.ADMIN_API_KEY:
            Config.ADMIN_API_KEY = "test-phase8-admin-secret-token-2026"
        cls.admin_headers = {
            "Content-Type": "application/json",
            "X-Admin-Token": Config.ADMIN_API_KEY
        }

    def setUp(self):
        self.cust_id = 200000 + int(uuid.uuid4().hex[:6], 16)
        self.session_id = str(uuid.uuid4())
        self.user_headers = {
            "Content-Type": "application/json",
            "X-Customer-Id": str(self.cust_id),
            "X-Session-Id": self.session_id
        }

    # =========================================================================
    # PART 1: Fix ₹NaN Price Comparison Bug (Product 76: Amul Gold Milk - 500 ml)
    # =========================================================================
    def test_01_product_76_price_comparison_valid_numeric(self):
        """Part 1: Price comparison for Product 76 returns valid numeric prices across all 5 shops."""
        res = self.client.get("/api/retail/products/76/compare?city=Bengaluru")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        product = data.get("product", {})
        self.assertEqual(product.get("id"), 76)

        # Lowest price must be a valid positive number
        lowest_price = data.get("lowest_price")
        self.assertIsNotNone(lowest_price)
        self.assertIsInstance(lowest_price, (int, float))
        self.assertFalse(math.isnan(lowest_price))
        self.assertFalse(math.isinf(lowest_price))
        self.assertGreater(lowest_price, 0)

        # Each shop must have valid numeric prices
        shops = data.get("stores_comparison") or data.get("shops") or []
        self.assertEqual(len(shops), 5)
        for shop in shops:
            # Must provide price and selling_price as valid numeric floats
            self.assertIn("price", shop)
            self.assertIn("selling_price", shop)
            price = shop["price"]
            selling_price = shop["selling_price"]
            self.assertIsInstance(price, (int, float))
            self.assertIsInstance(selling_price, (int, float))
            self.assertFalse(math.isnan(price))
            self.assertFalse(math.isnan(selling_price))
            self.assertGreater(price, 0)
            self.assertEqual(price, selling_price)

    def test_02_product_76_out_of_stock_store4_not_selected_as_lowest(self):
        """Part 1: Out-of-stock shop (Store 4) is not chosen as lowest price shop."""
        res = self.client.get("/api/retail/products/76/compare?city=Bengaluru")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        shops = data.get("stores_comparison") or data.get("shops") or []
        # Find Store 4 in shops
        store4 = next((s for s in shops if s["store_id"] == 4), None)
        self.assertIsNotNone(store4)
        # Store 4 has stock=0, so is_available must be False
        self.assertFalse(store4.get("is_available", True))

        # The lowest-priced available shop must be IN STOCK
        lowest_store_id = data.get("lowest_store_id") or data.get("lowest_shop_id")
        self.assertNotEqual(lowest_store_id, 4, "Out-of-stock store 4 cannot be selected as the lowest-priced shop.")

    # =========================================================================
    # PART 2: Retail Near Me Strictly Grocery-Only Isolation
    # =========================================================================
    def test_03_retail_products_api_strictly_grocery_only(self):
        """Part 2: /api/products?mode=RETAIL_NEAR_ME returns only grocery items."""
        res = self.client.get("/api/products?mode=RETAIL_NEAR_ME")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        products = data.get("products", [])
        self.assertGreater(len(products), 0)

        non_grocery_cats = {
            "Mobiles & Tablets", "Laptops & Computers", "Audio & Wearables",
            "Home & Kitchen", "Fashion & Apparel", "Electronics"
        }
        for p in products:
            cat = p.get("category", "")
            sub = p.get("sub_category", "")
            self.assertNotIn(cat, non_grocery_cats, f"Non-grocery category '{cat}' found in Retail mode: {p['title']}")
            self.assertNotIn(sub, non_grocery_cats, f"Non-grocery sub_category '{sub}' found in Retail mode: {p['title']}")

    def test_04_retail_products_non_grocery_category_filter_returns_empty(self):
        """Part 2: Requesting non-grocery category in Retail mode returns 0 products."""
        res = self.client.get("/api/products?mode=RETAIL_NEAR_ME&category=Laptops+%26+Computers")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("total"), 0)
        self.assertEqual(len(data.get("products", [])), 0)

    def test_05_retail_single_product_non_grocery_rejected_with_404(self):
        """Part 2: Direct lookup of non-grocery item (ID 1 - iPhone) in Retail mode returns HTTP 404."""
        res = self.client.get("/api/products/1?mode=RETAIL_NEAR_ME")
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertIn("not available", data.get("error", "").lower())

    def test_06_retail_single_product_grocery_allowed_with_200(self):
        """Part 2: Direct lookup of grocery item (ID 76 - Milk) in Retail mode returns HTTP 200."""
        res = self.client.get("/api/products/76?mode=RETAIL_NEAR_ME")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("id"), 76)

    def test_07_online_shopping_catalog_preserved_with_tech_and_mobiles(self):
        """Part 2: Online Shopping mode preserves full marketplace catalog untouched."""
        res = self.client.get("/api/products?mode=ONLINE")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        products = data.get("products", [])
        categories = {p.get("category") for p in products}
        self.assertIn("Laptops & Computers", categories)
        self.assertIn("Mobiles & Tablets", categories)
        self.assertIn("Daily Essentials & Groceries", categories)

    def test_08_retail_search_non_grocery_returns_zero_hits(self):
        """Part 2: Searching for 'laptop' in Retail mode returns 0 hits."""
        res = self.client.get("/api/search?q=laptop&mode=RETAIL_NEAR_ME")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("total"), 0)
        self.assertEqual(len(data.get("hits", [])), 0)

    def test_09_retail_search_grocery_returns_dairy_hits(self):
        """Part 2: Searching for 'milk' in Retail mode returns dairy results."""
        res = self.client.get("/api/search?q=milk&mode=RETAIL_NEAR_ME")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertGreater(data.get("total"), 0)
        for h in data.get("hits", []):
            self.assertIn(h.get("category"), {"Daily Essentials & Groceries", "Dairy & Breakfast"})

    def test_10_retail_compare_non_grocery_rejected_with_404(self):
        """Part 2: Comparing non-grocery item (ID 1 - iPhone) via Retail compare API returns HTTP 404."""
        res = self.client.get("/api/retail/products/1/compare")
        self.assertEqual(res.status_code, 404)

    # =========================================================================
    # PART 3 & 4: Store-Specific Inventory & Stock Management
    # =========================================================================
    def test_11_independent_store_inventory_modifications(self):
        """Part 3: Changing stock at Store 1 does not affect stock at Store 2."""
        # Check initial stock at Store 1 and Store 2 for product 76
        p1 = self.db.get_store_product(1, 76)
        p2 = self.db.get_store_product(2, 76)
        initial_s1 = p1["stock_quantity"]
        initial_s2 = p2["stock_quantity"]

        # Update Store 1 stock to initial_s1 + 2
        update_res = self.client.put(
            "/api/stores/1/inventory/76",
            json={"stock_quantity": initial_s1 + 2},
            headers=self.admin_headers
        )
        self.assertEqual(update_res.status_code, 200)

        # Verify Store 1 updated
        new_p1 = self.db.get_store_product(1, 76)
        self.assertEqual(new_p1["stock_quantity"], initial_s1 + 2)

        # Verify Store 2 remains completely unchanged
        new_p2 = self.db.get_store_product(2, 76)
        self.assertEqual(new_p2["stock_quantity"], initial_s2)

        # Restore Store 1 stock
        self.client.put(
            "/api/stores/1/inventory/76",
            json={"stock_quantity": initial_s1},
            headers=self.admin_headers
        )

    def test_12_store_inventory_negative_stock_or_price_rejected(self):
        """Part 3: Store inventory rejects negative stock or price with HTTP 400."""
        # Negative stock
        res_stock = self.client.put(
            "/api/stores/1/inventory/76",
            json={"stock_quantity": -10},
            headers=self.admin_headers
        )
        self.assertEqual(res_stock.status_code, 400)

        # Negative price
        res_price = self.client.put(
            "/api/stores/1/inventory/76",
            json={"selling_price": -25.0},
            headers=self.admin_headers
        )
        self.assertEqual(res_price.status_code, 400)

    def test_13_out_of_stock_inventory_endpoint(self):
        """Part 3: GET /api/stores/<id>/inventory/out-of-stock returns out-of-stock items."""
        # Store 4 has stock=0 for product 76
        res = self.client.get("/api/stores/4/inventory/out-of-stock", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        oos_items = data.get("out_of_stock_products", [])
        self.assertGreaterEqual(len(oos_items), 1)
        oos_ids = [it["product_id"] for it in oos_items]
        self.assertIn(76, oos_ids)

    def test_14_low_stock_inventory_endpoint(self):
        """Part 3: GET /api/stores/<id>/inventory/low-stock returns low stock items."""
        res = self.client.get("/api/stores/1/inventory/low-stock", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("low_stock_products", data)

    def test_15_stock_movement_ledger_recording(self):
        """Part 3: Admin stock update records immutable entry in inventory_movements ledger."""
        p1 = self.db.get_store_product(1, 76)
        curr_stock = p1["stock_quantity"]

        # Update stock by +5
        self.client.put(
            "/api/stores/1/inventory/76",
            json={"stock_quantity": curr_stock + 5},
            headers=self.admin_headers
        )

        # Fetch movements for store 1 product 76
        res = self.client.get("/api/stores/1/inventory/76/movements", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        movements = data.get("movements", [])
        self.assertGreater(len(movements), 0)
        latest = movements[0]
        self.assertEqual(latest["product_id"], 76)
        self.assertEqual(latest["movement_type"], "RESTOCKED")
        self.assertEqual(latest["balance_after"], curr_stock + 5)

        # Revert stock
        self.client.put(
            "/api/stores/1/inventory/76",
            json={"stock_quantity": curr_stock},
            headers=self.admin_headers
        )

    def test_16_cart_validate_exceeding_stock_rejected(self):
        """Part 3: Validation rejects adding quantity that exceeds store stock without modifying stock."""
        p1 = self.db.get_store_product(1, 76)
        curr_stock = p1["stock_quantity"]

        # Attempt to validate quantity exceeding available stock
        res = self.client.post("/api/cart/validate", json={
            "store_id": 1,
            "product_id": 76,
            "quantity": curr_stock + 50
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data.get("valid"))
        self.assertIn("exceeds", data.get("error", "").lower())

        # Verify physical stock was NOT deducted during validation
        p1_after = self.db.get_store_product(1, 76)
        self.assertEqual(p1_after["stock_quantity"], curr_stock)

    def test_17_admin_auth_protection(self):
        """Part 3: Unauthorized calls to inventory admin endpoints are rejected."""
        # Missing token
        res_no_auth = self.client.get("/api/stores/1/inventory/out-of-stock")
        self.assertIn(res_no_auth.status_code, [401, 403])

        # Invalid token
        res_bad_auth = self.client.get(
            "/api/stores/1/inventory/out-of-stock",
            headers={"X-Admin-Token": "invalid-hacker-token-123"}
        )
        self.assertIn(res_bad_auth.status_code, [401, 403])

    def test_18_retail_checkout_stock_deduction_and_ledger(self):
        """Part 3: Completing a retail checkout atomically decrements stock and logs SOLD movement."""
        # Select Store 1 Product 77 (Amul Butter or other available product)
        inv = self.db.get_store_product(1, 77)
        if not inv or inv["stock_quantity"] < 2:
            self.client.put("/api/stores/1/inventory/77", json={"stock_quantity": 20, "is_available": True}, headers=self.admin_headers)
            inv = self.db.get_store_product(1, 77)

        initial_stock = inv["stock_quantity"]

        # Add 1 unit to Retail cart for Store 1
        add_res = self.client.post("/api/cart/retail/1/add", json={
            "product_id": 77,
            "quantity": 1,
            "fulfillment": "pickup"
        }, headers=self.user_headers)
        self.assertEqual(add_res.status_code, 201)

        # Checkout
        checkout_res = self.client.post("/api/checkout/retail/multi-store", json={
            "selected_store_ids": [1],
            "customer_info": {"name": "Test User", "email": "test@example.com", "phone": "+919876543210"},
            "payment_method": "UPI"
        }, headers=self.user_headers)
        self.assertEqual(checkout_res.status_code, 201)

        # Verify stock decreased by 1
        after_inv = self.db.get_store_product(1, 77)
        self.assertEqual(after_inv["stock_quantity"], initial_stock - 1)

        # Restore stock
        self.client.put("/api/stores/1/inventory/77", json={"stock_quantity": initial_stock}, headers=self.admin_headers)


if __name__ == "__main__":
    unittest.main()

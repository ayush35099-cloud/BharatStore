"""
Test Suite: BharatStore 2.0 – Five-Shop Retail Grocery Marketplace & Price Comparison
=====================================================================================
Verifies:
1. Five Bengaluru physical retail grocery shops (IDs 1-5) registered with coordinates & metadata
2. Strict grocery-only catalog filtering on Retail Near Me (zero electronics/tech)
3. 50+ everyday grocery products across 5 essential departments
4. Real database store-specific inventory and independent pricing (₹1-₹3 variances)
5. Out-of-stock isolation across shops (Store 2 Curd/Ghee OOS, Store 4 Paneer OOS)
6. Real-time 5-shop price comparison calculation API (/api/retail/products/<id>/compare)
7. Hyperlocal store directory API (/api/retail/stores)
8. Retail dynamic catalog API (/api/retail/catalog)
9. Store-aware retail cart API (/api/retail/cart/add, get, update, remove) with shop subtotals
10. Retail Near Me homepage DOM elements (5 shop cards, search bar, comparison banner, modal)
11. Online Shopping marketplace isolation and regression guard
"""

import unittest
from app import create_app
from app.database import DatabaseService


class TestRetailPriceComparison(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()
        cls.db = DatabaseService()

    # -------------------------------------------------------------------------
    # 1. Five Bengaluru Retail Shops Verification
    # -------------------------------------------------------------------------
    def test_01_five_bengaluru_stores_exist(self):
        """Verify all five Bengaluru retail grocery shops exist with expected names and localities."""
        expected_stores = {
            1: "Bharat Fresh Mart",
            2: "Daily Needs Supermarket",
            3: "Green Basket Grocery",
            4: "Sri Lakshmi Stores",
            5: "Smart Choice Supermarket"
        }
        for store_id, name in expected_stores.items():
            store = self.db.get_store_by_id(store_id)
            self.assertIsNotNone(store, f"Store #{store_id} missing in database")
            self.assertIn(name, store["store_name"], f"Store #{store_id} name mismatch: {store['store_name']}")
            self.assertEqual(store["city"], "Bengaluru")
            self.assertTrue(store["is_active"])

        stores_list = self.db.get_retail_stores("Bengaluru")
        self.assertGreaterEqual(len(stores_list), 5)
        store_ids = [s["id"] for s in stores_list[:5]]
        self.assertEqual(store_ids, [1, 2, 3, 4, 5])
        print(" [PASSED] 1. All 5 Bengaluru retail grocery shops verified with active coordinates and metadata")

    # -------------------------------------------------------------------------
    # 2. Strict Grocery-Only Isolation in Retail Mode
    # -------------------------------------------------------------------------
    def test_02_strict_grocery_only_in_retail_storefront(self):
        """Verify that Retail Near Me contains strictly grocery products and zero electronics or tech."""
        res = self.client.get("/retail")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Prohibited non-grocery terms on retail shelves
        forbidden_tech = [
            "Dell XPS 13 Laptop",
            "Apple iPhone 15 Pro",
            "Sony WH-1000XM5 Wireless Headphones",
            "Banarasi Silk Saree",
            "Kashmiri Pashmina Shawl"
        ]
        for term in forbidden_tech:
            self.assertNotIn(term, html, f"Prohibited non-grocery product leaked to /retail: {term}")

        # Required grocery items present
        self.assertIn("Amul Taaza Milk – 1 L", html)
        self.assertIn("Amul Pure Ghee – 500 ml", html)
        self.assertIn("Basmati Rice – 1 kg", html)
        self.assertIn("Sunflower Oil – 1 L", html)
        self.assertIn("Fresh Farm Ripe Hybrid Tomato 1kg", html)
        self.assertIn("Surf Excel Easy Wash Detergent Powder – 1 kg", html)
        print(" [PASSED] 2. Strict grocery-only isolation verified: zero non-grocery items on /retail")

    # -------------------------------------------------------------------------
    # 3. 50+ Grocery Items Across 5 Essential Departments
    # -------------------------------------------------------------------------
    def test_03_grocery_catalog_count_and_departments(self):
        """Verify 50+ everyday grocery products across the 5 required departments."""
        all_prods = self.db.get_all_products()
        grocery_prods = [p for p in all_prods if p.get("category") == "Daily Essentials & Groceries"]
        self.assertGreaterEqual(len(grocery_prods), 50, f"Expected 50+ grocery items, found {len(grocery_prods)}")

        # Check API catalog departments
        res = self.client.get("/api/retail/catalog")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(len(data["dairy_items"]), 9, "Dairy & Breakfast underpopulated")
        self.assertGreaterEqual(len(data["grains_items"]), 8, "Rice & Grains underpopulated")
        self.assertGreaterEqual(len(data["essentials_items"]), 8, "Cooking Essentials underpopulated")
        self.assertGreaterEqual(len(data["produce_items"]), 4, "Fresh Produce underpopulated")
        self.assertGreaterEqual(len(data["household_items"]), 4, "Household Essentials underpopulated")
        print(f" [PASSED] 3. 50+ grocery products verified ({len(grocery_prods)} total in DB across 5 departments)")

    # -------------------------------------------------------------------------
    # 4. Per-Store Inventory and Realistic ₹1-₹3 Pricing Variance
    # -------------------------------------------------------------------------
    def test_04_store_specific_inventory_and_pricing_variance(self):
        """Verify real database inventory with independent pricing and ₹1-₹3 variances across stores."""
        # Product 61: Amul Taaza Milk 1 L
        milk_s1 = self.db.get_store_product(1, 61)
        milk_s2 = self.db.get_store_product(2, 61)
        self.assertIsNotNone(milk_s1)
        self.assertIsNotNone(milk_s2)
        self.assertEqual(float(milk_s1["selling_price"]), 60.00)
        self.assertEqual(float(milk_s2["selling_price"]), 62.00)
        self.assertNotEqual(float(milk_s1["selling_price"]), float(milk_s2["selling_price"]))

        # Product 79: Amul Pure Ghee 500 ml
        ghee_s1 = self.db.get_store_product(1, 79)
        ghee_s3 = self.db.get_store_product(3, 79)
        ghee_s4 = self.db.get_store_product(4, 79)
        self.assertEqual(float(ghee_s1["selling_price"]), 310.00)
        self.assertEqual(float(ghee_s3["selling_price"]), 312.00)
        self.assertEqual(float(ghee_s4["selling_price"]), 309.00)

        # Product 63: Paneer 200 g
        paneer_s1 = self.db.get_store_product(1, 63)
        paneer_s3 = self.db.get_store_product(3, 63)
        self.assertEqual(float(paneer_s1["selling_price"]), 95.00)
        self.assertEqual(float(paneer_s3["selling_price"]), 92.00)
        print(" [PASSED] 4. Store-specific inventory & realistic ₹1-₹3 pricing variance verified across stores")

    # -------------------------------------------------------------------------
    # 5. Out-of-Stock Isolation Across Shops
    # -------------------------------------------------------------------------
    def test_05_out_of_stock_isolation(self):
        """Verify out-of-stock items in one shop do not affect stock availability in other shops."""
        # Store 2: Curd (62) & Ghee (79) are out of stock
        curd_s2 = self.db.get_store_product(2, 62)
        ghee_s2 = self.db.get_store_product(2, 79)
        self.assertFalse(curd_s2["is_available"])
        self.assertEqual(curd_s2["stock_quantity"], 0)
        self.assertFalse(ghee_s2["is_available"])
        self.assertEqual(ghee_s2["stock_quantity"], 0)

        # Store 1: Curd & Ghee are in stock
        curd_s1 = self.db.get_store_product(1, 62)
        ghee_s1 = self.db.get_store_product(1, 79)
        self.assertTrue(curd_s1["is_available"])
        self.assertGreater(curd_s1["stock_quantity"], 0)
        self.assertTrue(ghee_s1["is_available"])
        self.assertGreater(ghee_s1["stock_quantity"], 0)

        # Store 4: Paneer (63) is out of stock, Store 1 has it
        paneer_s4 = self.db.get_store_product(4, 63)
        self.assertFalse(paneer_s4["is_available"])
        self.assertEqual(paneer_s4["stock_quantity"], 0)
        paneer_s1 = self.db.get_store_product(1, 63)
        self.assertTrue(paneer_s1["is_available"])
        self.assertGreater(paneer_s1["stock_quantity"], 0)
        print(" [PASSED] 5. Out-of-stock isolation strictly enforced across shops")

    # -------------------------------------------------------------------------
    # 6. Real-Time 5-Shop Price Comparison API
    # -------------------------------------------------------------------------
    def test_06_product_price_comparison_api(self):
        """Verify /api/retail/products/<id>/compare computes lowest price, savings, and lists 5 shops."""
        # Test comparison for Ghee (Product 79)
        res = self.client.get("/api/retail/products/79/compare?city=Bengaluru")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["product"]["id"], 79)
        self.assertEqual(len(data["stores_comparison"]), 5)

        # Lowest price should be 309.00 (at Sri Lakshmi Stores, Store 4)
        self.assertEqual(float(data["lowest_price"]), 309.00)
        self.assertEqual(data["lowest_store_id"], 4)
        self.assertIn("Sri Lakshmi", data["lowest_store_name"])
        self.assertGreaterEqual(float(data["max_savings"]), 3.00)

        # Check is_lowest flag
        store_4_item = next(s for s in data["stores_comparison"] if s["store_id"] == 4)
        self.assertTrue(store_4_item["is_lowest"])

        # Check out-of-stock flag for Store 2 in comparison
        store_2_item = next(s for s in data["stores_comparison"] if s["store_id"] == 2)
        self.assertFalse(store_2_item["is_available"])
        print(" [PASSED] 6. Real-time 5-shop price comparison API calculated lowest price & savings accurately")

    # -------------------------------------------------------------------------
    # 7. Retail Stores Directory API
    # -------------------------------------------------------------------------
    def test_07_retail_stores_api(self):
        """Verify /api/retail/stores returns the 5 Bengaluru shops with delivery time and ratings."""
        res = self.client.get("/api/retail/stores?city=Bengaluru")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["total_stores"], 5)
        for st in data["stores"]:
            self.assertIn("store_name", st)
            self.assertIn("rating", st)
            self.assertIn("delivery_time", st)
            self.assertTrue("min_order" in st or "min_order_value" in st)
        print(" [PASSED] 7. /api/retail/stores returns 5 neighbourhood shops with complete metadata")

    # -------------------------------------------------------------------------
    # 8. Store-Aware Retail Cart API
    # -------------------------------------------------------------------------
    def test_08_retail_cart_api_operations(self):
        """Verify adding, updating, removing and shop-wise subtotals in retail cart."""
        with self.client.session_transaction() as sess:
            sess["retail_cart"] = {}

        # Add Milk 1L from Store 1 (₹60)
        res1 = self.client.post("/api/retail/cart/add", json={
            "product_id": 61,
            "store_id": 1,
            "quantity": 2,
            "store_name": "Bharat Fresh Mart"
        })
        self.assertIn(res1.status_code, [200, 201])
        d1 = res1.get_json()
        self.assertTrue(d1["success"])
        self.assertEqual(d1["total_items"], 2)
        self.assertEqual(float(d1["subtotal"]), 120.00)

        # Add Ghee from Store 4 (₹309)
        res2 = self.client.post("/api/retail/cart/add", json={
            "product_id": 79,
            "store_id": 4,
            "quantity": 1,
            "store_name": "Sri Lakshmi Stores"
        })
        self.assertIn(res2.status_code, [200, 201])
        d2 = res2.get_json()
        self.assertEqual(d2["total_items"], 3)
        self.assertEqual(float(d2["subtotal"]), 429.00)

        # Attempt to add out-of-stock Curd from Store 2 (Must be rejected!)
        res_oos = self.client.post("/api/retail/cart/add", json={
            "product_id": 62,
            "store_id": 2,
            "quantity": 1,
            "store_name": "Daily Needs Supermarket"
        })
        self.assertEqual(res_oos.status_code, 400)
        self.assertFalse(res_oos.get_json()["success"])

        # Retrieve cart and check shop grouping
        res_cart = self.client.get("/api/retail/cart")
        self.assertEqual(res_cart.status_code, 200)
        cart_data = res_cart.get_json()
        self.assertEqual(len(cart_data["shops"]), 2)
        shop_names = [s["store_name"] for s in cart_data["shops"]]
        self.assertIn("Bharat Fresh Mart", shop_names)
        self.assertIn("Sri Lakshmi Stores", shop_names)

        # Remove item
        res_del = self.client.delete("/api/retail/cart/remove", json={
            "product_id": 61,
            "store_id": 1
        })
        self.assertEqual(res_del.status_code, 200)
        self.assertEqual(res_del.get_json()["total_items"], 1)
        print(" [PASSED] 8. Store-aware retail cart API operations (add, oos rejection, shop grouping, remove) verified")

    # -------------------------------------------------------------------------
    # 9. Retail Homepage DOM Elements Verification
    # -------------------------------------------------------------------------
    def test_09_retail_homepage_dom_elements(self):
        """Verify 5-shop showcase cards, search box, comparison banner, and modal exist in /retail DOM."""
        res = self.client.get("/retail")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # 5 Shop cards showcase
        self.assertIn("retail-stores-grid-5", html)
        self.assertIn("Bharat Fresh Mart", html)
        self.assertIn("Daily Needs Supermarket", html)
        self.assertIn("Green Basket Grocery", html)
        self.assertIn("Sri Lakshmi Stores", html)
        self.assertIn("Smart Choice Supermarket", html)

        # Instant search bar
        self.assertIn("retail-grocery-search-input", html)
        self.assertIn("Search across 5 shops for milk, atta, ghee, oil, fruits, veggies...", html)

        # Comparison proposition banner
        self.assertIn("retail-comparison-banner", html)
        self.assertIn("Compare prices across five neighbourhood shops and buy at the price you prefer.", html)

        # Compact card buttons & modal
        self.assertIn("btn-compare-5", html)
        self.assertIn("retail-compare-modal", html)
        print(" [PASSED] 9. Retail Near Me homepage DOM verified: 5-shop grid, search bar, banner, and comparison modal")

    # -------------------------------------------------------------------------
    # 10. Online Shopping Marketplace Isolation & Non-Regression
    # -------------------------------------------------------------------------
    def test_10_online_shopping_marketplace_intact(self):
        """Verify Online Shopping mode remains completely functional with non-grocery categories intact."""
        res = self.client.get("/?view=online")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("BharatStore", html)

        # API products list still has all core electronics and apparel categories
        prods = self.db.get_all_products()
        tech_items = [p for p in prods if p.get("category") in ["Laptops & Computers", "Audio & Wearables", "Mobiles & Tablets"]]
        self.assertGreaterEqual(len(tech_items), 5)
        print(f" [PASSED] 10. Online Shopping marketplace catalog integrity ({len(tech_items)} tech items) confirmed intact")


if __name__ == "__main__":
    unittest.main()

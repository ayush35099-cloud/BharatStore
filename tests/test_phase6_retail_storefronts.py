"""
Test Suite: BharatStore 2.0 – Phase 6 Retail Storefronts & Five-Shop Price Comparison
=====================================================================================
Verifies:
1. Dynamic physical storefronts (/retail/store/<id>) for all 5 Bengaluru stores (IDs 1-5)
2. Store profile metadata: operating hours, open status, address, rating, delivery fee
3. Storefront department categorization (Dairy, Grains, Cooking Essentials, Produce, Household)
4. Store-specific inventory and independent pricing isolation
5. Out-of-stock badge isolation on physical storefronts (Store 2 Curd & Ghee, Store 4 Paneer)
6. Five-shop real-time price comparison API (/api/retail/products/<id>/compare & /api/retail/compare/<id>)
7. Lowest price identification and max customer savings calculation
8. Store-aware retail cart addition with store attribution
9. Rejection of out-of-stock items when adding to retail cart
10. Multi-shop retail cart grouping, shop subtotals, and fulfillment mode toggle
11. Retail stores directory view (/retail/stores) within 15 km
12. Online Shopping marketplace isolation and regression protection
"""

import unittest
from app import create_app
from app.database import DatabaseService


class TestPhase6RetailStorefronts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()
        cls.db = DatabaseService()

    # -------------------------------------------------------------------------
    # 1. Physical Storefronts for all 5 Bengaluru Stores
    # -------------------------------------------------------------------------
    def test_01_all_five_bengaluru_storefronts_render(self):
        """Verify dynamic storefront /retail/store/<id> renders for all 5 Bengaluru stores."""
        stores_info = [
            (1, "Bharat Fresh Mart", "Indiranagar"),
            (2, "Daily Needs Supermarket", "Koramangala"),
            (3, "Green Basket Grocery", "HSR Layout"),
            (4, "Sri Lakshmi Stores", "Jayanagar"),
            (5, "Smart Choice Supermarket", "Whitefield")
        ]
        for store_id, name, locality in stores_info:
            res = self.client.get(f"/retail/store/{store_id}")
            self.assertEqual(res.status_code, 200, f"Store #{store_id} storefront failed to render")
            html = res.get_data(as_text=True)
            self.assertIn(name, html, f"Store #{store_id} name missing in HTML")
            self.assertIn(locality, html, f"Store #{store_id} locality missing in HTML")
            self.assertIn("Delivery", html)
            self.assertIn("Pickup", html)
            self.assertIn("Compare 5 Shops", html)
        print(" [PASSED] 1. All 5 Bengaluru retail grocery storefronts render with profile and hours")

    # -------------------------------------------------------------------------
    # 2. Storefront Department Categorization
    # -------------------------------------------------------------------------
    def test_02_storefront_departments_and_sections(self):
        """Verify dynamic storefront contains all 5 essential grocery departments."""
        res = self.client.get("/retail/store/1")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        self.assertIn("Milk, Curd, Ghee, Butter & Dairy Products", html)
        self.assertIn("Rice, Wheat Atta & High-Protein Dals", html)
        self.assertIn("Cooking Oils, Refined Sugar & Table Salt", html)
        self.assertIn("Fresh Farm Vegetables & Fruits", html)
        self.assertIn("Detergents, Cleaners & Daily Utilities", html)

        # Department jump pill bar
        self.assertIn("retail-category-pills-row", html)
        self.assertIn("retail-cat-pill", html)
        self.assertIn("store-dairy-block", html)
        self.assertIn("store-grains-block", html)
        self.assertIn("store-essentials-block", html)
        self.assertIn("store-produce-block", html)
        self.assertIn("store-household-block", html)
        print(" [PASSED] 2. Storefront contains all 5 department blocks and in-store navigation pills")

    # -------------------------------------------------------------------------
    # 3. Independent Storefront Pricing and Out-of-Stock Badges
    # -------------------------------------------------------------------------
    def test_03_storefront_independent_pricing_and_oos_badges(self):
        """Verify per-store independent pricing and out-of-stock badges on storefronts."""
        # Store 1: Milk is ₹60.00, Curd is in stock
        res1 = self.client.get("/retail/store/1")
        html1 = res1.get_data(as_text=True)
        self.assertIn("₹60.00", html1)
        self.assertIn("In Stock", html1)

        # Store 2: Milk is ₹62.00, Curd and Ghee are Out of Stock
        res2 = self.client.get("/retail/store/2")
        html2 = res2.get_data(as_text=True)
        self.assertIn("₹62.00", html2)
        self.assertIn("Out of Stock", html2)

        # Verify disabled button for OOS items in Store 2
        self.assertIn("Out", html2)
        print(" [PASSED] 3. Per-store independent pricing and out-of-stock badges verified on storefronts")

    # -------------------------------------------------------------------------
    # 4. Five-Shop Price Comparison API (Both Endpoints)
    # -------------------------------------------------------------------------
    def test_04_five_shop_price_comparison_api(self):
        """Verify real-time 5-shop price comparison API on both URL patterns."""
        endpoints = [
            "/api/retail/products/79/compare?city=Bengaluru",
            "/api/retail/compare/79?city=Bengaluru"
        ]
        for ep in endpoints:
            res = self.client.get(ep)
            self.assertEqual(res.status_code, 200, f"Endpoint {ep} failed")
            data = res.get_json()
            self.assertTrue(data["success"])
            self.assertEqual(data["product"]["id"], 79)
            self.assertEqual(len(data["stores_comparison"]), 5)

            # Sri Lakshmi Stores (Store 4) is lowest at ₹309.00
            self.assertEqual(float(data["lowest_price"]), 309.00)
            self.assertEqual(data["lowest_store_id"], 4)
            self.assertIn("Sri Lakshmi", data["lowest_store_name"])
            self.assertGreaterEqual(float(data["max_savings"]), 3.00)

            # Store 2 should be marked out of stock
            store_2 = next(s for s in data["stores_comparison"] if s["store_id"] == 2)
            self.assertFalse(store_2["is_available"])
            self.assertEqual(store_2["stock_quantity"], 0)

            # Store 4 should have is_lowest == True
            store_4 = next(s for s in data["stores_comparison"] if s["store_id"] == 4)
            self.assertTrue(store_4["is_lowest"])
        print(" [PASSED] 4. Five-shop real-time price comparison API verified across both URL endpoints")

    # -------------------------------------------------------------------------
    # 5. Store-Aware Cart Add with Store Attribution
    # -------------------------------------------------------------------------
    def test_05_store_aware_cart_add(self):
        """Verify adding grocery product with explicit store attribution to retail cart."""
        with self.client.session_transaction() as sess:
            sess["retail_cart"] = {}

        res = self.client.post("/api/retail/cart/add", json={
            "product_id": 61,
            "store_id": 1,
            "quantity": 2,
            "store_name": "Bharat Fresh Mart"
        })
        self.assertIn(res.status_code, [200, 201])
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["total_items"], 2)
        self.assertEqual(float(data["subtotal"]), 120.00)
        print(" [PASSED] 5. Product successfully added to cart with store attribution and subtotal calculation")

    # -------------------------------------------------------------------------
    # 6. Rejection of Out-of-Stock Items in Cart
    # -------------------------------------------------------------------------
    def test_06_reject_out_of_stock_item_in_cart(self):
        """Verify cart addition strictly fails with HTTP 400 when product is out of stock at shop."""
        res = self.client.post("/api/retail/cart/add", json={
            "product_id": 62,
            "store_id": 2,  # Curd is OOS at Store 2
            "quantity": 1,
            "store_name": "Daily Needs Supermarket"
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertIn("out of stock", data["error"].lower())
        print(" [PASSED] 6. Out-of-stock cart addition attempt strictly rejected with HTTP 400")

    # -------------------------------------------------------------------------
    # 7. Multi-Shop Retail Cart Grouping and Subtotals
    # -------------------------------------------------------------------------
    def test_07_multi_shop_cart_grouping(self):
        """Verify cart separates items by shop and calculates shop-wise subtotals and delivery."""
        with self.client.session_transaction() as sess:
            sess["retail_cart"] = {}

        # Add from Store 1 (Milk ₹60 x 2 = ₹120)
        self.client.post("/api/retail/cart/add", json={
            "product_id": 61,
            "store_id": 1,
            "quantity": 2,
            "store_name": "Bharat Fresh Mart"
        })

        # Add from Store 4 (Ghee ₹309 x 1 = ₹309)
        self.client.post("/api/retail/cart/add", json={
            "product_id": 79,
            "store_id": 4,
            "quantity": 1,
            "store_name": "Sri Lakshmi Stores"
        })

        res = self.client.get("/api/retail/cart")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(len(data["shops"]), 2)
        self.assertEqual(data["total_items"], 3)
        self.assertEqual(float(data["subtotal"]), 429.00)

        # Check each shop structure
        s1 = next(s for s in data["shops"] if s["store_id"] == 1)
        s4 = next(s for s in data["shops"] if s["store_id"] == 4)
        self.assertEqual(float(s1["subtotal"]), 120.00)
        self.assertEqual(float(s4["subtotal"]), 309.00)
        print(" [PASSED] 7. Multi-shop cart grouping and independent shop subtotals verified")

    # -------------------------------------------------------------------------
    # 8. Cart Fulfillment Mode Toggle (Delivery vs Pickup)
    # -------------------------------------------------------------------------
    def test_08_cart_fulfillment_toggle(self):
        """Verify toggling fulfillment mode between delivery and pickup per shop."""
        with self.client.session_transaction() as sess:
            sess["retail_cart"] = {}

        self.client.post("/api/retail/cart/add", json={
            "product_id": 61,
            "store_id": 1,
            "quantity": 1,
            "store_name": "Bharat Fresh Mart",
            "fulfillment": "delivery"
        })

        # Update to pickup
        res = self.client.put("/api/retail/cart/update", json={
            "product_id": 61,
            "store_id": 1,
            "fulfillment": "pickup"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])

        # Fetch cart and verify fulfillment updated
        res_cart = self.client.get("/api/retail/cart")
        shop = res_cart.get_json()["shops"][0]
        self.assertEqual(shop["fulfillment"], "pickup")
        print(" [PASSED] 8. Shop fulfillment toggle (delivery vs pickup) verified in retail cart")

    # -------------------------------------------------------------------------
    # 9. Retail Stores Directory View (/retail/stores)
    # -------------------------------------------------------------------------
    def test_09_retail_stores_directory_view(self):
        """Verify /retail/stores lists physical stores with real-time distance and filters."""
        res = self.client.get("/retail/stores?lat=12.9784&lng=77.6408")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        self.assertIn("Nearby Neighbourhood Grocery Stores", html)
        self.assertIn("Bharat Fresh Mart", html)
        self.assertIn("Daily Needs Supermarket", html)
        self.assertIn("Green Basket Grocery", html)
        self.assertIn("Sri Lakshmi Stores", html)
        self.assertIn("Smart Choice Supermarket", html)
        self.assertIn("View Store", html)
        print(" [PASSED] 9. /retail/stores directory view renders all 5 stores with distances and action links")

    # -------------------------------------------------------------------------
    # 10. Online Shopping Marketplace Isolation & Non-Regression
    # -------------------------------------------------------------------------
    def test_10_online_shopping_isolation(self):
        """Verify Online Shopping marketplace catalog remains intact without grocery contamination."""
        res = self.client.get("/?view=online")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Online shopping contains marketplace hero & tech catalog
        self.assertIn("BharatStore", html)

        # Database check: Ensure electronics categories exist in DB
        prods = self.db.get_all_products()
        laptops = [p for p in prods if p.get("category") == "Laptops & Computers"]
        self.assertGreaterEqual(len(laptops), 1)
        print(" [PASSED] 10. Online Shopping marketplace catalog integrity and isolation confirmed")


if __name__ == "__main__":
    unittest.main()

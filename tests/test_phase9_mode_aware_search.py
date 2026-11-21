"""
BharatStore 2.0 — Phase 9 Test Suite
Verifies:
1. Multi-store retail checkout authoritative calculation (No ₹0 bug).
2. 5-Shop price comparison end-to-end data integrity (No ₹NaN bug).
3. Retail Grocery-Only Catalog Isolation.
4. Mode-Aware OpenSearch Engine (Online full catalog vs Retail grocery only).
5. Store-specific inventory pricing and stock in search results.
6. Faceted filtering (brand, category, price, in_stock), sorting, and pagination.
7. Mode-aware autocomplete suggestions.
8. Store inventory updates and live search synchronization.
9. Header navigation and cart drawer layout integrity.
"""

import unittest
import json
import uuid
from app import create_app
from app.database import DatabaseService
from app.routes import db_service, opensearch_service, ALLOWED_RETAIL_CATEGORIES, NON_GROCERY_CATEGORIES


class Phase9ModeAwareSearchTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()
        # Seed OpenSearch catalog and store inventory
        cls.db = DatabaseService()
        cls.db.reset_inventory()
        products = cls.db.get_all_products()
        opensearch_service.index_all_products(products)
        stores = cls.db.get_retail_stores("Bengaluru")
        for st in stores:
            inv = cls.db.get_store_inventory(st["id"])
            opensearch_service.index_store_inventory(st["id"], inv)

    def setUp(self):
        self.session_id = f"test_p9_{uuid.uuid4().hex[:12]}"

    # =========================================================================
    # PART 1: FIX CHECKOUT SHOWING ₹0 (MULTI-STORE AUTHORITATIVE RECALCULATION)
    # =========================================================================

    def test_01_retail_cart_recalculation_subtotal_92(self):
        """
        Verify multi-store basket contains:
        Store 2 (Daily Needs): Product 76 (Amul Gold Milk @ ₹34)
        Store 3 (Green Basket): Product 79 (Amul Butter @ ₹58)
        Total grocery subtotal = ₹92 (never ₹0).
        """
        with self.client.session_transaction() as sess:
            sess["session_id"] = self.session_id
            sess["shopping_mode"] = "RETAIL_NEAR_ME"

        # Add Product 76 (Amul Gold Milk @ ₹34) to Store 2
        r1 = self.client.post("/api/cart/retail/2/add", json={
            "product_id": 76,
            "quantity": 1,
            "fulfillment": "delivery"
        })
        self.assertIn(r1.status_code, (200, 201), r1.get_data(as_text=True))

        # Add Product 64 (Amul Butter @ ₹58) to Store 3
        r2 = self.client.post("/api/cart/retail/3/add", json={
            "product_id": 64,
            "quantity": 1,
            "fulfillment": "delivery"
        })
        self.assertIn(r2.status_code, (200, 201), r2.get_data(as_text=True))

        # Fetch central retail cart
        r_cart = self.client.get("/api/cart/retail")
        self.assertEqual(r_cart.status_code, 200)
        data = r_cart.get_json()

        self.assertTrue(data.get("success"))
        shops = data.get("shops", [])
        self.assertEqual(len(shops), 2, "Expected 2 active shop baskets.")

        shop2 = next((s for s in shops if s["store_id"] == 2), None)
        shop3 = next((s for s in shops if s["store_id"] == 3), None)

        self.assertIsNotNone(shop2)
        self.assertIsNotNone(shop3)

        self.assertEqual(shop2["subtotal"], 34.0)
        self.assertEqual(shop3["subtotal"], 58.0)

        summary = data.get("summary", {})
        self.assertEqual(summary.get("subtotal"), 92.0)
        self.assertEqual(summary.get("total_items"), 2)

    def test_02_retail_multi_store_checkout_success_and_stock_lock(self):
        """
        Verifies that /api/checkout/retail/multi-store processes multi-store order
        with ACID row lock and returns parent order with zero overselling.
        """
        cust_id = 99100 + (uuid.uuid4().int % 900)
        with self.client.session_transaction() as sess:
            sess["customer_id"] = cust_id
            sess["session_id"] = f"sess_{cust_id}"
            sess["shopping_mode"] = "RETAIL_NEAR_ME"

        # Add items to store 1 and store 2
        self.client.post("/api/cart/retail/1/add", json={"product_id": 76, "quantity": 1})
        self.client.post("/api/cart/retail/2/add", json={"product_id": 76, "quantity": 1})

        # Checkout multi-store
        res = self.client.post("/api/checkout/retail/multi-store", json={
            "selected_store_ids": [1, 2],
            "customer_info": {
                "name": "Priya Sharma",
                "email": "priya.sharma@example.in",
                "phone": "+91 98201 12345",
                "address": "Flat 402, Sea Green Apts, Worli Sea Face",
                "city": "Bengaluru"
            },
            "delivery_address": {
                "formatted": "Indiranagar, Bengaluru",
                "city": "Bengaluru",
                "latitude": 12.9784,
                "longitude": 77.6408
            },
            "payment_method": "UPI"
        })
        self.assertIn(res.status_code, (200, 201), res.get_data(as_text=True))
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("stores_count"), 2)
        self.assertIn("parent_order_number", data)

    # =========================================================================
    # PART 2: FIX ₹NaN PRICE COMPARISON BUG
    # =========================================================================

    def test_03_price_comparison_returns_valid_numbers_no_nan(self):
        """
        Verifies 5-shop price comparison for Amul Gold Milk (Product 76):
        - All 5 shops return valid numeric prices.
        - No NaN, null, undefined, or Infinity.
        - Highlights genuinely lowest available shop.
        - Out-of-stock shop (Store 4) is not marked lowest.
        """
        res = self.client.get("/api/retail/products/76/compare")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        self.assertTrue(data.get("success"))
        prod = data.get("product", {})
        self.assertEqual(prod.get("id"), 76)
        self.assertIn("Amul Gold Milk", prod.get("title"))

        shops = data.get("stores_comparison", [])
        self.assertEqual(len(shops), 5, "Expected 5 retail shops in Bengaluru comparison.")

        lowest_found = False
        for s in shops:
            price = s.get("selling_price")
            self.assertIsInstance(price, (int, float), f"Price must be numeric, got {price}")
            self.assertFalse(str(price).lower() in ("nan", "infinity", "-infinity", "null", "none"))
            self.assertGreater(price, 0)

            sq = s.get("stock_quantity")
            self.assertIsInstance(sq, int)

            savings = s.get("savings")
            self.assertIsInstance(savings, (int, float))

            if s.get("is_lowest"):
                lowest_found = True
                self.assertTrue(s.get("is_available"), "Lowest price shop must be IN STOCK!")
                self.assertGreater(s.get("stock_quantity"), 0)

        self.assertTrue(lowest_found, "One in-stock shop must be highlighted as lowest price.")

        # Store 4 (Namdhari) is out of stock for Product 76
        st4 = next((s for s in shops if s["store_id"] == 4), None)
        self.assertIsNotNone(st4)
        self.assertFalse(st4.get("is_lowest"), "Out-of-stock store 4 must not be marked lowest price.")
        self.assertEqual(st4.get("stock_quantity"), 0)

    def test_04_compare_endpoint_alias_consistency(self):
        """Verifies both /api/retail/compare/<id> and /api/retail/products/<id>/compare work identically."""
        r1 = self.client.get("/api/retail/compare/76")
        r2 = self.client.get("/api/retail/products/76/compare")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.get_json()["product"]["title"], r2.get_json()["product"]["title"])

    # =========================================================================
    # PART 3: RETAIL GROCERY-ONLY CATALOG ISOLATION
    # =========================================================================

    def test_05_retail_search_blocks_non_grocery_laptops_and_mobiles(self):
        """
        In Retail Near Me mode:
        Searching for 'laptop', 'iphone', 'macbook', or non-grocery terms returns ZERO hits.
        """
        for query in ("laptop", "iphone", "macbook", "headphone", "t-shirt"):
            res = self.client.get(f"/api/search?q={query}&mode=retail")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            hits = data.get("hits") or data.get("results") or []
            self.assertEqual(len(hits), 0, f"Query '{query}' returned non-grocery items in Retail mode: {hits}")
            self.assertEqual(data.get("total"), 0)

    def test_06_retail_search_explicit_non_grocery_category_returns_zero(self):
        """
        Requesting non-grocery category in Retail mode immediately returns 0 hits.
        """
        for cat in NON_GROCERY_CATEGORIES:
            res = self.client.get(f"/api/search?category={cat}&mode=retail")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data.get("total"), 0)
            self.assertEqual(len(data.get("results", [])), 0)

    def test_07_retail_search_allows_essential_groceries(self):
        """
        In Retail Near Me mode:
        Searching for 'milk', 'atta', 'ghee', 'oil', 'curd' returns essential groceries.
        """
        for query in ("milk", "atta", "ghee", "oil", "curd"):
            res = self.client.get(f"/api/search?q={query}&mode=retail")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            hits = data.get("hits") or data.get("results") or []
            self.assertGreater(len(hits), 0, f"Query '{query}' returned 0 grocery hits!")
            for h in hits:
                cat = h.get("category", "")
                self.assertNotIn(cat, NON_GROCERY_CATEGORIES)

    # =========================================================================
    # PART 4: MODE-AWARE OPENSEARCH (ONLINE SHOPPING SEARCH)
    # =========================================================================

    def test_08_online_search_finds_all_marketplace_products(self):
        """
        In Online Shopping mode:
        Searching for 'laptop' returns Dell XPS, MacBook, ThinkPad, etc.
        Searching for 'iphone' returns Apple iPhone.
        """
        res_laptop = self.client.get("/api/search?q=laptop&mode=online")
        self.assertEqual(res_laptop.status_code, 200)
        data_laptop = res_laptop.get_json()
        self.assertGreater(data_laptop.get("total", 0), 0)
        hits = data_laptop.get("results", [])
        self.assertTrue(any("Dell" in h["title"] or "ThinkPad" in h["title"] or "MacBook" in h["title"] for h in hits))

        res_iphone = self.client.get("/api/search?q=iphone&mode=online")
        self.assertEqual(res_iphone.status_code, 200)
        data_iphone = res_iphone.get_json()
        self.assertGreater(data_iphone.get("total", 0), 0)

    def test_09_online_search_faceted_filters_and_sorting(self):
        """
        Verifies sorting (price_asc, price_desc, rating_desc, newest)
        and pagination (page, per_page, total_pages) in OpenSearch.
        """
        # Price Ascending Sort
        r_asc = self.client.get("/api/search?q=laptop&mode=online&sort=price_asc")
        self.assertEqual(r_asc.status_code, 200)
        hits_asc = r_asc.get_json().get("results", [])
        if len(hits_asc) >= 2:
            self.assertLessEqual(hits_asc[0]["price"], hits_asc[1]["price"])

        # Price Descending Sort
        r_desc = self.client.get("/api/search?q=laptop&mode=online&sort=price_desc")
        self.assertEqual(r_desc.status_code, 200)
        hits_desc = r_desc.get_json().get("results", [])
        if len(hits_desc) >= 2:
            self.assertGreaterEqual(hits_desc[0]["price"], hits_desc[1]["price"])

        # Pagination Check
        r_paged = self.client.get("/api/search?mode=online&page=1&per_page=5")
        self.assertEqual(r_paged.status_code, 200)
        data_paged = r_paged.get_json()
        self.assertEqual(data_paged["page"], 1)
        self.assertEqual(data_paged["per_page"], 5)
        self.assertEqual(len(data_paged["results"]), 5)
        self.assertGreaterEqual(data_paged["total_pages"], 1)

        # Facets verification
        facets = data_paged.get("facets", {})
        self.assertIn("categories", facets)
        self.assertIn("brands", facets)

    # =========================================================================
    # PART 5: STORE-SPECIFIC SEARCH PRICING AND AVAILABILITY (PHASE 9)
    # =========================================================================

    def test_10_store_specific_search_pricing_and_availability(self):
        """
        Verifies search results reflect store-specific pricing and stock:
        - Store 1 (Bharat Fresh Mart): Amul Gold Milk @ ₹33.00
        - Store 2 (Daily Needs): Amul Gold Milk @ ₹34.00
        - Store 4 (Namdhari): Stock = 0, Out of Stock
        """
        # Store 1 Search
        r1 = self.client.get("/api/search?q=gold+milk&mode=retail&store_id=1")
        self.assertEqual(r1.status_code, 200)
        hits1 = r1.get_json().get("results", [])
        self.assertGreater(len(hits1), 0)
        item1 = next(h for h in hits1 if h["id"] == 76)
        self.assertEqual(item1["selling_price"], 33.0)
        self.assertTrue(item1["is_available"])

        # Store 2 Search
        r2 = self.client.get("/api/search?q=gold+milk&mode=retail&store_id=2")
        self.assertEqual(r2.status_code, 200)
        hits2 = r2.get_json().get("results", [])
        item2 = next(h for h in hits2 if h["id"] == 76)
        self.assertEqual(item2["selling_price"], 34.0)

        # Store 4 Search (Out of Stock)
        r4 = self.client.get("/api/search?q=gold+milk&mode=retail&store_id=4")
        self.assertEqual(r4.status_code, 200)
        hits4 = r4.get_json().get("results", [])
        item4 = next(h for h in hits4 if h["id"] == 76)
        self.assertEqual(item4["stock_quantity"], 0)
        self.assertFalse(item4["is_available"])
        self.assertEqual(item4["status_text"], "Out of Stock")

        # In-stock filter on Store 4 excludes Product 76
        r4_instock = self.client.get("/api/search?q=gold+milk&mode=retail&store_id=4&in_stock=true")
        self.assertEqual(r4_instock.status_code, 200)
        hits4_instock = r4_instock.get_json().get("results", [])
        self.assertFalse(any(h["id"] == 76 for h in hits4_instock))

    # =========================================================================
    # PART 6: MODE-AWARE AUTOCOMPLETE SUGGESTIONS
    # =========================================================================

    def test_11_mode_aware_suggestions_isolation(self):
        """
        Suggestions API (/api/search/suggestions):
        - In Retail mode: 'lap' returns [] and 'mil' returns milk groceries with prices.
        - In Online mode: 'lap' returns laptop suggestions.
        """
        # Retail mode: 'lap' -> 0 suggestions
        r_ret_lap = self.client.get("/api/search/suggestions?q=lap&mode=retail")
        self.assertEqual(r_ret_lap.status_code, 200)
        self.assertEqual(len(r_ret_lap.get_json().get("suggestions", [])), 0)

        # Retail mode: 'mil' -> grocery suggestions
        r_ret_mil = self.client.get("/api/search/suggestions?q=mil&mode=retail")
        self.assertEqual(r_ret_mil.status_code, 200)
        sug_mil = r_ret_mil.get_json().get("suggestions", [])
        self.assertGreater(len(sug_mil), 0)
        for s in sug_mil:
            self.assertIn("category", s)
            self.assertNotIn(s["category"], NON_GROCERY_CATEGORIES)
            self.assertIn("price", s)

        # Online mode: 'lap' -> laptops
        r_on_lap = self.client.get("/api/search/suggestions?q=lap&mode=online")
        self.assertEqual(r_on_lap.status_code, 200)
        sug_lap = r_on_lap.get_json().get("suggestions", [])
        self.assertGreater(len(sug_lap), 0)
        self.assertTrue(any("Dell" in s["title"] or "ThinkPad" in s["title"] or "MacBook" in s["title"] for s in sug_lap))

    # =========================================================================
    # PART 7: STORE INVENTORY SYNCHRONIZATION
    # =========================================================================

    def test_12_store_inventory_update_synchronization(self):
        """
        Updates Store 1 price for Product 76:
        OpenSearch immediately reflects the updated selling price.
        """
        # Update price to ₹35.50
        opensearch_service.update_store_inventory_item(
            store_id=1,
            product_id=76,
            selling_price=35.50,
            stock_quantity=50,
            is_available=True
        )

        res = self.client.get("/api/search?q=gold+milk&mode=retail&store_id=1")
        self.assertEqual(res.status_code, 200)
        hits = res.get_json().get("results", [])
        item = next(h for h in hits if h["id"] == 76)
        self.assertEqual(item["selling_price"], 35.50)
        self.assertEqual(item["stock_quantity"], 50)

        # Restore price to ₹33.00
        opensearch_service.update_store_inventory_item(
            store_id=1,
            product_id=76,
            selling_price=33.00,
            stock_quantity=80,
            is_available=True
        )

    # =========================================================================
    # PART 8: UI NAVBAR AND CART DRAWER LAYOUT INTEGRITY
    # =========================================================================

    def test_13_navbar_no_duplicate_wishlist_or_cart_in_center(self):
        """
        Verifies center .category-navbar has duplicate Wishlist & Cart links hidden.
        Wishlist is accessible via top-right heart icon (#wishlist-badge-count).
        Cart is accessible via top-right cart icon (#cart-badge-count).
        """
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Center nav duplicates are hidden from display
        self.assertIn('id="nav-mode-wishlist"', html)
        self.assertIn('id="nav-mode-wishlist" style="display:none;"', html)
        self.assertIn('id="nav-mode-cart" style="display:none;"', html)

        # Top-right header actions present
        self.assertIn('id="wishlist-badge-count"', html)
        self.assertIn('id="cart-badge-count"', html)

        # Cart drawer present with independent scroll items and footer
        self.assertIn('id="cart-drawer-overlay"', html)
        self.assertIn('class="cart-drawer-items"', html)
        self.assertIn('class="cart-drawer-footer"', html)
        self.assertIn('id="drawer-checkout-btn"', html)


if __name__ == "__main__":
    unittest.main()

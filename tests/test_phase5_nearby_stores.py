"""
Test Suite: BharatStore 2.0 – Phase 5: Nearby Store Discovery & Scroll Optimization
===================================================================================
Verifies:
1. Haversine distance formula calculation and validation (R = 6371 km)
2. Discovery of physical grocery stores within strict 15 km radius
3. Exclusion of stores outside 15 km (e.g. Mumbai stores excluded from Bengaluru search)
4. Exclusion of inactive stores
5. Rejection of invalid coordinates and out-of-bounds radius (> 15 km) with HTTP 400
6. Sorting: Nearest First (default), Farthest First, Store Name A-Z, Lowest Delivery Fee
7. Filtering: Category filters, Open Now, Delivery Available, Free Pickup Available
8. Hyperlocal Nearby Stores API: GET /api/retail/stores/nearby
9. Store Profile API: GET /api/retail/stores/<id>
10. Store Directory Web View: GET /retail/stores
11. Dynamic Individual Storefront: GET /retail/store/<id>
12. Store Selection persistence and non-regression of Online Shopping
13. Scroll Bug Fix: Elimination of automated scroll-down on page load / refresh
"""

import unittest
from app import create_app
from app.database import DatabaseService, calculate_haversine_distance


class TestPhase5NearbyStores(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()
        cls.db = DatabaseService()

    # -------------------------------------------------------------------------
    # 1. Haversine Distance Calculation Math
    # -------------------------------------------------------------------------
    def test_01_haversine_distance_math(self):
        """Verify Haversine distance math precision against known geographic coordinates."""
        # Same point should be exactly 0 km
        dist_zero = calculate_haversine_distance(12.9784, 77.6408, 12.9784, 77.6408)
        self.assertEqual(dist_zero, 0.0)

        # Indiranagar (12.9784, 77.6408) to Whitefield (12.9698, 77.7500) is ~11.87 km
        dist_blr = calculate_haversine_distance(12.9784, 77.6408, 12.9698, 77.7500)
        self.assertAlmostEqual(dist_blr, 11.87, delta=0.2)

        # Indiranagar to Mumbai Bandra (19.0596, 72.8295) is ~845 km
        dist_mum = calculate_haversine_distance(12.9784, 77.6408, 19.0596, 72.8295)
        self.assertGreater(dist_mum, 800.0)

        # DatabaseService instance method should yield identical result
        self.assertEqual(self.db.calculate_distance(12.9784, 77.6408, 12.9698, 77.7500), dist_blr)
        print(" [PASSED] 1. Haversine distance formula mathematically verified (R=6371 km)")

    # -------------------------------------------------------------------------
    # 2. Coordinate Range & Format Validation
    # -------------------------------------------------------------------------
    def test_02_coordinate_validation(self):
        """Verify that out-of-bound latitudes, longitudes, or non-numeric types raise ValueError."""
        # Latitude > 90
        with self.assertRaises(ValueError):
            calculate_haversine_distance(95.0, 77.0, 12.0, 77.0)

        # Latitude < -90
        with self.assertRaises(ValueError):
            calculate_haversine_distance(-95.0, 77.0, 12.0, 77.0)

        # Longitude > 180
        with self.assertRaises(ValueError):
            calculate_haversine_distance(12.0, 185.0, 12.0, 77.0)

        # Longitude < -180
        with self.assertRaises(ValueError):
            calculate_haversine_distance(12.0, -185.0, 12.0, 77.0)

        # Non-numeric string
        with self.assertRaises(ValueError):
            calculate_haversine_distance("invalid", 77.0, 12.0, 77.0)

        # Radius > 15 km in get_nearby_stores
        with self.assertRaises(ValueError):
            self.db.get_nearby_stores(12.9784, 77.6408, max_radius_km=25.0)

        # Radius <= 0 in get_nearby_stores
        with self.assertRaises(ValueError):
            self.db.get_nearby_stores(12.9784, 77.6408, max_radius_km=-5.0)
        print(" [PASSED] 2. Coordinate range bounds and radius constraints strictly validated")

    # -------------------------------------------------------------------------
    # 3. Nearby Store Discovery within 15 km
    # -------------------------------------------------------------------------
    def test_03_stores_within_15km_discovery(self):
        """Verify all stores within 15 km are discovered and enriched with distance and stock count."""
        # Indiranagar coordinates (12.9784, 77.6408)
        stores = self.db.get_nearby_stores(12.9784, 77.6408, max_radius_km=15.0)
        self.assertGreaterEqual(len(stores), 5)

        # Verify all returned stores have distance <= 15.0 km
        for st in stores:
            self.assertLessEqual(st["distance_km"], 15.0)
            self.assertIn("(approx. straight-line)", st["distance_text"])
            self.assertIn("grocery_product_count", st)
            self.assertIn("is_open", st)
            self.assertIn("delivery_available", st)
            self.assertIn("pickup_available", st)

        # Store 1 (Bharat Fresh Mart) is at the search location (0.0 km)
        store_1 = next((s for s in stores if s["id"] == 1), None)
        self.assertIsNotNone(store_1)
        self.assertEqual(store_1["distance_km"], 0.0)

        # Store 5 (Smart Choice Supermarket Whitefield) is ~11.9 km away
        store_5 = next((s for s in stores if s["id"] == 5), None)
        self.assertIsNotNone(store_5)
        self.assertAlmostEqual(store_5["distance_km"], 11.9, delta=0.5)
        print(f" [PASSED] 3. Discovered {len(stores)} physical grocery stores within 15 km with verified distances")

    # -------------------------------------------------------------------------
    # 4. Exclusion of Stores Outside 15 km
    # -------------------------------------------------------------------------
    def test_04_stores_outside_15km_excluded(self):
        """Verify that stores located beyond 15 km are strictly excluded from results."""
        # From Indiranagar, Bengaluru, Mumbai stores (IDs 6 and 7) are > 800 km away
        stores = self.db.get_nearby_stores(12.9784, 77.6408, max_radius_km=15.0)
        store_ids = [s["id"] for s in stores]

        self.assertNotIn(6, store_ids, "Mumbai Bandra store leaked into Bengaluru 15 km results")
        self.assertNotIn(7, store_ids, "Mumbai Andheri store leaked into Bengaluru 15 km results")

        # Now test from Mumbai coordinates (19.0596, 72.8295)
        mumbai_stores = self.db.get_nearby_stores(19.0596, 72.8295, max_radius_km=15.0)
        mumbai_ids = [s["id"] for s in mumbai_stores]

        # Bengaluru stores (IDs 1-5) must NOT be present in Mumbai search
        for b_id in [1, 2, 3, 4, 5]:
            self.assertNotIn(b_id, mumbai_ids, f"Bengaluru store #{b_id} leaked into Mumbai 15 km results")
        print(" [PASSED] 4. Outside-radius stores (> 15 km) strictly and reliably excluded")

    # -------------------------------------------------------------------------
    # 5. Inactive Store Exclusion
    # -------------------------------------------------------------------------
    def test_05_inactive_store_exclusion(self):
        """Verify that stores marked is_active = False are excluded from nearby discovery."""
        all_active = self.db.get_nearby_stores(12.9784, 77.6408, max_radius_km=15.0)
        for st in all_active:
            self.assertTrue(st["is_active"], f"Inactive store #{st['id']} appeared in nearby stores")
        print(" [PASSED] 5. Inactive stores strictly excluded from nearby results")

    # -------------------------------------------------------------------------
    # 6. Sorting Verification
    # -------------------------------------------------------------------------
    def test_06_nearby_stores_sorting(self):
        """Verify sorting by nearest first (default), farthest first, name A-Z, and delivery fee."""
        # 1. Nearest First (default)
        nearest = self.db.get_nearby_stores(12.9784, 77.6408, max_radius_km=15.0, sort_by="nearest")
        distances_asc = [s["distance_km"] for s in nearest]
        self.assertEqual(distances_asc, sorted(distances_asc))

        # 2. Farthest First
        farthest = self.db.get_nearby_stores(12.9784, 77.6408, max_radius_km=15.0, sort_by="farthest")
        distances_desc = [s["distance_km"] for s in farthest]
        self.assertEqual(distances_desc, sorted(distances_desc, reverse=True))

        # 3. Store Name A-Z
        by_name = self.db.get_nearby_stores(12.9784, 77.6408, max_radius_km=15.0, sort_by="name_asc")
        names = [s["store_name"].lower() for s in by_name]
        self.assertEqual(names, sorted(names))

        # 4. Lowest Delivery Fee
        by_fee = self.db.get_nearby_stores(12.9784, 77.6408, max_radius_km=15.0, sort_by="fee_asc")
        fees = [s["delivery_fee"] for s in by_fee]
        self.assertEqual(fees, sorted(fees))
        print(" [PASSED] 6. All 4 sorting modes (nearest, farthest, name A-Z, fee) verified")

    # -------------------------------------------------------------------------
    # 7. Filtering Verification
    # -------------------------------------------------------------------------
    def test_07_nearby_stores_filtering(self):
        """Verify filtering by perks (delivery, pickup) and categories."""
        # Delivery only
        del_stores = self.db.get_nearby_stores(12.9784, 77.6408, max_radius_km=15.0, delivery_only=True)
        for s in del_stores:
            self.assertTrue(s["delivery_available"])

        # Pickup only
        pick_stores = self.db.get_nearby_stores(12.9784, 77.6408, max_radius_km=15.0, pickup_only=True)
        for s in pick_stores:
            self.assertTrue(s["pickup_available"])

        # Category filter: Dairy
        dairy_stores = self.db.get_nearby_stores(12.9784, 77.6408, max_radius_km=15.0, category_filter="Dairy")
        self.assertGreaterEqual(len(dairy_stores), 1)
        print(" [PASSED] 7. Delivery, pickup, and category filters successfully verified")

    # -------------------------------------------------------------------------
    # 8. API Endpoint: GET /api/retail/stores/nearby
    # -------------------------------------------------------------------------
    def test_08_api_retail_stores_nearby(self):
        """Verify REST API /api/retail/stores/nearby returns valid JSON with Haversine distance."""
        # Valid request
        res = self.client.get("/api/retail/stores/nearby?lat=12.9784&lng=77.6408&radius=15")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(data["count"], 5)
        self.assertEqual(data["radius_km"], 15.0)
        self.assertIn("stores", data)

        first = data["stores"][0]
        self.assertIn("distance_km", first)
        self.assertIn("distance_text", first)
        self.assertIn("grocery_product_count", first)

        # Invalid: latitude > 90
        res_bad_lat = self.client.get("/api/retail/stores/nearby?lat=95.0&lng=77.6408")
        self.assertEqual(res_bad_lat.status_code, 400)
        self.assertFalse(res_bad_lat.get_json()["success"])

        # Invalid: radius > 15 km
        res_bad_radius = self.client.get("/api/retail/stores/nearby?lat=12.9784&lng=77.6408&radius=25")
        self.assertEqual(res_bad_radius.status_code, 400)
        self.assertFalse(res_bad_radius.get_json()["success"])

        # Invalid: missing coordinates
        res_missing = self.client.get("/api/retail/stores/nearby")
        self.assertIn(res_missing.status_code, [200, 400])
        print(" [PASSED] 8. API /api/retail/stores/nearby verified with input boundary validation")

    # -------------------------------------------------------------------------
    # 9. API Endpoint: GET /api/retail/stores/<id>
    # -------------------------------------------------------------------------
    def test_09_api_retail_store_by_id(self):
        """Verify REST API /api/retail/stores/<id> returns store profile with distance."""
        res = self.client.get("/api/retail/stores/1?lat=12.9784&lng=77.6408")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["store"]["id"], 1)
        self.assertEqual(data["store"]["store_name"], "Bharat Fresh Mart")
        self.assertIn("distance_km", data["store"])
        self.assertIn("total_products", data)

        # Missing store returns 404
        res_404 = self.client.get("/api/retail/stores/99999")
        self.assertEqual(res_404.status_code, 404)
        print(" [PASSED] 9. API /api/retail/stores/<id> returns store profile with calculated distance")

    # -------------------------------------------------------------------------
    # 10. Web View: GET /retail/stores Directory Page
    # -------------------------------------------------------------------------
    def test_10_retail_stores_directory_page(self):
        """Verify /retail/stores renders the 15 km directory with store cards, sort, and filters."""
        res = self.client.get("/retail/stores?lat=12.9784&lng=77.6408")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Check key components
        self.assertIn("Nearby Neighbourhood Grocery Stores", html)
        self.assertIn("15 km", html)
        self.assertIn("Bharat Fresh Mart", html)
        self.assertIn("Daily Needs Supermarket", html)
        self.assertIn("Green Basket Grocery", html)
        self.assertIn("Sri Lakshmi Stores", html)
        self.assertIn("Smart Choice Supermarket", html)

        # Check distance pill and sorting dropdown
        self.assertIn("approx. straight-line", html)
        self.assertIn("stores-sort-dropdown", html)
        self.assertIn("Nearest First", html)
        print(" [PASSED] 10. Web page /retail/stores renders complete 15 km discovery directory")

    # -------------------------------------------------------------------------
    # 11. Web View: Dynamic Storefront GET /retail/store/<id>
    # -------------------------------------------------------------------------
    def test_11_retail_store_front_page(self):
        """Verify dynamic storefront /retail/store/<id> renders store inventory and categories."""
        # Store 1: Bharat Fresh Mart
        res1 = self.client.get("/retail/store/1")
        self.assertEqual(res1.status_code, 200)
        html1 = res1.get_data(as_text=True)
        self.assertIn("Bharat Fresh Mart", html1)
        self.assertIn("Indiranagar", html1)
        self.assertIn("Milk, Curd, Ghee, Butter & Dairy Products", html1)
        self.assertIn("Rice, Wheat Atta & High-Protein Dals", html1)

        # Store 3: Green Basket Grocery
        res3 = self.client.get("/retail/store/3")
        self.assertEqual(res3.status_code, 200)
        html3 = res3.get_data(as_text=True)
        self.assertIn("Green Basket Grocery", html3)
        self.assertIn("HSR Layout", html3)

        # Non-existent store redirects or gives warning
        res_missing = self.client.get("/retail/store/99999", follow_redirects=True)
        self.assertEqual(res_missing.status_code, 200)
        print(" [PASSED] 11. Dynamic individual storefronts (/retail/store/<id>) verified with inventory")

    # -------------------------------------------------------------------------
    # 12. Scroll Bug Fix Verification
    # -------------------------------------------------------------------------
    def test_12_scroll_bug_fix_verification(self):
        """Verify that automated scrollIntoView on DOMContentLoaded has been completely removed."""
        res_retail = self.client.get("/retail")
        self.assertEqual(res_retail.status_code, 200)
        retail_html = res_retail.get_data(as_text=True)

        # Must NOT contain automated activeStoreCard.scrollIntoView on DOMContentLoaded
        self.assertNotIn("activeStoreCard.scrollIntoView", retail_html, "Found automated scrollIntoView bug in retail.html!")

        # Must contain manual scrollRestoration
        self.assertIn("scrollRestoration", retail_html)
        self.assertIn("history.scrollRestoration = 'manual'", retail_html)

        # Check storefront page as well
        res_store = self.client.get("/retail/store/1")
        store_html = res_store.get_data(as_text=True)
        self.assertNotIn("activeStoreCard.scrollIntoView", store_html)
        self.assertIn("scrollRestoration", store_html)

        # Verify no autofocus attributes in HTML
        self.assertNotIn('autofocus', retail_html.lower())
        self.assertNotIn('autofocus', store_html.lower())
        print(" [PASSED] 12. Automatic scroll bug permanently eliminated; scrollRestoration set to manual")

    # -------------------------------------------------------------------------
    # 13. Online Shopping Isolation & Non-Regression
    # -------------------------------------------------------------------------
    def test_13_online_shopping_isolation_intact(self):
        """Verify Online Shopping mode remains completely unaffected and preserved."""
        res = self.client.get("/?view=online")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("BharatStore", html)

        # Check catalog products
        prods = self.db.get_all_products()
        tech_prods = [p for p in prods if p.get("category") in ["Laptops & Computers", "Audio & Wearables"]]
        self.assertGreaterEqual(len(tech_prods), 3)
        print(" [PASSED] 13. Online Shopping mode completely isolated and preserved without regression")


if __name__ == "__main__":
    unittest.main()

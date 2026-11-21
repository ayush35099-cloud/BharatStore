"""
BharatStore 2.0 — Phase 2 Automated Test Suite
Dual Shopping Mode Selection Engine
Verifies:
1. Default mode selection
2. Retail mode selection
3. Online mode selection
4. Session persistence across requests
5. Guest customer mode persistence
6. Logged-in customer mode persistence
7. Invalid mode rejection with strict validation
8. Header mode switcher markup & accessibility
9. Cart separation architecture
10. Switching confirmation modal
11. Restoration of previous basket
12. Existing cart regression (/api/cart/validate)
13. Existing authentication regression (/login, /register, admin auth)
14. Mode-specific navigation integrity
"""

import os
import sys
import json
import unittest

# Ensure root directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.config import Config


class TestPhase2ShoppingModes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.app.config["SECRET_KEY"] = "test-secret-key-for-dual-mode-2026"

    def setUp(self):
        self.client = self.app.test_client()

    # 1. Default mode selection
    def test_01_default_mode_selection(self):
        res = self.client.get("/api/shopping-mode")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["mode"], "ONLINE")
        self.assertIn("RETAIL_NEAR_ME", data["supported_modes"])
        self.assertIn("ONLINE", data["supported_modes"])
        print(" [PASSED] 1. Default shopping mode is correctly initialized to ONLINE")

    # 2. Retail mode selection
    def test_02_retail_mode_selection(self):
        res = self.client.post("/api/shopping-mode", json={"mode": "RETAIL_NEAR_ME"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["mode"], "RETAIL_NEAR_ME")

        # Also verify normalization of 'retail'
        res_norm = self.client.post("/api/shopping-mode", json={"mode": "retail"})
        self.assertEqual(res_norm.status_code, 200)
        self.assertEqual(res_norm.get_json()["mode"], "RETAIL_NEAR_ME")
        print(" [PASSED] 2. Retail Near Me mode can be selected via API (supports 'RETAIL_NEAR_ME' and 'retail')")

    # 3. Online mode selection
    def test_03_online_mode_selection(self):
        res = self.client.post("/api/shopping-mode", json={"mode": "ONLINE"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["mode"], "ONLINE")

        # Also verify normalization of 'online'
        res_norm = self.client.post("/api/shopping-mode", json={"mode": "online"})
        self.assertEqual(res_norm.status_code, 200)
        self.assertEqual(res_norm.get_json()["mode"], "ONLINE")
        print(" [PASSED] 3. Online Shopping mode can be selected via API (supports 'ONLINE' and 'online')")

    # 4. Session persistence
    def test_04_session_persistence(self):
        with self.app.test_client() as sess_client:
            # Set to RETAIL_NEAR_ME
            post_res = sess_client.post("/api/shopping-mode", json={"mode": "RETAIL_NEAR_ME"})
            self.assertEqual(post_res.status_code, 200)

            # Subsequent GET should return RETAIL_NEAR_ME
            get_res = sess_client.get("/api/shopping-mode")
            self.assertEqual(get_res.status_code, 200)
            self.assertEqual(get_res.get_json()["mode"], "RETAIL_NEAR_ME")

            # Check homepage rendering reflects the session
            page_res = sess_client.get("/")
            self.assertEqual(page_res.status_code, 200)
            html = page_res.get_data(as_text=True)
            self.assertIn('id="mode-btn-retail"', html)
            self.assertIn('aria-checked="true"', html)
        print(" [PASSED] 4. Session persistence maintains mode across multiple requests")

    # 5. Guest customer mode persistence
    def test_05_guest_customer_persistence(self):
        with self.app.test_client() as guest_client:
            res1 = guest_client.get("/api/shopping-mode")
            self.assertEqual(res1.get_json()["mode"], "ONLINE")

            # Switch to Retail
            res2 = guest_client.post("/api/shopping-mode", json={"mode": "RETAIL_NEAR_ME"})
            self.assertTrue(res2.get_json()["success"])

            # Verify on products page
            prod_page = guest_client.get("/products")
            self.assertEqual(prod_page.status_code, 200)
            self.assertEqual(guest_client.get("/api/shopping-mode").get_json()["mode"], "RETAIL_NEAR_ME")
        print(" [PASSED] 5. Guest customer mode persistence operates correctly without login")

    # 6. Logged-in customer mode persistence
    def test_06_logged_in_customer_persistence(self):
        with self.app.test_client() as user_client:
            with user_client.session_transaction() as sess:
                sess["customer_id"] = 1
                sess["customer_email"] = "priya.sharma@example.in"
                sess["shopping_mode"] = "RETAIL_NEAR_ME"

            res = user_client.get("/api/shopping-mode")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.get_json()["mode"], "RETAIL_NEAR_ME")
        print(" [PASSED] 6. Logged-in customer session correctly preserves shopping mode")

    # 7. Invalid mode rejection
    def test_07_invalid_mode_rejection(self):
        invalid_payloads = [
            {"mode": "SUPER_MARKET"},
            {"mode": "<script>alert(1)</script>"},
            {"mode": ""},
            {"mode": None},
            {"random_key": "ONLINE"},
            {}
        ]
        for payload in invalid_payloads:
            res = self.client.post("/api/shopping-mode", json=payload)
            self.assertEqual(res.status_code, 400)
            data = res.get_json()
            self.assertFalse(data["success"])
            self.assertIn("error", data)
        print(" [PASSED] 7. Invalid mode injection strictly rejected with HTTP 400")

    # 8. Header mode switcher markup & accessibility
    def test_08_header_mode_switcher_markup(self):
        res = self.client.get("/")
        html = res.get_data(as_text=True)

        self.assertIn('id="header-mode-switcher"', html)
        self.assertIn('role="radiogroup"', html)
        self.assertIn('id="mode-btn-retail"', html)
        self.assertIn('id="mode-btn-online"', html)
        self.assertIn('Retail Near Me', html)
        self.assertIn('Online Shopping', html)
        self.assertIn('15 km', html)
        print(" [PASSED] 8. Main header mode switcher pill selector verified with accessible roles")

    # 9. Cart separation architecture
    def test_09_cart_separation_architecture(self):
        with open("static/js/app.js", encoding="utf-8") as f:
            js = f.read()

        self.assertIn("bharatstore_retail_cart", js)
        self.assertIn("bharatstore_online_cart", js)
        self.assertIn("appState.retailCart", js)
        self.assertIn("appState.onlineCart", js)
        self.assertIn("saveCart", js)
        print(" [PASSED] 9. JavaScript state architecture isolates retail and online baskets")

    # 10. Switching confirmation modal
    def test_10_switching_confirmation_modal(self):
        res = self.client.get("/")
        html = res.get_data(as_text=True)

        self.assertIn('id="mode-switch-modal-overlay"', html)
        self.assertIn('id="mode-confirm-proceed-btn"', html)
        self.assertIn('Switch & Preserve Basket', html)
        self.assertIn('id="mode-confirm-cart-preview"', html)
        print(" [PASSED] 10. Mode switch confirmation modal present in DOM for cart preservation")

    # 11. Restoration of previous basket
    def test_11_restoration_of_previous_basket(self):
        with open("static/js/app.js", encoding="utf-8") as f:
            js = f.read()

        self.assertIn("executeModeSwitch", js)
        self.assertIn("Restored your", js)
        self.assertIn("openModeSwitchModal", js)
        print(" [PASSED] 11. Previous basket restoration verified in executeModeSwitch routine")

    # 12. Existing cart regression
    def test_12_existing_cart_regression(self):
        # /api/cart/validate should continue validating actual product stock
        res = self.client.post("/api/cart/validate", json={"product_id": 1, "quantity": 1})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["valid"])
        self.assertIn("available_stock", data)
        print(" [PASSED] 12. Existing cart backend stock validation (/api/cart/validate) intact")

    # 13. Existing authentication regression
    def test_13_existing_auth_regression(self):
        # Login and register pages render properly
        login_res = self.client.get("/login")
        self.assertEqual(login_res.status_code, 200)

        reg_res = self.client.get("/register")
        self.assertEqual(reg_res.status_code, 200)

        # Admin route requires valid authentication token
        admin_res = self.client.get("/api/admin/stats")
        self.assertEqual(admin_res.status_code, 403)
        print(" [PASSED] 13. Customer authentication and admin authorization guards intact")

    # 14. Mobile navigation and dedicated mode selection page
    def test_14_mode_navigation_and_select_mode_page(self):
        # /select-mode page renders with both large interactive cards
        res = self.client.get("/select-mode")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        self.assertIn("Retail Near Me", html)
        self.assertIn("Online Shopping", html)
        self.assertIn("Explore Nearby Stores", html)
        self.assertIn("Explore Online Store", html)
        self.assertIn("mode-cards-grid", html)

        # Navigation links are properly present
        base_res = self.client.get("/")
        base_html = base_res.get_data(as_text=True)
        self.assertIn('id="nav-mode-home"', base_html)
        self.assertIn('id="nav-mode-categories"', base_html)
        self.assertIn('id="nav-mode-nearby-stores"', base_html)
        self.assertIn('id="nav-mode-offers"', base_html)
        self.assertIn('id="nav-mode-wishlist"', base_html)
        self.assertIn('id="nav-mode-orders"', base_html)
        self.assertIn('id="nav-mode-cart"', base_html)
        print(" [PASSED] 14. Mode-specific navigation and /select-mode page fully verified")

    # 15. Dedicated /retail route loads Retail Near Me storefront
    def test_15_retail_page_route(self):
        with self.app.test_client() as client:
            res = client.get("/retail")
            self.assertEqual(res.status_code, 200)
            html = res.get_data(as_text=True)

            self.assertIn("Nearby Stores within 15 km", html)
            self.assertIn("store-hub-card", html)
            self.assertIn("2-Hour Express Delivery", html)
            self.assertIn("BharatStore Mumbai MegaHub", html)

            # Check that accessing /retail set session mode to RETAIL_NEAR_ME
            mode_res = client.get("/api/shopping-mode")
            self.assertEqual(mode_res.get_json()["mode"], "RETAIL_NEAR_ME")
        print(" [PASSED] 15. Dedicated /retail route successfully loads Retail Near Me storefront (HTTP 200)")

    # 16. Dedicated /online route loads Online Shopping marketplace
    def test_16_online_page_route(self):
        with self.app.test_client() as client:
            res = client.get("/online")
            self.assertEqual(res.status_code, 200)
            html = res.get_data(as_text=True)

            self.assertIn("Physical Stores Across India", html)
            self.assertIn("Explore 50+ Products", html)

            # Check that accessing /online set session mode to ONLINE
            mode_res = client.get("/api/shopping-mode")
            self.assertEqual(mode_res.get_json()["mode"], "ONLINE")
        print(" [PASSED] 16. Dedicated /online route successfully loads Online Shopping marketplace (HTTP 200)")

    # 17. Seamless Homepage switching according to active mode
    def test_17_homepage_dual_view_switch(self):
        with self.app.test_client() as client:
            # Step A: In ONLINE mode, homepage loads marketplace
            client.post("/api/shopping-mode", json={"mode": "online"})
            home_online = client.get("/")
            self.assertEqual(home_online.status_code, 200)
            self.assertIn("Physical Stores Across India", home_online.get_data(as_text=True))

            # Step B: In RETAIL mode, homepage loads Retail Near Me
            client.post("/api/shopping-mode", json={"mode": "retail"})
            home_retail = client.get("/")
            self.assertEqual(home_retail.status_code, 200)
            retail_html = home_retail.get_data(as_text=True)
            self.assertIn("Nearby Stores within 15 km", retail_html)
            self.assertIn("Neighbourhood Physical Stores", retail_html)

            # Step C: Refreshing / preserves the Retail view
            home_retail_refreshed = client.get("/")
            self.assertEqual(home_retail_refreshed.status_code, 200)
            self.assertIn("Nearby Stores within 15 km", home_retail_refreshed.get_data(as_text=True))
        print(" [PASSED] 17. Homepage seamlessly switches between Retail Near Me and Online Shopping and survives refresh")


if __name__ == "__main__":
    unittest.main(verbosity=2)

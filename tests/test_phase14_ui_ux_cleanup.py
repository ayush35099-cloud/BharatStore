import unittest
from app import create_app
from app.database import DatabaseService

class Phase14UIUXCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()
        cls.db = DatabaseService()
        cls.headers = {"Content-Type": "application/json"}

    def setUp(self):
        # Fresh test client per test so session state does not leak between tests
        self.client = self.app.test_client()
        # Use isolated test customer ID (e.g., 999) for address tests
        self.test_customer_id = 999
        self._cleanup_test_customer_addresses()

    def tearDown(self):
        self._cleanup_test_customer_addresses()

    def _cleanup_test_customer_addresses(self):
        conn = self.db._get_sqlite_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM addresses WHERE customer_id = ?;", (self.test_customer_id,))
        conn.commit()
        conn.close()

    # -------------------------------------------------------------------------
    # 1. Saved Address Management: 5-Address Cap
    # -------------------------------------------------------------------------
    def test_01_address_limit_enforced_at_five(self):
        """Spec 1: Customers can save at most 5 addresses; 6th address is rejected."""
        # Add 5 distinct addresses
        for i in range(1, 6):
            addr = self.db.add_customer_address(self.test_customer_id, {
                "full_name": f"Test User {i}",
                "phone": "+91 98201 12345",
                "address_line1": f"House {i}, Test Street",
                "city": "Bengaluru",
                "state": "Karnataka",
                "pincode": f"56000{i}",
                "address_type": "HOME"
            })
            self.assertIsNotNone(addr)
            self.assertEqual(addr["customer_id"], self.test_customer_id)

        # 5 addresses saved
        saved = self.db.get_customer_addresses(self.test_customer_id)
        self.assertEqual(len(saved), 5)

        # Attempt to add a 6th address
        with self.assertRaises(ValueError) as ctx:
            self.db.add_customer_address(self.test_customer_id, {
                "full_name": "Test User 6",
                "phone": "+91 98201 12345",
                "address_line1": "House 6, Test Street",
                "city": "Bengaluru",
                "state": "Karnataka",
                "pincode": "560006",
                "address_type": "WORK"
            })
        self.assertIn("Maximum limit of 5 saved addresses reached", str(ctx.exception))
        print(" [PASSED] 1. Backend strictly enforces maximum 5 saved addresses per customer")

    # -------------------------------------------------------------------------
    # 2. Saved Address Management: Duplicate Prevention
    # -------------------------------------------------------------------------
    def test_02_duplicate_address_prevention(self):
        """Spec 2: Prevent adding duplicate addresses with matching line1, city, and pincode."""
        # Add first address
        self.db.add_customer_address(self.test_customer_id, {
            "full_name": "Test User",
            "phone": "+91 98201 12345",
            "address_line1": "Flat 101, Palm Grove Apts",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pincode": "400050",
            "address_type": "HOME"
        })

        # Try to add exact duplicate (even with case or whitespace variance)
        with self.assertRaises(ValueError) as ctx:
            self.db.add_customer_address(self.test_customer_id, {
                "full_name": "Different Name",
                "phone": "+91 98201 99999",
                "address_line1": "  flat 101, palm grove apts  ",
                "city": "  MUMBAI ",
                "state": "Maharashtra",
                "pincode": "400050",
                "address_type": "WORK"
            })
        self.assertIn("Duplicate addresses are not allowed", str(ctx.exception))
        print(" [PASSED] 2. Duplicate address prevention strictly rejects identical destinations")

    # -------------------------------------------------------------------------
    # 3. Address Update & Delete Lifecycle
    # -------------------------------------------------------------------------
    def test_03_address_edit_delete_and_default_toggle(self):
        """Spec 3: Addresses can be updated, deleted, and have default status toggled."""
        a1 = self.db.add_customer_address(self.test_customer_id, {
            "full_name": "Original Name",
            "phone": "+91 98201 12345",
            "address_line1": "Old Street 1",
            "city": "Bengaluru",
            "pincode": "560038"
        })
        a2 = self.db.add_customer_address(self.test_customer_id, {
            "full_name": "Second Address",
            "phone": "+91 98201 12345",
            "address_line1": "Old Street 2",
            "city": "Bengaluru",
            "pincode": "560001"
        })

        # Edit a1
        updated = self.db.update_customer_address(a1["id"], self.test_customer_id, {
            "full_name": "Updated Name",
            "address_line1": "New Street 100"
        })
        self.assertEqual(updated["full_name"], "Updated Name")
        self.assertEqual(updated["address_line1"], "New Street 100")

        # Set a2 as default
        self.db.set_default_customer_address(a2["id"], self.test_customer_id)
        addresses = self.db.get_customer_addresses(self.test_customer_id)
        a2_refreshed = next(a for a in addresses if a["id"] == a2["id"])
        self.assertTrue(a2_refreshed["is_default"])

        # Delete a2
        deleted = self.db.delete_customer_address(a2["id"], self.test_customer_id)
        self.assertTrue(deleted)
        remaining = self.db.get_customer_addresses(self.test_customer_id)
        self.assertEqual(len(remaining), 1)
        # Deleted was default, so a1 is promoted to default
        self.assertTrue(remaining[0]["is_default"])
        print(" [PASSED] 3. Full address lifecycle (edit, set default, delete with auto-promote) verified")

    # -------------------------------------------------------------------------
    # 4. Five Simplified Retail Categories in Backend & Catalog API
    # -------------------------------------------------------------------------
    def test_04_five_simplified_retail_categories_in_api(self):
        """Spec 4: Exactly 5 Retail categories exposed via /api/retail/catalog."""
        res = self.client.get("/api/retail/catalog")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))

        expected_categories = [
            "fruits_vegetables_items",
            "dairy_bakery_items",
            "rice_atta_dal_items",
            "snacks_beverages_items",
            "household_personal_items"
        ]
        for cat in expected_categories:
            self.assertIn(cat, data, f"Category list '{cat}' missing from /api/retail/catalog")
            self.assertGreater(len(data[cat]), 0, f"Category '{cat}' is empty")

        # Verify all products across categories sum to total grocery catalog
        all_prods = data["all_products"]
        self.assertGreaterEqual(len(all_prods), 50)
        total_categorized = (
            len(data["fruits_vegetables_items"]) +
            len(data["dairy_bakery_items"]) +
            len(data["rice_atta_dal_items"]) +
            len(data["snacks_beverages_items"]) +
            len(data["household_personal_items"])
        )
        self.assertEqual(total_categorized, len(all_prods))
        print(f" [PASSED] 4. All {len(all_prods)} grocery products cleanly mapped across the 5 simplified Retail categories")

    # -------------------------------------------------------------------------
    # 5. Retail Homepage Department Sections
    # -------------------------------------------------------------------------
    def test_05_retail_homepage_renders_all_five_categories(self):
        """Spec 5: Retail Near Me homepage DOM contains the 5 simplified categories and filter tabs."""
        res = self.client.get("/retail")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Check section badges / titles (supporting both literal '&' and HTML entity '&amp;')
        for cat in [
            "Dairy & Bakery",
            "Rice, Atta & Dal",
            "Fruits & Vegetables",
            "Snacks & Beverages",
            "Household & Personal Care"
        ]:
            cat_escaped = cat.replace("&", "&amp;")
            self.assertTrue(
                cat in html or cat_escaped in html,
                f"Category '{cat}' not found on Retail Near Me homepage"
            )

        # Check section IDs
        self.assertIn('id="dairy-section"', html)
        self.assertIn('id="grains-section"', html)
        self.assertIn('id="produce-section"', html)
        self.assertIn('id="snacks-section"', html)
        self.assertIn('id="household-section"', html)
        print(" [PASSED] 5. Retail Near Me homepage cleanly renders all 5 simplified department sections")

    # -------------------------------------------------------------------------
    # 6. Storefront Detail Page Department Sections
    # -------------------------------------------------------------------------
    def test_06_storefront_detail_renders_all_five_categories(self):
        """Spec 6: Physical store detail page renders all 5 simplified categories."""
        res = self.client.get("/retail/store/1")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        for cat in [
            "Dairy & Bakery",
            "Rice, Atta & Dal",
            "Fruits & Vegetables",
            "Snacks & Beverages",
            "Household & Personal Care"
        ]:
            cat_escaped = cat.replace("&", "&amp;")
            self.assertTrue(
                cat in html or cat_escaped in html,
                f"Category '{cat}' not found on storefront detail page"
            )
        print(" [PASSED] 6. Physical store detail page cleanly renders all 5 category blocks")

    # -------------------------------------------------------------------------
    # 7. Search Bar UI: Magnifying-Glass Inside Input
    # -------------------------------------------------------------------------
    def test_07_search_bar_inner_icon_and_placeholder(self):
        """Spec 7: Search input contains an interior magnifying glass icon with proper styling."""
        res = self.client.get("/online")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        self.assertIn("search-inner-icon", html)
        self.assertIn("header-search-input", html)
        self.assertIn("Search 50+ authentic products", html)

        # Retail mode search placeholder
        with self.client.session_transaction() as sess:
            sess["shopping_mode"] = "RETAIL_NEAR_ME"
        res_retail = self.client.get("/retail")
        html_retail = res_retail.get_data(as_text=True)
        self.assertIn("Search grocery essentials across nearby shops", html_retail)
        print(" [PASSED] 7. Search bar contains integrated interior magnifying-glass icon and mode-aware placeholders")

    # -------------------------------------------------------------------------
    # 8. Hero Image Separation: Online vs Retail
    # -------------------------------------------------------------------------
    def test_08_hero_image_separation(self):
        """Spec 8: Online homepage displays online-shopping-hero.jpg, while Retail uses grocery layout."""
        # Online homepage
        res_online = self.client.get("/online")
        self.assertEqual(res_online.status_code, 200)
        html_online = res_online.get_data(as_text=True)
        self.assertIn("/static/images/online-shopping-hero.jpg", html_online)

        # Retail Near Me homepage
        res_retail = self.client.get("/retail")
        self.assertEqual(res_retail.status_code, 200)
        html_retail = res_retail.get_data(as_text=True)
        # Retail should NOT use online hero
        self.assertNotIn("/static/images/online-shopping-hero.jpg", html_retail)
        self.assertIn("retail-hub-hero", html_retail)
        print(" [PASSED] 8. Clean hero image separation verified between Online Shopping and Retail Near Me")

    # -------------------------------------------------------------------------
    # 9. Unsupported Delivery Claims Removed from Checkout UI
    # -------------------------------------------------------------------------
    def test_09_unsupported_delivery_claims_removed_from_checkout(self):
        """Spec 9: Checkout displays standard doorstep delivery without 2-hour or express promises."""
        res = self.client.get("/checkout")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        self.assertIn("Standard Doorstep Delivery", html)
        self.assertNotIn("Hyperlocal 2-Hour Express Delivery", html)
        self.assertNotIn("Store Counter Pickup (Click & Collect)", html)
        print(" [PASSED] 9. Checkout cleanly displays standard doorstep delivery without unsupported claims")

    # -------------------------------------------------------------------------
    # 10. Profile Saved Addresses (X / 5) UI & Modal Cap
    # -------------------------------------------------------------------------
    def test_10_profile_address_count_badge_and_limit_banner(self):
        """Spec 10: Profile template renders address count indicator and max address limit alert."""
        res = self.client.get("/profile")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        self.assertIn("address-count-badge", html)
        self.assertIn("max-addr-limit-banner", html)
        self.assertIn("Maximum limit of 5 saved addresses reached", html)
        print(" [PASSED] 10. Profile page includes address limit indicators and user-friendly guidance")


if __name__ == "__main__":
    unittest.main()

import unittest
import os
import re
from unittest.mock import patch
from app import create_app
from app.config import Config
from app.database import DatabaseService


class TestLiveAuditAndFixes(unittest.TestCase):
    """
    Comprehensive functional audit and regression verification suite covering:
    1. UI Button text integrity ("Out of Stock" button truncation fix).
    2. Multi-city store isolation across 7 Indian metros (no cross-city store leakage).
    3. Session location context synchronization (both customer_location and delivery_location keys).
    4. Production database fail-fast requirement (fail with RuntimeError, zero credential leaks).
    5. Location-aware retail store selection and dynamic distance calculation.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()
        cls.db = DatabaseService()

    # -------------------------------------------------------------------------
    # 1. UI Button Text Audit: No truncated "Out" buttons
    # -------------------------------------------------------------------------
    def test_01_no_truncated_out_of_stock_buttons_in_templates(self):
        """Verifies that all out-of-stock buttons across templates display 'Out of Stock' and not truncated 'Out'."""
        templates_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
        truncated_pattern = re.compile(r'<i[^>]*class="[^"]*fa-ban[^"]*"[^>]*>\s*</i>\s*Out\b(?!\s*of\s*Stock)', re.IGNORECASE)

        for root, _, files in os.walk(templates_dir):
            for file in files:
                if file.endswith(".html"):
                    filepath = os.path.join(root, file)
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    matches = truncated_pattern.findall(content)
                    self.assertEqual(
                        len(matches),
                        0,
                        f"Found truncated '<i class=\"fa-ban\"></i> Out' in {file}"
                    )
        print(" [PASSED] 1. All out-of-stock buttons across templates display complete 'Out of Stock' text")

    def test_02_rendered_retail_pages_contain_full_button_labels(self):
        """Verifies rendered HTML for /retail and /retail/store/<id> has valid button text."""
        res_retail = self.client.get("/retail")
        self.assertEqual(res_retail.status_code, 200)
        html_retail = res_retail.get_data(as_text=True)
        self.assertNotIn(">Out</button>", html_retail)
        self.assertNotIn("> Out</button>", html_retail)

        res_store = self.client.get("/retail/store/1")
        self.assertEqual(res_store.status_code, 200)
        html_store = res_store.get_data(as_text=True)
        self.assertNotIn(">Out</button>", html_store)
        self.assertNotIn("> Out</button>", html_store)
        print(" [PASSED] 2. Rendered storefront HTML contains complete non-truncated button labels")

    # -------------------------------------------------------------------------
    # 2. Location & Store Consistency: Cross-City Store Isolation
    # -------------------------------------------------------------------------
    def test_03_store_city_isolation_across_seven_cities(self):
        """
        Verifies that querying retail stores for any of the 7 supported cities
        strictly returns stores from that city and never leaks stores from another city.
        """
        cities_to_test = [
            ("Bengaluru", [1, 2, 3, 4, 5]),
            ("Mumbai", [6, 7]),
            ("Delhi NCR", [8, 9]),
            ("Hyderabad", [10, 11]),
            ("Chennai", [12, 13]),
            ("Pune", [16, 17]),
            ("Kolkata", [14, 15]),
        ]

        for city_name, expected_ids in cities_to_test:
            stores = self.db.get_retail_stores(city_name)
            self.assertGreaterEqual(
                len(stores),
                len(expected_ids),
                f"Expected at least {len(expected_ids)} stores for {city_name}, got {len(stores)}"
            )
            returned_ids = [s["id"] for s in stores]
            for exp_id in expected_ids:
                self.assertIn(
                    exp_id,
                    returned_ids,
                    f"Store #{exp_id} missing from {city_name} retail stores"
                )

            # Strict cross-city isolation: verify all returned stores belong to this city
            for s in stores:
                store_city = s.get("city", "").lower()
                target_city = city_name.lower()
                self.assertTrue(
                    target_city in store_city or store_city in target_city,
                    f"Store #{s['id']} with city '{s.get('city')}' leaked into {city_name} stores list!"
                )

        print(" [PASSED] 3. Strict cross-city store isolation verified across 7 Indian metros (BLR, MUM, DEL, HYD, MAA, PNQ, CCU)")

    def test_04_unknown_city_does_not_leak_other_city_stores(self):
        """Verifies that an unsupported or unserviced city returns an empty list, not Bengaluru stores."""
        stores = self.db.get_retail_stores("NonExistentCity")
        self.assertEqual(len(stores), 0, "Non-serviced city must return 0 stores, not leak Bengaluru stores")
        print(" [PASSED] 4. Non-serviced city returns empty list without cross-city store leakage")

    # -------------------------------------------------------------------------
    # 3. Session Location Key & Attribute Synchronization
    # -------------------------------------------------------------------------
    def test_05_session_location_synchronization(self):
        """
        Verifies that /api/location/set-current sets both session['customer_location']
        and session['delivery_location'] with normalized lat/lng and latitude/longitude.
        """
        with self.client as c:
            res = c.post("/api/location/set-current", json={
                "city": "Mumbai",
                "area": "Bandra West",
                "pincode": "400050",
                "address_line": "Linking Road, Bandra West",
                "latitude": 19.0596,
                "longitude": 72.8295,
                "source": "manual"
            })
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["success"])
            self.assertEqual(data["location"]["city"], "Mumbai")

            # Verify session has both keys populated with synchronized coordinates
            from flask import session
            self.assertIn("customer_location", session)
            self.assertIn("delivery_location", session)
            self.assertEqual(session["customer_location"]["city"], "Mumbai")
            self.assertEqual(session["delivery_location"]["city"], "Mumbai")
            self.assertEqual(session["customer_location"]["lat"], 19.0596)
            self.assertEqual(session["delivery_location"]["lat"], 19.0596)
            self.assertEqual(session["customer_location"]["latitude"], 19.0596)
            self.assertEqual(session["delivery_location"]["latitude"], 19.0596)
            self.assertEqual(session["customer_location"]["lng"], 72.8295)
            self.assertEqual(session["delivery_location"]["lng"], 72.8295)

            # Verify retail storefront renders Mumbai stores, not Bengaluru
            res_retail = c.get("/retail")
            self.assertEqual(res_retail.status_code, 200)
            html = res_retail.get_data(as_text=True)
            self.assertIn("Mumbai", html)
            self.assertIn("BharatStore Mumbai Bandra", html)

        print(" [PASSED] 5. Session location keys (customer_location & delivery_location) synchronized with normalized coordinates")

    def test_06_switching_city_updates_active_store(self):
        """
        Verifies that switching location to another city (e.g. Pune)
        automatically resets the active store in session to a store in that city.
        """
        with self.client as c:
            # 1. Start with Bengaluru
            c.post("/api/location/set-current", json={
                "city": "Bengaluru",
                "area": "Indiranagar",
                "pincode": "560038"
            })
            from flask import session
            self.assertIn(session.get("retail_store_id"), [1, 2, 3, 4, 5])

            # 2. Switch to Pune
            c.post("/api/location/set-current", json={
                "city": "Pune",
                "area": "Kothrud",
                "pincode": "411038"
            })
            # retail_store_id must now be a Pune store (16 or 17)
            self.assertIn(session.get("retail_store_id"), [16, 17])

            # 3. GET /retail must feature Pune store
            res = c.get("/retail")
            self.assertEqual(res.status_code, 200)
            html = res.get_data(as_text=True)
            self.assertIn("Pune", html)

        print(" [PASSED] 6. City switch automatically updates session active store to local city shop")

    # -------------------------------------------------------------------------
    # 4. Production Database Fail-Fast & Redaction Verification
    # -------------------------------------------------------------------------
    def test_07_production_fail_fast_when_pg_missing(self):
        """
        Verifies that in production mode (RENDER=true or FLASK_ENV=production),
        if PostgreSQL is not configured, the service fails clearly with RuntimeError
        rather than silently creating an ephemeral SQLite database.
        """
        with patch.dict(os.environ, {"RENDER": "true", "DATABASE_URL": "", "AIVEN_PG_URL": ""}):
            with patch.object(Config, "is_pg_configured", return_value=False):
                with self.assertRaises(RuntimeError) as ctx:
                    DatabaseService()
                self.assertIn("BharatStore requires persistent PostgreSQL in production", str(ctx.exception))
        print(" [PASSED] 7. Production mode fails fast with RuntimeError when PostgreSQL is not configured")

    def test_08_production_fail_fast_when_pg_connection_fails(self):
        """
        Verifies that in production mode, if PostgreSQL connection fails,
        the service raises RuntimeError with credentials sanitized.
        """
        with patch.dict(os.environ, {"RENDER": "true", "DATABASE_URL": "postgresql://usr:secret_pass_123@host:5432/db"}):
            with patch.object(Config, "is_pg_configured", return_value=True):
                with patch.object(DatabaseService, "_get_pg_connection", side_effect=Exception("password=secret_pass_123 failed")):
                    with self.assertRaises(RuntimeError) as ctx:
                        DatabaseService()
                    err = str(ctx.exception)
                    self.assertIn("Production PostgreSQL connection failed", err)
                    self.assertNotIn("secret_pass_123", err, "CRITICAL: Password leaked in production database error!")
                    self.assertIn("password=******", err)
        print(" [PASSED] 8. Production PostgreSQL failure raises RuntimeError with credentials fully redacted")

    def test_09_credential_sanitization_removes_secrets(self):
        """Verifies _sanitize_db_error redacts passwords, URI credentials, and tokens."""
        raw_error = "FATAL: password authentication failed for user 'aiven_admin': postgresql://admin:SuperSecret999@pg.aivencloud.com:12345/defaultdb password=SuperSecret999"
        sanitized = self.db._sanitize_db_error(raw_error)
        self.assertNotIn("SuperSecret999", sanitized)
        self.assertIn("://admin:******@", sanitized)
        self.assertIn("password=******", sanitized)
        print(" [PASSED] 9. Credential sanitization utility reliably redacts passwords and URI credentials")


if __name__ == "__main__":
    unittest.main()

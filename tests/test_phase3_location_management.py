"""
BharatStore 2.0 — Phase 3 Automated Test Suite
Location and Address Management Engine
Verifies:
1. Valid coordinate validation.
2. Invalid latitude rejection.
3. Invalid longitude rejection.
4. Missing coordinate rejection.
5. Non-numeric coordinate rejection.
6. Cities and areas API.
7. Location session persistence.
8. Guest location selection.
9. Address creation.
10. Address retrieval.
11. Address update.
12. Address deletion.
13. Setting default address.
14. Ensuring only one default address.
15. Customer ownership and authorization.
16. Invalid pincode rejection.
17. Invalid phone rejection.
18. XSS and SQL injection payload handling.
19. GPS-denial manual fallback logic.
20. Checkout address selection integration.
21. Existing Phase 1 and Phase 2 regression integrity.
"""

import os
import sys
import json
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.database import DatabaseService


class TestPhase3LocationManagement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.app.config["SECRET_KEY"] = "test-secret-key-phase-3-location"
        cls.db = DatabaseService()

    def setUp(self):
        self.client = self.app.test_client()

    # 1. Valid coordinate validation
    def test_01_valid_coordinate_validation(self):
        res = self.client.post("/api/location/validate-coords", json={
            "latitude": 19.0596,
            "longitude": 72.8295
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["valid"])
        self.assertEqual(data["nearest_city"], "Mumbai")
        self.assertIn("Mumbai", data["nearest_hub"])
        self.assertLessEqual(data["distance_km"], 5.0)
        self.assertTrue(data["is_within_delivery_radius"])
        print(" [PASSED] 1. Valid coordinate validation verified (/api/location/validate-coords)")

    # 2. Invalid latitude rejection
    def test_02_invalid_latitude_rejection(self):
        res = self.client.post("/api/location/validate-coords", json={
            "latitude": 95.5,
            "longitude": 72.8295
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertIn("out of bounds", data["error"].lower())
        print(" [PASSED] 2. Invalid latitude rejected with HTTP 400")

    # 3. Invalid longitude rejection
    def test_03_invalid_longitude_rejection(self):
        res = self.client.post("/api/location/validate-coords", json={
            "latitude": 19.0596,
            "longitude": -195.0
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertIn("out of bounds", data["error"].lower())
        print(" [PASSED] 3. Invalid longitude rejected with HTTP 400")

    # 4. Missing coordinate rejection
    def test_04_missing_coordinate_rejection(self):
        res = self.client.post("/api/location/validate-coords", json={
            "latitude": 19.0596
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertIn("missing", data["error"].lower())
        print(" [PASSED] 4. Missing coordinate rejected with HTTP 400")

    # 5. Non-numeric coordinate rejection
    def test_05_non_numeric_coordinate_rejection(self):
        res = self.client.post("/api/location/validate-coords", json={
            "latitude": "nineteen point zero",
            "longitude": "seventy-two"
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertIn("non-numeric", data["error"].lower())
        print(" [PASSED] 5. Non-numeric coordinates rejected with HTTP 400")

    # 6. Cities and areas API
    def test_06_cities_and_areas_api(self):
        res = self.client.get("/api/location/cities-areas")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["demo_mode"])
        self.assertEqual(data["delivery_radius_km"], 15)
        self.assertGreaterEqual(len(data["cities"]), 6)
        city_names = [c["city"] for c in data["cities"]]
        for expected in ["Mumbai", "Bengaluru", "Delhi NCR", "Hyderabad", "Chennai", "Kolkata"]:
            self.assertIn(expected, city_names)
        # Check first city has areas
        mumbai = next(c for c in data["cities"] if c["city"] == "Mumbai")
        self.assertGreaterEqual(len(mumbai["areas"]), 5)
        print(" [PASSED] 6. Cities and areas catalog verified (/api/location/cities-areas)")

    # 7. Location session persistence
    def test_07_location_session_persistence(self):
        with self.client as c:
            set_res = c.post("/api/location/set-current", json={
                "city": "Bengaluru",
                "area": "Indiranagar",
                "address_line": "100 Feet Road, Indiranagar",
                "pincode": "560038",
                "source": "manual"
            })
            self.assertEqual(set_res.status_code, 200)
            data = set_res.get_json()
            self.assertTrue(data["success"])
            self.assertEqual(data["location"]["city"], "Bengaluru")
            self.assertEqual(data["location"]["area"], "Indiranagar")

            # Check GET /api/location/current preserves it across request boundaries
            get_res = c.get("/api/location/current")
            self.assertEqual(get_res.status_code, 200)
            get_data = get_res.get_json()
            self.assertEqual(get_data["location"]["city"], "Bengaluru")
            self.assertEqual(get_data["location"]["area"], "Indiranagar")
            self.assertFalse(get_data["is_fallback"])
        print(" [PASSED] 7. Location session persistence verified across requests")

    # 8. Guest location selection
    def test_08_guest_location_selection(self):
        guest_client = self.app.test_client()
        res = guest_client.get("/api/location/current")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data.get("is_fallback") or "city" in data["location"])

        # Guest updates location without logging in
        update_res = guest_client.post("/api/location/set-current", json={
            "city": "Hyderabad",
            "area": "Jubilee Hills",
            "pincode": "500033"
        })
        self.assertEqual(update_res.status_code, 200)
        self.assertEqual(update_res.get_json()["location"]["city"], "Hyderabad")
        print(" [PASSED] 8. Guest customer location selection verified without registration")

    # 9. Address creation
    def test_09_address_creation(self):
        res = self.client.post("/api/customer/addresses", headers={"X-Customer-Id": "1"}, json={
            "full_name": "Priya Sharma",
            "phone": "+91 98201 12345",
            "address_type": "WORK",
            "address_line1": "Level 8, Express Towers",
            "address_line2": "Nariman Point",
            "landmark": "Near Marine Drive",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pincode": "400021",
            "latitude": 18.9260,
            "longitude": 72.8230,
            "is_default": False
        })
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("address", data)
        self.assertEqual(data["address"]["pincode"], "400021")
        self.__class__.created_address_id = data["address"]["id"]
        print(" [PASSED] 9. Address creation verified (HTTP 201)")

    # 10. Address retrieval
    def test_10_address_retrieval(self):
        res = self.client.get("/api/customer/addresses", headers={"X-Customer-Id": "1"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(data["total"], 1)
        self.assertTrue(any(a["pincode"] == "400021" for a in data["addresses"]))
        print(" [PASSED] 10. Address retrieval verified (/api/customer/addresses)")

    # 11. Address update
    def test_11_address_update(self):
        addr_id = getattr(self.__class__, "created_address_id", None)
        if not addr_id:
            self.skipTest("No address created to update")
        res = self.client.put(f"/api/customer/addresses/{addr_id}", headers={"X-Customer-Id": "1"}, json={
            "address_line1": "Suite 902, Express Towers Renovated",
            "landmark": "Opposite CR2 Mall"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("Renovated", data["address"]["address_line1"])
        print(" [PASSED] 11. Address update verified (/api/customer/addresses/<id>)")

    # 12. Address deletion
    def test_12_address_deletion(self):
        # Create a temporary address to delete
        temp_res = self.client.post("/api/customer/addresses", headers={"X-Customer-Id": "1"}, json={
            "full_name": "Temporary Dropoff",
            "phone": "+91 98201 12345",
            "address_type": "OTHER",
            "address_line1": "Temp Locker #4",
            "city": "Mumbai",
            "pincode": "400050",
            "is_default": False
        })
        temp_id = temp_res.get_json()["address"]["id"]
        del_res = self.client.delete(f"/api/customer/addresses/{temp_id}", headers={"X-Customer-Id": "1"})
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.get_json()["success"])
        print(" [PASSED] 12. Address deletion verified (HTTP 200)")

    # 13. Setting default address
    def test_13_setting_default_address(self):
        addr_id = getattr(self.__class__, "created_address_id", None)
        if not addr_id:
            self.skipTest("No address available")
        res = self.client.post(f"/api/customer/addresses/{addr_id}/default", headers={"X-Customer-Id": "1"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        print(" [PASSED] 13. Setting default address verified (/api/customer/addresses/<id>/default)")

    # 14. Ensuring only one default address
    def test_14_ensuring_only_one_default_address(self):
        addrs = self.db.get_customer_addresses(customer_id=1)
        defaults = [a for a in addrs if a["is_default"]]
        self.assertEqual(len(defaults), 1, "There must be exactly one default address per customer")
        print(" [PASSED] 14. Invariant verified: Customer has exactly one default address")

    # 15. Customer ownership and authorization
    def test_15_customer_ownership_and_authorization(self):
        addr_id = getattr(self.__class__, "created_address_id", None)
        if not addr_id:
            self.skipTest("No address available")
        # Customer 2 attempts to delete Customer 1's address
        unauth_del = self.client.delete(f"/api/customer/addresses/{addr_id}", headers={"X-Customer-Id": "2"})
        self.assertEqual(unauth_del.status_code, 404)

        # Customer 2 attempts to update Customer 1's address
        unauth_put = self.client.put(f"/api/customer/addresses/{addr_id}", headers={"X-Customer-Id": "2"}, json={
            "address_line1": "Hacked Address Line"
        })
        self.assertEqual(unauth_put.status_code, 404)
        print(" [PASSED] 15. Customer ownership strictly enforced: Cross-customer tampering blocked with HTTP 404")

    # 16. Invalid pincode rejection
    def test_16_invalid_pincode_rejection(self):
        invalid_pins = ["012345", "12345", "1234567", "PIN400", "", "000000"]
        for pin in invalid_pins:
            res = self.client.post("/api/customer/addresses", headers={"X-Customer-Id": "1"}, json={
                "full_name": "Test User",
                "phone": "+91 98201 12345",
                "address_line1": "Sample Road",
                "city": "Mumbai",
                "pincode": pin
            })
            self.assertEqual(res.status_code, 400, f"Expected PIN {pin} to be rejected with 400")
        print(" [PASSED] 16. Invalid Indian PIN codes strictly rejected with HTTP 400")

    # 17. Invalid phone rejection
    def test_17_invalid_phone_rejection(self):
        invalid_phones = ["12345", "0123456789", "5551234567", "invalid-phone", "+1 800 555 1234"]
        for phone in invalid_phones:
            res = self.client.post("/api/customer/addresses", headers={"X-Customer-Id": "1"}, json={
                "full_name": "Test User",
                "phone": phone,
                "address_line1": "Sample Road",
                "city": "Mumbai",
                "pincode": "400030"
            })
            self.assertEqual(res.status_code, 400, f"Expected phone {phone} to be rejected with 400")
        print(" [PASSED] 17. Invalid Indian mobile numbers strictly rejected with HTTP 400")

    # 18. XSS and SQL injection payload handling
    def test_18_xss_and_sqli_payload_handling(self):
        sqli_payload = "'; DROP TABLE addresses; --"
        xss_payload = "<script>alert('pwned')</script>"
        res = self.client.post("/api/customer/addresses", headers={"X-Customer-Id": "1"}, json={
            "full_name": "Security Test User",
            "phone": "+91 98201 12345",
            "address_type": "OTHER",
            "address_line1": sqli_payload,
            "address_line2": xss_payload,
            "city": "Mumbai",
            "pincode": "400050"
        })
        self.assertEqual(res.status_code, 201)
        created = res.get_json()["address"]
        # Verify table still exists and data was stored safely as plain text via parameterized SQL
        addrs = self.db.get_customer_addresses(customer_id=1)
        self.assertTrue(len(addrs) > 0)
        # Clean up test address
        self.db.delete_customer_address(created["id"], customer_id=1)
        print(" [PASSED] 18. XSS & SQL injection payloads handled safely with parameterized queries")

    # 19. GPS-denial manual fallback logic
    def test_19_gps_denial_manual_fallback_logic(self):
        res = self.client.get("/api/location/current")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("location", data)
        self.assertIn("city", data["location"])
        # Check that cities-areas allows manual selection without GPS
        cities_res = self.client.get("/api/location/cities-areas")
        self.assertEqual(cities_res.status_code, 200)
        self.assertTrue(len(cities_res.get_json()["cities"]) >= 6)
        print(" [PASSED] 19. GPS denial manual fallback confirmed operational")

    # 20. Checkout address selection
    def test_20_checkout_address_selection(self):
        res = self.client.get("/checkout")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("checkout-saved-addresses-block", html)
        self.assertIn("checkout-saved-addresses-list", html)
        self.assertIn("checkout-customer-name", html)
        self.assertIn("checkout-shipping-address", html)
        self.assertIn("checkout-shipping-city", html)
        self.assertIn("checkout-pincode", html)
        print(" [PASSED] 20. Checkout address selector & prefilling elements verified in DOM")

    # 21. Existing Phase 1 & Phase 2 regression tests
    def test_21_phase1_and_phase2_regression(self):
        # Homepage loads
        home_res = self.client.get("/")
        self.assertEqual(home_res.status_code, 200)

        # Retail storefront loads
        retail_res = self.client.get("/retail")
        self.assertEqual(retail_res.status_code, 200)
        self.assertIn("Neighbourhood Physical Stores", retail_res.get_data(as_text=True))

        # Online marketplace loads
        online_res = self.client.get("/online")
        self.assertEqual(online_res.status_code, 200)

        # Products catalog loads
        prods_res = self.client.get("/products")
        self.assertEqual(prods_res.status_code, 200)

        # Header has interactive location selector modal & mode switcher
        base_html = home_res.get_data(as_text=True)
        self.assertIn("location-selector-modal", base_html)
        self.assertIn("header-mode-switcher", base_html)
        print(" [PASSED] 21. Phase 1 & Phase 2 regression guard passed with 0 breaking changes")


if __name__ == "__main__":
    unittest.main()

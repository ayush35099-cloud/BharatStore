"""
Test Suite: Five Independent Store Carts & Partial Checkout
============================================================
Comprehensive test suite verifying the 12 required scenarios for
five independent retail store baskets in BharatStore:
1. Bharat Fresh Mart (Store 1)
2. Daily Needs Supermarket (Store 2)
3. Green Basket Grocery (Store 3)
4. Sri Lakshmi Stores (Store 4)
5. Smart Choice Supermarket (Store 5)

Covers:
- Independent store cart additions
- Cross-store separation for identical products
- Independent quantity modifications and removals
- Partial multi-store checkout leaving unselected baskets active
- Stock decrement strictly upon checkout completion
- Persistence across sessions
- Full isolation between Retail Near Me and Online Shopping carts
"""

import unittest
import json
import uuid
from app import create_app
from app.database import DatabaseService


class TestFiveStoreCarts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()
        cls.db = DatabaseService()
        cls.db.reset_inventory()

    def setUp(self):
        self.cust_id = 200000 + int(uuid.uuid4().hex[:6], 16)
        self.session_id = f"test_session_{uuid.uuid4()}"
        self.headers = {
            "Content-Type": "application/json",
            "X-Customer-Id": str(self.cust_id),
            "X-Session-Id": self.session_id
        }

    # =========================================================================
    # Scenario 1 to 5: Add products to each of the 5 stores independently
    # =========================================================================
    def test_01_add_product_to_store_1_basket(self):
        """Scenario 1: Add a product to Store 1 (Bharat Fresh Mart) basket."""
        res = self.client.post(
            "/api/cart/retail/1/add",
            json={"product_id": 61, "quantity": 2, "fulfillment": "delivery"},
            headers=self.headers
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["cart"]["store_id"], 1)
        self.assertEqual(data["cart"]["store_name"], "Bharat Fresh Mart")
        self.assertEqual(data["cart"]["total_items"], 2)
        self.assertEqual(data["cart"]["items"][0]["unit_price"], 60.0)

    def test_02_add_product_to_store_2_basket(self):
        """Scenario 2: Add a product to Store 2 (Daily Needs Supermarket) basket."""
        res = self.client.post(
            "/api/cart/retail/2/add",
            json={"product_id": 65, "quantity": 1, "fulfillment": "delivery"},
            headers=self.headers
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["cart"]["store_id"], 2)
        self.assertEqual(data["cart"]["store_name"], "Daily Needs Supermarket")
        self.assertEqual(data["cart"]["total_items"], 1)

    def test_03_add_product_to_store_3_basket(self):
        """Scenario 3: Add a product to Store 3 (Green Basket Grocery) basket."""
        res = self.client.post(
            "/api/cart/retail/3/add",
            json={"product_id": 63, "quantity": 3, "fulfillment": "pickup"},
            headers=self.headers
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["cart"]["store_id"], 3)
        self.assertEqual(data["cart"]["store_name"], "Green Basket Grocery")
        self.assertEqual(data["cart"]["total_items"], 3)

    def test_04_add_product_to_store_4_basket(self):
        """Scenario 4: Add a product to Store 4 (Sri Lakshmi Stores) basket."""
        res = self.client.post(
            "/api/cart/retail/4/add",
            json={"product_id": 64, "quantity": 1, "fulfillment": "delivery"},
            headers=self.headers
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["cart"]["store_id"], 4)
        self.assertEqual(data["cart"]["store_name"], "Sri Lakshmi Stores")
        self.assertEqual(data["cart"]["total_items"], 1)

    def test_05_add_product_to_store_5_basket(self):
        """Scenario 5: Add a product to Store 5 (Smart Choice Supermarket) basket."""
        res = self.client.post(
            "/api/cart/retail/5/add",
            json={"product_id": 65, "quantity": 2, "fulfillment": "delivery"},
            headers=self.headers
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["cart"]["store_id"], 5)
        self.assertEqual(data["cart"]["store_name"], "Smart Choice Supermarket")
        self.assertEqual(data["cart"]["total_items"], 2)

    # =========================================================================
    # Scenario 6: Verify all 5 baskets exist independently
    # =========================================================================
    def test_06_verify_all_5_baskets_exist_independently(self):
        """Scenario 6: Verify all 5 baskets exist independently with correct products and store associations."""
        store_products = {
            1: (61, 2),  # Store 1: product 61, qty 2
            2: (65, 1),  # Store 2: product 65, qty 1
            3: (63, 3),  # Store 3: product 63, qty 3
            4: (64, 1),  # Store 4: product 64, qty 1
            5: (61, 2),  # Store 5: product 61, qty 2
        }

        for s_id, (p_id, qty) in store_products.items():
            r = self.client.post(
                f"/api/cart/retail/{s_id}/add",
                json={"product_id": p_id, "quantity": qty},
                headers=self.headers
            )
            self.assertEqual(r.status_code, 201)

        # Query all retail carts
        res = self.client.get("/api/cart/retail", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        self.assertTrue(data["success"])
        self.assertEqual(len(data["shops"]), 5)
        self.assertEqual(data["summary"]["store_count"], 5)
        self.assertEqual(data["summary"]["total_items"], 9)  # 2 + 1 + 3 + 1 + 2 = 9

        returned_store_ids = [s["store_id"] for s in data["shops"]]
        self.assertEqual(sorted(returned_store_ids), [1, 2, 3, 4, 5])

        expected_names = {
            1: "Bharat Fresh Mart",
            2: "Daily Needs Supermarket",
            3: "Green Basket Grocery",
            4: "Sri Lakshmi Stores",
            5: "Smart Choice Supermarket"
        }
        for shop in data["shops"]:
            sid = shop["store_id"]
            self.assertEqual(shop["store_name"], expected_names[sid])
            self.assertEqual(len(shop["items"]), 1)
            self.assertEqual(shop["items"][0]["product_id"], store_products[sid][0])
            self.assertEqual(shop["items"][0]["quantity"], store_products[sid][1])

    # =========================================================================
    # Scenario 7: Same product in two different stores has separate entries
    # =========================================================================
    def test_07_same_product_in_two_different_stores(self):
        """Scenario 7: Add same product to two stores and verify separate entries with independent quantities and prices."""
        # Product 61: Amul Taaza Milk 1L (available in both Store 1 and Store 2)
        # Add to Store 1 (Bharat Fresh Mart)
        res1 = self.client.post(
            "/api/cart/retail/1/add",
            json={"product_id": 61, "quantity": 3},
            headers=self.headers
        )
        self.assertEqual(res1.status_code, 201)
        cart1 = res1.get_json()["cart"]

        # Add to Store 2 (Daily Needs Supermarket)
        res2 = self.client.post(
            "/api/cart/retail/2/add",
            json={"product_id": 61, "quantity": 1},
            headers=self.headers
        )
        self.assertEqual(res2.status_code, 201)
        cart2 = res2.get_json()["cart"]

        # Store 1 checks
        self.assertEqual(cart1["store_id"], 1)
        self.assertEqual(cart1["total_items"], 3)
        self.assertEqual(cart1["items"][0]["unit_price"], 60.0)
        self.assertEqual(cart1["subtotal"], 180.0)

        # Store 2 checks
        self.assertEqual(cart2["store_id"], 2)
        self.assertEqual(cart2["total_items"], 1)
        self.assertEqual(cart2["items"][0]["unit_price"], 62.0)
        self.assertEqual(cart2["subtotal"], 62.0)

        # Overall retail carts check
        res_all = self.client.get("/api/cart/retail", headers=self.headers)
        shops = res_all.get_json()["shops"]
        self.assertEqual(len(shops), 2)
        s1 = next(s for s in shops if s["store_id"] == 1)
        s2 = next(s for s in shops if s["store_id"] == 2)
        self.assertEqual(s1["items"][0]["quantity"], 3)
        self.assertEqual(s1["items"][0]["unit_price"], 60.0)
        self.assertEqual(s2["items"][0]["quantity"], 1)
        self.assertEqual(s2["items"][0]["unit_price"], 62.0)

    # =========================================================================
    # Scenario 8: Modify quantity in one store basket
    # =========================================================================
    def test_08_modify_quantity_in_one_store_basket(self):
        """Scenario 8: Modify quantity in Store 1 basket and verify other stores are unaffected."""
        # Add to Store 1 and Store 2
        r1 = self.client.post("/api/cart/retail/1/add", json={"product_id": 61, "quantity": 2}, headers=self.headers)
        r2 = self.client.post("/api/cart/retail/2/add", json={"product_id": 61, "quantity": 4}, headers=self.headers)
        item1_id = r1.get_json()["cart"]["items"][0]["item_id"]

        # Update Store 1 item quantity from 2 to 5
        patch_res = self.client.patch(
            f"/api/cart/items/{item1_id}",
            json={"quantity": 5},
            headers=self.headers
        )
        self.assertEqual(patch_res.status_code, 200)

        # Verify Store 1 has 5, and Store 2 still has exactly 4
        c1 = self.client.get("/api/cart/retail/1", headers=self.headers).get_json()["cart"]
        c2 = self.client.get("/api/cart/retail/2", headers=self.headers).get_json()["cart"]

        self.assertEqual(c1["total_items"], 5)
        self.assertEqual(c1["items"][0]["quantity"], 5)
        self.assertEqual(c2["total_items"], 4)
        self.assertEqual(c2["items"][0]["quantity"], 4)

    # =========================================================================
    # Scenario 9: Remove a product from one store basket
    # =========================================================================
    def test_09_remove_product_from_one_store_basket(self):
        """Scenario 9: Remove a product from Store 1 and verify Store 2 basket is unaffected."""
        r1 = self.client.post("/api/cart/retail/1/add", json={"product_id": 61, "quantity": 2}, headers=self.headers)
        r2 = self.client.post("/api/cart/retail/2/add", json={"product_id": 65, "quantity": 3}, headers=self.headers)
        item1_id = r1.get_json()["cart"]["items"][0]["item_id"]

        # Remove item from Store 1
        del_res = self.client.delete(f"/api/cart/items/{item1_id}", headers=self.headers)
        self.assertEqual(del_res.status_code, 200)

        # Store 1 should now be empty
        c1 = self.client.get("/api/cart/retail/1", headers=self.headers).get_json()["cart"]
        self.assertEqual(c1["total_items"], 0)
        self.assertEqual(len(c1["items"]), 0)

        # Store 2 must remain completely intact
        c2 = self.client.get("/api/cart/retail/2", headers=self.headers).get_json()["cart"]
        self.assertEqual(c2["total_items"], 3)
        self.assertEqual(len(c2["items"]), 1)
        self.assertEqual(c2["items"][0]["product_id"], 65)

    # =========================================================================
    # Scenario 10: Checkout 2 of the 5 stores (Partial checkout)
    # =========================================================================
    def test_10_partial_checkout_preserves_unselected_stores(self):
        """Scenario 10: Checkout 2 of 5 stores; parent & sub-orders created; unselected baskets remain active; stock decreases only for checked-out stores."""
        # Add products to all 5 stores with verified stock
        store_items = [
            (1, 61),  # Store 1: product 61
            (2, 65),  # Store 2: product 65
            (3, 63),  # Store 3: product 63
            (4, 64),  # Store 4: product 64
            (5, 61),  # Store 5: product 61
        ]
        for sid, pid in store_items:
            r = self.client.post(
                f"/api/cart/retail/{sid}/add",
                json={"product_id": pid, "quantity": 2},
                headers=self.headers
            )
            self.assertEqual(r.status_code, 201)

        # Record initial stock before checkout
        inv1_before = self.db.get_store_product(1, 61)["stock_quantity"]
        inv2_before = self.db.get_store_product(2, 65)["stock_quantity"]
        inv3_before = self.db.get_store_product(3, 63)["stock_quantity"]

        # Perform partial checkout selecting only Stores 1 and 2
        chk_res = self.client.post(
            "/api/checkout/retail/multi-store",
            json={
                "selected_store_ids": [1, 2],
                "customer_info": {
                    "name": "Priya Sharma",
                    "email": "priya.sharma@example.in",
                    "phone": "+91 98201 12345",
                    "address": "CMH Road, Indiranagar",
                    "city": "Bengaluru"
                },
                "delivery_address": {
                    "formatted": "CMH Road, Indiranagar, Bengaluru",
                    "city": "Bengaluru",
                    "latitude": 12.9784,
                    "longitude": 77.6408
                },
                "payment_method": "UPI"
            },
            headers=self.headers
        )
        self.assertEqual(chk_res.status_code, 201)
        chk_data = chk_res.get_json()
        self.assertTrue(chk_data["success"])

        # 1. Verify parent order and sub-orders
        self.assertIn("BK-RET-P-", chk_data["parent_order_number"])
        self.assertEqual(len(chk_data["suborders"]), 2)
        sub_store_ids = [s["store_id"] for s in chk_data["suborders"]]
        self.assertEqual(sorted(sub_store_ids), [1, 2])
        for sub in chk_data["suborders"]:
            self.assertIn(f"BK-RET-S{sub['store_id']}-", sub["suborder_number"])

        # 2. Verify unselected stores (Stores 3, 4, 5) remain active in DB
        remaining_res = self.client.get("/api/cart/retail", headers=self.headers)
        remaining_data = remaining_res.get_json()
        active_store_ids = [s["store_id"] for s in remaining_data["shops"]]
        self.assertEqual(sorted(active_store_ids), [3, 4, 5])
        self.assertEqual(remaining_data["summary"]["store_count"], 3)
        self.assertEqual(remaining_data["summary"]["total_items"], 6)  # 2 + 2 + 2 = 6

        # 3. Verify stock decremented ONLY for checked-out stores (Stores 1 & 2), NOT Store 3
        inv1_after = self.db.get_store_product(1, 61)["stock_quantity"]
        inv2_after = self.db.get_store_product(2, 65)["stock_quantity"]
        inv3_after = self.db.get_store_product(3, 63)["stock_quantity"]

        self.assertEqual(inv1_after, inv1_before - 2)
        self.assertEqual(inv2_after, inv2_before - 2)
        self.assertEqual(inv3_after, inv3_before)  # Store 3 stock unchanged!

    # =========================================================================
    # Scenario 11: Cart contents persist across browser reload / session refresh
    # =========================================================================
    def test_11_cart_persists_across_session_refresh(self):
        """Scenario 11: Verify cart contents persist across browser reload / session refresh."""
        # Add to Store 1 and Store 4
        self.client.post("/api/cart/retail/1/add", json={"product_id": 61, "quantity": 3}, headers=self.headers)
        self.client.post("/api/cart/retail/4/add", json={"product_id": 64, "quantity": 2}, headers=self.headers)

        # Simulate fresh HTTP request with same session headers (simulating browser reload)
        fresh_res = self.client.get("/api/cart/retail", headers=self.headers)
        self.assertEqual(fresh_res.status_code, 200)
        data = fresh_res.get_json()

        self.assertEqual(data["summary"]["store_count"], 2)
        self.assertEqual(data["summary"]["total_items"], 5)
        shops = data["shops"]
        s1 = next(s for s in shops if s["store_id"] == 1)
        s4 = next(s for s in shops if s["store_id"] == 4)
        self.assertEqual(s1["items"][0]["quantity"], 3)
        self.assertEqual(s4["items"][0]["quantity"], 2)

    # =========================================================================
    # Scenario 12: Retail Near Me carts do not interfere with Online Shopping cart
    # =========================================================================
    def test_12_retail_and_online_cart_isolation(self):
        """Scenario 12: Verify Retail Near Me carts and Online Shopping cart remain completely isolated."""
        # Add tech item (ID 1: Apple iPhone 15 Pro) to Online cart
        res_online = self.client.post(
            "/api/cart/online/add",
            json={"product_id": 1, "quantity": 1},
            headers=self.headers
        )
        self.assertEqual(res_online.status_code, 201)

        # Add grocery item (ID 61: Amul Taaza Milk) to Retail Store 1
        res_retail = self.client.post(
            "/api/cart/retail/1/add",
            json={"product_id": 61, "quantity": 2},
            headers=self.headers
        )
        self.assertEqual(res_retail.status_code, 201)

        # Verify Online cart only has product 1
        online_cart = self.client.get("/api/cart/online", headers=self.headers).get_json()["cart"]
        self.assertEqual(online_cart["total_items"], 1)
        self.assertEqual(online_cart["items"][0]["product_id"], 1)

        # Verify Retail cart only has product 61
        retail_cart = self.client.get("/api/cart/retail/1", headers=self.headers).get_json()["cart"]
        self.assertEqual(retail_cart["total_items"], 2)
        self.assertEqual(retail_cart["items"][0]["product_id"], 61)

        # Verify Summary endpoint reports both accurately
        sum_res = self.client.get("/api/cart/summary", headers=self.headers)
        sum_data = sum_res.get_json()
        self.assertEqual(sum_data["online"]["total_items"], 1)
        self.assertEqual(sum_data["retail"]["total_items"], 2)
        self.assertEqual(sum_data["total_items"], 3)

    # =========================================================================
    # Physical stock integrity test
    # =========================================================================
    def test_13_cart_modifications_do_not_decrement_physical_stock(self):
        """Stock integrity: Adding, updating qty, or removing items must NOT change stock in DB."""
        inv_before = self.db.get_store_product(1, 61)["stock_quantity"]

        # 1. Add to cart
        r = self.client.post("/api/cart/retail/1/add", json={"product_id": 61, "quantity": 3}, headers=self.headers)
        inv_after_add = self.db.get_store_product(1, 61)["stock_quantity"]
        self.assertEqual(inv_after_add, inv_before)

        # 2. Update quantity
        item_id = r.get_json()["cart"]["items"][0]["item_id"]
        self.client.patch(f"/api/cart/items/{item_id}", json={"quantity": 5}, headers=self.headers)
        inv_after_update = self.db.get_store_product(1, 61)["stock_quantity"]
        self.assertEqual(inv_after_update, inv_before)

        # 3. Delete from cart
        self.client.delete(f"/api/cart/items/{item_id}", headers=self.headers)
        inv_after_delete = self.db.get_store_product(1, 61)["stock_quantity"]
        self.assertEqual(inv_after_delete, inv_before)


if __name__ == "__main__":
    unittest.main()

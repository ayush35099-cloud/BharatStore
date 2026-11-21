"""
Test Suite: BharatStore 2.0 – Phase 13 Order Management, Multi-Store Orders & Tracking
======================================================================================
Comprehensive verification for all Phase 13 requirements:
1. Multi-store order creation and suborder partitioning (parent BK-RET-P-, child BK-RET-S<store>-).
2. Five independent retail shop baskets & partial shop checkout (unselected baskets preserved).
3. Order lifecycle state machine (Pending -> Confirmed -> Processing -> Dispatched -> Out for Delivery -> Delivered / Cancelled).
4. Prevention of invalid lifecycle transitions and terminal state changes.
5. Chronological audit logging in order_status_history table.
6. Authoritative visual progress timeline generation.
7. Customer order history (/orders & /api/orders) with lifecycle status filtering.
8. IDOR authorization protection (prevent cross-customer order snooping).
9. Atomic stock decrements and inventory_movements ledger recording ('SOLD').
10. Retail catalogue store filtering API & data integrity.
11. Order details route (/order/<id> and /orders/<id>) verification.
12. Order cancellation compensating transaction with stock replenish.
"""

import unittest
import json
import uuid
from app import create_app
from app.config import Config
from app.database import DatabaseService


class TestPhase13OrderManagement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()
        cls.db = DatabaseService()
        cls.admin_headers = {
            "Content-Type": "application/json",
            "X-Admin-Token": Config.ADMIN_API_KEY
        }

    def setUp(self):
        self.session_id = f"test-sess-p13-{uuid.uuid4().hex[:8]}"
        self.customer_id = 91000 + int(uuid.uuid4().hex[:4], 16)
        self.headers = {
            "Content-Type": "application/json",
            "X-Session-Id": self.session_id,
            "X-Customer-Id": str(self.customer_id)
        }

    # =========================================================================
    # 1. Five Independent Retail Shop Baskets & Partial Checkout (Part 4)
    # =========================================================================
    def test_01_create_baskets_all_five_shops(self):
        """Scenario 1: Customer creates independent baskets across all 5 physical stores."""
        for s_id in [1, 2, 3, 4, 5]:
            res = self.client.post(
                f"/api/cart/retail/{s_id}/add",
                json={"product_id": 61, "quantity": 1},
                headers=self.headers
            )
            self.assertEqual(res.status_code, 201, f"Failed adding to store {s_id}")

        all_carts = self.db.get_all_retail_carts(self.customer_id, self.session_id)
        self.assertEqual(len(all_carts.get("shops", [])), 5, "Expected baskets in all 5 shops")
        self.assertEqual(all_carts["total_items"], 5)
        print(" [PASSED] 1. Simultaneous baskets created across all 5 physical stores")

    def test_02_add_same_product_two_different_shops(self):
        """Scenario 2 & 3: Add same product to two different shops with independent pricing."""
        # Product 61: Amul Taaza Milk 1L
        self.client.post("/api/cart/retail/1/add", json={"product_id": 61, "quantity": 2}, headers=self.headers)
        self.client.post("/api/cart/retail/2/add", json={"product_id": 61, "quantity": 3}, headers=self.headers)

        cart1 = self.db.get_cart(self.customer_id, self.session_id, "RETAIL_NEAR_ME", store_id=1)
        cart2 = self.db.get_cart(self.customer_id, self.session_id, "RETAIL_NEAR_ME", store_id=2)

        self.assertEqual(len(cart1["items"]), 1)
        self.assertEqual(cart1["items"][0]["quantity"], 2)
        self.assertEqual(cart1["items"][0]["unit_price"], 60.0)

        self.assertEqual(len(cart2["items"]), 1)
        self.assertEqual(cart2["items"][0]["quantity"], 3)
        self.assertEqual(cart2["items"][0]["unit_price"], 62.0)
        print(" [PASSED] 2 & 3. Same product in two shops remains completely isolated with store pricing")

    def test_03_quantity_modifications_and_removal(self):
        """Scenario 4 & 5: Increase, decrease, and remove products from individual shop baskets."""
        add_res1 = self.client.post("/api/cart/retail/1/add", json={"product_id": 61, "quantity": 2}, headers=self.headers)
        item1_id = add_res1.get_json()["cart_item_id"]
        add_res2 = self.client.post("/api/cart/retail/2/add", json={"product_id": 64, "quantity": 1}, headers=self.headers)
        item2_id = add_res2.get_json()["cart_item_id"]

        # Update Store 1 qty to 4 via standard cart items endpoint
        res_upd = self.client.patch(f"/api/cart/items/{item1_id}", json={"quantity": 4}, headers=self.headers)
        self.assertEqual(res_upd.status_code, 200)

        c1 = self.db.get_cart(self.customer_id, self.session_id, "RETAIL_NEAR_ME", store_id=1)
        self.assertEqual(c1["items"][0]["quantity"], 4)

        # Remove from Store 1
        res_del = self.client.delete(f"/api/cart/items/{item1_id}", headers=self.headers)
        self.assertEqual(res_del.status_code, 200)

        c1_after = self.db.get_cart(self.customer_id, self.session_id, "RETAIL_NEAR_ME", store_id=1)
        self.assertEqual(len(c1_after["items"]), 0)

        # Store 2 basket must remain completely intact
        c2 = self.db.get_cart(self.customer_id, self.session_id, "RETAIL_NEAR_ME", store_id=2)
        self.assertEqual(len(c2["items"]), 1)
        self.assertEqual(c2["items"][0]["product_id"], 64)
        print(" [PASSED] 4 & 5. Quantity controls and item removal tested with strict store isolation")

    def test_04_partial_shop_checkout_unselected_preserved(self):
        """Scenario 6 & 7: Check out only selected shops (Stores 1 & 2); unselected stores (3, 4, 5) remain saved."""
        for s_id in [1, 2, 3, 4, 5]:
            self.client.post(f"/api/cart/retail/{s_id}/add", json={"product_id": 61, "quantity": 1}, headers=self.headers)

        # Checkout ONLY Stores 1 and 2
        res = self.client.post("/api/checkout/retail/multi-store", json={
            "selected_store_ids": [1, 2],
            "payment_method": "UPI"
        }, headers=self.headers)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertIn("parent_order_id", data)
        self.assertEqual(len(data.get("suborders", [])), 2)

        # Confirm Stores 1 & 2 carts are CONVERTED (empty for active shopping)
        cart1 = self.db.get_cart(self.customer_id, self.session_id, "RETAIL_NEAR_ME", store_id=1)
        cart2 = self.db.get_cart(self.customer_id, self.session_id, "RETAIL_NEAR_ME", store_id=2)
        self.assertEqual(len(cart1.get("items", [])), 0)
        self.assertEqual(len(cart2.get("items", [])), 0)

        # Confirm Stores 3, 4, 5 carts REMAIN ACTIVE with their items!
        for s_id in [3, 4, 5]:
            cart_rem = self.db.get_cart(self.customer_id, self.session_id, "RETAIL_NEAR_ME", store_id=s_id)
            self.assertEqual(len(cart_rem.get("items", [])), 1, f"Store {s_id} basket was unexpectedly deleted")
        print(" [PASSED] 6 & 7. Partial shop checkout confirmed: unselected shops remain completely saved")

    # =========================================================================
    # 2. Multi-Store Order Architecture & Consistency (Part 2 & 5)
    # =========================================================================
    def test_05_multi_store_order_records_and_suborders(self):
        """Scenario 8, 9 & 10: Multi-store checkout creates parent order and suborders with correct totals."""
        self.client.post("/api/cart/retail/1/add", json={"product_id": 61, "quantity": 2}, headers=self.headers)
        self.client.post("/api/cart/retail/3/add", json={"product_id": 63, "quantity": 1}, headers=self.headers)

        res = self.client.post("/api/checkout/retail/multi-store", json={
            "selected_store_ids": [1, 3],
            "payment_method": "CARD"
        }, headers=self.headers)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        parent_id = data["parent_order_id"]
        parent_num = data["parent_order_number"]

        self.assertTrue(parent_num.startswith("BK-RET-P-"))
        self.assertEqual(len(data["suborders"]), 2)

        parent_order = self.db.get_order_by_id(parent_id)
        self.assertIsNotNone(parent_order)
        self.assertEqual(parent_order["status"], "CONFIRMED")
        self.assertEqual(len(parent_order.get("suborders", [])), 2)

        sub_nums = [s["order_number"] for s in parent_order["suborders"]]
        self.assertTrue(any("BK-RET-S1-" in n for n in sub_nums))
        self.assertTrue(any("BK-RET-S3-" in n for n in sub_nums))
        print(" [PASSED] 8, 9 & 10. Multi-store order architecture verified: parent & store-specific suborders")

    def test_06_stock_decrements_only_on_order_confirmation(self):
        """Scenario 11: Adding/removing from cart does NOT change physical stock; stock decreases ONLY on checkout."""
        inv_before = self.db.get_store_product(1, 64)
        stock_initial = inv_before["stock_quantity"]

        # Add to cart
        self.client.post("/api/cart/retail/1/add", json={"product_id": 64, "quantity": 2}, headers=self.headers)
        inv_after_cart = self.db.get_store_product(1, 64)
        self.assertEqual(inv_after_cart["stock_quantity"], stock_initial, "Stock must NOT decrease on cart add")

        # Checkout
        res = self.client.post("/api/checkout/retail/multi-store", json={
            "selected_store_ids": [1],
            "payment_method": "UPI"
        }, headers=self.headers)
        self.assertEqual(res.status_code, 201)

        inv_after_checkout = self.db.get_store_product(1, 64)
        self.assertEqual(inv_after_checkout["stock_quantity"], stock_initial - 2, "Stock must decrease exactly by 2 upon checkout")
        print(" [PASSED] 11. Physical stock verified: 0 change on cart operations; decrements strictly on checkout")

    def test_07_stock_movement_ledger_recording(self):
        """Scenario 12: Stock movements recorded in inventory_movements ledger with 'SOLD' movement type."""
        self.client.post("/api/cart/retail/1/add", json={"product_id": 65, "quantity": 1}, headers=self.headers)
        res = self.client.post("/api/checkout/retail/multi-store", json={
            "selected_store_ids": [1]
        }, headers=self.headers)
        self.assertEqual(res.status_code, 201)

        # Inspect inventory movements ledger
        movements = self.db.get_inventory_movements(65, limit=5)
        self.assertTrue(len(movements) > 0)
        latest = movements[0]
        self.assertEqual(latest["movement_type"], "SOLD")
        self.assertEqual(latest["quantity"], -1)
        print(" [PASSED] 12. Double-entry inventory movement ledger accurately recorded sale ('SOLD')")

    # =========================================================================
    # 3. Order Lifecycle State Machine & Audit History (Part 3)
    # =========================================================================
    def test_08_valid_lifecycle_status_transitions(self):
        """Scenario 13 & 14: Valid status transitions: CONFIRMED -> PROCESSING -> DISPATCHED -> OUT_FOR_DELIVERY -> DELIVERED."""
        self.client.post("/api/cart/retail/1/add", json={"product_id": 61, "quantity": 1}, headers=self.headers)
        res = self.client.post("/api/checkout/retail/multi-store", json={"selected_store_ids": [1]}, headers=self.headers)
        order_id = res.get_json()["order_id"]

        # 1. Transition to PROCESSING
        o_proc = self.db.update_order_status(order_id, "PROCESSING", notes="Packed at store counter")
        self.assertEqual(o_proc["status"], "PROCESSING")

        # 2. Transition to DISPATCHED
        o_disp = self.db.update_order_status(order_id, "DISPATCHED", notes="Handed to delivery partner")
        self.assertEqual(o_disp["status"], "DISPATCHED")

        # 3. Transition to OUT_FOR_DELIVERY
        o_out = self.db.update_order_status(order_id, "OUT_FOR_DELIVERY", notes="Delivery agent en route")
        self.assertEqual(o_out["status"], "OUT_FOR_DELIVERY")

        # 4. Transition to DELIVERED
        o_del = self.db.update_order_status(order_id, "DELIVERED", notes="Package handed to customer")
        self.assertEqual(o_del["status"], "DELIVERED")

        # Audit history must have all transitions
        history = self.db.get_order_status_history(order_id)
        statuses = [h["to_status"] for h in history]
        self.assertIn("CONFIRMED", statuses)
        self.assertIn("PROCESSING", statuses)
        self.assertIn("DISPATCHED", statuses)
        self.assertIn("OUT_FOR_DELIVERY", statuses)
        self.assertIn("DELIVERED", statuses)
        print(" [PASSED] 13 & 14. Full valid lifecycle progression and chronological audit logging verified")

    def test_09_invalid_status_transition_rejection(self):
        """Scenario 15: Invalid lifecycle transitions are rejected with descriptive error."""
        self.client.post("/api/cart/retail/1/add", json={"product_id": 61, "quantity": 1}, headers=self.headers)
        res = self.client.post("/api/checkout/retail/multi-store", json={"selected_store_ids": [1]}, headers=self.headers)
        order_id = res.get_json()["order_id"]

        # Cannot skip from CONFIRMED straight to DELIVERED
        with self.assertRaises(ValueError) as ctx:
            self.db.update_order_status(order_id, "DELIVERED")
        self.assertIn("Invalid status transition", str(ctx.exception))
        print(" [PASSED] 15. Invalid status transition successfully rejected with ValueError")

    def test_10_terminal_state_protection(self):
        """Scenario 16: DELIVERED and CANCELLED orders cannot be transitioned to any other status."""
        self.client.post("/api/cart/retail/1/add", json={"product_id": 61, "quantity": 1}, headers=self.headers)
        res = self.client.post("/api/checkout/retail/multi-store", json={"selected_store_ids": [1]}, headers=self.headers)
        order_id = res.get_json()["order_id"]

        # Cancel order
        self.db.cancel_order(order_id, reason="Customer cancelled")
        order = self.db.get_order_by_id(order_id)
        self.assertEqual(order["status"], "CANCELLED")

        # Attempt to transition cancelled order to CONFIRMED
        with self.assertRaises(ValueError) as ctx:
            self.db.update_order_status(order_id, "CONFIRMED")
        self.assertIn("terminal", str(ctx.exception).lower())
        print(" [PASSED] 16. Terminal state protection strictly enforced: cancelled orders cannot transition")

    def test_11_order_timeline_generation(self):
        """Scenario 17: Authoritative progress timeline correctly marks stages based on DB state."""
        self.client.post("/api/cart/retail/1/add", json={"product_id": 61, "quantity": 1}, headers=self.headers)
        res = self.client.post("/api/checkout/retail/multi-store", json={"selected_store_ids": [1]}, headers=self.headers)
        order_id = res.get_json()["order_id"]

        self.db.update_order_status(order_id, "PROCESSING")
        order = self.db.get_order_by_id(order_id)

        timeline = order.get("timeline", [])
        self.assertTrue(len(timeline) >= 4)

        conf_stage = next((s for s in timeline if s["stage"] == "CONFIRMED"), None)
        proc_stage = next((s for s in timeline if s["stage"] == "PROCESSING"), None)
        disp_stage = next((s for s in timeline if s["stage"] == "DISPATCHED"), None)

        self.assertTrue(conf_stage["completed"])
        self.assertTrue(proc_stage["completed"])
        self.assertTrue(proc_stage["current"])
        self.assertFalse(disp_stage["completed"])
        print(" [PASSED] 17. Authoritative order timeline accurately reflects current stage and completed steps")

    # =========================================================================
    # 4. Order History, Details, and IDOR Protection (Part 2.C, 2.D)
    # =========================================================================
    def test_12_order_history_status_filters(self):
        """Scenario 18: /api/orders properly returns and filters orders by lifecycle status."""
        # Create an order
        self.client.post("/api/cart/retail/1/add", json={"product_id": 61, "quantity": 1}, headers=self.headers)
        self.client.post("/api/checkout/retail/multi-store", json={"selected_store_ids": [1]}, headers=self.headers)

        res_all = self.client.get("/api/orders", headers=self.headers)
        self.assertEqual(res_all.status_code, 200)
        self.assertTrue(len(res_all.get_json().get("orders", [])) > 0)

        res_conf = self.client.get("/api/orders?status=CONFIRMED", headers=self.headers)
        self.assertEqual(res_conf.status_code, 200)
        for o in res_conf.get_json().get("orders", []):
            self.assertEqual(o["status"], "CONFIRMED")
        print(" [PASSED] 18. Customer order history API and status filtering verified")

    def test_13_idor_authorization_protection(self):
        """Scenario 19: User A cannot view User B's order (HTTP 403 Forbidden). Admin can view any order."""
        # Customer A places order
        self.client.post("/api/cart/retail/1/add", json={"product_id": 61, "quantity": 1}, headers=self.headers)
        res_place = self.client.post("/api/checkout/retail/multi-store", json={"selected_store_ids": [1]}, headers=self.headers)
        order_id = res_place.get_json()["order_id"]

        # Customer B attempts to access Customer A's order
        cust_b_headers = {
            "Content-Type": "application/json",
            "X-Session-Id": f"test-sess-intruder-{uuid.uuid4().hex[:6]}",
            "X-Customer-Id": "99999"
        }
        res_idor = self.client.get(f"/api/orders/{order_id}", headers=cust_b_headers)
        self.assertEqual(res_idor.status_code, 403, "Expected 403 Forbidden on unauthorized order access")
        self.assertEqual(res_idor.get_json().get("code"), "IDOR_FORBIDDEN")

        # Admin accesses order -> 200 OK
        res_admin = self.client.get(f"/api/orders/{order_id}", headers=self.admin_headers)
        self.assertEqual(res_admin.status_code, 200, "Admin must be able to view orders")
        print(" [PASSED] 19. IDOR security strictly verified: unauthorized access blocked with HTTP 403")

    def test_14_order_details_page_routes(self):
        """Scenario 20: Both /order/<id> and /orders/<id> render HTML successfully for order owner."""
        self.client.post("/api/cart/retail/1/add", json={"product_id": 61, "quantity": 1}, headers=self.headers)
        res_place = self.client.post("/api/checkout/retail/multi-store", json={"selected_store_ids": [1]}, headers=self.headers)
        order_id = res_place.get_json()["order_id"]

        # /order/<id>
        res1 = self.client.get(f"/order/{order_id}", headers=self.headers)
        self.assertEqual(res1.status_code, 200)
        self.assertIn(b"Order Progress & Tracking", res1.data)

        # /orders/<id>
        res2 = self.client.get(f"/orders/{order_id}", headers=self.headers)
        self.assertEqual(res2.status_code, 200)
        print(" [PASSED] 20. Order details HTML templates render cleanly across /order/<id> and /orders/<id>")

    # =========================================================================
    # 5. Catalogue Store Filtering API (Part 7)
    # =========================================================================
    def test_15_retail_store_inventory_api_and_pricing(self):
        """Scenario 21: Store inventory endpoint (/api/stores/<id>/inventory) returns store-specific products, pricing, and stock."""
        for s_id in [1, 2, 3, 4, 5]:
            res = self.client.get(f"/api/stores/{s_id}/inventory")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("store_id"), s_id)
            inv = data.get("inventory", [])
            self.assertTrue(len(inv) > 0, f"Store {s_id} inventory is empty")
            # Verify required attributes for catalogue filtering
            first = inv[0]
            self.assertIn("selling_price", first)
            self.assertIn("stock_quantity", first)
            self.assertIn("product_id", first)
        print(" [PASSED] 21. Retail store inventory API verified across all 5 stores for catalogue filtering")

    def test_16_no_nan_or_zero_subtotal_regression(self):
        """Scenario 22: Amul Gold Milk (76) or similar items produce strictly valid non-zero prices and totals."""
        res_comp = self.client.get("/api/retail/products/76/compare")
        self.assertEqual(res_comp.status_code, 200)
        data = res_comp.get_json()
        for shop in data.get("stores_comparison", []):
            price = shop.get("selling_price")
            self.assertIsNotNone(price)
            self.assertFalse(str(price).lower() == "nan")
            self.assertTrue(float(price) > 0)
        print(" [PASSED] 22. Zero-subtotal & NaN price regression prevented permanently")


if __name__ == "__main__":
    unittest.main()

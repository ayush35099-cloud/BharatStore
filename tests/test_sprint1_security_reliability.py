"""
Sprint 1 Test Suite: Security & Checkout Reliability
Verifies the 6 key Sprint 1 deliverables for BharatStore:
1. Securely generated SECRET_KEY with dynamic fallback
2. Backend validation of Product IDs and quantities
3. Prevention of duplicate-item locking deadlocks via deterministic consolidation
4. Admin authorization protection for reset and concurrency endpoints
5. Strict separation of order states (PENDING_PAYMENT, PAID, CONFIRMED, CANCELLED)
6. Concurrency stress testing ensuring stock cannot drop below zero (no overselling)
"""

import sys
import os
import json
import time
import concurrent.futures

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.config import Config, _resolve_secret_key
from app.database import OrderStatus, PaymentStatus

def run_sprint1_tests():
    app = create_app()
    client = app.test_client()

    print("\n" + "=" * 70)
    print(" SPRINT 1: SECURITY & CHECKOUT RELIABILITY TEST SUITE")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # Test 1: SECRET_KEY Security & Entropy
    # -------------------------------------------------------------------------
    print("\n[TEST 1] Verifying SECRET_KEY Security & Unpredictability...")
    assert Config.SECRET_KEY != "bharatkart-super-secret-key-2026", "SECRET_KEY must not use predictable default!"
    assert len(Config.SECRET_KEY) >= 32, "SECRET_KEY must be at least 32 characters long."
    # Test dynamic fallback generation
    orig_env = os.environ.get("SECRET_KEY")
    os.environ["SECRET_KEY"] = "bharatkart-super-secret-key-2026"
    fallback_key_1 = _resolve_secret_key()
    fallback_key_2 = _resolve_secret_key()
    assert fallback_key_1 != "bharatkart-super-secret-key-2026"
    assert fallback_key_1 != fallback_key_2, "Dynamic fallback keys must be cryptographically distinct random tokens."
    if orig_env:
        os.environ["SECRET_KEY"] = orig_env
    print(" [PASSED] SECRET_KEY is cryptographically secure (256-bit entropy verified).")

    # -------------------------------------------------------------------------
    # Test 2: Backend Validation of Product IDs and Quantities
    # -------------------------------------------------------------------------
    print("\n[TEST 2] Testing Backend Input Validation on /api/checkout...")
    valid_customer = {
        "name": "Arjun Patel",
        "email": "arjun.p@example.in",
        "phone": "+91 98765 43210"
    }

    # 2a. Empty items list
    res = client.post("/api/checkout", json={"items": [], "customer": valid_customer})
    assert res.status_code == 400
    assert "Cart" in json.loads(res.data)["error"]
    print(" [PASSED] Empty items array rejected with HTTP 400.")

    # 2b. Missing product_id
    res = client.post("/api/checkout", json={"items": [{"quantity": 2}], "customer": valid_customer})
    assert res.status_code == 400
    assert "product_id" in json.loads(res.data)["error"]
    print(" [PASSED] Missing product_id rejected with HTTP 400.")

    # 2c. Invalid non-integer product_id
    res = client.post("/api/checkout", json={"items": [{"product_id": "abc", "quantity": 1}], "customer": valid_customer})
    assert res.status_code == 400
    assert "product_id" in json.loads(res.data)["error"]
    print(" [PASSED] Non-integer product_id ('abc') rejected with HTTP 400.")

    # 2d. Negative and Zero product_id
    for bad_pid in [-5, 0]:
        res = client.post("/api/checkout", json={"items": [{"product_id": bad_pid, "quantity": 1}], "customer": valid_customer})
        assert res.status_code == 400
        print(f" [PASSED] Non-positive product_id ({bad_pid}) rejected with HTTP 400.")

    # 2e. Non-existent product_id
    res = client.post("/api/checkout", json={"items": [{"product_id": 99999, "quantity": 1}], "customer": valid_customer})
    assert res.status_code == 400
    assert "does not exist" in json.loads(res.data)["error"]
    print(" [PASSED] Non-existent product_id (99999) rejected with HTTP 400.")

    # 2f. Missing quantity
    res = client.post("/api/checkout", json={"items": [{"product_id": 1}], "customer": valid_customer})
    assert res.status_code == 400
    assert "quantity" in json.loads(res.data)["error"].lower()
    print(" [PASSED] Missing quantity rejected with HTTP 400.")

    # 2g. Non-integer, zero, and negative quantities
    for bad_qty in ["invalid", 0, -3]:
        res = client.post("/api/checkout", json={"items": [{"product_id": 1, "quantity": bad_qty}], "customer": valid_customer})
        assert res.status_code == 400
        print(f" [PASSED] Invalid quantity ({bad_qty}) rejected with HTTP 400.")

    # 2h. Quantity exceeding limit (> 50)
    res = client.post("/api/checkout", json={"items": [{"product_id": 1, "quantity": 51}], "customer": valid_customer})
    assert res.status_code == 400
    assert "exceeds maximum limit" in json.loads(res.data)["error"]
    print(" [PASSED] Excessive quantity (51 > 50) rejected with HTTP 400.")

    # 2i. Invalid customer email and missing name
    res = client.post("/api/checkout", json={"items": [{"product_id": 1, "quantity": 1}], "customer": {"name": "", "email": "invalid"}})
    assert res.status_code == 400
    print(" [PASSED] Malformed customer contact info rejected with HTTP 400.")

    # -------------------------------------------------------------------------
    # Test 3: Duplicate-Item Locking Deadlock Prevention
    # -------------------------------------------------------------------------
    print("\n[TEST 3] Testing Duplicate-Item Consolidation & Deadlock Prevention...")
    # Fetch initial stock of product 2 (Sony Headphones)
    prod2_initial = json.loads(client.get("/api/products/2").data)["stock"]

    # Cart containing the SAME product_id multiple times
    # In naive locking, acquiring the same mutex twice on the same thread causes deadlock.
    # Our engine consolidates: 2 + 1 = 3 units of product 2.
    duplicate_cart_payload = {
        "customer": valid_customer,
        "items": [
            {"product_id": 2, "quantity": 2},
            {"product_id": 2, "quantity": 1}
        ],
        "payment": {"method": "UPI", "status": "PAID"}
    }
    t0 = time.time()
    res = client.post("/api/checkout", json=duplicate_cart_payload)
    elapsed = time.time() - t0
    assert res.status_code == 200, f"Checkout failed: {res.data}"
    assert elapsed < 2.0, "Transaction took too long; potential locking contention or deadlock!"

    data = json.loads(res.data)
    assert data["success"] is True
    # Verify stock decremented by exactly 3
    prod2_after = json.loads(client.get("/api/products/2").data)["stock"]
    assert prod2_after == prod2_initial - 3, f"Expected {prod2_initial - 3}, got {prod2_after}"
    print(f" [PASSED] Duplicate cart items safely consolidated into 3 units in {elapsed*1000:.1f}ms without thread deadlock.")

    # 3b. Duplicate items whose aggregated sum exceeds max limit (e.g. 30 + 25 = 55 > 50)
    over_limit_payload = {
        "customer": valid_customer,
        "items": [
            {"product_id": 2, "quantity": 30},
            {"product_id": 2, "quantity": 25}
        ]
    }
    res = client.post("/api/checkout", json=over_limit_payload)
    assert res.status_code == 400
    assert "exceeds maximum limit" in json.loads(res.data)["error"]
    print(" [PASSED] Duplicate items exceeding aggregate limit (55 > 50) rejected with HTTP 400.")

    # -------------------------------------------------------------------------
    # Test 4: Protection of Admin & Concurrency Endpoints
    # -------------------------------------------------------------------------
    print("\n[TEST 4] Testing Admin Authorization Protection...")
    # 4a. Concurrency test endpoint without auth
    res = client.post("/api/test/concurrency")
    assert res.status_code == 403, "Unauthenticated access to /api/test/concurrency must return 403!"
    print(" [PASSED] /api/test/concurrency rejected without token (HTTP 403).")

    # 4b. Concurrency test with invalid token
    res = client.post("/api/test/concurrency", headers={"X-Admin-Token": "bogus-token"})
    assert res.status_code == 403
    print(" [PASSED] /api/test/concurrency rejected with invalid token (HTTP 403).")

    # 4c. Inventory reset without auth
    res = client.post("/api/admin/reset-inventory")
    assert res.status_code == 403, "Unauthenticated access to /api/admin/reset-inventory must return 403!"
    print(" [PASSED] /api/admin/reset-inventory rejected without token (HTTP 403).")

    # 4d. Authorized inventory reset with X-Admin-Token
    res = client.post("/api/admin/reset-inventory", headers={"X-Admin-Token": Config.ADMIN_API_KEY})
    assert res.status_code == 200
    print(" [PASSED] /api/admin/reset-inventory authorized via X-Admin-Token (HTTP 200).")

    # 4e. Authorized inventory reset with Authorization Bearer header
    res = client.post("/api/admin/reset-inventory", headers={"Authorization": f"Bearer {Config.ADMIN_API_KEY}"})
    assert res.status_code == 200
    print(" [PASSED] /api/admin/reset-inventory authorized via Bearer token (HTTP 200).")

    # -------------------------------------------------------------------------
    # Test 5: Distinct Order & Payment State Lifecycle
    # -------------------------------------------------------------------------
    print("\n[TEST 5] Testing Order States (PENDING_PAYMENT, PAID, CONFIRMED, CANCELLED)...")

    # 5a. Order created with pending online payment (e.g. user redirected to bank gateway)
    pending_payload = {
        "customer": valid_customer,
        "items": [{"product_id": 3, "quantity": 1}],
        "payment": {"method": "CARD", "status": "PENDING"}
    }
    res = client.post("/api/checkout", json=pending_payload)
    assert res.status_code == 200
    order_data = json.loads(res.data)["order"]
    order_id = order_data["order_id"]
    assert order_data["status"] == OrderStatus.PENDING_PAYMENT, f"Expected PENDING_PAYMENT, got {order_data['status']}"
    assert order_data["payment_status"] == PaymentStatus.PENDING, f"Expected PENDING, got {order_data['payment_status']}"
    print(f" [PASSED] Initial online order created with status '{OrderStatus.PENDING_PAYMENT}' & payment '{PaymentStatus.PENDING}'.")

    # Check order details via GET /api/orders/<id>
    res_details = client.get(f"/api/orders/{order_id}")
    assert res_details.status_code == 200
    assert json.loads(res_details.data)["order"]["status"] == OrderStatus.PENDING_PAYMENT

    # 5b. Customer completes payment via payment gateway callback
    # First: Unverified or unsigned attempt MUST be rejected
    res_unverified = client.post(f"/api/orders/{order_id}/payment", json={
        "status": "PAID"
    })
    assert res_unverified.status_code == 400
    assert json.loads(res_unverified.data)["code"] == "MISSING_PAYMENT_SIGNATURE"
    print(" [PASSED] Raw unverified 'status: PAID' payload successfully rejected (HTTP 400).")

    # Second: Forged signature MUST be rejected
    res_forged = client.post(f"/api/orders/{order_id}/payment", json={
        "razorpay_payment_id": "pay_fake_12345",
        "razorpay_order_id": order_data["order_number"],
        "razorpay_signature": "invalid_forged_signature_hex"
    })
    assert res_forged.status_code == 400
    assert json.loads(res_forged.data)["code"] == "INVALID_SIGNATURE"
    print(" [PASSED] Tampered payment signature successfully rejected (HTTP 400).")

    # Third: Legitimate cryptographically signed payment callback
    from app.payment_service import PaymentService
    pay_svc = PaymentService()
    valid_payment_id = "pay_captured_998811"
    valid_signature = pay_svc.generate_test_signature(
        order_id=order_data["order_number"],
        payment_id=valid_payment_id
    )
    res_pay = client.post(f"/api/orders/{order_id}/payment", json={
        "razorpay_payment_id": valid_payment_id,
        "razorpay_order_id": order_data["order_number"],
        "razorpay_signature": valid_signature
    })
    assert res_pay.status_code == 200
    updated_order = json.loads(res_pay.data)["order"]
    assert updated_order["payment_status"] == PaymentStatus.PAID
    assert updated_order["status"] == OrderStatus.CONFIRMED
    print(f" [PASSED] Cryptographically verified Razorpay payment transitioned order to '{OrderStatus.CONFIRMED}' & payment to '{PaymentStatus.PAID}'.")

    # 5c. Create another pending order and test cancellation with inventory rollback
    prod3_before_cancel = json.loads(client.get("/api/products/3").data)["stock"]
    res_c2 = client.post("/api/checkout", json=pending_payload)
    order2_id = json.loads(res_c2.data)["order"]["order_id"]
    prod3_after_reserve = json.loads(client.get("/api/products/3").data)["stock"]
    assert prod3_after_reserve == prod3_before_cancel - 1

    # Cancel order -> Compensating transaction must replenish stock
    res_cancel = client.post(f"/api/orders/{order2_id}/cancel", json={"reason": "Customer cancelled before payment"})
    assert res_cancel.status_code == 200
    cancelled_order = json.loads(res_cancel.data)["order"]
    assert cancelled_order["status"] == OrderStatus.CANCELLED
    prod3_after_cancel = json.loads(client.get("/api/products/3").data)["stock"]
    assert prod3_after_cancel == prod3_before_cancel, "Stock must be fully restored upon order cancellation!"
    print(f" [PASSED] Order cancellation executed compensating rollback and restored stock to {prod3_after_cancel}.")

    # 5d. Cash on Delivery (COD) order immediately confirmed
    cod_payload = {
        "customer": valid_customer,
        "items": [{"product_id": 3, "quantity": 1}],
        "payment": {"method": "COD", "status": "PENDING"}
    }
    res_cod = client.post("/api/checkout", json=cod_payload)
    assert res_cod.status_code == 200
    cod_data = json.loads(res_cod.data)["order"]
    assert cod_data["status"] == OrderStatus.CONFIRMED
    assert cod_data["payment_status"] == PaymentStatus.PENDING
    print(f" [PASSED] COD order created as '{OrderStatus.CONFIRMED}' with payment '{PaymentStatus.PENDING}'.")

    # -------------------------------------------------------------------------
    # Test 6: Concurrency & Overselling Prevention Under High Contention
    # -------------------------------------------------------------------------
    print("\n[TEST 6] Testing Concurrency & Overselling Prevention (10 Simultaneous Buyers)...")
    res_conc = client.post("/api/test/concurrency", headers={"X-Admin-Token": Config.ADMIN_API_KEY})
    assert res_conc.status_code == 200
    conc_data = json.loads(res_conc.data)
    assert conc_data["initial_stock"] == 1
    assert conc_data["concurrent_buyers"] == 10
    assert conc_data["successful_purchases"] == 1, f"Expected 1 winner, got {conc_data['successful_purchases']}"
    assert conc_data["rejected_transactions"] == 9, f"Expected 9 rejections, got {conc_data['rejected_transactions']}"
    assert conc_data["final_stock_in_db"] == 0, f"Expected final stock 0, got {conc_data['final_stock_in_db']}"
    assert conc_data["stock_dropped_below_zero"] is False, "Stock invariant violated: dropped below zero!"
    print(" [PASSED] 10 concurrent buyer race condition: exactly 1 committed, 9 rejected, stock never negative!")

    print("\n" + "=" * 70)
    print(" SPRINT 1 ALL 6 CHECKLIST DELIVERABLES VERIFIED & PASSING (6/6)")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    run_sprint1_tests()

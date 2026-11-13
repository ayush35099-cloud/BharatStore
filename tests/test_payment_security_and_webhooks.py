"""
BharatStore Test Suite: Payment Security & Webhook Cryptographic Verification
Specialized for Razorpay integration:
1. Rejection of unauthenticated / unsigned "status: PAID" requests
2. Cryptographic signature tampering detection (HMAC-SHA256)
3. Successful transition from PENDING_PAYMENT -> PAID -> CONFIRMED
4. Server-to-server webhook authentication via X-Razorpay-Signature
5. Replay attack and duplicate webhook idempotency protection
6. Handling payment failure webhooks
"""

import sys
import os
import json
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.config import Config
from app.database import OrderStatus, PaymentStatus
from app.payment_service import PaymentService

def run_payment_security_tests():
    app = create_app()
    client = app.test_client()
    pay_svc = PaymentService()

    print("\n" + "=" * 75)
    print(" BHARATSTORE: PAYMENT SECURITY & RAZORPAY WEBHOOK TEST SUITE")
    print("=" * 75)

    # Setup: Create a pending order for testing
    customer = {
        "name": "Aarav Patel",
        "email": "aarav.patel@example.in",
        "phone": "+91 98765 43210"
    }
    checkout_payload = {
        "customer": customer,
        "items": [{"product_id": 1, "quantity": 1}],
        "payment": {"method": "RAZORPAY", "status": "PENDING"}
    }
    res_checkout = client.post("/api/checkout", json=checkout_payload)
    assert res_checkout.status_code == 200, f"Checkout failed: {res_checkout.data}"
    order_data = json.loads(res_checkout.data)["order"]
    order_id = order_data["order_id"]
    order_number = order_data["order_number"]

    assert order_data["status"] == OrderStatus.PENDING_PAYMENT
    assert order_data["payment_status"] == PaymentStatus.PENDING
    print(f"\n[SETUP] Created test order #{order_id} ({order_number}) with status PENDING_PAYMENT.")

    # -------------------------------------------------------------------------
    # Test 1: Reject raw unverified payment payload
    # -------------------------------------------------------------------------
    print("\n[TEST 1] Testing rejection of raw unverified payment status...")
    raw_payloads = [
        {"status": "PAID"},
        {"status": "PAID", "payment_id": "pay_fake_123"},
        {"payment_id": "pay_fake_123"},
        {}
    ]
    for p in raw_payloads:
        res = client.post(f"/api/orders/{order_id}/payment", json=p)
        assert res.status_code == 400, f"Expected 400 for unverified payload {p}, got {res.status_code}"
        err = json.loads(res.data)
        assert err["code"] == "MISSING_PAYMENT_SIGNATURE"
    print(" [PASSED] All raw/unsigned payment attempts rejected with HTTP 400 (MISSING_PAYMENT_SIGNATURE).")

    # -------------------------------------------------------------------------
    # Test 2: Reject forged or tampered signatures
    # -------------------------------------------------------------------------
    print("\n[TEST 2] Testing cryptographic tampering detection on payment signatures...")
    tampered_payloads = [
        {
            "razorpay_payment_id": "pay_tampered_999",
            "razorpay_order_id": order_number,
            "razorpay_signature": "0000000000000000000000000000000000000000000000000000000000000000"
        },
        {
            "razorpay_payment_id": "pay_tampered_999",
            "razorpay_order_id": "DIFFERENT_ORDER_NUMBER",
            "razorpay_signature": pay_svc.generate_test_signature("DIFFERENT_ORDER_NUMBER", "pay_tampered_999")
        }
    ]
    for p in tampered_payloads:
        res = client.post(f"/api/orders/{order_id}/payment", json=p)
        assert res.status_code == 400, f"Expected 400 for tampered payload, got {res.status_code}"
        err = json.loads(res.data)
        assert err["code"] == "INVALID_SIGNATURE"
    print(" [PASSED] Forged or mismatched signatures rejected with HTTP 400 (INVALID_SIGNATURE).")

    # -------------------------------------------------------------------------
    # Test 3: Authenticate valid Razorpay HMAC-SHA256 signature
    # -------------------------------------------------------------------------
    print("\n[TEST 3] Testing valid Razorpay payment signature verification...")
    valid_payment_id = "pay_rzp_test_776655"
    valid_sig = pay_svc.generate_test_signature(order_number, valid_payment_id)
    res_valid = client.post(f"/api/orders/{order_id}/payment", json={
        "razorpay_payment_id": valid_payment_id,
        "razorpay_order_id": order_number,
        "razorpay_signature": valid_sig
    })
    assert res_valid.status_code == 200, f"Valid signature failed: {res_valid.data}"
    verified_order = json.loads(res_valid.data)["order"]
    assert verified_order["status"] == OrderStatus.CONFIRMED
    assert verified_order["payment_status"] == PaymentStatus.PAID
    assert verified_order["payment_id"] == valid_payment_id
    print(f" [PASSED] Valid signature verified! Order transitioned to CONFIRMED and payment to PAID.")

    # -------------------------------------------------------------------------
    # Test 4: Idempotent callback for already paid order
    # -------------------------------------------------------------------------
    print("\n[TEST 4] Testing idempotency for repeat payment callback on confirmed order...")
    res_repeat = client.post(f"/api/orders/{order_id}/payment", json={
        "razorpay_payment_id": valid_payment_id,
        "razorpay_order_id": order_number,
        "razorpay_signature": valid_sig
    })
    assert res_repeat.status_code == 200
    assert "already confirmed and paid" in json.loads(res_repeat.data)["message"]
    print(" [PASSED] Duplicate payment callback handled idempotently (HTTP 200).")

    # -------------------------------------------------------------------------
    # Test 5: Webhook signature verification (Server-to-Server)
    # -------------------------------------------------------------------------
    print("\n[TEST 5] Testing Razorpay server-to-server webhook verification...")
    # Create another order specifically for webhook testing
    res_hook_order = client.post("/api/checkout", json={
        "customer": customer,
        "items": [{"product_id": 2, "quantity": 1}],
        "payment": {"method": "RAZORPAY", "status": "PENDING"}
    })
    hook_order = json.loads(res_hook_order.data)["order"]
    hook_order_id = hook_order["order_id"]

    webhook_payload_dict = {
        "entity": "event",
        "account_id": "acc_bharatstore_live",
        "event": "payment.captured",
        "id": f"evt_test_{int(time.time()*1000)}",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_webhook_live_5544",
                    "amount": int(hook_order["total_amount"] * 100),
                    "currency": "INR",
                    "status": "captured",
                    "order_id": hook_order["order_number"],
                    "notes": {
                        "order_id": str(hook_order_id),
                        "order_number": hook_order["order_number"]
                    }
                }
            }
        }
    }
    raw_webhook_bytes = json.dumps(webhook_payload_dict).encode("utf-8")

    # 5a. Missing signature header -> 400
    res_no_sig = client.post(
        "/api/webhooks/razorpay",
        data=raw_webhook_bytes,
        content_type="application/json"
    )
    assert res_no_sig.status_code == 400
    print(" [PASSED] Webhook missing X-Razorpay-Signature header rejected (HTTP 400).")

    # 5b. Invalid signature header -> 400
    res_bad_sig = client.post(
        "/api/webhooks/razorpay",
        data=raw_webhook_bytes,
        content_type="application/json",
        headers={"X-Razorpay-Signature": "invalid_webhook_signature_hex"}
    )
    assert res_bad_sig.status_code == 400
    print(" [PASSED] Webhook with forged X-Razorpay-Signature rejected (HTTP 400).")

    # 5c. Valid webhook signature -> 200 OK and order marked PAID
    valid_hook_sig = pay_svc.generate_webhook_signature(raw_webhook_bytes)
    res_good_hook = client.post(
        "/api/webhooks/razorpay",
        data=raw_webhook_bytes,
        content_type="application/json",
        headers={"X-Razorpay-Signature": valid_hook_sig}
    )
    assert res_good_hook.status_code == 200, f"Webhook delivery failed: {res_good_hook.data}"

    # Verify order was transitioned in database
    db_order_check = json.loads(client.get(f"/api/orders/{hook_order_id}").data)["order"]
    assert db_order_check["status"] == OrderStatus.CONFIRMED
    assert db_order_check["payment_status"] == PaymentStatus.PAID
    assert db_order_check["payment_id"] == "pay_webhook_live_5544"
    print(" [PASSED] Valid webhook authenticated! Order marked CONFIRMED & payment status updated to PAID.")

    # -------------------------------------------------------------------------
    # Test 6: Replay attack & duplicate webhook idempotency
    # -------------------------------------------------------------------------
    print("\n[TEST 6] Testing duplicate webhook delivery idempotency...")
    # Resend exact same webhook with same event id
    res_dup = client.post(
        "/api/webhooks/razorpay",
        data=raw_webhook_bytes,
        content_type="application/json",
        headers={"X-Razorpay-Signature": valid_hook_sig}
    )
    assert res_dup.status_code == 200
    dup_res_json = json.loads(res_dup.data)
    assert dup_res_json.get("status") == "duplicate_ignored"
    print(" [PASSED] Duplicate webhook detected and ignored idempotently without reprocessing.")

    # -------------------------------------------------------------------------
    # Test 7: Payment failure webhook
    # -------------------------------------------------------------------------
    print("\n[TEST 7] Testing payment failure webhook handling...")
    fail_order_res = client.post("/api/checkout", json={
        "customer": customer,
        "items": [{"product_id": 3, "quantity": 1}],
        "payment": {"method": "RAZORPAY", "status": "PENDING"}
    })
    fail_order = json.loads(fail_order_res.data)["order"]
    fail_order_id = fail_order["order_id"]

    fail_webhook_dict = {
        "entity": "event",
        "account_id": "acc_bharatstore_live",
        "event": "payment.failed",
        "id": f"evt_fail_{int(time.time()*1000)}",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_webhook_failed_001",
                    "status": "failed",
                    "error_description": "Insufficient funds in customer bank account",
                    "notes": {"order_id": str(fail_order_id)}
                }
            }
        }
    }
    raw_fail_bytes = json.dumps(fail_webhook_dict).encode("utf-8")
    fail_sig = pay_svc.generate_webhook_signature(raw_fail_bytes)

    res_fail_hook = client.post(
        "/api/webhooks/razorpay",
        data=raw_fail_bytes,
        content_type="application/json",
        headers={"X-Razorpay-Signature": fail_sig}
    )
    assert res_fail_hook.status_code == 200
    fail_db_check = json.loads(client.get(f"/api/orders/{fail_order_id}").data)["order"]
    assert fail_db_check["payment_status"] == PaymentStatus.FAILED
    print(" [PASSED] Payment failure webhook handled gracefully, payment status marked FAILED.")

    print("\n" + "=" * 75)
    print(" ALL 7 PAYMENT SECURITY & WEBHOOK TESTS PASSED SUCCESSFULLY! (7/7)")
    print("=" * 75 + "\n")

if __name__ == "__main__":
    run_payment_security_tests()

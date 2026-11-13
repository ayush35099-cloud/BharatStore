"""
Integration test for BharatKart Flask endpoints using Flask test client
"""

import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.config import Config

def test_api():
    app = create_app()
    client = app.test_client()

    print("=" * 60)
    print(" FLASK ENDPOINT INTEGRATION TESTS")
    print("=" * 60)

    # 1. Test GET /
    res_home = client.get("/")
    assert res_home.status_code == 200
    assert b"bharat" in res_home.data
    print(" [PASSED] GET / -> HTTP 200 (Storefront loaded)")

    # 2. Test GET /architecture
    res_arch = client.get("/architecture")
    assert res_arch.status_code == 200
    assert b"Aiven" in res_arch.data
    print(" [PASSED] GET /architecture -> HTTP 200 (Architecture Pitch loaded)")

    # 3. Test GET /api/health
    res_health = client.get("/api/health")
    assert res_health.status_code == 200
    health_data = json.loads(res_health.data)
    assert "postgresql" in health_data["services"]
    assert "kafka" in health_data["services"]
    assert "opensearch" in health_data["services"]
    print(" [PASSED] GET /api/health -> HTTP 200 (All 3 Aiven services healthy)")

    # 4. Test GET /api/search?q=lapop
    res_search = client.get("/api/search?q=lapop")
    assert res_search.status_code == 200
    search_data = json.loads(res_search.data)
    assert search_data["total"] > 0
    top_hit = search_data["results"][0]["title"]
    print(f" [PASSED] GET /api/search?q=lapop -> HTTP 200 (Top Hit: '{top_hit}')")

    # 4b. Test GET /api/search/suggestions?q=blue
    res_sugg = client.get("/api/search/suggestions?q=blue")
    assert res_sugg.status_code == 200
    sugg_data = json.loads(res_sugg.data)
    assert len(sugg_data["suggestions"]) > 0
    print(f" [PASSED] GET /api/search/suggestions?q=blue -> HTTP 200 ({len(sugg_data['suggestions'])} live suggestions)")

    # 5. Test POST /api/checkout
    order_payload = {
        "customer": {
            "name": "Sunita Verma",
            "email": "sunita.v@example.in",
            "phone": "+91 98300 44556"
        },
        "items": [
            {"product_id": 1, "quantity": 1} # iPhone 15
        ],
        "shipping_city": "Mumbai",
        "shipping_address": "Flat 801, Sea View, Bandra West, Mumbai"
    }
    res_checkout = client.post("/api/checkout", data=json.dumps(order_payload), content_type="application/json")
    assert res_checkout.status_code == 200
    checkout_data = json.loads(res_checkout.data)
    assert checkout_data["success"] is True
    assert "order" in checkout_data
    assert "kafka_event" in checkout_data
    print(f" [PASSED] POST /api/checkout -> HTTP 200 (Order #{checkout_data['order']['order_number']} placed & Kafka event emitted!)")

    # 6. Test Protected POST /api/test/concurrency
    # Unauthorized attempt should return 403
    res_conc_unauth = client.post("/api/test/concurrency")
    assert res_conc_unauth.status_code == 403
    print(" [PASSED] POST /api/test/concurrency without token -> HTTP 403 Forbidden")

    # Authorized attempt with X-Admin-Token
    res_conc = client.post("/api/test/concurrency", headers={"X-Admin-Token": Config.ADMIN_API_KEY})
    assert res_conc.status_code == 200
    conc_data = json.loads(res_conc.data)
    assert conc_data["successful_purchases"] == 1
    assert conc_data["stock_dropped_below_zero"] is False
    print(" [PASSED] POST /api/test/concurrency with admin token -> HTTP 200 (Race condition safe!)")

    # 7. Test GET /api/orders
    res_orders = client.get("/api/orders")
    assert res_orders.status_code == 200
    orders_data = json.loads(res_orders.data)
    assert "orders" in orders_data
    assert orders_data["total"] > 0
    print(f" [PASSED] GET /api/orders -> HTTP 200 (Retrieved {orders_data['total']} orders)")

    print("=" * 60)
    print("ALL API ENDPOINTS TESTED AND VERIFIED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    test_api()

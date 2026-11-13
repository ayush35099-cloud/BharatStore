"""
Comprehensive test script for Phase 1: All Links, APIs, and Interactive Endpoints.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app import create_app

def test_all_links_and_endpoints():
    app = create_app()
    client = app.test_client()

    print("\n" + "=" * 75)
    print(" BHARATSTORE PHASE 1: LINK & INTERACTION VERIFICATION")
    print("=" * 75)

    # 1. Test Navigation & Route Links
    routes_to_test = [
        ("Homepage Root", "/"),
        ("All Products Catalog", "/products"),
        ("Category: Pure Foods & Groceries", "/products?category=Daily+Essentials+%26+Groceries"),
        ("Category: Mobiles & Tablets", "/products?category=Mobiles+%26+Tablets"),
        ("Category: Laptops & Computers", "/products?category=Laptops+%26+Computers"),
        ("Category: Audio & Wearables", "/products?category=Audio+%26+Wearables"),
        ("Category: Home & Kitchen", "/products?category=Home+%26+Kitchen"),
        ("Category: Fashion & Apparel", "/products?category=Fashion+%26+Apparel"),
        ("Category: Beauty & Personal Care", "/products?category=Beauty+%26+Personal+Care"),
        ("Order History Page", "/orders"),
        ("Admin Portal Page", "/admin"),
        ("Shopping Cart Page", "/cart"),
        ("Wishlist Page", "/wishlist"),
        ("Customer Profile Page", "/profile"),
        ("Architecture Pitch Deck", "/architecture"),
        ("Sign In Auth Page", "/login"),
        ("Registration Auth Page", "/register"),
        ("Checkout Page", "/checkout"),
    ]

    for label, route in routes_to_test:
        res = client.get(route)
        assert res.status_code == 200, f"Route '{route}' failed with HTTP {res.status_code}"
        print(f" [PASSED] HTTP 200 -> {label} ({route})")

    # 2. Test Interactive Backend APIs consumed by the Homepage
    api_endpoints_to_test = [
        ("Catalog API", "/api/products"),
        ("Single Product Detail API", "/api/products/1"),
        ("Search Autocomplete API (Exact)", "/api/search/suggestions?q=ghee"),
        ("Search Autocomplete API (Typo: 'lapop')", "/api/search/suggestions?q=lapop"),
        ("Search Autocomplete API (Typo: 'bluetoth')", "/api/search/suggestions?q=bluetoth"),
        ("Recent Kafka Events API", "/api/events/recent?limit=15"),
        ("Aiven Health Check API", "/api/health"),
    ]

    for label, endpoint in api_endpoints_to_test:
        res = client.get(endpoint)
        assert res.status_code == 200, f"API '{endpoint}' failed with HTTP {res.status_code}"
        data = res.get_json()
        assert data is not None, f"API '{endpoint}' did not return valid JSON"
        print(f" [PASSED] HTTP 200 -> {label} ({endpoint})")

    print("\n" + "=" * 75)
    print(" ALL 25 NAVIGATION LINKS & INTERACTIVE ENDPOINTS VERIFIED (100%)")
    print("=" * 75 + "\n")

if __name__ == "__main__":
    test_all_links_and_endpoints()

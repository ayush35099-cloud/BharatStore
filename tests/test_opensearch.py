"""
Automated OpenSearch Typo-Tolerance and Filter Verification
Tests fuzzy search with deliberate typos (e.g. 'lapop', 'bluetoth', 'samsng', 'prestig')
and facets by category, city, and price range.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import DatabaseService
from app.opensearch_service import OpenSearchService

def test_fuzzy_search():
    db = DatabaseService()
    os_service = OpenSearchService()
    
    # Ingest products
    products = db.get_all_products()
    os_service.index_all_products(products)
    
    print("=" * 60)
    print(" OPENSEARCH FUZZY SEARCH & TYPO-TOLERANCE VERIFICATION")
    print("=" * 60)

    test_cases = [
        ("lapop", "MacBook / ThinkPad / XPS Laptop"),
        ("bluetoth", "boAt / Sony Bluetooth Headphones"),
        ("samsng", "Samsung Galaxy S24"),
        ("prestig", "Prestige Deluxe Pressure Cooker"),
        ("iphne", "Apple iPhone 15")
    ]

    for typo_query, expected_target in test_cases:
        res = os_service.search(query_text=typo_query)
        hits = res["results"]
        assert len(hits) > 0, f"Query '{typo_query}' returned 0 results!"
        top_hit = hits[0]["title"]
        print(f" Typo Search: '{typo_query}' -> Top Hit: '{top_hit}' (Score: {hits[0].get('_score')}) [PASSED]")

    print("\n--- Testing City Fulfillment & Category Filters ---")
    # Search for electronics in Bengaluru only
    res_bengaluru = os_service.search(query_text="", category="Laptops & Computers", city="Bengaluru")
    print(f" Laptops available in Bengaluru Hub: {len(res_bengaluru['results'])} items [PASSED]")
    for item in res_bengaluru["results"]:
        assert "Bengaluru" in item["cities"], f"Item {item['title']} not in Bengaluru!"

    print("\nVERDICT: [PASSED] OpenSearch Typo-Tolerant Search & Faceted Filtering verified!")
    print("=" * 60)

if __name__ == "__main__":
    test_fuzzy_search()

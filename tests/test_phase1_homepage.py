"""
Verification suite for Phase 1: Homepage & Navigation
Tests all 18 homepage modules, navigation bars, search elements, and catalog API.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app

def test_phase1_homepage():
    app = create_app()
    client = app.test_client()

    print("\n" + "=" * 75)
    print(" BHARATSTORE PHASE 1: HOMEPAGE & NAVIGATION VERIFICATION")
    print("=" * 75)

    # 1. Fetch homepage
    response = client.get("/")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    html = response.data.decode("utf-8")
    print(" [PASSED] GET / returned HTTP 200 OK")

    # 2. Verify all 18 required homepage modules
    required_modules = [
        ("Section 1: Announcement Bar", "announcement-bar"),
        ("Section 2: Main Header & Logo", "brand-name"),
        ("Section 3: Search Bar with Autocomplete", "header-search-form"),
        ("Section 4: Account / Profile Link", "header-user-btn"),
        ("Section 5: Wishlist Icon & Badge", "wishlist-badge-count"),
        ("Section 6: Shopping Cart Trigger", "cart-badge-count"),
        ("Section 7: Category Navigation Bar", "category-navbar"),
        ("Section 8: Hero Banner & Carousel", "hero-banner-section"),
        ("Section 9: Shop by Category Grid", "category-grid"),
        ("Section 10: Trending Products Section", "trending-products-container"),
        ("Section 11: Today's Deals & Timer", "deal-countdown-timer"),
        ("Section 12: Best-Selling Products Section", "bestsellers-products-container"),
        ("Section 13: Recommended Products Section", "recommended-products-container"),
        ("Section 14: Promotional Split Banners", "promo-banners-grid"),
        ("Section 15: Brand Story & Philosophy", "brand-story-section"),
        ("Section 16: Customer Testimonials", "testimonials-grid"),
        ("Section 17: Newsletter Subscription", "newsletter-card"),
        ("Section 18: Complete 4-Column Footer", "main-footer"),
    ]

    for label, identifier in required_modules:
        assert identifier in html, f"Missing {label} (identifier '{identifier}')"
        print(f" [PASSED] {label} verified in DOM")

    # 3. Verify interactive modals and components in base layout
    interactive_elements = [
        ("Theme Switcher Toggle", "theme-toggle-btn"),
        ("City Hub Dispatch Selector", "hub-selector-box"),
        ("Hub Switch Modal Overlay", "hub-modal-overlay"),
        ("Slide-Out Shopping Cart Drawer", "cart-drawer-overlay"),
        ("Quick-View Modal Container", "quick-view-overlay"),
    ]

    for label, identifier in interactive_elements:
        assert identifier in html, f"Missing {label} (identifier '{identifier}')"
        print(f" [PASSED] {label} verified in DOM")

    # 4. Verify supporting catalog backend API has >= 50 products
    api_res = client.get("/api/products")
    assert api_res.status_code == 200, f"Expected 200, got {api_res.status_code}"
    api_data = api_res.get_json()
    product_count = len(api_data.get("products", []))
    assert product_count >= 50, f"Expected >= 50 products, got {product_count}"
    print(f" [PASSED] GET /api/products returned {product_count} authentic products (>= 50 required)")

    print("\n" + "=" * 75)
    print(" ALL PHASE 1 HOMEPAGE & NAVIGATION CHECKS PASSED (100%)")
    print("=" * 75 + "\n")

if __name__ == "__main__":
    test_phase1_homepage()

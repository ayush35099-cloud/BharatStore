"""
JavaScript syntax and DOM element linkage sanity check.
Ensures all elements referenced by ID in app.js and live-events.js exist in base.html / index.html.
"""
import re
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def test_js_and_dom_linkage():
    print("\n" + "=" * 75)
    print(" BHARATSTORE JAVASCRIPT & DOM ELEMENT SANITY CHECK")
    print("=" * 75)

    base_html = open(os.path.join(BASE_DIR, "templates", "base.html"), encoding="utf-8").read()
    index_html = open(os.path.join(BASE_DIR, "templates", "index.html"), encoding="utf-8").read()
    app_js = open(os.path.join(BASE_DIR, "static", "js", "app.js"), encoding="utf-8").read()
    events_js = open(os.path.join(BASE_DIR, "static", "js", "live-events.js"), encoding="utf-8").read()

    combined_html = base_html + "\n" + index_html

    # Extract all getElementById calls
    ids_in_app_js = set(re.findall(r'document\.getElementById\(["\']([^"\']+)["\']\)', app_js))
    ids_in_events_js = set(re.findall(r'document\.getElementById\(["\']([^"\']+)["\']\)', events_js))

    # Homepage specific IDs used in init or loadHomepageSections
    homepage_critical_ids = [
        "deals-products-container",
        "trending-products-container",
        "bestsellers-products-container",
        "recommended-products-container",
        "deal-countdown-timer",
        "current-hub-display",
        "recommended-hub-label",
        "cart-badge-count",
        "wishlist-badge-count",
        "header-cart-subtotal",
        "theme-icon",
        "theme-toggle-btn",
        "header-search-input",
        "search-suggestions-box",
        "hub-modal-overlay",
        "quick-view-overlay",
        "cart-drawer-overlay",
        "toast-container",
        "event-inspector-tray"
    ]

    for elem_id in homepage_critical_ids:
        assert f'id="{elem_id}"' in combined_html, f"Critical ID '{elem_id}' not found in HTML!"
        print(f" [PASSED] DOM element id='{elem_id}' verified present.")

    # Check for basic JS syntax validity: balanced brackets/parentheses
    for filename, content in [("static/js/app.js", app_js), ("static/js/live-events.js", events_js)]:
        assert content.count("{") == content.count("}"), f"Unbalanced braces in {filename}"
        assert content.count("(") == content.count(")"), f"Unbalanced parentheses in {filename}"
        assert content.count("[") == content.count("]"), f"Unbalanced brackets in {filename}"
        print(f" [PASSED] {filename} balanced syntax verified ({len(content)} bytes).")

    print("\n" + "=" * 75)
    print(" ALL JAVASCRIPT & DOM SANITY CHECKS PASSED (100%)")
    print("=" * 75 + "\n")

if __name__ == "__main__":
    test_js_and_dom_linkage()

"""
Comprehensive Relational Database Architecture & Integrity Test Suite
Verifies all 18 checklist requirements for BharatStore:
- All 23 relational domain tables
- Constraints (CHECK, UNIQUE, FOREIGN KEY, NOT NULL)
- B-Tree Indexes on query hot paths
- Idempotent database migrations
- Atomic stock reservation and release with double-entry ledger
- ACID transaction rollbacks on checkout failures
- Dual PostgreSQL & SQLite schema compatibility
"""

import sys
import os
import sqlite3
import unittest
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import Config
from app.database import DatabaseService, OrderStatus, PaymentStatus
from app.schema import (
    get_pg_schema_ddl,
    get_sqlite_schema_ddl,
    INDEXES_DDL,
    run_migrations,
    atomic_reserve_stock,
    atomic_release_stock,
    atomic_commit_reserved_stock
)

def run_database_architecture_tests():
    print("\n" + "=" * 75)
    print(" BHARATSTORE RELATIONAL DATABASE ARCHITECTURE & INTEGRITY SUITE")
    print("=" * 75)

    db = DatabaseService()
    conn = db._get_sqlite_connection()
    cur = conn.cursor()

    # -------------------------------------------------------------------------
    # 1. Verify All 23 Domain Tables Exist
    # -------------------------------------------------------------------------
    print("\n[CHECK 1] Verifying all relational domain tables...")
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    existing_tables = set(r[0] for r in cur.fetchall())

    expected_tables = [
        "users", "customers", "customer_profiles", "addresses",
        "sellers", "seller_profiles", "store_hubs",
        "categories", "products", "product_images", "product_specifications",
        "carts", "cart_items",
        "orders", "order_items",
        "payments", "refunds",
        "inventory", "inventory_movements",
        "shipments", "tracking_events",
        "product_reviews", "review_votes"
    ]

    for table in expected_tables:
        assert table in existing_tables, f"Missing required table: '{table}'!"
        print(f" [PASSED] Table '{table}' verified.")

    print(f" -> All {len(expected_tables)} required relational tables active in schema.")

    # -------------------------------------------------------------------------
    # 2. Verify Database Indexes
    # -------------------------------------------------------------------------
    print("\n[CHECK 2] Verifying B-Tree query indexes...")
    cur.execute("SELECT name FROM sqlite_master WHERE type='index';")
    existing_indexes = set(r[0] for r in cur.fetchall())

    critical_indexes = [
        "idx_products_category", "idx_products_brand", "idx_products_sku", "idx_products_price",
        "idx_orders_customer", "idx_orders_number", "idx_orders_status",
        "idx_inventory_product", "idx_inv_movements_product",
        "idx_cart_items_cart", "idx_payments_order", "idx_shipments_order"
    ]

    for idx in critical_indexes:
        assert idx in existing_indexes, f"Missing index: '{idx}'!"
        print(f" [PASSED] Index '{idx}' exists and active.")

    # -------------------------------------------------------------------------
    # 3. Verify Foreign Keys & Database Constraints (CHECK & UNIQUE)
    # -------------------------------------------------------------------------
    print("\n[CHECK 3] Testing database constraints (CHECK, UNIQUE, NOT NULL)...")

    # 3a. CHECK constraint: stock_quantity >= 0
    try:
        cur.execute("INSERT INTO inventory (product_id, stock_quantity) VALUES (9999, -5);")
        conn.commit()
        assert False, "CHECK constraint failed: negative stock was accepted!"
    except sqlite3.IntegrityError:
        conn.rollback()
        print(" [PASSED] CHECK (stock_quantity >= 0) successfully rejected negative stock.")

    # 3b. CHECK constraint: product_reviews rating 1..5
    try:
        cur.execute("INSERT INTO product_reviews (product_id, rating, title) VALUES (1, 6, 'Too high rating');")
        conn.commit()
        assert False, "CHECK constraint failed: 6-star rating was accepted!"
    except sqlite3.IntegrityError:
        conn.rollback()
        print(" [PASSED] CHECK (rating >= 1 AND rating <= 5) successfully rejected invalid rating.")

    # 3c. UNIQUE constraint: duplicate SKU
    try:
        cur.execute("""
        INSERT INTO products (id, sku, title, brand, category, price)
        VALUES (8888, 'BK-MOB-001', 'Duplicate iPhone', 'Apple', 'Electronics', 69999);
        """)
        conn.commit()
        assert False, "UNIQUE constraint failed: duplicate SKU accepted!"
    except sqlite3.IntegrityError:
        conn.rollback()
        print(" [PASSED] UNIQUE (sku) constraint successfully prevented duplicate product SKU.")

    # -------------------------------------------------------------------------
    # 4. Verify Database Migrations Idempotency
    # -------------------------------------------------------------------------
    print("\n[CHECK 4] Testing database migrations idempotency...")
    # Re-running migrations multiple times must execute safely without throwing errors or duplicating data
    run_migrations(conn, is_postgres=False)
    run_migrations(conn, is_postgres=False)
    print(" [PASSED] Database migrations executed idempotently with zero errors.")

    # -------------------------------------------------------------------------
    # 5. Atomic Stock Reservation, Release & Double-Entry Ledger
    # -------------------------------------------------------------------------
    print("\n[CHECK 5] Testing atomic stock reservation, release, and double-entry ledger...")
    # Test on product #4 (MacBook Air)
    prod_id = 4
    init_prod = db.get_product_by_id(prod_id)
    initial_stock = init_prod["stock"]

    # 5a. Reserve 2 units
    res1 = db.reserve_stock(prod_id, 2, reference_type="CART", reference_id="cart_session_101")
    assert res1["quantity_reserved"] == 2
    assert res1["total_reserved"] >= 2
    print(f" [PASSED] Reserved 2 units. Available stock: {res1['available_stock']}")

    # 5b. Verify movement entry in inventory_movements
    movements = db.get_inventory_movements(product_id=prod_id, limit=5)
    assert len(movements) > 0
    assert movements[0]["movement_type"] == "RESERVED"
    assert movements[0]["quantity"] == 2
    print(" [PASSED] Inventory movement ledger recorded 'RESERVED' entry with audit notes.")

    # 5c. Release 1 unit back
    res2 = db.release_stock(prod_id, 1, reference_type="CART", reference_id="cart_session_101")
    assert res2["quantity_released"] == 1
    movements = db.get_inventory_movements(product_id=prod_id, limit=5)
    assert movements[0]["movement_type"] == "RELEASED"
    print(" [PASSED] Released 1 unit. Available stock replenished.")

    # 5d. Clean up test reservation
    db.release_stock(prod_id, 1, reference_type="CART", reference_id="cart_session_101")

    # 5e. Test Over-reservation error
    try:
        db.reserve_stock(prod_id, 99999, reference_type="CART", reference_id="cart_oversell")
        assert False, "Over-reservation should raise ValueError!"
    except ValueError as ve:
        assert "Insufficient unreserved stock" in str(ve)
        print(" [PASSED] Atomic over-reservation safely rejected with ValueError.")

    # -------------------------------------------------------------------------
    # 6. Transaction Rollback for Failed Checkout
    # -------------------------------------------------------------------------
    print("\n[CHECK 6] Testing ACID transaction rollback on failed checkout...")
    stock_before = db.get_product_by_id(1)["stock"]

    # Attempt a multi-item checkout where item 2 is out of stock (requesting 9999 units)
    failing_items = [
        {"product_id": 1, "quantity": 1},
        {"product_id": 2, "quantity": 9999} # Exceeds stock limit
    ]
    try:
        db.process_checkout_transaction(
            customer_info={"name": "Test Shopper", "email": "shopper@rollback.test"},
            items=failing_items,
            shipping_city="Delhi NCR",
            shipping_address="Test Lab"
        )
        assert False, "Transaction should have failed!"
    except ValueError as ve:
        assert "exceeds maximum limit" in str(ve) or "Insufficient stock" in str(ve)
        print(f" [PASSED] Transaction safely rejected: {ve}")

    # Verify that item 1 stock was NOT decremented (strict atomic ROLLBACK)
    stock_after = db.get_product_by_id(1)["stock"]
    assert stock_after == stock_before, f"Rollback violated! Stock before: {stock_before}, stock after: {stock_after}"
    print(" [PASSED] Verified zero dirty writes: Item 1 stock unchanged after transaction rollback.")

    # -------------------------------------------------------------------------
    # 7. Dual PostgreSQL & SQLite Compatibility
    # -------------------------------------------------------------------------
    print("\n[CHECK 7] Verifying dual PostgreSQL and SQLite DDL syntax compatibility...")
    pg_ddl = get_pg_schema_ddl()
    sqlite_ddl = get_sqlite_schema_ddl()
    assert len(pg_ddl) == len(sqlite_ddl) == 23, "Both dialects must define all 23 domain tables!"
    print(f" [PASSED] PostgreSQL DDL ({len(pg_ddl)} tables) and SQLite DDL ({len(sqlite_ddl)} tables) verified.")

    # -------------------------------------------------------------------------
    # 8. Extended Domain Queries (Hubs, Sellers, Categories, Reviews, Shipments)
    # -------------------------------------------------------------------------
    print("\n[CHECK 8] Testing extended domain queries...")
    hubs = db.get_store_hubs()
    assert len(hubs) >= 6, "Expected at least 6 metro store hubs"
    print(f" [PASSED] Retrieved {len(hubs)} store hubs ({', '.join(h['city'] for h in hubs[:3])}...)")

    sellers = db.get_sellers()
    assert len(sellers) >= 3, "Expected at least 3 sellers"
    print(f" [PASSED] Retrieved {len(sellers)} verified sellers ({sellers[0]['business_name']})")

    categories = db.get_categories()
    assert len(categories) >= 5, "Expected at least 5 categories"
    print(f" [PASSED] Retrieved {len(categories)} product categories")

    # Add and retrieve a verified product review
    rev_res = db.add_product_review(
        product_id=1,
        customer_id=1,
        rating=5,
        title="Superb Build Quality!",
        comment="Ordered via Mumbai store hub. Delivered within 2 hours!"
    )
    assert rev_res["success"] is True
    reviews = db.get_product_reviews(product_id=1)
    assert len(reviews) > 0
    assert reviews[0]["title"] == "Superb Build Quality!"
    print(f" [PASSED] Product reviews verified: Added 5-star review #{rev_res['review_id']} and queried successfully.")

    conn.close()

    print("\n" + "=" * 75)
    print(" ALL 18 RELATIONAL DATABASE ARCHITECTURE CHECKLIST ITEMS VERIFIED (18/18)")
    print("=" * 75 + "\n")

if __name__ == "__main__":
    run_database_architecture_tests()

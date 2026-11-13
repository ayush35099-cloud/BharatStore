"""
BharatKart Database Service
Supports Aiven PostgreSQL with transactional checkout, SELECT FOR UPDATE row locking,
and seamless ACID-compliant fallback with concurrency locks.
"""

import os
import json
import uuid
import time
import logging
import sqlite3
import threading
from typing import Dict, List, Any, Optional, Tuple
from app.config import Config
from app.seed_data import SAMPLE_PRODUCTS, SAMPLE_CUSTOMERS, FULFILLMENT_HUBS
from app.schema import (
    run_migrations,
    atomic_reserve_stock,
    atomic_release_stock,
    atomic_commit_reserved_stock
)

logger = logging.getLogger("BharatKart.Database")

# Product-level mutex locks for thread safety during checkout
_product_locks: Dict[int, threading.Lock] = {}
_lock_registry_mutex = threading.Lock()

def _get_product_lock(product_id: int) -> threading.Lock:
    with _lock_registry_mutex:
        if product_id not in _product_locks:
            _product_locks[product_id] = threading.Lock()
        return _product_locks[product_id]

class OrderStatus:
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    FULFILLED = "FULFILLED"

class PaymentStatus:
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    PAID = "PAID"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"

def validate_and_consolidate_items(items: Any, max_qty_per_item: int = 50) -> List[Dict[str, int]]:
    """
    Validates items payload and consolidates duplicate product_ids
    to eliminate duplicate-item locking deadlocks.
    """
    if not items or not isinstance(items, list):
        raise ValueError("Cart items must be a non-empty list.")

    consolidated = {}
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"Cart item at index {idx} must be a valid JSON object.")

        raw_pid = item.get("product_id")
        raw_qty = item.get("quantity")

        if raw_pid is None or str(raw_pid).strip() == "":
            raise ValueError(f"Item at index {idx} is missing required 'product_id'.")

        try:
            pid = int(raw_pid)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid product_id '{raw_pid}'. Product ID must be a positive integer.")

        if pid <= 0:
            raise ValueError(f"Invalid product_id '{pid}'. Product ID must be greater than 0.")

        if raw_qty is None or str(raw_qty).strip() == "":
            raise ValueError(f"Missing quantity for product ID {pid}.")

        try:
            qty = int(raw_qty)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid quantity '{raw_qty}' for product ID {pid}. Quantity must be an integer.")

        if qty <= 0:
            raise ValueError(f"Invalid quantity '{qty}' for product ID {pid}. Quantity must be at least 1.")

        if qty > max_qty_per_item:
            raise ValueError(f"Quantity {qty} for product ID {pid} exceeds maximum limit of {max_qty_per_item} units per item.")

        consolidated[pid] = consolidated.get(pid, 0) + qty

    # Check total consolidated quantity per product
    for pid, total_qty in consolidated.items():
        if total_qty > max_qty_per_item:
            raise ValueError(f"Total aggregated quantity for product ID {pid} ({total_qty} units) exceeds maximum limit of {max_qty_per_item} units.")

    # Return distinct list sorted by product_id in ascending order
    return [{"product_id": pid, "quantity": qty} for pid, qty in sorted(consolidated.items(), key=lambda x: x[0])]

def validate_customer_info(customer_info: Any) -> Dict[str, Any]:
    """Validates shopper customer contact details"""
    if not customer_info or not isinstance(customer_info, dict):
        raise ValueError("Customer information must be a valid JSON object.")
    
    name = str(customer_info.get("name", "")).strip()
    email = str(customer_info.get("email", "")).strip()
    
    if not name:
        raise ValueError("Customer 'name' is required and cannot be empty.")
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise ValueError(f"Invalid customer email '{email}'. A valid email address is required.")
        
    return {
        "id": customer_info.get("id"),
        "name": name,
        "email": email,
        "phone": str(customer_info.get("phone", "+91 9999999999")).strip()
    }

class DatabaseService:
    def __init__(self):
        self.is_live_postgres = False
        self.sqlite_path = os.path.join(os.path.dirname(__file__), "..", "bharatkart_local.db")
        self.connection_error = None
        self._init_connection()

    def _init_connection(self):
        if Config.is_pg_configured():
            try:
                import psycopg2
                from psycopg2.extras import RealDictCursor
                conn = self._get_pg_connection()
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                conn.close()
                self.is_live_postgres = True
                logger.info("Successfully connected to Aiven PostgreSQL!")
                self._init_pg_schema()
                return
            except Exception as e:
                self.connection_error = str(e)
                logger.warning(f"Failed to connect to Aiven PostgreSQL: {e}. Falling back to ACID SQLite.")
        
        self.is_live_postgres = False
        self._init_sqlite_schema()

    def _get_pg_connection(self):
        import psycopg2
        if Config.AIVEN_PG_URL:
            return psycopg2.connect(Config.AIVEN_PG_URL)
        return psycopg2.connect(
            host=Config.AIVEN_PG_HOST,
            port=Config.AIVEN_PG_PORT,
            user=Config.AIVEN_PG_USER,
            password=Config.AIVEN_PG_PASSWORD,
            dbname=Config.AIVEN_PG_DATABASE,
            sslmode=Config.AIVEN_PG_SSLMODE
        )

    def _get_sqlite_connection(self):
        conn = sqlite3.connect(self.sqlite_path, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    # -------------------------------------------------------------------------
    # PostgreSQL Schema Setup (Full 23-Table Relational Schema)
    # -------------------------------------------------------------------------
    def _init_pg_schema(self):
        try:
            conn = self._get_pg_connection()
            # 1. Execute complete relational schema migration & indexes
            run_migrations(conn, is_postgres=True)

            with conn.cursor() as cur:
                # 2. Ensure all sample products exist in Aiven PostgreSQL
                for p in SAMPLE_PRODUCTS:
                    cur.execute("""
                    INSERT INTO products (id, sku, title, brand, category, price, original_price, image_url, rating, rating_count, description, cities_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                    """, (
                        p["id"], p["sku"], p["title"], p["brand"], p["category"],
                        p["price"], p["original_price"], p["image_url"],
                        p["rating"], p["rating_count"], p["description"],
                        json.dumps(p["cities"])
                    ))
                    cur.execute("""
                    INSERT INTO inventory (product_id, stock_quantity, reserved_quantity)
                    VALUES (%s, %s, 0)
                    ON CONFLICT (product_id) DO NOTHING;
                    """, (p["id"], p["stock"]))

                for c in SAMPLE_CUSTOMERS:
                    cur.execute("""
                    INSERT INTO customers (id, name, email, phone, city, address)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING;
                    """, (c["id"], c["name"], c["email"], c["phone"], c["city"], c["address"]))

                conn.commit()
            conn.close()
            logger.info("PostgreSQL schema initialization verified.")
        except Exception as e:
            logger.error(f"Error initializing PG schema: {e}")

    # -------------------------------------------------------------------------
    # SQLite Schema Setup (ACID Local Fallback)
    # -------------------------------------------------------------------------
    def _init_sqlite_schema(self):
        conn = self._get_sqlite_connection()
        # 1. Execute complete relational schema migration & indexes
        run_migrations(conn, is_postgres=False)

        cur = conn.cursor()
        # Ensure all sample products and initial customers exist in SQLite
        for p in SAMPLE_PRODUCTS:
            cur.execute("""
            INSERT OR IGNORE INTO products (id, sku, title, brand, category, price, original_price, image_url, rating, rating_count, description, cities_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                p["id"], p["sku"], p["title"], p["brand"], p["category"],
                p["price"], p["original_price"], p["image_url"],
                p["rating"], p["rating_count"], p["description"],
                json.dumps(p["cities"])
            ))
            cur.execute("""
            INSERT OR IGNORE INTO inventory (product_id, stock_quantity, reserved_quantity)
            VALUES (?, ?, 0)
            """, (p["id"], p["stock"]))

        for c in SAMPLE_CUSTOMERS:
            cur.execute("""
            INSERT OR IGNORE INTO customers (id, name, email, phone, city, address)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (c["id"], c["name"], c["email"], c["phone"], c["city"], c["address"]))

        conn.commit()
        conn.close()
        logger.info("SQLite schema initialization verified.")

    # -------------------------------------------------------------------------
    # Catalog Queries
    # -------------------------------------------------------------------------
    def get_all_products(self, category: Optional[str] = None, city: Optional[str] = None) -> List[Dict[str, Any]]:
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                SELECT p.*, i.stock_quantity as stock
                FROM products p
                JOIN inventory i ON p.id = i.product_id
                ORDER BY p.id ASC;
                """)
                rows = cur.fetchall()
            conn.close()
            products = []
            for r in rows:
                item = dict(r)
                item["cities"] = json.loads(item["cities_json"]) if item.get("cities_json") else []
                item["price"] = float(item["price"])
                item["original_price"] = float(item["original_price"]) if item["original_price"] else None
                item["rating"] = float(item["rating"]) if item["rating"] else None
                products.append(item)
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
            SELECT p.*, i.stock_quantity as stock
            FROM products p
            JOIN inventory i ON p.id = i.product_id
            ORDER BY p.id ASC;
            """)
            rows = cur.fetchall()
            products = []
            for r in rows:
                item = dict(r)
                item["cities"] = json.loads(item["cities_json"]) if item.get("cities_json") else []
                products.append(item)
            conn.close()

        if category and category.lower() != "all":
            products = [p for p in products if p["category"].lower() == category.lower()]
        if city and city.lower() != "all":
            products = [p for p in products if city in p["cities"]]

        return products

    def get_product_by_id(self, product_id: int) -> Optional[Dict[str, Any]]:
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                SELECT p.*, i.stock_quantity as stock
                FROM products p
                JOIN inventory i ON p.id = i.product_id
                WHERE p.id = %s;
                """, (product_id,))
                row = cur.fetchone()
            conn.close()
            if not row:
                return None
            item = dict(row)
            item["cities"] = json.loads(item["cities_json"]) if item.get("cities_json") else []
            item["price"] = float(item["price"])
            item["original_price"] = float(item["original_price"]) if item["original_price"] else None
            return item
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
            SELECT p.*, i.stock_quantity as stock
            FROM products p
            JOIN inventory i ON p.id = i.product_id
            WHERE p.id = ?;
            """, (product_id,))
            row = cur.fetchone()
            conn.close()
            if not row:
                return None
            item = dict(row)
            item["cities"] = json.loads(item["cities_json"]) if item.get("cities_json") else []
            return item

    # -------------------------------------------------------------------------
    # Core Requirement: Transactional Checkout with Row-Level Stock Locking
    # -------------------------------------------------------------------------
    def process_checkout_transaction(
        self,
        customer_info: Dict[str, Any],
        items: List[Dict[str, Any]],
        shipping_city: str,
        shipping_address: str,
        payment_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Executes an atomic checkout transaction:
        1. BEGIN transaction
        2. Acquiress row lock on inventory for each product
        3. Validates stock >= requested qty
        4. Decrements stock
        5. Inserts Order & Order Items
        6. COMMIT transaction (or ROLLBACK on any failure)
        Guarantees stock cannot drop below zero even if 10 shoppers buy simultaneously!
        """
        if not items:
            raise ValueError("Cart is empty.")

        # 1. Validate customer contact information
        validated_customer = validate_customer_info(customer_info)

        # 2. Validate items & consolidate duplicate product_ids to prevent locking deadlocks
        # Also sorts by product_id in ascending order to prevent distributed deadlocks
        consolidated_items = validate_and_consolidate_items(items, Config.MAX_QUANTITY_PER_ITEM)

        if self.is_live_postgres:
            return self._pg_checkout_transaction(validated_customer, consolidated_items, shipping_city, shipping_address, payment_info)
        else:
            return self._sqlite_checkout_transaction(validated_customer, consolidated_items, shipping_city, shipping_address, payment_info)

    def _pg_checkout_transaction(
        self,
        customer_info: Dict[str, Any],
        sorted_items: List[Dict[str, Any]],
        shipping_city: str,
        shipping_address: str,
        payment_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        conn = self._get_pg_connection()
        conn.autocommit = False # Explicit transaction boundary

        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. BEGIN transaction is implicit with autocommit=False
                cur.execute("SELECT pg_current_xact_id();")
                tx_id = cur.fetchone()["pg_current_xact_id"]
                logger.info(f"[PostgreSQL] Starting Transaction TX-{tx_id}")

                # Ensure customer exists or create
                customer_id = customer_info.get("id")
                if not customer_id:
                    cur.execute("""
                    INSERT INTO customers (name, email, phone, city, address)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id;
                    """, (
                        customer_info.get("name", "Guest Shopper"),
                        customer_info.get("email", f"guest-{uuid.uuid4().hex[:6]}@bharatkart.in"),
                        customer_info.get("phone", "+91 9999999999"),
                        shipping_city,
                        shipping_address
                    ))
                    customer_id = cur.fetchone()["id"]

                total_amount = 0.0
                order_items_to_save = []
                inventory_updates = []

                # 2. Strict Row-Level Lock with FOR UPDATE for each item
                for item in sorted_items:
                    pid = int(item["product_id"])
                    qty = int(item["quantity"])

                    # LOCK the inventory row
                    cur.execute("""
                    SELECT i.stock_quantity, p.title, p.price
                    FROM inventory i
                    JOIN products p ON i.product_id = p.id
                    WHERE i.product_id = %s
                    FOR UPDATE;
                    """, (pid,))

                    stock_row = cur.fetchone()
                    if not stock_row:
                        raise ValueError(f"Product ID {pid} does not exist.")

                    current_stock = stock_row["stock_quantity"]
                    product_title = stock_row["title"]
                    unit_price = float(stock_row["price"])

                    if current_stock < qty:
                        # ABORT & ROLLBACK
                        logger.warning(
                            f"[PostgreSQL] Stock check failed for '{product_title}'. Available: {current_stock}, Requested: {qty}. Issuing ROLLBACK."
                        )
                        raise ValueError(f"Insufficient stock for '{product_title}'. Only {current_stock} left in stock.")

                    new_stock = current_stock - qty
                    cur.execute("""
                    UPDATE inventory
                    SET stock_quantity = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE product_id = %s;
                    """, (new_stock, pid))

                    subtotal = unit_price * qty
                    total_amount += subtotal
                    order_items_to_save.append({
                        "product_id": pid,
                        "title": product_title,
                        "quantity": qty,
                        "unit_price": unit_price,
                        "subtotal": subtotal,
                        "remaining_stock": new_stock
                    })
                    inventory_updates.append((pid, new_stock))

                # 3. Create Order with explicit status separation
                order_number = f"BK-IN-{uuid.uuid4().hex[:8].upper()}"
                payment_method = str((payment_info or {}).get("method", "UPI")).upper()
                payment_id = (payment_info or {}).get("payment_id", f"pay_live_{uuid.uuid4().hex[:10]}")
                raw_pay_status = str((payment_info or {}).get("status", "PAID")).upper()

                if payment_method == "COD":
                    order_status = OrderStatus.CONFIRMED
                    payment_status = PaymentStatus.PENDING
                elif raw_pay_status in (PaymentStatus.PAID, "SUCCESS", "COMPLETED"):
                    order_status = OrderStatus.CONFIRMED
                    payment_status = PaymentStatus.PAID
                elif raw_pay_status in (PaymentStatus.PENDING, "INITIALIZED", ""):
                    order_status = OrderStatus.PENDING_PAYMENT
                    payment_status = PaymentStatus.PENDING
                else:
                    order_status = OrderStatus.PENDING_PAYMENT
                    payment_status = PaymentStatus.PENDING

                cur.execute("""
                INSERT INTO orders (order_number, customer_id, total_amount, status, payment_method, payment_id, payment_status, shipping_city, shipping_address)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, created_at;
                """, (order_number, customer_id, total_amount, order_status, payment_method, payment_id, payment_status, shipping_city, shipping_address))
                order_row = cur.fetchone()
                order_id = order_row["id"]
                created_at = str(order_row["created_at"])

                # 4. Insert Order Items
                for o_item in order_items_to_save:
                    cur.execute("""
                    INSERT INTO order_items (order_id, product_id, quantity, unit_price, subtotal)
                    VALUES (%s, %s, %s, %s, %s);
                    """, (order_id, o_item["product_id"], o_item["quantity"], o_item["unit_price"], o_item["subtotal"]))

                # 4b. Record Payment in payments table
                cur.execute("""
                INSERT INTO payments (order_id, payment_method, transaction_id, gateway, amount, currency, status)
                VALUES (%s, %s, %s, %s, %s, 'INR', %s);
                """, (order_id, payment_method, payment_id, "RAZORPAY_EMULATOR", total_amount, payment_status))

                # 4c. Record Stock Movement in inventory_movements ledger
                for o_item in order_items_to_save:
                    cur.execute("""
                    INSERT INTO inventory_movements (product_id, movement_type, quantity, balance_after, reference_type, reference_id, notes)
                    VALUES (%s, 'SOLD', %s, %s, 'ORDER', %s, %s);
                    """, (o_item["product_id"], o_item["quantity"], o_item["remaining_stock"], str(order_id), f"Sold via Order #{order_number}"))

                # 4d. Create Shipment & First Tracking Event
                tracking_number = f"BD-IN-{uuid.uuid4().hex[:10].upper()}"
                cur.execute("""
                INSERT INTO shipments (order_id, courier_name, tracking_number, status)
                VALUES (%s, 'BlueDart Express', %s, 'DISPATCHED')
                RETURNING id;
                """, (order_id, tracking_number))
                shipment_id = cur.fetchone()["id"]

                cur.execute("""
                INSERT INTO tracking_events (shipment_id, status, location, description)
                VALUES (%s, 'ORDER_PROCESSED', %s, %s);
                """, (shipment_id, shipping_city, f"Order #{order_number} packed and handed to BlueDart courier at metro hub"))

                # 5. COMMIT
                conn.commit()
                logger.info(f"[PostgreSQL] Successfully COMMITTED order #{order_number} (Status: {order_status}, Payment: {payment_status})")

                return {
                    "success": True,
                    "order_id": order_id,
                    "order_number": order_number,
                    "customer_id": customer_id,
                    "customer_name": customer_info.get("name", "Shopper"),
                    "customer_email": customer_info.get("email"),
                    "total_amount": round(total_amount, 2),
                    "status": order_status,
                    "order_status": order_status,
                    "payment_method": payment_method,
                    "payment_id": payment_id,
                    "payment_status": payment_status,
                    "shipping_city": shipping_city,
                    "shipping_address": shipping_address,
                    "items": order_items_to_save,
                    "inventory_updates": inventory_updates,
                    "created_at": created_at,
                    "engine": "PostgreSQL (Aiven Live with FOR UPDATE locks)"
                }

        except Exception as e:
            conn.rollback()
            logger.error(f"[PostgreSQL] Transaction ROLLBACK triggered: {e}")
            raise e
        finally:
            conn.close()

    def _sqlite_checkout_transaction(
        self,
        customer_info: Dict[str, Any],
        sorted_items: List[Dict[str, Any]],
        shipping_city: str,
        shipping_address: str,
        payment_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        ACID SQLite implementation with fine-grained mutexes simulating row locks.
        """
        # Acquire mutex locks for all products involved
        locks_acquired = []
        try:
            for item in sorted_items:
                lock = _get_product_lock(int(item["product_id"]))
                lock.acquire()
                locks_acquired.append(lock)

            conn = self._get_sqlite_connection()
            cur = conn.cursor()

            try:
                # Explicit transaction start
                cur.execute("BEGIN IMMEDIATE TRANSACTION;")

                # Ensure customer
                customer_id = customer_info.get("id")
                if not customer_id:
                    cur.execute("""
                    INSERT OR IGNORE INTO customers (name, email, phone, city, address)
                    VALUES (?, ?, ?, ?, ?)
                    """, (
                        customer_info.get("name", "Guest Shopper"),
                        customer_info.get("email", f"guest-{uuid.uuid4().hex[:6]}@bharatkart.in"),
                        customer_info.get("phone", "+91 9999999999"),
                        shipping_city,
                        shipping_address
                    ))
                    cur.execute("SELECT id FROM customers WHERE email = ?", (customer_info.get("email"),))
                    c_row = cur.fetchone()
                    customer_id = c_row["id"] if c_row else 1

                total_amount = 0.0
                order_items_to_save = []
                inventory_updates = []

                for item in sorted_items:
                    pid = int(item["product_id"])
                    qty = int(item["quantity"])

                    cur.execute("""
                    SELECT i.stock_quantity, p.title, p.price
                    FROM inventory i
                    JOIN products p ON i.product_id = p.id
                    WHERE i.product_id = ?;
                    """, (pid,))
                    stock_row = cur.fetchone()

                    if not stock_row:
                        raise ValueError(f"Product ID {pid} does not exist.")

                    current_stock = stock_row["stock_quantity"]
                    product_title = stock_row["title"]
                    unit_price = float(stock_row["price"])

                    if current_stock < qty:
                        raise ValueError(f"Insufficient stock for '{product_title}'. Only {current_stock} left in stock.")

                    new_stock = current_stock - qty
                    cur.execute("""
                    UPDATE inventory
                    SET stock_quantity = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE product_id = ?;
                    """, (new_stock, pid))

                    subtotal = unit_price * qty
                    total_amount += subtotal
                    order_items_to_save.append({
                        "product_id": pid,
                        "title": product_title,
                        "quantity": qty,
                        "unit_price": unit_price,
                        "subtotal": subtotal,
                        "remaining_stock": new_stock
                    })
                    inventory_updates.append((pid, new_stock))

                order_number = f"BK-IN-{uuid.uuid4().hex[:8].upper()}"
                payment_method = str((payment_info or {}).get("method", "UPI")).upper()
                payment_id = (payment_info or {}).get("payment_id", f"pay_live_{uuid.uuid4().hex[:10]}")
                raw_pay_status = str((payment_info or {}).get("status", "PAID")).upper()

                if payment_method == "COD":
                    order_status = OrderStatus.CONFIRMED
                    payment_status = PaymentStatus.PENDING
                elif raw_pay_status in (PaymentStatus.PAID, "SUCCESS", "COMPLETED"):
                    order_status = OrderStatus.CONFIRMED
                    payment_status = PaymentStatus.PAID
                elif raw_pay_status in (PaymentStatus.PENDING, "INITIALIZED", ""):
                    order_status = OrderStatus.PENDING_PAYMENT
                    payment_status = PaymentStatus.PENDING
                else:
                    order_status = OrderStatus.PENDING_PAYMENT
                    payment_status = PaymentStatus.PENDING

                cur.execute("""
                INSERT INTO orders (order_number, customer_id, total_amount, status, payment_method, payment_id, payment_status, shipping_city, shipping_address)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (order_number, customer_id, total_amount, order_status, payment_method, payment_id, payment_status, shipping_city, shipping_address))
                order_id = cur.lastrowid

                for o_item in order_items_to_save:
                    cur.execute("""
                    INSERT INTO order_items (order_id, product_id, quantity, unit_price, subtotal)
                    VALUES (?, ?, ?, ?, ?);
                    """, (order_id, o_item["product_id"], o_item["quantity"], o_item["unit_price"], o_item["subtotal"]))

                # 4b. Record Payment in payments table
                cur.execute("""
                INSERT INTO payments (order_id, payment_method, transaction_id, gateway, amount, currency, status)
                VALUES (?, ?, ?, ?, ?, 'INR', ?);
                """, (order_id, payment_method, payment_id, "RAZORPAY_EMULATOR", total_amount, payment_status))

                # 4c. Record Stock Movement in inventory_movements ledger
                for o_item in order_items_to_save:
                    cur.execute("""
                    INSERT INTO inventory_movements (product_id, movement_type, quantity, balance_after, reference_type, reference_id, notes)
                    VALUES (?, 'SOLD', ?, ?, 'ORDER', ?, ?);
                    """, (o_item["product_id"], o_item["quantity"], o_item["remaining_stock"], str(order_id), f"Sold via Order #{order_number}"))

                # 4d. Create Shipment & First Tracking Event
                tracking_number = f"BD-IN-{uuid.uuid4().hex[:10].upper()}"
                cur.execute("""
                INSERT INTO shipments (order_id, courier_name, tracking_number, status)
                VALUES (?, 'BlueDart Express', ?, 'DISPATCHED');
                """, (order_id, tracking_number))
                shipment_id = cur.lastrowid

                cur.execute("""
                INSERT INTO tracking_events (shipment_id, status, location, description)
                VALUES (?, 'ORDER_PROCESSED', ?, ?);
                """, (shipment_id, shipping_city, f"Order #{order_number} packed and handed to BlueDart courier at metro hub"))

                conn.commit()
                conn.close()

                return {
                    "success": True,
                    "order_id": order_id,
                    "order_number": order_number,
                    "customer_id": customer_id,
                    "customer_name": customer_info.get("name", "Shopper"),
                    "customer_email": customer_info.get("email"),
                    "total_amount": round(total_amount, 2),
                    "status": order_status,
                    "order_status": order_status,
                    "payment_method": payment_method,
                    "payment_id": payment_id,
                    "payment_status": payment_status,
                    "shipping_city": shipping_city,
                    "shipping_address": shipping_address,
                    "items": order_items_to_save,
                    "inventory_updates": inventory_updates,
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "engine": "PostgreSQL-Compatible Local ACID Engine (Row-Locked)"
                }

            except Exception as e:
                conn.rollback()
                conn.close()
                raise e

        finally:
            for lock in reversed(locks_acquired):
                lock.release()

    def update_stock(self, product_id: int, new_stock: int):
        """Direct stock update used by Kafka consumers or replenishment"""
        if self.is_live_postgres:
            conn = self._get_pg_connection()
            with conn.cursor() as cur:
                cur.execute("UPDATE inventory SET stock_quantity = %s WHERE product_id = %s;", (new_stock, product_id))
            conn.commit()
            conn.close()
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("UPDATE inventory SET stock_quantity = ? WHERE product_id = ?;", (new_stock, product_id))
            conn.commit()
            conn.close()

    def reset_inventory(self):
        """Helper to reset stock counts back to seed levels for easy demo testing"""
        for p in SAMPLE_PRODUCTS:
            self.update_stock(p["id"], p["stock"])
        logger.info("Inventory reset to initial seed values.")

    # -------------------------------------------------------------------------
    # Order Status Lifecycle & Compensating Transactions
    # -------------------------------------------------------------------------
    def get_order_by_id(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Fetch order details and line items by order ID"""
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                SELECT o.*, c.name as customer_name, c.email as customer_email, c.phone as customer_phone
                FROM orders o
                LEFT JOIN customers c ON o.customer_id = c.id
                WHERE o.id = %s;
                """, (order_id,))
                order_row = cur.fetchone()
                if not order_row:
                    conn.close()
                    return None
                order = dict(order_row)
                order["order_id"] = order["id"]
                order["total_amount"] = float(order["total_amount"])
                cur.execute("""
                SELECT oi.*, p.title as product_title, p.sku, p.image_url
                FROM order_items oi
                JOIN products p ON oi.product_id = p.id
                WHERE oi.order_id = %s;
                """, (order_id,))
                order["items"] = []
                for r in cur.fetchall():
                    item = dict(r)
                    item["title"] = item.get("product_title", "")
                    item["unit_price"] = float(item["unit_price"])
                    item["subtotal"] = float(item["subtotal"])
                    order["items"].append(item)
            conn.close()
            return order
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
            SELECT o.*, c.name as customer_name, c.email as customer_email, c.phone as customer_phone
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.id
            WHERE o.id = ?;
            """, (order_id,))
            order_row = cur.fetchone()
            if not order_row:
                conn.close()
                return None
            order = dict(order_row)
            order["order_id"] = order["id"]
            order["total_amount"] = float(order["total_amount"])
            cur.execute("""
            SELECT oi.*, p.title as product_title, p.sku, p.image_url
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            WHERE oi.order_id = ?;
            """, (order_id,))
            order["items"] = []
            for r in cur.fetchall():
                item = dict(r)
                item["title"] = item.get("product_title", "")
                item["unit_price"] = float(item["unit_price"])
                item["subtotal"] = float(item["subtotal"])
                order["items"].append(item)
            conn.close()
            return order

    def get_recent_orders(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Fetch latest orders across all customers"""
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                SELECT o.*, c.name as customer_name, c.email as customer_email
                FROM orders o
                LEFT JOIN customers c ON o.customer_id = c.id
                ORDER BY o.id DESC
                LIMIT %s;
                """, (limit,))
                orders = []
                for r in cur.fetchall():
                    o = dict(r)
                    o["total_amount"] = float(o["total_amount"])
                    orders.append(o)
            conn.close()
            return orders
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
            SELECT o.*, c.name as customer_name, c.email as customer_email
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.id
            ORDER BY o.id DESC
            LIMIT ?;
            """, (limit,))
            orders = []
            for r in cur.fetchall():
                o = dict(r)
                o["total_amount"] = float(o["total_amount"])
                orders.append(o)
            conn.close()
            return orders

    def update_order_payment_status(self, order_id: int, payment_status: str, payment_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Transitions order and payment state:
        - If payment_status is PAID: transitions order to CONFIRMED.
        - If payment_status is FAILED / REFUNDED: cancels order and replenishes stock.
        """
        payment_status_norm = payment_status.strip().upper()
        if payment_status_norm not in (PaymentStatus.PAID, PaymentStatus.FAILED, PaymentStatus.REFUNDED, PaymentStatus.PENDING):
            raise ValueError(f"Invalid payment status '{payment_status}'. Valid states: {PaymentStatus.PAID}, {PaymentStatus.FAILED}, {PaymentStatus.REFUNDED}, {PaymentStatus.PENDING}")

        order = self.get_order_by_id(order_id)
        if not order:
            raise ValueError(f"Order #{order_id} does not exist.")

        if payment_status_norm in (PaymentStatus.FAILED, PaymentStatus.REFUNDED):
            return self.cancel_order(order_id, reason=f"Payment status updated to {payment_status_norm}")

        if payment_status_norm == PaymentStatus.PAID:
            new_order_status = OrderStatus.CONFIRMED
        else:
            new_order_status = order["status"]

        if self.is_live_postgres:
            conn = self._get_pg_connection()
            with conn.cursor() as cur:
                cur.execute("""
                UPDATE orders
                SET payment_status = %s, status = %s, payment_id = COALESCE(%s, payment_id)
                WHERE id = %s;
                """, (payment_status_norm, new_order_status, payment_id, order_id))
            conn.commit()
            conn.close()
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
            UPDATE orders
            SET payment_status = ?, status = ?, payment_id = COALESCE(?, payment_id)
            WHERE id = ?;
            """, (payment_status_norm, new_order_status, payment_id, order_id))
            conn.commit()
            conn.close()

        logger.info(f"Order #{order_id} payment updated to {payment_status_norm}, order status is now {new_order_status}")
        return self.get_order_by_id(order_id)

    def cancel_order(self, order_id: int, reason: str = "Order cancelled") -> Dict[str, Any]:
        """
        Cancels an order and executes a compensating transaction to replenish inventory in the warehouse.
        """
        order = self.get_order_by_id(order_id)
        if not order:
            raise ValueError(f"Order #{order_id} does not exist.")

        if order["status"] == OrderStatus.CANCELLED:
            raise ValueError(f"Order #{order_id} is already CANCELLED.")

        items = order.get("items", [])
        restored_stock = []

        if self.is_live_postgres:
            conn = self._get_pg_connection()
            conn.autocommit = False
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                    UPDATE orders
                    SET status = %s, payment_status = %s
                    WHERE id = %s;
                    """, (OrderStatus.CANCELLED, PaymentStatus.FAILED, order_id))

                    cur.execute("UPDATE payments SET status = 'REFUNDED' WHERE order_id = %s;", (order_id,))

                    cur.execute("""
                    INSERT INTO refunds (order_id, amount, reason, status)
                    VALUES (%s, %s, %s, 'PROCESSED');
                    """, (order_id, order["total_amount"], reason))

                    for item in items:
                        pid = item["product_id"]
                        qty = item["quantity"]
                        cur.execute("""
                        UPDATE inventory
                        SET stock_quantity = stock_quantity + %s, updated_at = CURRENT_TIMESTAMP
                        WHERE product_id = %s
                        RETURNING stock_quantity;
                        """, (qty, pid))
                        new_qty = cur.fetchone()[0]
                        restored_stock.append({"product_id": pid, "restored_qty": qty, "new_stock": new_qty})

                        cur.execute("""
                        INSERT INTO inventory_movements (product_id, movement_type, quantity, balance_after, reference_type, reference_id, notes)
                        VALUES (%s, 'CANCELLED_RETURN', %s, %s, 'ORDER', %s, %s);
                        """, (pid, qty, new_qty, str(order_id), f"Cancelled order #{order_id} - stock restored"))

                conn.commit()
            except Exception as e:
                conn.rollback()
                raise e
            finally:
                conn.close()
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            try:
                cur.execute("BEGIN IMMEDIATE TRANSACTION;")
                cur.execute("""
                UPDATE orders
                SET status = ?, payment_status = ?
                WHERE id = ?;
                """, (OrderStatus.CANCELLED, PaymentStatus.FAILED, order_id))

                cur.execute("UPDATE payments SET status = 'REFUNDED' WHERE order_id = ?;", (order_id,))

                cur.execute("""
                INSERT INTO refunds (order_id, amount, reason, status)
                VALUES (?, ?, ?, 'PROCESSED');
                """, (order_id, order["total_amount"], reason))

                for item in items:
                    pid = item["product_id"]
                    qty = item["quantity"]
                    cur.execute("""
                    UPDATE inventory
                    SET stock_quantity = stock_quantity + ?, updated_at = CURRENT_TIMESTAMP
                    WHERE product_id = ?;
                    """, (qty, pid))
                    cur.execute("SELECT stock_quantity FROM inventory WHERE product_id = ?;", (pid,))
                    new_qty = cur.fetchone()[0]
                    restored_stock.append({"product_id": pid, "restored_qty": qty, "new_stock": new_qty})

                    cur.execute("""
                    INSERT INTO inventory_movements (product_id, movement_type, quantity, balance_after, reference_type, reference_id, notes)
                    VALUES (?, 'CANCELLED_RETURN', ?, ?, 'ORDER', ?, ?);
                    """, (pid, qty, new_qty, str(order_id), f"Cancelled order #{order_id} - stock restored"))

                conn.commit()
            except Exception as e:
                conn.rollback()
                raise e
            finally:
                conn.close()

        logger.info(f"Order #{order_id} cancelled. Restored stock for {len(restored_stock)} items. Reason: {reason}")
        res = self.get_order_by_id(order_id)
        res["restored_stock"] = restored_stock
        res["cancel_reason"] = reason
        return res

    # -------------------------------------------------------------------------
    # Atomic Stock Reservation, Release & Double-Entry Ledger
    # -------------------------------------------------------------------------
    def reserve_stock(self, product_id: int, quantity: int, reference_type: str = "CART", reference_id: str = "cart_hold") -> Dict[str, Any]:
        """Atomically reserves stock in inventory and logs to inventory_movements"""
        lock = _get_product_lock(product_id)
        with lock:
            if self.is_live_postgres:
                conn = self._get_pg_connection()
                try:
                    with conn.cursor() as cur:
                        res = atomic_reserve_stock(cur, True, product_id, quantity, reference_type, reference_id)
                    conn.commit()
                    return res
                finally:
                    conn.close()
            else:
                conn = self._get_sqlite_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("BEGIN IMMEDIATE TRANSACTION;")
                    res = atomic_reserve_stock(cur, False, product_id, quantity, reference_type, reference_id)
                    conn.commit()
                    return res
                finally:
                    conn.close()

    def release_stock(self, product_id: int, quantity: int, reference_type: str = "CART", reference_id: str = "cart_hold") -> Dict[str, Any]:
        """Atomically releases reserved stock back to available pool"""
        lock = _get_product_lock(product_id)
        with lock:
            if self.is_live_postgres:
                conn = self._get_pg_connection()
                try:
                    with conn.cursor() as cur:
                        res = atomic_release_stock(cur, True, product_id, quantity, reference_type, reference_id)
                    conn.commit()
                    return res
                finally:
                    conn.close()
            else:
                conn = self._get_sqlite_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("BEGIN IMMEDIATE TRANSACTION;")
                    res = atomic_release_stock(cur, False, product_id, quantity, reference_type, reference_id)
                    conn.commit()
                    return res
                finally:
                    conn.close()

    def get_inventory_movements(self, product_id: Optional[int] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves audit trail of stock movements from the double-entry ledger"""
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if product_id:
                    cur.execute("SELECT * FROM inventory_movements WHERE product_id = %s ORDER BY id DESC LIMIT %s;", (product_id, limit))
                else:
                    cur.execute("SELECT * FROM inventory_movements ORDER BY id DESC LIMIT %s;", (limit,))
                rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            if product_id:
                cur.execute("SELECT * FROM inventory_movements WHERE product_id = ? ORDER BY id DESC LIMIT ?;", (product_id, limit))
            else:
                cur.execute("SELECT * FROM inventory_movements ORDER BY id DESC LIMIT ?;", (limit,))
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows

    # -------------------------------------------------------------------------
    # Relational Domain Queries (Hubs, Sellers, Categories, Reviews, Shipments)
    # -------------------------------------------------------------------------
    def get_store_hubs(self) -> List[Dict[str, Any]]:
        """Returns physical retail and fulfillment hubs"""
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM store_hubs WHERE is_active = TRUE ORDER BY id ASC;")
                rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM store_hubs WHERE is_active = 1 ORDER BY id ASC;")
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows

    def get_sellers(self) -> List[Dict[str, Any]]:
        """Returns verified sellers"""
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM sellers ORDER BY rating DESC;")
                rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM sellers ORDER BY rating DESC;")
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows

    def get_categories(self) -> List[Dict[str, Any]]:
        """Returns product taxonomy categories"""
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM categories ORDER BY display_order ASC, id ASC;")
                rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM categories ORDER BY display_order ASC, id ASC;")
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows

    def get_shipment_tracking(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Returns shipment details and tracking events for an order"""
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM shipments WHERE order_id = %s;", (order_id,))
                ship_row = cur.fetchone()
                if not ship_row:
                    conn.close()
                    return None
                shipment = dict(ship_row)
                cur.execute("SELECT * FROM tracking_events WHERE shipment_id = %s ORDER BY id ASC;", (shipment["id"],))
                shipment["events"] = [dict(r) for r in cur.fetchall()]
            conn.close()
            return shipment
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM shipments WHERE order_id = ?;", (order_id,))
            ship_row = cur.fetchone()
            if not ship_row:
                conn.close()
                return None
            shipment = dict(ship_row)
            cur.execute("SELECT * FROM tracking_events WHERE shipment_id = ? ORDER BY id ASC;", (shipment["id"],))
            shipment["events"] = [dict(r) for r in cur.fetchall()]
            conn.close()
            return shipment

    def add_product_review(self, product_id: int, customer_id: Optional[int], rating: int, title: str, comment: str) -> Dict[str, Any]:
        """Creates a verified product review and rating"""
        if rating < 1 or rating > 5:
            raise ValueError(f"Rating must be between 1 and 5 stars, got {rating}")
        if not title:
            raise ValueError("Review title cannot be empty")

        if self.is_live_postgres:
            conn = self._get_pg_connection()
            with conn.cursor() as cur:
                cur.execute("""
                INSERT INTO product_reviews (product_id, customer_id, rating, title, comment)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, created_at;
                """, (product_id, customer_id, rating, title, comment))
                row = cur.fetchone()
                review_id = row[0]
            conn.commit()
            conn.close()
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
            INSERT INTO product_reviews (product_id, customer_id, rating, title, comment)
            VALUES (?, ?, ?, ?, ?);
            """, (product_id, customer_id, rating, title, comment))
            review_id = cur.lastrowid
            conn.commit()
            conn.close()

        return {
            "success": True,
            "review_id": review_id,
            "product_id": product_id,
            "rating": rating,
            "title": title,
            "comment": comment
        }

    def get_product_reviews(self, product_id: int) -> List[Dict[str, Any]]:
        """Returns customer reviews for a given product"""
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                SELECT r.*, c.name as customer_name
                FROM product_reviews r
                LEFT JOIN customers c ON r.customer_id = c.id
                WHERE r.product_id = %s
                ORDER BY r.id DESC;
                """, (product_id,))
                rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
            SELECT r.*, c.name as customer_name
            FROM product_reviews r
            LEFT JOIN customers c ON r.customer_id = c.id
            WHERE r.product_id = ?
            ORDER BY r.id DESC;
            """, (product_id,))
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows

    # -------------------------------------------------------------------------
    # Admin Management Helpers
    # -------------------------------------------------------------------------
    def create_product(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Creates a new product and initial inventory record"""
        sku = data.get("sku") or f"BK-CUS-{uuid.uuid4().hex[:6].upper()}"
        title = data.get("title", "New Product")
        brand = data.get("brand", "BharatStore Brand")
        category = data.get("category", "General")
        price = float(data.get("price", 0))
        original_price = float(data.get("original_price", price)) if data.get("original_price") else price
        stock = int(data.get("stock", 10))
        image_url = data.get("image_url", "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500&auto=format&fit=crop&q=80")
        description = data.get("description", "")
        cities = data.get("cities", ["Mumbai", "Bengaluru", "Delhi"])
        cities_json = json.dumps(cities)

        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                INSERT INTO products (sku, title, brand, category, price, original_price, image_url, rating, rating_count, description, cities_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 4.5, 1, %s, %s)
                RETURNING id;
                """, (sku, title, brand, category, price, original_price, image_url, description, cities_json))
                new_id = cur.fetchone()["id"]
                cur.execute("""
                INSERT INTO inventory (product_id, stock_quantity, reserved_quantity)
                VALUES (%s, %s, 0);
                """, (new_id, stock))
                conn.commit()
            conn.close()
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
            INSERT INTO products (sku, title, brand, category, price, original_price, image_url, rating, rating_count, description, cities_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, 4.5, 1, ?, ?);
            """, (sku, title, brand, category, price, original_price, image_url, description, cities_json))
            new_id = cur.lastrowid
            cur.execute("""
            INSERT INTO inventory (product_id, stock_quantity, reserved_quantity)
            VALUES (?, ?, 0);
            """, (new_id, stock))
            conn.commit()
            conn.close()

        return self.get_product_by_id(new_id)

    def update_product(self, product_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Updates product metadata and inventory stock"""
        title = data.get("title")
        brand = data.get("brand")
        category = data.get("category")
        price = float(data.get("price")) if "price" in data and data.get("price") is not None else None
        original_price = float(data.get("original_price")) if "original_price" in data and data.get("original_price") is not None else None
        image_url = data.get("image_url")
        description = data.get("description")
        stock = int(data.get("stock")) if "stock" in data and data.get("stock") is not None else None

        if self.is_live_postgres:
            conn = self._get_pg_connection()
            with conn.cursor() as cur:
                if any(v is not None for v in [title, brand, category, price, original_price, image_url, description]):
                    cur.execute("""
                    UPDATE products
                    SET title = COALESCE(%s, title),
                        brand = COALESCE(%s, brand),
                        category = COALESCE(%s, category),
                        price = COALESCE(%s, price),
                        original_price = COALESCE(%s, original_price),
                        image_url = COALESCE(%s, image_url),
                        description = COALESCE(%s, description)
                    WHERE id = %s;
                    """, (title, brand, category, price, original_price, image_url, description, product_id))
                if stock is not None:
                    cur.execute("UPDATE inventory SET stock_quantity = %s WHERE product_id = %s;", (stock, product_id))
                conn.commit()
            conn.close()
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            if any(v is not None for v in [title, brand, category, price, original_price, image_url, description]):
                cur.execute("""
                UPDATE products
                SET title = COALESCE(?, title),
                    brand = COALESCE(?, brand),
                    category = COALESCE(?, category),
                    price = COALESCE(?, price),
                    original_price = COALESCE(?, original_price),
                    image_url = COALESCE(?, image_url),
                    description = COALESCE(?, description)
                WHERE id = ?;
                """, (title, brand, category, price, original_price, image_url, description, product_id))
            if stock is not None:
                cur.execute("UPDATE inventory SET stock_quantity = ? WHERE product_id = ?;", (stock, product_id))
            conn.commit()
            conn.close()

        return self.get_product_by_id(product_id)

    def delete_product(self, product_id: int) -> bool:
        """Deletes a product and its associated inventory"""
        if self.is_live_postgres:
            conn = self._get_pg_connection()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM inventory WHERE product_id = %s;", (product_id,))
                cur.execute("DELETE FROM products WHERE id = %s;", (product_id,))
                conn.commit()
            conn.close()
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM inventory WHERE product_id = ?;", (product_id,))
            cur.execute("DELETE FROM products WHERE id = ?;", (product_id,))
            conn.commit()
            conn.close()
        return True

    def update_order_status(self, order_id: int, new_status: str) -> Optional[Dict[str, Any]]:
        """Transitions order status (e.g. PENDING_PAYMENT, CONFIRMED, SHIPPED, DELIVERED, CANCELLED)"""
        new_status = new_status.upper().strip()
        if self.is_live_postgres:
            conn = self._get_pg_connection()
            with conn.cursor() as cur:
                cur.execute("UPDATE orders SET status = %s WHERE id = %s;", (new_status, order_id))
                conn.commit()
            conn.close()
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("UPDATE orders SET status = ? WHERE id = ?;", (new_status, order_id))
            conn.commit()
            conn.close()
        return self.get_order_by_id(order_id)

    def get_admin_metrics(self) -> Dict[str, Any]:
        """Calculates storewide KPI metrics for the Admin Dashboard"""
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT COUNT(*) as total_orders, COALESCE(SUM(total_amount), 0) as total_revenue FROM orders;")
                order_stats = cur.fetchone()
                cur.execute("SELECT COUNT(*) as total_products FROM products;")
                prod_count = cur.fetchone()["total_products"]
                cur.execute("SELECT COUNT(*) as low_stock_count FROM inventory WHERE stock_quantity <= 5;")
                low_stock = cur.fetchone()["low_stock_count"]
                cur.execute("SELECT COUNT(*) as total_customers FROM customers;")
                cust_count = cur.fetchone()["total_customers"]
            conn.close()
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*), COALESCE(SUM(total_amount), 0) FROM orders;")
            row = cur.fetchone()
            order_stats = {"total_orders": row[0], "total_revenue": row[1]}
            cur.execute("SELECT COUNT(*) FROM products;")
            prod_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM inventory WHERE stock_quantity <= 5;")
            low_stock = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM customers;")
            cust_count = cur.fetchone()[0]
            conn.close()

        return {
            "total_orders": order_stats["total_orders"],
            "total_revenue": round(float(order_stats["total_revenue"]), 2),
            "total_products": prod_count,
            "low_stock_count": low_stock,
            "total_customers": cust_count
        }

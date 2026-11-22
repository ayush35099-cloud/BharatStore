"""
BharatKart Database Service
Supports Aiven PostgreSQL with transactional checkout, SELECT FOR UPDATE row locking,
and seamless ACID-compliant fallback with concurrency locks.
"""

import os
import re
import math
import json
import uuid
import time
import queue
import logging
import sqlite3
import threading
from typing import Dict, List, Any, Optional, Tuple
from app.config import Config
from app.seed_data import (
    SAMPLE_PRODUCTS,
    SAMPLE_CUSTOMERS,
    FULFILLMENT_HUBS,
    get_product_gallery_seed_data,
    get_product_specifications_seed_data,
    SEED_CUSTOMER_REVIEWS
)
from app.schema import (
    run_migrations,
    atomic_reserve_stock,
    atomic_release_stock,
    atomic_commit_reserved_stock
)
from app.cache import app_cache

logger = logging.getLogger("BharatKart.Database")

# Product-level mutex locks for thread safety during checkout
_product_locks: Dict[int, threading.Lock] = {}
_lock_registry_mutex = threading.Lock()

def _get_product_lock(product_id: int) -> threading.Lock:
    with _lock_registry_mutex:
        if product_id not in _product_locks:
            _product_locks[product_id] = threading.Lock()
        return _product_locks[product_id]


class BoundedConnectionPool:
    """
    Production-grade bounded connection pool engineered for Aiven PostgreSQL.
    Features:
    - Conservative hard ceiling (maxconn): strictly guarantees never exceeding Aiven connection limits.
    - True queue-based checkout (pool_timeout): requests wait on a thread-safe queue for up to pool_timeout seconds
      instead of failing immediately or creating unbounded direct connections.
    - Pre-ping liveness probe (pool_pre_ping): validates connection health before handing it to a caller.
    - Connection recycling (pool_recycle): transparently recycles connections older than recycle_seconds.
    - LIFO queue reuse: reuses the most recently used connection to minimize active server-side resources.
    - Safe cleanup: rolls back transactions on return and ensures connections are closed on pool shutdown.
    - Leak prevention: idempotent tracking of all created and checked-out connections with graceful shutdown.
    """
    def __init__(
        self,
        minconn: int = 1,
        maxconn: int = 3,
        timeout: float = 10.0,
        recycle: float = 1800.0,
        connect_fn = None
    ):
        self.minconn = max(1, int(minconn))
        self.maxconn = max(self.minconn, int(maxconn))
        self.timeout = float(timeout)
        self.recycle = float(recycle)
        self.connect_fn = connect_fn
        self._pool = queue.LifoQueue(maxsize=self.maxconn)
        self._all_conns = set()
        self._checked_out = set()
        self._created_count = 0
        self._lock = threading.RLock()
        self._closed = False

    def _create_raw_connection(self):
        """Creates a single raw PostgreSQL connection using the provided connect function."""
        if not self.connect_fn:
            raise RuntimeError("connect_fn is not defined for BoundedConnectionPool.")
        conn = self.connect_fn()
        return conn

    def _is_conn_healthy(self, conn) -> bool:
        """Pre-ping liveness probe validating socket health."""
        if not conn or getattr(conn, "closed", 1):
            return False
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
            if not getattr(conn, "autocommit", False):
                conn.rollback()
            return True
        except Exception:
            return False

    def _destroy_connection(self, conn):
        """Safely closes a connection and decrements the active count idempotently."""
        if not conn:
            return
        with self._lock:
            was_tracked = (conn in self._all_conns)
            self._all_conns.discard(conn)
            self._checked_out.discard(conn)
            if was_tracked:
                self._created_count = max(0, self._created_count - 1)
        try:
            if not getattr(conn, "closed", 1):
                conn.close()
        except Exception:
            pass

    def getconn(self, timeout: Optional[float] = None):
        """
        Checks out an active, healthy connection from the pool.
        Waits up to timeout seconds if the pool is currently at maxconn capacity.
        """
        if self._closed:
            raise RuntimeError("Connection pool is closed.")

        wait_timeout = self.timeout if timeout is None else float(timeout)
        deadline = time.time() + wait_timeout

        while time.time() < deadline:
            # 1. Try to pop an existing idle connection from the pool without waiting
            try:
                conn, created_at = self._pool.get_nowait()
                # Check pool_recycle
                if (time.time() - created_at) > self.recycle:
                    self._destroy_connection(conn)
                    continue
                # Pre-ping probe
                if self._is_conn_healthy(conn):
                    with self._lock:
                        if self._closed:
                            self._destroy_connection(conn)
                            raise RuntimeError("Connection pool is closed.")
                        self._checked_out.add(conn)
                    return conn
                else:
                    self._destroy_connection(conn)
                    continue
            except queue.Empty:
                pass

            # 2. Pool queue is currently empty. Atomically reserve a slot under lock
            can_create = False
            with self._lock:
                if self._closed:
                    raise RuntimeError("Connection pool is closed.")
                if self._created_count < self.maxconn:
                    self._created_count += 1
                    can_create = True

            if can_create:
                try:
                    conn = self._create_raw_connection()
                    with self._lock:
                        if self._closed:
                            self._created_count = max(0, self._created_count - 1)
                            try:
                                if not getattr(conn, "closed", 1):
                                    conn.close()
                            except Exception:
                                pass
                            raise RuntimeError("Connection pool is closed.")
                        self._all_conns.add(conn)
                        self._checked_out.add(conn)
                    return conn
                except Exception as ce:
                    with self._lock:
                        self._created_count = max(0, self._created_count - 1)
                    logger.warning(f"Connection creation attempt notice in pool: {ce}")
                    raise

            # 3. Pool is at max capacity. Wait on queue until a worker returns one.
            remaining = max(0.05, deadline - time.time())
            try:
                conn, created_at = self._pool.get(timeout=min(remaining, 1.0))
                if (time.time() - created_at) > self.recycle:
                    self._destroy_connection(conn)
                    continue
                if self._is_conn_healthy(conn):
                    with self._lock:
                        if self._closed:
                            self._destroy_connection(conn)
                            raise RuntimeError("Connection pool is closed.")
                        self._checked_out.add(conn)
                    return conn
                else:
                    self._destroy_connection(conn)
                    continue
            except queue.Empty:
                continue

        raise TimeoutError(
            f"PostgreSQL connection pool checkout timed out after {wait_timeout}s "
            f"(max={self.maxconn}, active={self._created_count})."
        )

    def putconn(self, conn, close: bool = False):
        """Returns a connection to the pool or closes it if requested/unhealthy/pool closed."""
        if not conn:
            return

        should_destroy = False
        with self._lock:
            if self._closed or close or getattr(conn, "closed", 1):
                should_destroy = True
            elif conn not in self._checked_out:
                # Idempotency: connection was already returned or not checked out from this pool
                return
            else:
                self._checked_out.discard(conn)

        if should_destroy:
            self._destroy_connection(conn)
            return

        # Rollback any active or uncommitted transaction before returning to pool
        try:
            import psycopg2.extensions
            if getattr(conn, "status", None) != psycopg2.extensions.STATUS_READY:
                conn.rollback()
        except Exception:
            self._destroy_connection(conn)
            return

        # Return to pool queue
        try:
            self._pool.put_nowait((conn, time.time()))
        except queue.Full:
            self._destroy_connection(conn)

    def closeall(self):
        """Closes all connections in the pool safely."""
        with self._lock:
            self._closed = True
            # 1. Drain and close all idle connections in the pool
            while not self._pool.empty():
                try:
                    conn, _ = self._pool.get_nowait()
                    try:
                        if not getattr(conn, "closed", 1):
                            conn.close()
                    except Exception:
                        pass
                    self._all_conns.discard(conn)
                except queue.Empty:
                    break

            # 2. For any connections still checked out, close their sockets and clear tracking
            for conn in list(self._checked_out):
                try:
                    if not getattr(conn, "closed", 1):
                        conn.close()
                except Exception:
                    pass
                self._all_conns.discard(conn)
                self._checked_out.discard(conn)

            self._created_count = 0

    def get_status(self) -> Dict[str, Any]:
        """Returns thread-safe metrics for diagnostics."""
        with self._lock:
            created = self._created_count
            checked_out = len(self._checked_out)
            idle = self._pool.qsize()
            return {
                "minconn": self.minconn,
                "maxconn": self.maxconn,
                "timeout": self.timeout,
                "recycle": self.recycle,
                "created_connections": created,
                "idle_connections": idle,
                "checked_out_connections": checked_out,
                "closed": self._closed
            }


class PooledConnectionProxy:
    """
    Transparent proxy wrapping a PostgreSQL connection checked out from BoundedConnectionPool.
    Delegates all operations to the underlying connection and safely returns it to the pool
    upon close() or context exit without terminating the TCP socket.
    """
    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn
        self._returned = False

    def close(self):
        if not self._returned and self._conn:
            self._returned = True
            try:
                import psycopg2.extensions
                if not getattr(self._conn, "closed", 1) and getattr(self._conn, "status", None) != psycopg2.extensions.STATUS_READY:
                    self._conn.rollback()
            except Exception:
                pass
            if self._pool:
                try:
                    self._pool.putconn(self._conn)
                    return
                except Exception as pe:
                    logger.debug(f"putconn notice: {pe}")
            # If putconn failed or pool unavailable, safely close raw TCP socket directly
            try:
                if not getattr(self._conn, "closed", 1):
                    self._conn.close()
            except Exception:
                pass

    def __enter__(self):
        return self._conn.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            return self._conn.__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()

    def __del__(self):
        """Finalizer fallback in case caller forgot to call close()."""
        try:
            self.close()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._conn, name)

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
        self._pg_pool = None
        self._pool_pid = None
        self._pool_lock = threading.Lock()
        self._init_connection()

    def reset_connection_pool(self):
        """Safely resets pool reference for worker process isolation after fork."""
        with self._pool_lock:
            self._pg_pool = None
            self._pool_pid = None

    def _get_pg_pool(self):
        """Returns thread-safe BoundedConnectionPool strictly isolated to current worker PID."""
        if not self.is_live_postgres:
            return None
        current_pid = os.getpid()
        if self._pg_pool is not None and self._pool_pid != current_pid:
            logger.info(f"Worker PID changed ({self._pool_pid} -> {current_pid}); resetting connection pool for worker isolation.")
            self._pg_pool = None
            self._pool_pid = None

        if self._pg_pool is None:
            with self._pool_lock:
                if self._pg_pool is None:
                    try:
                        min_conn = getattr(Config, "PG_POOL_MIN", 1)
                        max_conn = getattr(Config, "PG_POOL_MAX", 3)
                        timeout = getattr(Config, "PG_POOL_TIMEOUT", 10.0)
                        recycle = getattr(Config, "PG_POOL_RECYCLE", 1800.0)
                        self._pg_pool = BoundedConnectionPool(
                            minconn=min_conn,
                            maxconn=max_conn,
                            timeout=timeout,
                            recycle=recycle,
                            connect_fn=self._connect_pg_direct
                        )
                        self._pool_pid = current_pid
                        logger.info(
                            f"Initialized isolated BoundedConnectionPool for PID {current_pid} "
                            f"(min={min_conn}, max={max_conn}, timeout={timeout}s, recycle={recycle}s)"
                        )
                    except Exception as pe:
                        logger.warning(f"Connection pool init notice for PID {current_pid}: {pe}")
        return self._pg_pool

    def _sanitize_db_error(self, err_msg: str) -> str:
        """Removes credentials and passwords from database error messages before logging or reporting."""
        if not err_msg:
            return ""
        # Redact URI credentials: postgresql://user:password@host
        sanitized = re.sub(r"://([^:]+):([^@]+)@", r"://\1:******@", err_msg)
        # Redact keyword parameters: password=... or pwd=...
        sanitized = re.sub(r"password=([^\s]+)", r"password=******", sanitized)
        sanitized = re.sub(r"pwd=([^\s]+)", r"pwd=******", sanitized)
        sanitized = re.sub(r"user=([^\s]+)", r"user=******", sanitized)
        return sanitized

    @staticmethod
    def _parse_cities_json(val: Any) -> List[str]:
        if not val:
            return []
        if isinstance(val, list):
            return val
        if isinstance(val, (dict, set)):
            return list(val)
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else [str(parsed)]
        except Exception:
            try:
                import ast
                parsed = ast.literal_eval(val)
                return parsed if isinstance(parsed, list) else [str(parsed)]
            except Exception:
                return []

    def _init_connection(self):
        if Config.is_pg_configured():
            max_attempts = 6 if Config.is_production() else 1
            # 6 total attempts (1 initial + 5 retries) with progressive backoff delays: [3s, 6s, 9s, 12s, 12s]
            retry_delays = [3, 6, 9, 12, 12]
            start_time = time.time()
            for attempt in range(1, max_attempts + 1):
                try:
                    import psycopg2

                    conn = self._connect_pg_direct()
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1;")
                    conn.close()

                    self.is_live_postgres = True
                    logger.info("Successfully connected to PostgreSQL database with bounded worker pooling!")
                    self._init_pg_schema()
                    return
                except Exception as e:
                    clean_err = self._sanitize_db_error(str(e))
                    self.connection_error = clean_err
                    if attempt < max_attempts:
                        delay_override = os.getenv("PG_STARTUP_RETRY_DELAY")
                        if delay_override is not None:
                            wait_sec = int(delay_override)
                        elif getattr(Config, "TESTING", False):
                            wait_sec = 0
                        else:
                            idx = min(attempt - 1, len(retry_delays) - 1)
                            wait_sec = retry_delays[idx]

                        logger.warning(
                            f"PostgreSQL startup connection attempt {attempt}/{max_attempts} failed ({clean_err}). "
                            f"Waiting {wait_sec}s for existing container connections to release..."
                        )
                        if wait_sec > 0:
                            time.sleep(wait_sec)
                    else:
                        elapsed = int(time.time() - start_time)
                        if Config.is_production():
                            logger.error(
                                f"CRITICAL: Failed to connect to PostgreSQL in production after {max_attempts} attempts ({elapsed}s)! "
                                f"Error: {clean_err}."
                            )
                            raise RuntimeError(
                                f"Production PostgreSQL connection failed: {clean_err}. "
                                "BharatStore requires persistent PostgreSQL in production."
                            )
                        else:
                            logger.warning(f"Failed to connect to PostgreSQL: {clean_err}. Falling back to ACID SQLite.")
        elif Config.is_production():
            err_msg = "CRITICAL: DATABASE_URL / AIVEN_PG_URL not configured. BharatStore requires persistent PostgreSQL in production."
            logger.error(err_msg)
            raise RuntimeError(err_msg)
        
        self.is_live_postgres = False
        self._init_sqlite_schema()

    def _connect_pg_direct(self):
        """Creates a direct PostgreSQL connection with TCP keepalives and a 10s connect timeout."""
        import psycopg2
        pg_url = Config.get_pg_url()
        if pg_url:
            return psycopg2.connect(pg_url, connect_timeout=10, keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5)
        return psycopg2.connect(
            host=Config.AIVEN_PG_HOST,
            port=Config.AIVEN_PG_PORT,
            user=Config.AIVEN_PG_USER,
            password=Config.AIVEN_PG_PASSWORD,
            dbname=Config.AIVEN_PG_DATABASE,
            sslmode=Config.AIVEN_PG_SSLMODE,
            connect_timeout=10,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5
        )

    def _get_pg_connection(self):
        pool = self._get_pg_pool()
        if pool:
            raw_conn = pool.getconn()
            return PooledConnectionProxy(pool, raw_conn)
        return self._connect_pg_direct()

    def get_db_diagnostics(self) -> Dict[str, Any]:
        """
        Executes read-only diagnostic queries against PostgreSQL system catalogs
        (pg_stat_activity, pg_settings) to inspect connection usage, state, and limits.
        Completely non-destructive: never runs DROP, TRUNCATE, DELETE, or terminates connections.
        """
        pool_status = self._pg_pool.get_status() if self._pg_pool else None
        if not self.is_live_postgres:
            return {
                "engine": "SQLite",
                "pool_status": pool_status,
                "message": "Live PostgreSQL is not active; running in SQLite mode."
            }

        conn = None
        try:
            conn = self._get_pg_connection()
            from psycopg2.extras import RealDictCursor
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Server settings
                cur.execute("""
                    SELECT 
                        current_setting('max_connections')::int AS max_connections,
                        current_setting('superuser_reserved_connections')::int AS superuser_reserved;
                """)
                settings_row = cur.fetchone() or {}
                max_conn = settings_row.get("max_connections", 20)
                su_reserved = settings_row.get("superuser_reserved", 3)
                usable_slots = max(0, max_conn - su_reserved)

                # 2. Connection breakdown by state
                cur.execute("""
                    SELECT 
                        count(*) AS total_connections,
                        count(*) FILTER (WHERE state = 'active') AS active_connections,
                        count(*) FILTER (WHERE state = 'idle') AS idle_connections,
                        count(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_transaction_connections,
                        count(*) FILTER (WHERE state = 'idle in transaction (aborted)') AS idle_in_trans_aborted_connections,
                        count(*) FILTER (WHERE state IS NULL OR state = 'disabled') AS other_connections
                    FROM pg_stat_activity;
                """)
                summary_row = cur.fetchone() or {}

                # 3. Connections grouped by application_name, usename, and state
                cur.execute("""
                    SELECT 
                        COALESCE(NULLIF(application_name, ''), '[unnamed]') AS application_name,
                        COALESCE(usename, '[unknown]') AS usename,
                        COALESCE(state, 'unknown') AS state,
                        count(*) AS connection_count
                    FROM pg_stat_activity
                    GROUP BY application_name, usename, state
                    ORDER BY connection_count DESC;
                """)
                grouped_rows = [dict(r) for r in cur.fetchall()]

                return {
                    "engine": "PostgreSQL (Aiven Cloud)",
                    "limits": {
                        "max_connections": max_conn,
                        "superuser_reserved_connections": su_reserved,
                        "usable_application_slots": usable_slots
                    },
                    "summary": dict(summary_row),
                    "connections_grouped": grouped_rows,
                    "pool_status": pool_status
                }
        except Exception as e:
            logger.warning(f"DB diagnostics query notice: {e}")
            return {
                "error": self._sanitize_db_error(str(e)),
                "pool_status": pool_status
            }
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def _get_sqlite_connection(self):
        conn = sqlite3.connect(self.sqlite_path, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    # -------------------------------------------------------------------------
    # PostgreSQL Schema Setup (Full 23-Table Relational Schema)
    # -------------------------------------------------------------------------
    def _init_pg_schema(self):
        conn = None
        has_lock = False
        try:
            conn = self._connect_pg_direct()
            conn.autocommit = True
            with conn.cursor() as cur:
                # 1. Fast startup verification: if schema and domain catalog already exist, skip redundant DDL and 450+ seed queries
                try:
                    cur.execute("""
                        SELECT 
                            (SELECT to_regclass('products') IS NOT NULL) AS has_products,
                            (SELECT to_regclass('store_inventory') IS NOT NULL) AS has_store_inventory,
                            (SELECT to_regclass('product_images') IS NOT NULL) AS has_product_images;
                    """)
                    chk_row = cur.fetchone()
                    if chk_row and chk_row[0] and chk_row[1] and chk_row[2]:
                        cur.execute("SELECT COUNT(*) FROM products;")
                        prod_cnt = cur.fetchone()[0]
                        if prod_cnt >= len(SAMPLE_PRODUCTS):
                            cur.execute("SELECT COUNT(*) FROM product_images;")
                            if cur.fetchone()[0] > 0:
                                logger.info("PostgreSQL schema and domain catalog verified (fast startup path).")
                                return
                except Exception as fe:
                    logger.debug(f"PostgreSQL fast path check notice: {fe}")

                # Hold a session-level advisory lock to eliminate migration races between concurrent gunicorn workers
                cur.execute("SELECT pg_advisory_lock(742189);")
                has_lock = True
            
            conn.autocommit = False
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

                self._seed_phase2_metadata(conn, is_postgres=True)
                conn.commit()
            logger.info("PostgreSQL schema initialization verified.")
        except Exception as e:
            clean_err = self._sanitize_db_error(str(e))
            logger.error(f"Error initializing PG schema: {clean_err}")
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            if Config.is_production():
                raise RuntimeError(f"PostgreSQL schema initialization failed in production: {clean_err}")
        finally:
            if conn:
                try:
                    if has_lock:
                        with conn.cursor() as cur:
                            cur.execute("SELECT pg_advisory_unlock(742189);")
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

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

        self._seed_phase2_metadata(conn, is_postgres=False)
        conn.commit()
        conn.close()
        logger.info("SQLite schema initialization verified.")

    def _seed_phase2_metadata(self, conn, is_postgres=False):
        """Seeds product_images, product_specifications, and product_reviews if not populated"""
        try:
            cur = conn.cursor()
            # Fast check: skip if already populated
            cur.execute("SELECT COUNT(*) FROM product_images;")
            img_total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM product_specifications;")
            spec_total = cur.fetchone()[0]
            if img_total > 0 and spec_total > 0:
                return

            for p in SAMPLE_PRODUCTS:
                pid = p["id"]
                # 1. Product Images
                if is_postgres:
                    cur.execute("SELECT COUNT(*) FROM product_images WHERE product_id = %s", (pid,))
                else:
                    cur.execute("SELECT COUNT(*) FROM product_images WHERE product_id = ?", (pid,))
                count_imgs = cur.fetchone()[0]
                if count_imgs == 0:
                    gallery = get_product_gallery_seed_data(p)
                    for img in gallery:
                        if is_postgres:
                            cur.execute("""
                            INSERT INTO product_images (product_id, image_url, is_primary, display_order)
                            VALUES (%s, %s, %s, %s)
                            """, (pid, img["image_url"], img["is_primary"], img["display_order"]))
                        else:
                            cur.execute("""
                            INSERT INTO product_images (product_id, image_url, is_primary, display_order)
                            VALUES (?, ?, ?, ?)
                            """, (pid, img["image_url"], 1 if img["is_primary"] else 0, img["display_order"]))

                # 2. Product Specifications
                if is_postgres:
                    cur.execute("SELECT COUNT(*) FROM product_specifications WHERE product_id = %s", (pid,))
                else:
                    cur.execute("SELECT COUNT(*) FROM product_specifications WHERE product_id = ?", (pid,))
                count_specs = cur.fetchone()[0]
                if count_specs == 0:
                    specs = get_product_specifications_seed_data(p)
                    for sp in specs:
                        if is_postgres:
                            cur.execute("""
                            INSERT INTO product_specifications (product_id, spec_group, spec_key, spec_value)
                            VALUES (%s, %s, %s, %s)
                            """, (pid, sp["spec_group"], sp["spec_key"], sp["spec_value"]))
                        else:
                            cur.execute("""
                            INSERT INTO product_specifications (product_id, spec_group, spec_key, spec_value)
                            VALUES (?, ?, ?, ?)
                            """, (pid, sp["spec_group"], sp["spec_key"], sp["spec_value"]))

            # 3. Product Reviews
            cur.execute("SELECT COUNT(*) FROM product_reviews")
            rev_count = cur.fetchone()[0]
            if rev_count <= 5:
                for rev in SEED_CUSTOMER_REVIEWS:
                    if is_postgres:
                        cur.execute("""
                        INSERT INTO product_reviews (product_id, customer_id, rating, title, comment, is_verified_purchase)
                        VALUES (%s, %s, %s, %s, %s, TRUE)
                        """, (rev["product_id"], rev["customer_id"], rev["rating"], rev["title"], rev["comment"]))
                    else:
                        cur.execute("""
                        INSERT INTO product_reviews (product_id, customer_id, rating, title, comment, is_verified_purchase)
                        VALUES (?, ?, ?, ?, ?, 1)
                        """, (rev["product_id"], rev["customer_id"], rev["rating"], rev["title"], rev["comment"]))
        except Exception as e:
            logger.warning(f"Note on seeding Phase 2 metadata: {e}")


    # -------------------------------------------------------------------------
    # Catalog Queries
    # -------------------------------------------------------------------------
    def get_all_products(self, category: Optional[str] = None, city: Optional[str] = None) -> List[Dict[str, Any]]:
        cached_raw = app_cache.get("catalog:all_products_raw")
        if cached_raw is not None:
            products = [dict(p) for p in cached_raw]
        else:
            products = []
            if self.is_live_postgres:
                from psycopg2.extras import RealDictCursor
                conn = self._get_pg_connection()
                try:
                    with conn.cursor(cursor_factory=RealDictCursor) as cur:
                        cur.execute("""
                        SELECT p.*, COALESCE(i.stock_quantity, 20) as stock
                        FROM products p
                        LEFT JOIN inventory i ON p.id = i.product_id
                        ORDER BY p.id ASC;
                        """)
                        rows = cur.fetchall()
                    for r in rows:
                        item = dict(r)
                        item["cities"] = self._parse_cities_json(item.get("cities_json"))
                        item["price"] = float(item["price"]) if item.get("price") is not None else 0.0
                        item["original_price"] = float(item["original_price"]) if item.get("original_price") else None
                        item["rating"] = float(item["rating"]) if item.get("rating") else None
                        products.append(item)
                finally:
                    conn.close()
            else:
                conn = self._get_sqlite_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("""
                    SELECT p.*, COALESCE(i.stock_quantity, 20) as stock
                    FROM products p
                    LEFT JOIN inventory i ON p.id = i.product_id
                    ORDER BY p.id ASC;
                    """)
                    rows = cur.fetchall()
                    for r in rows:
                        item = dict(r)
                        item["cities"] = self._parse_cities_json(item.get("cities_json"))
                        products.append(item)
                finally:
                    conn.close()
            app_cache.set("catalog:all_products_raw", products, ttl=120.0)

        if category and category.lower() != "all":
            products = [p for p in products if (p.get("category") or "").lower() == category.lower()]
        if city and city.lower() != "all":
            products = [p for p in products if city in p.get("cities", [])]

        return products

    def get_product_by_id(self, product_id: int) -> Optional[Dict[str, Any]]:
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                    SELECT p.*, COALESCE(i.stock_quantity, 20) as stock
                    FROM products p
                    LEFT JOIN inventory i ON p.id = i.product_id
                    WHERE p.id = %s;
                    """, (product_id,))
                    row = cur.fetchone()
            finally:
                conn.close()
            if not row:
                return None
            item = dict(row)
            item["cities"] = self._parse_cities_json(item.get("cities_json"))
            item["price"] = float(item["price"]) if item.get("price") is not None else 0.0
            item["original_price"] = float(item["original_price"]) if item.get("original_price") else None
            item["images"] = self.get_product_images(product_id, item)
            item["specifications"] = self.get_product_specifications(product_id, item)
            item["review_stats"] = self.get_review_statistics(product_id)
            return item
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                cur.execute("""
                SELECT p.*, COALESCE(i.stock_quantity, 20) as stock
                FROM products p
                LEFT JOIN inventory i ON p.id = i.product_id
                WHERE p.id = ?;
                """, (product_id,))
                row = cur.fetchone()
            finally:
                conn.close()
            if not row:
                return None
            item = dict(row)
            item["cities"] = self._parse_cities_json(item.get("cities_json"))
            item["price"] = float(item["price"]) if item.get("price") is not None else 0.0
            item["original_price"] = float(item["original_price"]) if item.get("original_price") else None
            item["images"] = self.get_product_images(product_id, item)
            item["specifications"] = self.get_product_specifications(product_id, item)
            item["review_stats"] = self.get_review_statistics(product_id)
            return item

    def get_product_images(self, product_id: int, product: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Returns ordered gallery images for a product, falling back to seed generator if not in database"""
        images = []
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                SELECT id, product_id, image_url, is_primary, display_order
                FROM product_images
                WHERE product_id = %s
                ORDER BY display_order ASC, id ASC;
                """, (product_id,))
                images = [dict(r) for r in cur.fetchall()]
            conn.close()
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
            SELECT id, product_id, image_url, is_primary, display_order
            FROM product_images
            WHERE product_id = ?
            ORDER BY display_order ASC, id ASC;
            """, (product_id,))
            images = [dict(r) for r in cur.fetchall()]
            conn.close()

        if images:
            return images

        # Fallback to category angles template
        prod = product or {"id": product_id, "image_url": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=700", "category": "Electronics"}
        return get_product_gallery_seed_data(prod)

    def get_product_specifications(self, product_id: int, product: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Returns structured specifications grouped by category, falling back to seed generator"""
        specs = []
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                SELECT id, product_id, spec_group, spec_key, spec_value
                FROM product_specifications
                WHERE product_id = %s
                ORDER BY id ASC;
                """, (product_id,))
                specs = [dict(r) for r in cur.fetchall()]
            conn.close()
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
            SELECT id, product_id, spec_group, spec_key, spec_value
            FROM product_specifications
            WHERE product_id = ?
            ORDER BY id ASC;
            """, (product_id,))
            specs = [dict(r) for r in cur.fetchall()]
            conn.close()

        if specs:
            return specs

        prod = product or {"id": product_id, "brand": "BharatStore", "title": "Product", "category": "Daily Essentials & Groceries", "sku": f"BK-{product_id}"}
        return get_product_specifications_seed_data(prod)

    def get_related_products(self, product_id: int, category: Optional[str] = None, limit: int = 4) -> List[Dict[str, Any]]:
        """Returns active catalog items from the same category (or top rated), excluding current product"""
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if category:
                    cur.execute("""
                    SELECT p.*, i.stock_quantity as stock
                    FROM products p
                    JOIN inventory i ON p.id = i.product_id
                    WHERE p.id != %s AND p.category = %s
                    ORDER BY p.rating DESC, p.rating_count DESC
                    LIMIT %s;
                    """, (product_id, category, limit))
                    rows = [dict(r) for r in cur.fetchall()]
                else:
                    rows = []
                if len(rows) < limit:
                    exclude_ids = [product_id] + [r["id"] for r in rows]
                    if category == "Daily Essentials & Groceries":
                        cur.execute("""
                        SELECT p.*, i.stock_quantity as stock
                        FROM products p
                        JOIN inventory i ON p.id = i.product_id
                        WHERE p.id NOT IN %s AND p.category = 'Daily Essentials & Groceries'
                        ORDER BY p.rating DESC
                        LIMIT %s;
                        """, (tuple(exclude_ids), limit - len(rows)))
                    else:
                        cur.execute("""
                        SELECT p.*, i.stock_quantity as stock
                        FROM products p
                        JOIN inventory i ON p.id = i.product_id
                        WHERE p.id NOT IN %s
                        ORDER BY p.rating DESC
                        LIMIT %s;
                        """, (tuple(exclude_ids), limit - len(rows)))
                    rows.extend([dict(r) for r in cur.fetchall()])
            conn.close()
            for r in rows:
                r["cities"] = self._parse_cities_json(r.get("cities_json"))
                r["price"] = float(r["price"])
                r["original_price"] = float(r["original_price"]) if r.get("original_price") else None
            return rows
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            rows = []
            if category:
                cur.execute("""
                SELECT p.*, i.stock_quantity as stock
                FROM products p
                JOIN inventory i ON p.id = i.product_id
                WHERE p.id != ? AND p.category = ?
                ORDER BY p.rating DESC, p.rating_count DESC
                LIMIT ?;
                """, (product_id, category, limit))
                rows = [dict(r) for r in cur.fetchall()]
            if len(rows) < limit:
                exclude_ids = [product_id] + [r["id"] for r in rows]
                placeholders = ",".join("?" * len(exclude_ids))
                if category == "Daily Essentials & Groceries":
                    cur.execute(f"""
                    SELECT p.*, i.stock_quantity as stock
                    FROM products p
                    JOIN inventory i ON p.id = i.product_id
                    WHERE p.id NOT IN ({placeholders}) AND p.category = 'Daily Essentials & Groceries'
                    ORDER BY p.rating DESC
                    LIMIT ?;
                    """, (*exclude_ids, limit - len(rows)))
                else:
                    cur.execute(f"""
                    SELECT p.*, i.stock_quantity as stock
                    FROM products p
                    JOIN inventory i ON p.id = i.product_id
                    WHERE p.id NOT IN ({placeholders})
                    ORDER BY p.rating DESC
                    LIMIT ?;
                    """, (*exclude_ids, limit - len(rows)))
                rows.extend([dict(r) for r in cur.fetchall()])
            conn.close()
            for r in rows:
                r["cities"] = self._parse_cities_json(r.get("cities_json"))
                r["price"] = float(r["price"])
                r["original_price"] = float(r["original_price"]) if r.get("original_price") else None
            return rows

    def get_review_statistics(self, product_id: int) -> Dict[str, Any]:
        """Calculates star distribution, percentages, and verified review score"""
        reviews = self.get_product_reviews(product_id)
        total = len(reviews)
        dist = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
        for r in reviews:
            star = max(1, min(5, int(r.get("rating", 5))))
            dist[star] += 1
        percentages = {star: round((count / total * 100) if total > 0 else 0) for star, count in dist.items()}
        avg = round(sum(star * count for star, count in dist.items()) / total, 1) if total > 0 else 4.5
        return {
            "average_rating": avg,
            "total_reviews": total,
            "distribution": dist,
            "percentages": percentages
        }


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

                try:
                    self.record_order_status_transition(order_id, None, order_status, notes="Order placed via checkout", changed_by="CUSTOMER")
                except Exception as e:
                    logger.warning(f"Status history record notice: {e}")

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

                try:
                    self.record_order_status_transition(order_id, None, order_status, notes="Order placed via checkout", changed_by="CUSTOMER")
                except Exception as e:
                    logger.warning(f"Status history record notice: {e}")

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
        self._invalidate_catalog_and_inventory_cache()
        logger.info("Inventory reset to initial seed values.")

    # -------------------------------------------------------------------------
    # Order Status Lifecycle & Compensating Transactions
    # -------------------------------------------------------------------------
    ALLOWED_ORDER_TRANSITIONS = {
        "PENDING": ["CONFIRMED", "CANCELLED"],
        "PENDING_PAYMENT": ["CONFIRMED", "PAID", "PROCESSING", "CANCELLED"],
        "PAID": ["CONFIRMED", "PROCESSING", "CANCELLED"],
        "CONFIRMED": ["PROCESSING", "DISPATCHED", "SHIPPED", "CANCELLED"],
        "PROCESSING": ["DISPATCHED", "SHIPPED", "OUT_FOR_DELIVERY", "CANCELLED"],
        "DISPATCHED": ["OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED"],
        "SHIPPED": ["OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED"],
        "OUT_FOR_DELIVERY": ["DELIVERED", "CANCELLED"],
        "DELIVERED": [],
        "CANCELLED": []
    }

    def _get_suborder_items(self, sub_order_id: int) -> List[Dict[str, Any]]:
        """Fetch line items for a suborder."""
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                SELECT oi.*, p.title as product_title, p.sku, p.image_url
                FROM order_items oi
                JOIN products p ON oi.product_id = p.id
                WHERE oi.order_id = %s;
                """, (sub_order_id,))
                items = []
                for r in cur.fetchall():
                    item = dict(r)
                    item["title"] = item.get("product_title", "")
                    item["unit_price"] = float(item["unit_price"])
                    item["subtotal"] = float(item["subtotal"])
                    items.append(item)
            conn.close()
            return items
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
            SELECT oi.*, p.title as product_title, p.sku, p.image_url
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            WHERE oi.order_id = ?;
            """, (sub_order_id,))
            items = []
            for r in cur.fetchall():
                item = dict(r)
                item["title"] = item.get("product_title", "")
                item["unit_price"] = float(item["unit_price"])
                item["subtotal"] = float(item["subtotal"])
                items.append(item)
            conn.close()
            return items

    def record_order_status_transition(self, order_id: int, from_status: Optional[str], to_status: str, notes: Optional[str] = None, changed_by: str = "SYSTEM") -> Dict[str, Any]:
        """Records an immutable audit trail entry for an order status transition."""
        to_status = str(to_status).upper().strip()
        from_status = str(from_status).upper().strip() if from_status else None
        if self.is_live_postgres:
            conn = self._get_pg_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO order_status_history (order_id, from_status, to_status, notes, changed_by)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, created_at;
                """, (order_id, from_status, to_status, notes, changed_by))
                row = cur.fetchone()
                conn.commit()
                hist_id = row["id"] if isinstance(row, dict) else row[0]
                created_at = str(row["created_at"]) if isinstance(row, dict) else str(row[1])
            conn.close()
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO order_status_history (order_id, from_status, to_status, notes, changed_by)
                VALUES (?, ?, ?, ?, ?);
            """, (order_id, from_status, to_status, notes, changed_by))
            hist_id = cur.lastrowid
            conn.commit()
            cur.execute("SELECT created_at FROM order_status_history WHERE id = ?;", (hist_id,))
            r = cur.fetchone()
            created_at = str(r[0]) if r else datetime.now().isoformat()
            conn.close()
        return {
            "id": hist_id,
            "order_id": order_id,
            "from_status": from_status,
            "to_status": to_status,
            "notes": notes,
            "changed_by": changed_by,
            "created_at": created_at
        }

    def get_order_status_history(self, order_id: int) -> List[Dict[str, Any]]:
        """Retrieves chronological lifecycle transition history for an order."""
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, order_id, from_status, to_status, notes, changed_by, created_at
                    FROM order_status_history
                    WHERE order_id = %s
                    ORDER BY id ASC;
                """, (order_id,))
                rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT id, order_id, from_status, to_status, notes, changed_by, created_at
                FROM order_status_history
                WHERE order_id = ?
                ORDER BY id ASC;
            """, (order_id,))
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            conn.close()
            return rows

    def _build_order_timeline(self, order: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Constructs an authoritative visual order progress timeline based on database audit records."""
        status = (order.get("status") or "PENDING").upper().strip()
        history = order.get("status_history") or []
        created_at = str(order.get("created_at") or "")

        hist_map = {}
        for h in history:
            to_s = h.get("to_status", "").upper()
            if to_s not in hist_map:
                hist_map[to_s] = h

        is_cancelled = (status == "CANCELLED")

        stages_def = [
            ("CONFIRMED", "Order Confirmed", "fa-check", "Order placed and inventory reserved"),
            ("PROCESSING", "Processing", "fa-box", "Items packed and prepared for pickup / dispatch"),
            ("DISPATCHED", "Dispatched", "fa-truck", "Order handed over for local delivery"),
            ("DELIVERED", "Delivered", "fa-house-circle-check", "Order delivered to destination")
        ]

        order_ranks = {
            "PENDING": 0,
            "PENDING_PAYMENT": 0,
            "PAID": 1,
            "CONFIRMED": 1,
            "PROCESSING": 2,
            "SHIPPED": 3,
            "DISPATCHED": 3,
            "OUT_FOR_DELIVERY": 3,
            "DELIVERED": 4,
            "CANCELLED": -1
        }
        current_rank = order_ranks.get(status, 1)

        timeline = []
        for stage_key, label, icon, desc in stages_def:
            stage_rank = order_ranks.get(stage_key, 0)
            h_entry = hist_map.get(stage_key)
            if not h_entry and stage_key == "DISPATCHED":
                h_entry = hist_map.get("SHIPPED") or hist_map.get("OUT_FOR_DELIVERY")

            if is_cancelled:
                completed = False
                is_curr = False
                ts = h_entry.get("created_at") if h_entry else None
            else:
                completed = (current_rank >= stage_rank)
                is_curr = (current_rank == stage_rank)
                ts = h_entry.get("created_at") if h_entry else (created_at if stage_key == "CONFIRMED" and completed else None)

            timeline.append({
                "stage": stage_key,
                "label": label,
                "icon": icon,
                "description": desc,
                "completed": completed,
                "current": is_curr,
                "timestamp": ts,
                "notes": h_entry.get("notes") if h_entry else None
            })

        if is_cancelled:
            cancel_entry = hist_map.get("CANCELLED")
            timeline.append({
                "stage": "CANCELLED",
                "label": "Cancelled",
                "icon": "fa-ban",
                "description": cancel_entry.get("notes") if cancel_entry else "Order cancelled and inventory restored",
                "completed": True,
                "current": True,
                "timestamp": cancel_entry.get("created_at") if cancel_entry else None,
                "notes": cancel_entry.get("notes") if cancel_entry else None
            })

        return timeline

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

                cur.execute("SELECT * FROM orders WHERE parent_order_id = %s ORDER BY id ASC;", (order_id,))
                sub_rows = cur.fetchall()
                if sub_rows:
                    order["suborders"] = [dict(s) for s in sub_rows]
                    statuses = set(s["status"] for s in sub_rows)
                    if len(statuses) == 1:
                        order["status"] = list(statuses)[0]
                    elif "PROCESSING" in statuses or "SHIPPED" in statuses:
                        order["status"] = "PROCESSING"
            conn.close()
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

            cur.execute("SELECT * FROM orders WHERE parent_order_id = ? ORDER BY id ASC;", (order_id,))
            cols = [c[0] for c in cur.description]
            sub_rows = cur.fetchall()
            if sub_rows:
                order["suborders"] = [dict(zip(cols, s)) for s in sub_rows]
                statuses = set(s["status"] for s in order["suborders"])
                if len(statuses) == 1:
                    order["status"] = list(statuses)[0]
                elif "PROCESSING" in statuses or "SHIPPED" in statuses:
                    order["status"] = "PROCESSING"
            conn.close()

        # Enrich order with store details, suborder items, audit history, and timeline
        if order.get("store_id"):
            try:
                st = self.get_store_by_id(order["store_id"])
                if st:
                    order["store_name"] = st.get("store_name", "")
                    order["store_area"] = st.get("area", "")
                    order["store_address"] = st.get("full_address", "")
            except Exception:
                pass

        if order.get("suborders"):
            for sub in order["suborders"]:
                if sub.get("store_id"):
                    try:
                        st = self.get_store_by_id(sub["store_id"])
                        if st:
                            sub["store_name"] = st.get("store_name", "")
                            sub["store_area"] = st.get("area", "")
                    except Exception:
                        pass
                try:
                    sub["items"] = self._get_suborder_items(sub["id"])
                except Exception:
                    sub["items"] = []

        try:
            order["status_history"] = self.get_order_status_history(order_id)
            order["timeline"] = self._build_order_timeline(order)
        except Exception as e:
            logger.warning(f"Order timeline build note: {e}")
            order["status_history"] = []
            order["timeline"] = []

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

    def get_orders_for_customer(self, customer_id: Optional[int] = None, session_id: Optional[str] = None, status_filter: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Retrieves consolidated customer orders (standalone and parent orders) with store names,
        suborders, items summary, and optional status filtering.
        """
        where_clauses = ["o.parent_order_id IS NULL"]
        params = []

        if customer_id:
            where_clauses.append("o.customer_id = %s" if self.is_live_postgres else "o.customer_id = ?")
            params.append(customer_id)

        if status_filter and status_filter.upper() != "ALL":
            s_filt = status_filter.upper().strip()
            if s_filt in ("DISPATCHED", "SHIPPED"):
                where_clauses.append("o.status IN ('DISPATCHED', 'SHIPPED', 'OUT_FOR_DELIVERY')")
            elif s_filt in ("PENDING", "PENDING_PAYMENT"):
                where_clauses.append("o.status IN ('PENDING', 'PENDING_PAYMENT')")
            else:
                where_clauses.append("o.status = %s" if self.is_live_postgres else "o.status = ?")
                params.append(s_filt)

        where_sql = " AND ".join(where_clauses)
        limit_param = "%s" if self.is_live_postgres else "?"
        params.append(limit)

        query = f"""
            SELECT o.*, c.name as customer_name, c.email as customer_email
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.id
            WHERE {where_sql}
            ORDER BY o.id DESC
            LIMIT {limit_param};
        """

        orders = []
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, tuple(params))
                raw_orders = [dict(r) for r in cur.fetchall()]
            conn.close()
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute(query, tuple(params))
            cols = [c[0] for c in cur.description]
            raw_orders = [dict(zip(cols, r)) for r in cur.fetchall()]
            conn.close()

        for o in raw_orders:
            o["order_id"] = o["id"]
            o["total_amount"] = float(o["total_amount"])
            try:
                full_order = self.get_order_by_id(o["id"])
                if full_order:
                    o["items"] = full_order.get("items", [])
                    o["suborders"] = full_order.get("suborders", [])
                    o["store_name"] = full_order.get("store_name")
                    o["timeline"] = full_order.get("timeline", [])
                    o["status_history"] = full_order.get("status_history", [])
            except Exception:
                o["items"] = []
                o["suborders"] = []
            orders.append(o)

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
        try:
            self.record_order_status_transition(order_id, from_status=order.get("status"), to_status="CANCELLED", notes=reason, changed_by="CUSTOMER")
        except Exception as e:
            logger.warning(f"Status history record notice on cancel: {e}")
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
        cached = app_cache.get("hubs:all")
        if cached is not None:
            return cached
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM store_hubs WHERE is_active = TRUE ORDER BY id ASC;")
                rows = [dict(r) for r in cur.fetchall()]
            conn.close()
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM store_hubs WHERE is_active = 1 ORDER BY id ASC;")
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
        app_cache.set("hubs:all", rows, ttl=300.0)
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

    def get_customer_product_review(self, product_id: int, customer_id: int) -> Optional[Dict[str, Any]]:
        """Returns customer review for product if exists"""
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM product_reviews WHERE product_id = %s AND customer_id = %s;", (product_id, customer_id))
                row = cur.fetchone()
            conn.close()
            return dict(row) if row else None
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM product_reviews WHERE product_id = ? AND customer_id = ?;", (product_id, customer_id))
            row = cur.fetchone()
            conn.close()
            return dict(row) if row else None

    def add_product_review(
        self,
        product_id: int,
        customer_id: Optional[int],
        rating: int,
        title: str,
        comment: str,
        check_duplicate: bool = False
    ) -> Dict[str, Any]:
        """Creates a verified product review and updates overall product rating"""
        if rating < 1 or rating > 5:
            raise ValueError(f"Rating must be between 1 and 5 stars, got {rating}")
        if not title or not title.strip():
            raise ValueError("Review title cannot be empty")
        if not comment or not comment.strip():
            raise ValueError("Review comment cannot be empty")

        if check_duplicate and customer_id:
            if self.get_customer_product_review(product_id, customer_id):
                raise ValueError("Customer has already submitted a verified review for this product.")

        avg_rating = float(rating)
        total_count = 1

        if self.is_live_postgres:
            conn = self._get_pg_connection()
            with conn.cursor() as cur:
                cur.execute("""
                INSERT INTO product_reviews (product_id, customer_id, rating, title, comment, is_verified_purchase)
                VALUES (%s, %s, %s, %s, %s, TRUE)
                RETURNING id, created_at;
                """, (product_id, customer_id, rating, title.strip(), comment.strip()))
                row = cur.fetchone()
                review_id = row[0]

                # Recalculate average rating & review count
                cur.execute("SELECT AVG(rating), COUNT(*) FROM product_reviews WHERE product_id = %s", (product_id,))
                stats_row = cur.fetchone()
                if stats_row and stats_row[0] is not None:
                    avg_rating = round(float(stats_row[0]), 1)
                    total_count = int(stats_row[1])
                    cur.execute("UPDATE products SET rating = %s, rating_count = %s WHERE id = %s", (avg_rating, total_count, product_id))

            conn.commit()
            conn.close()
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
            INSERT INTO product_reviews (product_id, customer_id, rating, title, comment, is_verified_purchase)
            VALUES (?, ?, ?, ?, ?, 1);
            """, (product_id, customer_id, rating, title.strip(), comment.strip()))
            review_id = cur.lastrowid

            # Recalculate average rating & review count
            cur.execute("SELECT AVG(rating), COUNT(*) FROM product_reviews WHERE product_id = ?", (product_id,))
            stats_row = cur.fetchone()
            if stats_row and stats_row[0] is not None:
                avg_rating = round(float(stats_row[0]), 1)
                total_count = int(stats_row[1])
                cur.execute("UPDATE products SET rating = ?, rating_count = ? WHERE id = ?", (avg_rating, total_count, product_id))

            conn.commit()
            conn.close()

        return {
            "success": True,
            "review_id": review_id,
            "product_id": product_id,
            "rating": rating,
            "title": title.strip(),
            "comment": comment.strip(),
            "updated_product_rating": avg_rating,
            "updated_rating_count": total_count
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

    def update_order_status(self, order_id: int, new_status: str, notes: Optional[str] = None, changed_by: str = "ADMIN") -> Optional[Dict[str, Any]]:
        """
        Transitions order status following valid lifecycle rules:
        Pending -> Confirmed -> Processing -> Dispatched -> Out for Delivery -> Delivered (or Cancelled)
        Records transition in order_status_history and cascades to parent/child orders.
        """
        new_status = new_status.upper().strip()
        order = self.get_order_by_id(order_id)
        if not order:
            return None

        current_status = order["status"].upper().strip()
        if current_status == new_status:
            return order

        # Terminal state protection
        if current_status in ("DELIVERED", "CANCELLED"):
            raise ValueError(f"Cannot transition order #{order_id} from terminal status '{current_status}' to '{new_status}'.")

        allowed = self.ALLOWED_ORDER_TRANSITIONS.get(current_status, [])
        if new_status not in allowed:
            raise ValueError(f"Invalid status transition from '{current_status}' to '{new_status}'. Allowed transitions: {allowed}")

        if self.is_live_postgres:
            conn = self._get_pg_connection()
            with conn.cursor() as cur:
                cur.execute("UPDATE orders SET status = %s WHERE id = %s;", (new_status, order_id))
                # If parent order, cascade to child suborders that are not terminal
                cur.execute("UPDATE orders SET status = %s WHERE parent_order_id = %s AND status NOT IN ('DELIVERED', 'CANCELLED');", (new_status, order_id))
                conn.commit()
            conn.close()
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("UPDATE orders SET status = ? WHERE id = ?;", (new_status, order_id))
            cur.execute("UPDATE orders SET status = ? WHERE parent_order_id = ? AND status NOT IN ('DELIVERED', 'CANCELLED');", (new_status, order_id))
            conn.commit()
            conn.close()

        # Record audit trail
        try:
            self.record_order_status_transition(order_id, from_status=current_status, to_status=new_status, notes=notes, changed_by=changed_by)
        except Exception as e:
            logger.warning(f"Failed to record status transition for order #{order_id}: {e}")

        # If suborder, check if sibling suborders are all completed to synchronize parent
        if order.get("parent_order_id"):
            parent_id = order["parent_order_id"]
            parent = self.get_order_by_id(parent_id)
            if parent and parent.get("suborders"):
                sub_statuses = set(s["status"] for s in parent["suborders"])
                if len(sub_statuses) == 1 and list(sub_statuses)[0] in ("DELIVERED", "CANCELLED"):
                    target_p_status = list(sub_statuses)[0]
                    if parent["status"] != target_p_status:
                        self.update_order_status(parent_id, target_p_status, notes=f"Cascaded from suborders reaching {target_p_status}", changed_by="SYSTEM")

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

    # =========================================================================
    # Phase 3: Location & Customer Saved Address Management
    # =========================================================================

    @staticmethod
    def validate_pincode(pincode: Any) -> bool:
        """Validates Indian 6-digit postal PIN code (e.g. 400050, cannot start with 0)."""
        if not pincode or not isinstance(pincode, (str, int)):
            return False
        return bool(re.match(r"^[1-9][0-9]{5}$", str(pincode).strip()))

    @staticmethod
    def validate_phone(phone: Any) -> bool:
        """Validates Indian 10-digit mobile number with optional +91 prefix."""
        if not phone or not isinstance(phone, str):
            return False
        clean = re.sub(r"[\s\-\(\)]", "", phone.strip())
        return bool(re.match(r"^(\+91)?[6-9]\d{9}$", clean))

    @staticmethod
    def validate_coordinates(lat: Any, lng: Any) -> bool:
        """Validates geographic latitude (-90 to 90) and longitude (-180 to 180)."""
        try:
            lat_f = float(lat)
            lng_f = float(lng)
            return -90.0 <= lat_f <= 90.0 and -180.0 <= lng_f <= 180.0
        except (ValueError, TypeError):
            return False

    def get_customer_addresses(self, customer_id: int) -> List[Dict[str, Any]]:
        """
        Retrieves all saved delivery addresses for a customer,
        ordered by default address first, then most recently added.
        """
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, customer_id, address_type, full_name, phone,
                           address_line1, address_line2, landmark, city, state, pincode,
                           latitude, longitude, is_default, created_at
                    FROM addresses
                    WHERE customer_id = %s
                    ORDER BY is_default DESC, id DESC;
                """, (customer_id,))
                rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT id, customer_id, address_type, full_name, phone,
                       address_line1, address_line2, landmark, city, state, pincode,
                       latitude, longitude, is_default, created_at
                FROM addresses
                WHERE customer_id = ?
                ORDER BY is_default DESC, id DESC;
            """, (customer_id,))
            rows = []
            for r in cur.fetchall():
                d = dict(r)
                d["is_default"] = bool(d.get("is_default"))
                rows.append(d)
            conn.close()
            return rows

    def add_customer_address(self, customer_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Creates a new delivery address for a customer with strict server-side validation.
        Guarantees that each customer has only one default address.
        """
        full_name = str(data.get("full_name") or "").strip()
        phone = str(data.get("phone") or "").strip()
        address_line1 = str(data.get("address_line1") or "").strip()
        address_line2 = str(data.get("address_line2") or "").strip() or None
        landmark = str(data.get("landmark") or "").strip() or None
        city = str(data.get("city") or "").strip()
        state = str(data.get("state") or "").strip() or "India"
        pincode = str(data.get("pincode") or "").strip()
        address_type = str(data.get("address_type") or "HOME").strip().upper()

        if not full_name:
            raise ValueError("Full name is required for delivery address.")
        if not phone or not self.validate_phone(phone):
            raise ValueError("Invalid phone number. Must be a valid 10-digit Indian mobile number (e.g. +91 98201 12345).")
        if not address_line1:
            raise ValueError("Street address / apartment line is required.")
        if not city:
            raise ValueError("City is required.")
        if not pincode or not self.validate_pincode(pincode):
            raise ValueError("Invalid Indian postal PIN code. Must be exactly 6 digits (e.g. 400030).")
        if address_type not in {"HOME", "WORK", "OTHER"}:
            address_type = "HOME"

        lat = data.get("latitude")
        lng = data.get("longitude")
        if lat is not None and lng is not None and str(lat).strip() != "" and str(lng).strip() != "":
            if not self.validate_coordinates(lat, lng):
                raise ValueError("Coordinates out of range (-90 to 90 lat, -180 to 180 lng).")
            lat_f = float(lat)
            lng_f = float(lng)
        else:
            lat_f = None
            lng_f = None

        existing = self.get_customer_addresses(customer_id)
        if len(existing) >= 5:
            raise ValueError("Maximum limit of 5 saved addresses reached. Please delete an address to add a new one.")

        norm_line1 = address_line1.strip().lower()
        norm_city = city.strip().lower()
        norm_pin = pincode.strip()
        for addr in existing:
            if (str(addr.get("address_line1") or "").strip().lower() == norm_line1 and
                str(addr.get("city") or "").strip().lower() == norm_city and
                str(addr.get("pincode") or "").strip() == norm_pin):
                raise ValueError("This delivery address is already saved. Duplicate addresses are not allowed.")

        is_default = bool(data.get("is_default")) or len(existing) == 0

        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if is_default:
                    cur.execute("UPDATE addresses SET is_default = FALSE WHERE customer_id = %s;", (customer_id,))
                cur.execute("""
                    INSERT INTO addresses (customer_id, address_type, full_name, phone, address_line1, address_line2, landmark, city, state, pincode, latitude, longitude, is_default)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *;
                """, (customer_id, address_type, full_name, phone, address_line1, address_line2, landmark, city, state, pincode, lat_f, lng_f, is_default))
                new_addr = dict(cur.fetchone())
                conn.commit()
            conn.close()
            return new_addr
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            if is_default:
                cur.execute("UPDATE addresses SET is_default = 0 WHERE customer_id = ?;", (customer_id,))
            cur.execute("""
                INSERT INTO addresses (customer_id, address_type, full_name, phone, address_line1, address_line2, landmark, city, state, pincode, latitude, longitude, is_default)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (customer_id, address_type, full_name, phone, address_line1, address_line2, landmark, city, state, pincode, lat_f, lng_f, 1 if is_default else 0))
            new_id = cur.lastrowid
            conn.commit()
            cur.execute("SELECT * FROM addresses WHERE id = ?;", (new_id,))
            row = dict(cur.fetchone())
            row["is_default"] = bool(row.get("is_default"))
            conn.close()
            return row

    def update_customer_address(self, address_id: int, customer_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Updates an existing address belonging to the specified customer.
        Returns None if address does not exist or customer is not the owner.
        """
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM addresses WHERE id = %s AND customer_id = %s;", (address_id, customer_id))
                row = cur.fetchone()
                if not row:
                    conn.close()
                    return None
                existing = dict(row)
            conn.close()
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM addresses WHERE id = ? AND customer_id = ?;", (address_id, customer_id))
            row = cur.fetchone()
            conn.close()
            if not row:
                return None
            existing = dict(row)

        # Validate updating fields
        full_name = str(data.get("full_name") if "full_name" in data else existing["full_name"]).strip()
        phone = str(data.get("phone") if "phone" in data else existing["phone"]).strip()
        address_line1 = str(data.get("address_line1") if "address_line1" in data else existing["address_line1"]).strip()
        address_line2 = data.get("address_line2") if "address_line2" in data else existing.get("address_line2")
        landmark = data.get("landmark") if "landmark" in data else existing.get("landmark")
        city = str(data.get("city") if "city" in data else existing["city"]).strip()
        state = str(data.get("state") if "state" in data else existing["state"]).strip()
        pincode = str(data.get("pincode") if "pincode" in data else existing["pincode"]).strip()
        address_type = str(data.get("address_type") if "address_type" in data else existing["address_type"]).strip().upper()

        if not full_name:
            raise ValueError("Full name cannot be empty.")
        if not self.validate_phone(phone):
            raise ValueError("Invalid phone number format.")
        if not address_line1:
            raise ValueError("Street address cannot be empty.")
        if not city:
            raise ValueError("City cannot be empty.")
        if not self.validate_pincode(pincode):
            raise ValueError("Invalid Indian postal PIN code format.")
        if address_type not in {"HOME", "WORK", "OTHER"}:
            address_type = "HOME"

        # Check for duplicate with other saved addresses of this customer
        existing_all = self.get_customer_addresses(customer_id)
        norm_line1 = address_line1.strip().lower()
        norm_city = city.strip().lower()
        norm_pin = pincode.strip()
        for addr in existing_all:
            if addr["id"] != address_id and (
                str(addr.get("address_line1") or "").strip().lower() == norm_line1 and
                str(addr.get("city") or "").strip().lower() == norm_city and
                str(addr.get("pincode") or "").strip() == norm_pin
            ):
                raise ValueError("Another saved address already has this street address, city, and PIN code. Duplicate addresses are not allowed.")

        lat = data.get("latitude") if "latitude" in data else existing.get("latitude")
        lng = data.get("longitude") if "longitude" in data else existing.get("longitude")
        if lat is not None and lng is not None and str(lat).strip() != "" and str(lng).strip() != "":
            if not self.validate_coordinates(lat, lng):
                raise ValueError("Coordinates out of range (-90 to 90 lat, -180 to 180 lng).")
            lat_f = float(lat)
            lng_f = float(lng)
        else:
            lat_f = None
            lng_f = None

        is_default = bool(data.get("is_default")) if "is_default" in data else bool(existing["is_default"])

        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if is_default:
                    cur.execute("UPDATE addresses SET is_default = FALSE WHERE customer_id = %s;", (customer_id,))
                cur.execute("""
                    UPDATE addresses
                    SET address_type = %s, full_name = %s, phone = %s, address_line1 = %s,
                        address_line2 = %s, landmark = %s, city = %s, state = %s,
                        pincode = %s, latitude = %s, longitude = %s, is_default = %s
                    WHERE id = %s AND customer_id = %s
                    RETURNING *;
                """, (address_type, full_name, phone, address_line1, address_line2, landmark, city, state, pincode, lat_f, lng_f, is_default, address_id, customer_id))
                updated = dict(cur.fetchone())
                conn.commit()
            conn.close()
            return updated
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            if is_default:
                cur.execute("UPDATE addresses SET is_default = 0 WHERE customer_id = ?;", (customer_id,))
            cur.execute("""
                UPDATE addresses
                SET address_type = ?, full_name = ?, phone = ?, address_line1 = ?,
                    address_line2 = ?, landmark = ?, city = ?, state = ?,
                    pincode = ?, latitude = ?, longitude = ?, is_default = ?
                WHERE id = ? AND customer_id = ?;
            """, (address_type, full_name, phone, address_line1, address_line2, landmark, city, state, pincode, lat_f, lng_f, 1 if is_default else 0, address_id, customer_id))
            conn.commit()
            cur.execute("SELECT * FROM addresses WHERE id = ?;", (address_id,))
            row = dict(cur.fetchone())
            row["is_default"] = bool(row.get("is_default"))
            conn.close()
            return row

    def delete_customer_address(self, address_id: int, customer_id: int) -> bool:
        """
        Deletes an address owned by customer.
        If the deleted address was default, promotes the most recent remaining address to default.
        """
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, is_default FROM addresses WHERE id = %s AND customer_id = %s;", (address_id, customer_id))
                row = cur.fetchone()
                if not row:
                    conn.close()
                    return False
                was_default = row["is_default"]
                cur.execute("DELETE FROM addresses WHERE id = %s AND customer_id = %s;", (address_id, customer_id))
                if was_default:
                    cur.execute("""
                        SELECT id FROM addresses WHERE customer_id = %s ORDER BY id DESC LIMIT 1;
                    """, (customer_id,))
                    rem = cur.fetchone()
                    if rem:
                        cur.execute("UPDATE addresses SET is_default = TRUE WHERE id = %s;", (rem["id"],))
                conn.commit()
            conn.close()
            return True
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("SELECT id, is_default FROM addresses WHERE id = ? AND customer_id = ?;", (address_id, customer_id))
            row = cur.fetchone()
            if not row:
                conn.close()
                return False
            was_default = bool(row["is_default"])
            cur.execute("DELETE FROM addresses WHERE id = ? AND customer_id = ?;", (address_id, customer_id))
            if was_default:
                cur.execute("SELECT id FROM addresses WHERE customer_id = ? ORDER BY id DESC LIMIT 1;", (customer_id,))
                rem = cur.fetchone()
                if rem:
                    cur.execute("UPDATE addresses SET is_default = 1 WHERE id = ?;", (rem["id"],))
            conn.commit()
            conn.close()
            return True

    def set_default_customer_address(self, address_id: int, customer_id: int) -> bool:
        """
        Atomically marks a specified address as the customer's sole default address.
        Returns False if address does not exist or is not owned by customer.
        """
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id FROM addresses WHERE id = %s AND customer_id = %s;", (address_id, customer_id))
                if not cur.fetchone():
                    conn.close()
                    return False
                cur.execute("UPDATE addresses SET is_default = FALSE WHERE customer_id = %s;", (customer_id,))
                cur.execute("UPDATE addresses SET is_default = TRUE WHERE id = %s AND customer_id = %s;", (address_id, customer_id))
                conn.commit()
            conn.close()
            return True
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("SELECT id FROM addresses WHERE id = ? AND customer_id = ?;", (address_id, customer_id))
            if not cur.fetchone():
                conn.close()
                return False
            cur.execute("UPDATE addresses SET is_default = 0 WHERE customer_id = ?;", (customer_id,))
            cur.execute("UPDATE addresses SET is_default = 1 WHERE id = ? AND customer_id = ?;", (address_id, customer_id))
            conn.commit()
            conn.close()
            return True

    # -------------------------------------------------------------------------
    # Phase 4: Physical Stores Management
    # -------------------------------------------------------------------------

    def create_store(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Creates a new physical retail store with strict input validation.
        """
        store_name = str(data.get("store_name") or "").strip()
        store_slug = str(data.get("store_slug") or "").strip().lower()
        store_description = str(data.get("store_description") or "").strip() or None
        store_logo = str(data.get("store_logo") or "").strip() or None
        store_banner = str(data.get("store_banner") or "").strip() or None
        owner_name = str(data.get("owner_name") or "").strip() or None
        contact_phone = str(data.get("contact_phone") or "").strip() or None
        email = str(data.get("email") or "").strip() or None
        full_address = str(data.get("full_address") or "").strip()
        city = str(data.get("city") or "").strip()
        area = str(data.get("area") or "").strip()
        pincode = str(data.get("pincode") or "").strip()
        opening_time = str(data.get("opening_time") or "07:00 AM").strip()
        closing_time = str(data.get("closing_time") or "11:00 PM").strip()
        is_active = bool(data.get("is_active", True))
        accepts_delivery = bool(data.get("accepts_delivery", True))
        accepts_pickup = bool(data.get("accepts_pickup", True))

        if not store_name:
            raise ValueError("Store name cannot be empty.")
        if not store_slug:
            store_slug = re.sub(r"[^a-z0-9]+", "-", store_name.lower()).strip("-")
        if not full_address:
            raise ValueError("Full address is required.")
        if not city:
            raise ValueError("City is required.")
        if not area:
            raise ValueError("Area / neighbourhood is required.")
        if not pincode or not self.validate_pincode(pincode):
            raise ValueError("Invalid Indian postal PIN code.")
        if contact_phone and not self.validate_phone(contact_phone):
            raise ValueError("Invalid phone number format.")

        lat = data.get("latitude")
        lng = data.get("longitude")
        if lat is not None and lng is not None and str(lat).strip() != "" and str(lng).strip() != "":
            if not self.validate_coordinates(lat, lng):
                raise ValueError("Coordinates out of range (-90 to 90 lat, -180 to 180 lng).")
            lat_f = float(lat)
            lng_f = float(lng)
        else:
            lat_f = None
            lng_f = None

        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO stores (store_name, store_slug, store_description, store_logo, store_banner, owner_name, contact_phone, email, full_address, city, area, pincode, latitude, longitude, opening_time, closing_time, is_active, accepts_delivery, accepts_pickup)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *;
                """, (store_name, store_slug, store_description, store_logo, store_banner, owner_name, contact_phone, email, full_address, city, area, pincode, lat_f, lng_f, opening_time, closing_time, is_active, accepts_delivery, accepts_pickup))
                created = dict(cur.fetchone())
                conn.commit()
            conn.close()
            return created
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO stores (store_name, store_slug, store_description, store_logo, store_banner, owner_name, contact_phone, email, full_address, city, area, pincode, latitude, longitude, opening_time, closing_time, is_active, accepts_delivery, accepts_pickup)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (store_name, store_slug, store_description, store_logo, store_banner, owner_name, contact_phone, email, full_address, city, area, pincode, lat_f, lng_f, opening_time, closing_time, 1 if is_active else 0, 1 if accepts_delivery else 0, 1 if accepts_pickup else 0))
            new_id = cur.lastrowid
            conn.commit()
            cur.execute("SELECT * FROM stores WHERE id = ?;", (new_id,))
            row = dict(cur.fetchone())
            row["is_active"] = bool(row.get("is_active"))
            row["accepts_delivery"] = bool(row.get("accepts_delivery"))
            row["accepts_pickup"] = bool(row.get("accepts_pickup"))
            conn.close()
            return row

    def get_store_by_id(self, store_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves a store by ID."""
        if not isinstance(store_id, (int, str)) or str(store_id).strip() == "":
            return None
        try:
            s_id = int(store_id)
        except (ValueError, TypeError):
            return None

        cache_key = f"store_by_id:{s_id}"
        cached = app_cache.get(cache_key)
        if cached is not None:
            return cached

        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT * FROM stores WHERE id = %s;", (s_id,))
                    row = cur.fetchone()
            finally:
                conn.close()
            if not row:
                return None
            d = dict(row)
            d["is_active"] = bool(d.get("is_active"))
            d["accepts_delivery"] = bool(d.get("accepts_delivery"))
            d["accepts_pickup"] = bool(d.get("accepts_pickup"))
            app_cache.set(cache_key, d, ttl=300.0)
            return d
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM stores WHERE id = ?;", (s_id,))
                row = cur.fetchone()
            finally:
                conn.close()
            if not row:
                return None
            d = dict(row)
            d["is_active"] = bool(d.get("is_active"))
            d["accepts_delivery"] = bool(d.get("accepts_delivery"))
            d["accepts_pickup"] = bool(d.get("accepts_pickup"))
            app_cache.set(cache_key, d, ttl=300.0)
            return d

    def get_store_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """Retrieves a store by unique slug with backward-compatibility alias resolution."""
        if not slug or not isinstance(slug, str):
            return None
        slug_clean = slug.strip().lower()

        alias_map = {
            "bharatstore-bengaluru-tech-store": 1,
            "fresh-mart-bengaluru": 2
        }

        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT * FROM stores WHERE store_slug = %s;", (slug_clean,))
                    row = cur.fetchone()
                    if not row and slug_clean in alias_map:
                        cur.execute("SELECT * FROM stores WHERE id = %s;", (alias_map[slug_clean],))
                        row = cur.fetchone()
            finally:
                conn.close()
            if not row:
                return None
            d = dict(row)
            d["is_active"] = bool(d.get("is_active"))
            d["accepts_delivery"] = bool(d.get("accepts_delivery"))
            d["accepts_pickup"] = bool(d.get("accepts_pickup"))
            return d
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM stores WHERE store_slug = ?;", (slug_clean,))
                row = cur.fetchone()
                if not row and slug_clean in alias_map:
                    cur.execute("SELECT * FROM stores WHERE id = ?;", (alias_map[slug_clean],))
                    row = cur.fetchone()
            finally:
                conn.close()
            if not row:
                return None
            d = dict(row)
            d["is_active"] = bool(d.get("is_active"))
            d["accepts_delivery"] = bool(d.get("accepts_delivery"))
            d["accepts_pickup"] = bool(d.get("accepts_pickup"))
            return d

    def get_all_stores(self, active_only: bool = True, city: Optional[str] = None, area: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves physical stores with optional city/area/active filtering."""
        where_clauses = []
        params = []
        if active_only:
            where_clauses.append("is_active = TRUE" if self.is_live_postgres else "is_active = 1")
        if city:
            where_clauses.append("LOWER(city) = LOWER(%s)" if self.is_live_postgres else "LOWER(city) = LOWER(?)")
            params.append(city.strip())
        if area:
            where_clauses.append("LOWER(area) = LOWER(%s)" if self.is_live_postgres else "LOWER(area) = LOWER(?)")
            params.append(area.strip())

        where_str = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        sql = f"SELECT * FROM stores{where_str} ORDER BY id ASC;"

        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, tuple(params))
                    rows = [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()
            for d in rows:
                d["is_active"] = bool(d.get("is_active"))
                d["accepts_delivery"] = bool(d.get("accepts_delivery"))
                d["accepts_pickup"] = bool(d.get("accepts_pickup"))
            return rows
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                cur.execute(sql, tuple(params))
                rows = []
                for r in cur.fetchall():
                    d = dict(r)
                    d["is_active"] = bool(d.get("is_active"))
                    d["accepts_delivery"] = bool(d.get("accepts_delivery"))
                    d["accepts_pickup"] = bool(d.get("accepts_pickup"))
                    rows.append(d)
            finally:
                conn.close()
            return rows

    def update_store(self, store_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Updates physical store details."""
        existing = self.get_store_by_id(store_id)
        if not existing:
            return None

        store_name = str(data.get("store_name") if "store_name" in data else existing["store_name"]).strip()
        store_slug = str(data.get("store_slug") if "store_slug" in data else existing["store_slug"]).strip().lower()
        store_description = data.get("store_description") if "store_description" in data else existing.get("store_description")
        store_logo = data.get("store_logo") if "store_logo" in data else existing.get("store_logo")
        store_banner = data.get("store_banner") if "store_banner" in data else existing.get("store_banner")
        owner_name = data.get("owner_name") if "owner_name" in data else existing.get("owner_name")
        contact_phone = data.get("contact_phone") if "contact_phone" in data else existing.get("contact_phone")
        email = data.get("email") if "email" in data else existing.get("email")
        full_address = str(data.get("full_address") if "full_address" in data else existing["full_address"]).strip()
        city = str(data.get("city") if "city" in data else existing["city"]).strip()
        area = str(data.get("area") if "area" in data else existing["area"]).strip()
        pincode = str(data.get("pincode") if "pincode" in data else existing["pincode"]).strip()
        opening_time = str(data.get("opening_time") if "opening_time" in data else existing.get("opening_time", "07:00 AM")).strip()
        closing_time = str(data.get("closing_time") if "closing_time" in data else existing.get("closing_time", "11:00 PM")).strip()
        is_active = bool(data.get("is_active") if "is_active" in data else existing["is_active"])
        accepts_delivery = bool(data.get("accepts_delivery") if "accepts_delivery" in data else existing["accepts_delivery"])
        accepts_pickup = bool(data.get("accepts_pickup") if "accepts_pickup" in data else existing["accepts_pickup"])

        if not store_name:
            raise ValueError("Store name cannot be empty.")
        if not full_address:
            raise ValueError("Full address is required.")
        if not city:
            raise ValueError("City is required.")
        if not pincode or not self.validate_pincode(pincode):
            raise ValueError("Invalid Indian postal PIN code.")
        if contact_phone and not self.validate_phone(str(contact_phone)):
            raise ValueError("Invalid phone number format.")

        lat = data.get("latitude") if "latitude" in data else existing.get("latitude")
        lng = data.get("longitude") if "longitude" in data else existing.get("longitude")
        if lat is not None and lng is not None and str(lat).strip() != "" and str(lng).strip() != "":
            if not self.validate_coordinates(lat, lng):
                raise ValueError("Coordinates out of range (-90 to 90 lat, -180 to 180 lng).")
            lat_f = float(lat)
            lng_f = float(lng)
        else:
            lat_f = None
            lng_f = None

        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    UPDATE stores
                    SET store_name = %s, store_slug = %s, store_description = %s, store_logo = %s, store_banner = %s,
                        owner_name = %s, contact_phone = %s, email = %s, full_address = %s, city = %s, area = %s,
                        pincode = %s, latitude = %s, longitude = %s, opening_time = %s, closing_time = %s,
                        is_active = %s, accepts_delivery = %s, accepts_pickup = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING *;
                """, (store_name, store_slug, store_description, store_logo, store_banner, owner_name, contact_phone, email, full_address, city, area, pincode, lat_f, lng_f, opening_time, closing_time, is_active, accepts_delivery, accepts_pickup, store_id))
                updated = dict(cur.fetchone())
                conn.commit()
            conn.close()
            app_cache.delete(f"store_by_id:{store_id}")
            app_cache.invalidate_prefix("retail_stores:")
            app_cache.invalidate_prefix("price_comparisons_batch:")
            return updated
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
                UPDATE stores
                SET store_name = ?, store_slug = ?, store_description = ?, store_logo = ?, store_banner = ?,
                    owner_name = ?, contact_phone = ?, email = ?, full_address = ?, city = ?, area = ?,
                    pincode = ?, latitude = ?, longitude = ?, opening_time = ?, closing_time = ?,
                    is_active = ?, accepts_delivery = ?, accepts_pickup = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?;
            """, (store_name, store_slug, store_description, store_logo, store_banner, owner_name, contact_phone, email, full_address, city, area, pincode, lat_f, lng_f, opening_time, closing_time, 1 if is_active else 0, 1 if accepts_delivery else 0, 1 if accepts_pickup else 0, store_id))
            conn.commit()
            conn.close()
            app_cache.delete(f"store_by_id:{store_id}")
            app_cache.invalidate_prefix("retail_stores:")
            app_cache.invalidate_prefix("price_comparisons_batch:")
            return self.get_store_by_id(store_id)

    def deactivate_store(self, store_id: int) -> bool:
        """Deactivates a store."""
        return self._set_store_active(store_id, False)

    def activate_store(self, store_id: int) -> bool:
        """Activates a store."""
        return self._set_store_active(store_id, True)

    def _set_store_active(self, store_id: int, is_active: bool) -> bool:
        existing = self.get_store_by_id(store_id)
        if not existing:
            return False
        if self.is_live_postgres:
            conn = self._get_pg_connection()
            with conn.cursor() as cur:
                cur.execute("UPDATE stores SET is_active = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;", (is_active, store_id))
                affected = cur.rowcount
                conn.commit()
            conn.close()
            return affected > 0
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("UPDATE stores SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;", (1 if is_active else 0, store_id))
            affected = cur.rowcount
            conn.commit()
            conn.close()
            return affected > 0

    # -------------------------------------------------------------------------
    # Phase 4: Store Inventory & Pricing Management
    # -------------------------------------------------------------------------

    def add_store_inventory(self, store_id: int, product_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Adds a product to a physical store's inventory with store-specific price and stock.
        """
        store = self.get_store_by_id(store_id)
        if not store:
            raise ValueError(f"Store #{store_id} does not exist.")

        product = self.get_product_by_id(product_id)
        if not product:
            raise ValueError(f"Product #{product_id} does not exist.")

        selling_price = float(data.get("selling_price", product.get("price", 0)))
        original_price = float(data["original_price"]) if data.get("original_price") is not None else (float(product["original_price"]) if product.get("original_price") is not None else None)
        stock_quantity = int(data.get("stock_quantity", 0))
        low_stock_threshold = int(data.get("low_stock_threshold", 5))

        if selling_price < 0:
            raise ValueError("Selling price cannot be negative.")
        if original_price is not None and original_price < selling_price:
            raise ValueError("Original price cannot be lower than selling price.")
        if stock_quantity < 0:
            raise ValueError("Stock quantity cannot be negative.")
        if low_stock_threshold < 0:
            raise ValueError("Low stock threshold cannot be negative.")

        is_available = bool(data.get("is_available", stock_quantity > 0))

        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO store_inventory (store_id, product_id, selling_price, original_price, stock_quantity, reserved_quantity, low_stock_threshold, is_available)
                    VALUES (%s, %s, %s, %s, %s, 0, %s, %s)
                    RETURNING *;
                """, (store_id, product_id, selling_price, original_price, stock_quantity, low_stock_threshold, is_available))
                created = dict(cur.fetchone())
                conn.commit()
            conn.close()
            try:
                self.record_store_stock_movement(
                    store_id=store_id,
                    product_id=product_id,
                    movement_type="RESTOCKED",
                    quantity=stock_quantity,
                    balance_after=stock_quantity,
                    reference_type="INITIAL_STOCK",
                    reference_id=str(product_id),
                    notes=f"Initial stock added for store #{store_id}"
                )
            except Exception as me:
                logger.warning(f"Could not record stock movement for store {store_id}: {me}")
            return created
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO store_inventory (store_id, product_id, selling_price, original_price, stock_quantity, reserved_quantity, low_stock_threshold, is_available)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?);
            """, (store_id, product_id, selling_price, original_price, stock_quantity, low_stock_threshold, 1 if is_available else 0))
            new_id = cur.lastrowid
            conn.commit()
            cur.execute("SELECT * FROM store_inventory WHERE id = ?;", (new_id,))
            row = dict(cur.fetchone())
            row["is_available"] = bool(row.get("is_available"))
            conn.close()
            try:
                self.record_store_stock_movement(
                    store_id=store_id,
                    product_id=product_id,
                    movement_type="RESTOCKED",
                    quantity=stock_quantity,
                    balance_after=stock_quantity,
                    reference_type="INITIAL_STOCK",
                    reference_id=str(product_id),
                    notes=f"Initial stock added for store #{store_id}"
                )
            except Exception as me:
                logger.warning(f"Could not record stock movement for store {store_id}: {me}")
            return row

    def get_store_inventory(self, store_id: int) -> List[Dict[str, Any]]:
        """
        Retrieves all inventory items for a store joined with product details.
        """
        cache_key = f"store_inventory:{store_id}"
        cached = app_cache.get(cache_key)
        if cached is not None:
            return cached

        store = self.get_store_by_id(store_id)
        if not store:
            return []

        sql = """
            SELECT si.id, si.store_id, si.product_id, si.selling_price, si.original_price,
                   si.stock_quantity, si.reserved_quantity, (si.stock_quantity - si.reserved_quantity) AS available_quantity,
                   si.low_stock_threshold, si.is_available, si.updated_at,
                   p.sku, p.title, p.brand, p.category, p.sub_category, p.image_url, p.description, p.rating, p.rating_count
            FROM store_inventory si
            JOIN products p ON si.product_id = p.id
            WHERE si.store_id = %s
            ORDER BY p.title ASC;
        """ if self.is_live_postgres else """
            SELECT si.id, si.store_id, si.product_id, si.selling_price, si.original_price,
                   si.stock_quantity, si.reserved_quantity, (si.stock_quantity - si.reserved_quantity) AS available_quantity,
                   si.low_stock_threshold, si.is_available, si.updated_at,
                   p.sku, p.title, p.brand, p.category, p.sub_category, p.image_url, p.description, p.rating, p.rating_count
            FROM store_inventory si
            JOIN products p ON si.product_id = p.id
            WHERE si.store_id = ?
            ORDER BY p.title ASC;
        """

        def _classify_subcat(title: str, subcat: Optional[str] = None) -> str:
            if subcat and str(subcat).strip():
                sc = str(subcat).strip()
                if sc in ("Fruits & Vegetables", "Fresh Produce"):
                    return "Fruits & Vegetables"
                if sc in ("Dairy & Bakery", "Dairy & Breakfast"):
                    return "Dairy & Bakery"
                if sc in ("Rice, Atta & Dal", "Rice & Grains"):
                    return "Rice, Atta & Dal"
                if sc in ("Cooking Essentials", "Packaged Foods"):
                    t_lower = (title or "").lower()
                    if any(k in t_lower for k in ["tea", "coffee", "sugar", "honey", "oat", "flake", "cereal"]):
                        return "Snacks & Beverages"
                    return "Household & Personal Care"
                if sc in ("Household Essentials", "Household & Personal Care"):
                    return "Household & Personal Care"
                if sc == "Snacks & Beverages":
                    return "Snacks & Beverages"
                return sc
            t = (title or "").lower()
            if any(k in t for k in ["potato", "onion", "tomato", "banana", "apple", "orange", "capsicum", "chilli", "ginger", "adrak", "dhaniya", "coriander", "fruit", "vegetable"]):
                return "Fruits & Vegetables"
            if any(k in t for k in ["milk", "curd", "dahi", "paneer", "butter", "ghee", "cheese", "bread", "egg"]):
                return "Dairy & Bakery"
            if any(k in t for k in ["rice", "atta", "wheat", "dal", "besan", "grain", "chana", "rajma", "poha"]):
                return "Rice, Atta & Dal"
            if any(k in t for k in ["tea", "coffee", "sugar", "honey", "oat", "flake", "cereal"]):
                return "Snacks & Beverages"
            if any(k in t for k in ["oil", "salt", "masala", "spice", "haldi", "turmeric", "cleaner", "surf", "vim", "lizol", "dettol", "harpic", "colin", "goodknight", "scrub"]):
                return "Household & Personal Care"
            return "Household & Personal Care"

        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (store_id,))
                    rows = []
                    for r in cur.fetchall():
                        d = dict(r)
                        d["is_available"] = bool(d.get("is_available"))
                        d["selling_price"] = float(d["selling_price"]) if d.get("selling_price") is not None else 0.0
                        d["original_price"] = float(d["original_price"]) if d.get("original_price") is not None else None
                        d["stock_quantity"] = int(d.get("stock_quantity") or 0)
                        d["available_quantity"] = int(d.get("available_quantity") or 0)
                        d["sub_category"] = _classify_subcat(d.get("title", ""), d.get("sub_category"))
                        rows.append(d)
            finally:
                conn.close()
            app_cache.set(cache_key, rows, ttl=60.0)
            return rows
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                cur.execute(sql, (store_id,))
                rows = []
                for r in cur.fetchall():
                    d = dict(r)
                    d["is_available"] = bool(d.get("is_available"))
                    d["selling_price"] = float(d["selling_price"]) if d.get("selling_price") is not None else 0.0
                    d["original_price"] = float(d["original_price"]) if d.get("original_price") is not None else None
                    d["stock_quantity"] = int(d.get("stock_quantity") or 0)
                    d["available_quantity"] = int(d.get("available_quantity") or 0)
                    d["sub_category"] = _classify_subcat(d.get("title", ""), d.get("sub_category"))
                    rows.append(d)
            finally:
                conn.close()
            app_cache.set(cache_key, rows, ttl=60.0)
            return rows

    def get_store_product(self, store_id: int, product_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieves product availability, price, and stock for a specific physical store.
        """
        try:
            s_id = int(store_id)
            p_id = int(product_id)
        except (ValueError, TypeError):
            return None

        sql = """
            SELECT si.id, si.store_id, si.product_id, si.selling_price, si.original_price,
                   si.stock_quantity, si.reserved_quantity, (si.stock_quantity - si.reserved_quantity) AS available_quantity,
                   si.low_stock_threshold, si.is_available, si.updated_at,
                   p.sku, p.title, p.brand, p.category, p.sub_category, p.image_url, p.description, p.rating, p.rating_count
            FROM store_inventory si
            JOIN products p ON si.product_id = p.id
            WHERE si.store_id = %s AND si.product_id = %s;
        """ if self.is_live_postgres else """
            SELECT si.id, si.store_id, si.product_id, si.selling_price, si.original_price,
                   si.stock_quantity, si.reserved_quantity, (si.stock_quantity - si.reserved_quantity) AS available_quantity,
                   si.low_stock_threshold, si.is_available, si.updated_at,
                   p.sku, p.title, p.brand, p.category, p.sub_category, p.image_url, p.description, p.rating, p.rating_count
            FROM store_inventory si
            JOIN products p ON si.product_id = p.id
            WHERE si.store_id = ? AND si.product_id = ?;
        """

        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (s_id, p_id))
                    row = cur.fetchone()
            finally:
                conn.close()
            if not row:
                return None
            d = dict(row)
            d["is_available"] = bool(d.get("is_available"))
            d["selling_price"] = float(d["selling_price"]) if d.get("selling_price") is not None else 0.0
            d["original_price"] = float(d["original_price"]) if d.get("original_price") is not None else None
            d["stock_quantity"] = int(d.get("stock_quantity") or 0)
            d["available_quantity"] = int(d.get("available_quantity") or 0)
            return d
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                cur.execute(sql, (s_id, p_id))
                row = cur.fetchone()
            finally:
                conn.close()
            if not row:
                return None
            d = dict(row)
            d["is_available"] = bool(d.get("is_available"))
            d["selling_price"] = float(d["selling_price"]) if d.get("selling_price") is not None else 0.0
            d["original_price"] = float(d["original_price"]) if d.get("original_price") is not None else None
            d["stock_quantity"] = int(d.get("stock_quantity") or 0)
            d["available_quantity"] = int(d.get("available_quantity") or 0)
            return d

    def update_store_inventory(self, store_id: int, product_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Updates store-specific selling price, stock quantity, or threshold.
        """
        existing = self.get_store_product(store_id, product_id)
        if not existing:
            return None

        selling_price = float(data.get("selling_price") if "selling_price" in data else existing["selling_price"])
        original_price = float(data["original_price"]) if "original_price" in data and data["original_price"] is not None else existing.get("original_price")
        stock_quantity = int(data.get("stock_quantity") if "stock_quantity" in data else existing["stock_quantity"])
        low_stock_threshold = int(data.get("low_stock_threshold") if "low_stock_threshold" in data else existing.get("low_stock_threshold", 5))

        if selling_price < 0:
            raise ValueError("Selling price cannot be negative.")
        if original_price is not None and original_price < selling_price:
            raise ValueError("Original price cannot be lower than selling price.")
        if stock_quantity < 0:
            raise ValueError("Stock quantity cannot be negative.")
        if low_stock_threshold < 0:
            raise ValueError("Low stock threshold cannot be negative.")

        is_available = bool(data.get("is_available", stock_quantity > 0) if "is_available" in data else (stock_quantity > 0))

        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    UPDATE store_inventory
                    SET selling_price = %s, original_price = %s, stock_quantity = %s,
                        low_stock_threshold = %s, is_available = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE store_id = %s AND product_id = %s
                    RETURNING *;
                """, (selling_price, original_price, stock_quantity, low_stock_threshold, is_available, store_id, product_id))
                updated = dict(cur.fetchone())
                conn.commit()
            conn.close()
            if "stock_quantity" in data and stock_quantity != existing.get("stock_quantity", 0):
                diff = stock_quantity - existing.get("stock_quantity", 0)
                m_type = "RESTOCKED" if diff > 0 else "ADJUSTED"
                try:
                    self.record_store_stock_movement(
                        store_id=store_id,
                        product_id=product_id,
                        movement_type=m_type,
                        quantity=abs(diff),
                        balance_after=stock_quantity,
                        reference_type="STORE_UPDATE",
                        reference_id=str(product_id),
                        notes=f"Stock updated from {existing.get('stock_quantity', 0)} to {stock_quantity}"
                    )
                except Exception as me:
                    logger.warning(f"Could not record stock movement for store {store_id}: {me}")
            self._invalidate_catalog_and_inventory_cache(store_id)
            return updated
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
                UPDATE store_inventory
                SET selling_price = ?, original_price = ?, stock_quantity = ?,
                    low_stock_threshold = ?, is_available = ?, updated_at = CURRENT_TIMESTAMP
                WHERE store_id = ? AND product_id = ?;
            """, (selling_price, original_price, stock_quantity, low_stock_threshold, 1 if is_available else 0, store_id, product_id))
            conn.commit()
            conn.close()
            if "stock_quantity" in data and stock_quantity != existing.get("stock_quantity", 0):
                diff = stock_quantity - existing.get("stock_quantity", 0)
                m_type = "RESTOCKED" if diff > 0 else "ADJUSTED"
                try:
                    self.record_store_stock_movement(
                        store_id=store_id,
                        product_id=product_id,
                        movement_type=m_type,
                        quantity=abs(diff),
                        balance_after=stock_quantity,
                        reference_type="STORE_UPDATE",
                        reference_id=str(product_id),
                        notes=f"Stock updated from {existing.get('stock_quantity', 0)} to {stock_quantity}"
                    )
                except Exception as me:
                    logger.warning(f"Could not record stock movement for store {store_id}: {me}")
            self._invalidate_catalog_and_inventory_cache(store_id)
            return self.get_store_product(store_id, product_id)

    def remove_store_inventory(self, store_id: int, product_id: int) -> bool:
        """Removes a product from a store's inventory."""
        if self.is_live_postgres:
            conn = self._get_pg_connection()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM store_inventory WHERE store_id = %s AND product_id = %s;", (store_id, product_id))
                affected = cur.rowcount
                conn.commit()
            conn.close()
            self._invalidate_catalog_and_inventory_cache(store_id)
            return affected > 0
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM store_inventory WHERE store_id = ? AND product_id = ?;", (store_id, product_id))
            affected = cur.rowcount
            conn.commit()
            conn.close()
            self._invalidate_catalog_and_inventory_cache(store_id)
            return affected > 0

    def get_available_store_products(self, store_id: int) -> List[Dict[str, Any]]:
        """
        Returns only products currently available (stock > 0 and is_available = TRUE) at the specified store.
        """
        all_items = self.get_store_inventory(store_id)
        return [item for item in all_items if item.get("is_available") and item.get("stock_quantity", 0) > item.get("reserved_quantity", 0)]

    def get_low_stock_products(self, store_id: int) -> List[Dict[str, Any]]:
        """
        Returns items at the specified store whose available stock is <= low_stock_threshold.
        """
        all_items = self.get_store_inventory(store_id)
        return [item for item in all_items if (item.get("stock_quantity", 0) - item.get("reserved_quantity", 0)) <= item.get("low_stock_threshold", 5)]

    def get_out_of_stock_products(self, store_id: int) -> List[Dict[str, Any]]:
        """
        Returns items at the specified store that are out of stock (stock_quantity <= 0 or is_available = FALSE).
        """
        all_items = self.get_store_inventory(store_id)
        return [item for item in all_items if not item.get("is_available") or int(item.get("stock_quantity", 0)) <= 0]

    def record_store_stock_movement(self, store_id: int, product_id: int, movement_type: str, quantity: int, balance_after: int, reference_type: str = "STORE_ADJUST", reference_id: str = "0", notes: str = "") -> Dict[str, Any]:
        """
        Appends an entry to the immutable stock movement ledger for a physical store.
        """
        ref_id_str = f"store_{store_id}:{reference_id}"
        detailed_notes = f"[Store #{store_id}] {notes}" if not notes.startswith(f"[Store #{store_id}]") else notes
        if self.is_live_postgres:
            conn = self._get_pg_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO inventory_movements (product_id, movement_type, quantity, balance_after, reference_type, reference_id, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, product_id, movement_type, quantity, balance_after, reference_type, reference_id, notes, created_at;
                """, (product_id, movement_type, quantity, balance_after, reference_type, ref_id_str, detailed_notes))
                row = dict(cur.fetchone())
                conn.commit()
            conn.close()
            return row
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO inventory_movements (product_id, movement_type, quantity, balance_after, reference_type, reference_id, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (product_id, movement_type, quantity, balance_after, reference_type, ref_id_str, detailed_notes))
            m_id = cur.lastrowid
            conn.commit()
            cur.execute("SELECT id, product_id, movement_type, quantity, balance_after, reference_type, reference_id, notes, created_at FROM inventory_movements WHERE id = ?;", (m_id,))
            cols = [c[0] for c in cur.description]
            row = dict(zip(cols, cur.fetchone()))
            conn.close()
            return row

    def get_store_stock_movements(self, store_id: int, product_id: Optional[int] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Retrieves recent stock movement history for a physical store.
        """
        ref_prefix = f"store_{store_id}:%"
        if self.is_live_postgres:
            conn = self._get_pg_connection()
            with conn.cursor() as cur:
                if product_id:
                    cur.execute("""
                        SELECT m.id, m.product_id, m.movement_type, m.quantity, m.balance_after, m.reference_type, m.reference_id, m.notes, m.created_at,
                               p.title AS product_title, p.sku
                        FROM inventory_movements m
                        JOIN products p ON m.product_id = p.id
                        WHERE (m.reference_id LIKE %s OR m.notes LIKE %s) AND m.product_id = %s
                        ORDER BY m.id DESC
                        LIMIT %s;
                    """, (ref_prefix, f"%[Store #{store_id}]%", product_id, limit))
                else:
                    cur.execute("""
                        SELECT m.id, m.product_id, m.movement_type, m.quantity, m.balance_after, m.reference_type, m.reference_id, m.notes, m.created_at,
                               p.title AS product_title, p.sku
                        FROM inventory_movements m
                        JOIN products p ON m.product_id = p.id
                        WHERE (m.reference_id LIKE %s OR m.notes LIKE %s)
                        ORDER BY m.id DESC
                        LIMIT %s;
                    """, (ref_prefix, f"%[Store #{store_id}]%", limit))
                rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            if product_id:
                cur.execute("""
                    SELECT m.id, m.product_id, m.movement_type, m.quantity, m.balance_after, m.reference_type, m.reference_id, m.notes, m.created_at,
                           p.title AS product_title, p.sku
                    FROM inventory_movements m
                    JOIN products p ON m.product_id = p.id
                    WHERE (m.reference_id LIKE ? OR m.notes LIKE ?) AND m.product_id = ?
                    ORDER BY m.id DESC
                    LIMIT ?;
                """, (ref_prefix, f"%[Store #{store_id}]%", product_id, limit))
            else:
                cur.execute("""
                    SELECT m.id, m.product_id, m.movement_type, m.quantity, m.balance_after, m.reference_type, m.reference_id, m.notes, m.created_at,
                           p.title AS product_title, p.sku
                    FROM inventory_movements m
                    JOIN products p ON m.product_id = p.id
                    WHERE (m.reference_id LIKE ? OR m.notes LIKE ?)
                    ORDER BY m.id DESC
                    LIMIT ?;
                """, (ref_prefix, f"%[Store #{store_id}]%", limit))
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            conn.close()
            return rows

    # -------------------------------------------------------------------------
    # Concurrency, Stock Reservation & Overselling Protection
    # -------------------------------------------------------------------------

    def reserve_store_stock(self, store_id: int, product_id: int, quantity: int, reference_type: str = "CART", reference_id: str = "0") -> Dict[str, Any]:
        """Atomically reserves stock for a product at a physical store."""
        from app.schema import atomic_reserve_store_stock
        if self.is_live_postgres:
            conn = self._get_pg_connection()
            with conn.cursor() as cur:
                res = atomic_reserve_store_stock(cur, True, store_id, product_id, quantity, reference_type, reference_id)
                conn.commit()
            conn.close()
            return res
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            res = atomic_reserve_store_stock(cur, False, store_id, product_id, quantity, reference_type, reference_id)
            conn.commit()
            conn.close()
            return res

    def release_store_stock(self, store_id: int, product_id: int, quantity: int, reference_type: str = "CART_ABANDON", reference_id: str = "0") -> Dict[str, Any]:
        """Atomically releases reserved stock back to the store inventory."""
        from app.schema import atomic_release_store_stock
        if self.is_live_postgres:
            conn = self._get_pg_connection()
            with conn.cursor() as cur:
                res = atomic_release_store_stock(cur, True, store_id, product_id, quantity, reference_type, reference_id)
                conn.commit()
            conn.close()
            return res
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            res = atomic_release_store_stock(cur, False, store_id, product_id, quantity, reference_type, reference_id)
            conn.commit()
            conn.close()
            return res

    def commit_store_sale(self, store_id: int, product_id: int, quantity: int, reference_type: str = "ORDER", reference_id: str = "0") -> Dict[str, Any]:
        """Finalizes an order sale: decrements physical stock and releases reservation."""
        from app.schema import atomic_commit_store_sale
        if self.is_live_postgres:
            conn = self._get_pg_connection()
            with conn.cursor() as cur:
                res = atomic_commit_store_sale(cur, True, store_id, product_id, quantity, reference_type, reference_id)
                conn.commit()
            conn.close()
            self._invalidate_catalog_and_inventory_cache(store_id)
            return res
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            res = atomic_commit_store_sale(cur, False, store_id, product_id, quantity, reference_type, reference_id)
            conn.commit()
            conn.close()
            self._invalidate_catalog_and_inventory_cache(store_id)
            return res

    # -------------------------------------------------------------------------
    # Phase 5: Retail Near Me 5-Shop Price Comparison & Hyperlocal Marketplace
    # -------------------------------------------------------------------------

    def _enrich_store_metadata(self, store: Dict[str, Any]) -> Dict[str, Any]:
        """Adds delivery time, rating, and quick-commerce metadata to store object."""
        s = dict(store)
        sid = s.get("id")
        meta = {
            1: {"rating": 4.8, "rating_count": 840, "delivery_time": "15-20 min", "min_order": 99.0, "delivery_fee": 15.0, "badge": "Fastest Delivery"},
            2: {"rating": 4.7, "rating_count": 690, "delivery_time": "20-25 min", "min_order": 149.0, "delivery_fee": 20.0, "badge": "Daily Staples Value"},
            3: {"rating": 4.9, "rating_count": 920, "delivery_time": "15-25 min", "min_order": 99.0, "delivery_fee": 15.0, "badge": "Top Rated Organic"},
            4: {"rating": 4.6, "rating_count": 580, "delivery_time": "25-35 min", "min_order": 199.0, "delivery_fee": 25.0, "badge": "Pure Ghee & Spices"},
            5: {"rating": 4.8, "rating_count": 1120, "delivery_time": "20-30 min", "min_order": 149.0, "delivery_fee": 20.0, "badge": "Mega Pantry Savings"},
            6: {"rating": 4.9, "rating_count": 760, "delivery_time": "20-30 min", "min_order": 149.0, "delivery_fee": 20.0, "badge": "West Coast Express"},
            7: {"rating": 4.7, "rating_count": 480, "delivery_time": "25-35 min", "min_order": 99.0, "delivery_fee": 15.0, "badge": "Andheri Local Mart"}
        }.get(sid, {"rating": 4.7, "rating_count": 350, "delivery_time": "20-30 min", "min_order": 99.0, "delivery_fee": 20.0, "badge": "Neighbourhood Store"})

        for k, v in meta.items():
            if k not in s or s[k] is None:
                s[k] = v
        return s

    def get_retail_stores(self, city: str = "Bengaluru") -> List[Dict[str, Any]]:
        """
        Retrieves active physical retail shops for the specified city, enriched with metadata.
        Filters strictly by city so stores from one city never leak into another.
        For Bengaluru, returns the 5 canonical neighbourhood retail shops (IDs 1 to 5).
        Cached in app_cache for rapid repeated accesses.
        """
        city_lower = (city or "Bengaluru").strip().lower()
        cache_key = f"retail_stores:{city_lower}"
        cached = app_cache.get(cache_key)
        if cached is not None:
            return cached

        all_stores = self.get_all_stores(active_only=True)
        matched = [
            s for s in all_stores
            if (city_lower in s.get("city", "").lower() or s.get("city", "").lower() in city_lower)
        ]
        # For Bengaluru, preserve canonical 5-shop marketplace (IDs 1 to 5)
        if "bengaluru" in city_lower or "bangalore" in city_lower:
            blr_order = {sid: i for i, sid in enumerate([1, 2, 3, 4, 5])}
            flagship = [s for s in matched if s.get("id") in [1, 2, 3, 4, 5]]
            if len(flagship) == 5:
                matched = sorted(flagship, key=lambda s: blr_order.get(s.get("id"), 99))
            else:
                matched = sorted(matched, key=lambda s: blr_order.get(s.get("id"), 99))
        res = [self._enrich_store_metadata(s) for s in matched]
        app_cache.set(cache_key, res, ttl=120.0)
        return res

    def get_all_product_price_comparisons(self, city: str = "Bengaluru") -> Dict[int, Dict[str, Any]]:
        """
        High-performance batched multi-store price and stock comparison across retail shops in a city.
        Replaces N+1 queries (500+ database roundtrips) with a single batch query and in-memory evaluation.
        Cached in app_cache for sub-millisecond response times.
        """
        city_clean = (city or "Bengaluru").strip()
        cache_key = f"price_comparisons_batch:{city_clean.lower()}"
        cached = app_cache.get(cache_key)
        if cached is not None:
            return cached

        stores = self.get_retail_stores(city_clean)
        if not stores:
            return {}

        store_ids = [s["id"] for s in stores]
        inv_map = {}

        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                    SELECT store_id, product_id, selling_price, original_price, stock_quantity, is_available
                    FROM store_inventory
                    WHERE store_id = ANY(%s);
                    """, (store_ids,))
                    rows = cur.fetchall()
                    for r in rows:
                        inv_map[(r["store_id"], r["product_id"])] = dict(r)
            finally:
                conn.close()
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                placeholders = ",".join("?" for _ in store_ids)
                cur.execute(f"""
                    SELECT store_id, product_id, selling_price, original_price, stock_quantity, is_available
                    FROM store_inventory
                    WHERE store_id IN ({placeholders});
                """, store_ids)
                rows = cur.fetchall()
                for r in rows:
                    inv_map[(r["store_id"], r["product_id"])] = dict(r)
            finally:
                conn.close()

        all_prods = {p["id"]: p for p in self.get_all_products()}
        result = {}

        for pid, prod in all_prods.items():
            stores_comparison = []
            in_stock_prices = []
            prod_price = float(prod.get("price", 0))
            prod_op = float(prod.get("original_price", prod_price)) if prod.get("original_price") is not None else prod_price

            for st in stores:
                inv = inv_map.get((st["id"], pid))
                if inv:
                    sp = float(inv["selling_price"]) if inv.get("selling_price") is not None else prod_price
                    op = float(inv["original_price"]) if inv.get("original_price") is not None else sp
                    sq = int(inv["stock_quantity"]) if inv.get("stock_quantity") is not None else 0
                    ia = bool(inv.get("is_available", True) and sq > 0)
                else:
                    sp = prod_price
                    op = prod_op
                    sq = 0
                    ia = False

                if ia and sq > 0:
                    in_stock_prices.append(sp)

                status_text = "In Stock" if ia else "Out of Stock"
                if ia and sq <= 5:
                    status_text = f"Only {sq} left!"

                stores_comparison.append({
                    "store_id": st["id"],
                    "store_name": st["store_name"],
                    "store_slug": st["store_slug"],
                    "area": st["area"],
                    "city": st["city"],
                    "full_address": st["full_address"],
                    "rating": st.get("rating", 4.8),
                    "delivery_time": st.get("delivery_time", "20-30 min"),
                    "badge": st.get("badge", ""),
                    "price": round(sp, 2),
                    "selling_price": round(sp, 2),
                    "original_price": round(op, 2),
                    "stock_quantity": sq,
                    "is_available": ia,
                    "status_text": status_text,
                    "is_lowest": False,
                    "savings": 0.0
                })

            lowest_price = min(in_stock_prices) if in_stock_prices else None
            highest_price = max(in_stock_prices) if in_stock_prices else None
            lowest_store_name = None
            lowest_store_id = None

            if lowest_price is not None:
                for item in stores_comparison:
                    if item["is_available"] and item["price"] == lowest_price:
                        item["is_lowest"] = True
                        if not lowest_store_name:
                            lowest_store_name = item["store_name"]
                            lowest_store_id = item["store_id"]
                    if highest_price and item["is_available"]:
                        item["savings"] = round(highest_price - item["price"], 2)

            max_savings = round(highest_price - lowest_price, 2) if (highest_price and lowest_price) else 0.0

            result[pid] = {
                "product": {
                    "id": prod["id"],
                    "sku": prod.get("sku"),
                    "title": prod["title"],
                    "brand": prod.get("brand"),
                    "category": prod.get("category"),
                    "sub_category": prod.get("sub_category"),
                    "image_url": prod.get("image_url"),
                    "description": prod.get("description"),
                    "rating": prod.get("rating", 4.5),
                    "rating_count": prod.get("rating_count", 0),
                    "price": prod["price"],
                    "original_price": prod.get("original_price", prod["price"]),
                    "stock": prod.get("stock", 20),
                    "cities": prod.get("cities", [])
                },
                "lowest_price": lowest_price,
                "highest_price": highest_price,
                "max_savings": max_savings,
                "lowest_store_id": lowest_store_id,
                "lowest_store_name": lowest_store_name,
                "stores_comparison": stores_comparison,
                "total_stores_count": len(stores_comparison),
                "in_stock_stores_count": len(in_stock_prices)
            }

        app_cache.set(cache_key, result, ttl=45.0)
        return result

    def get_product_price_comparison(self, product_id: int, city: str = "Bengaluru") -> Optional[Dict[str, Any]]:
        """
        Retrieves multi-store price and stock comparison across the retail shops in a city.
        Identifies the lowest price, savings amount, and stock status per shop.
        Delegates to cached batch calculation for maximum performance.
        """
        all_comps = self.get_all_product_price_comparisons(city)
        if product_id in all_comps:
            return all_comps[product_id]

        prod = self.get_product_by_id(product_id)
        if not prod:
            return None

        stores = self.get_retail_stores(city)
        stores_comparison = []
        for st in stores:
            orig_p = prod.get("original_price")
            op = float(orig_p) if orig_p is not None else float(prod["price"])
            stores_comparison.append({
                "store_id": st["id"],
                "store_name": st["store_name"],
                "store_slug": st["store_slug"],
                "area": st["area"],
                "city": st["city"],
                "full_address": st["full_address"],
                "rating": st.get("rating", 4.8),
                "delivery_time": st.get("delivery_time", "20-30 min"),
                "badge": st.get("badge", ""),
                "price": round(float(prod["price"]), 2),
                "selling_price": round(float(prod["price"]), 2),
                "original_price": round(op, 2),
                "stock_quantity": 0,
                "is_available": False,
                "status_text": "Out of Stock",
                "is_lowest": False,
                "savings": 0.0
            })
        return {
            "product": prod,
            "lowest_price": None,
            "highest_price": None,
            "max_savings": 0.0,
            "lowest_store_id": None,
            "lowest_store_name": None,
            "stores_comparison": stores_comparison,
            "total_stores_count": len(stores_comparison),
            "in_stock_stores_count": 0
        }

    def _invalidate_catalog_and_inventory_cache(self, store_id: Optional[int] = None):
        """Invalidates in-memory caches when catalog or store inventory changes."""
        app_cache.delete("catalog:all_products_raw")
        app_cache.invalidate_prefix("price_comparisons_batch:")
        app_cache.invalidate_prefix("retail_stores:")
        if store_id:
            app_cache.delete(f"store_inventory:{store_id}")
        else:
            app_cache.invalidate_prefix("store_inventory:")

    # -------------------------------------------------------------------------
    # Phase 5: Nearby Store Discovery & Haversine Distance (Max 15 km)
    # -------------------------------------------------------------------------

    def calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Alias for calculate_haversine_distance on the DatabaseService instance."""
        return calculate_haversine_distance(lat1, lon1, lat2, lon2)

    def _is_store_open_now(self, opening_time: Optional[str], closing_time: Optional[str]) -> bool:
        """
        Determines if a store is currently open based on opening and closing time strings.
        Supports standard Indian store formats like '06:30 AM', '11:30 PM', '07:00 AM', etc.
        """
        if not opening_time or not closing_time:
            return True

        def _to_mins(t_str: str) -> Optional[int]:
            try:
                m = re.match(r"^(\d{1,2}):(\d{2})\s*(AM|PM)?$", t_str.strip().upper())
                if not m:
                    return None
                hr = int(m.group(1))
                mn = int(m.group(2))
                meridiem = m.group(3)
                if meridiem == "PM" and hr < 12:
                    hr += 12
                elif meridiem == "AM" and hr == 12:
                    hr = 0
                return hr * 60 + mn
            except Exception:
                return None

        open_m = _to_mins(opening_time)
        close_m = _to_mins(closing_time)
        if open_m is None or close_m is None:
            return True

        # Current time in local minutes
        now = time.localtime()
        now_m = now.tm_hour * 60 + now.tm_min

        if open_m <= close_m:
            return open_m <= now_m <= close_m
        else:
            # Crosses midnight (e.g. 18:00 to 02:00)
            return now_m >= open_m or now_m <= close_m

    def get_nearby_stores(
        self,
        lat: float,
        lng: float,
        max_radius_km: float = 15.0,
        sort_by: str = "nearest",
        category_filter: Optional[str] = None,
        open_only: bool = False,
        delivery_only: bool = False,
        pickup_only: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Retrieves active physical stores within max_radius_km (strictly capped at 15 km)
        from user geographic coordinates using the Haversine formula.
        Excludes inactive stores and stores without valid coordinates.
        Enriches results with distance, real grocery product counts, and open status.
        """
        try:
            user_lat = float(lat)
            user_lng = float(lng)
            radius = float(max_radius_km)
        except (ValueError, TypeError):
            raise ValueError("Latitude, longitude, and radius must be valid numbers.")

        if not (-90.0 <= user_lat <= 90.0):
            raise ValueError("Latitude must be between -90 and 90 degrees.")
        if not (-180.0 <= user_lng <= 180.0):
            raise ValueError("Longitude must be between -180 and 180 degrees.")
        if radius <= 0 or radius > 15.0:
            raise ValueError("Radius must be greater than 0 and cannot exceed 15 km.")

        all_stores = self.get_all_stores(active_only=True)
        nearby_stores = []

        for st in all_stores:
            s_lat = st.get("latitude")
            s_lng = st.get("longitude")
            if s_lat is None or s_lng is None:
                continue

            try:
                dist = calculate_haversine_distance(user_lat, user_lng, float(s_lat), float(s_lng))
            except Exception:
                continue

            # Strict 15 km maximum radius check
            if dist > radius:
                continue

            enriched = self._enrich_store_metadata(dict(st))
            enriched["distance_km"] = dist
            enriched["distance_text"] = f"{dist:.1f} km (approx. straight-line)"

            # Delivery & Pickup settings from store record
            enriched["delivery_available"] = bool(st.get("accepts_delivery", True))
            enriched["pickup_available"] = bool(st.get("accepts_pickup", True))
            enriched["delivery_fee"] = float(st.get("delivery_fee", 20.0))

            # Operating hours / open status
            enriched["is_open"] = self._is_store_open_now(st.get("opening_time"), st.get("closing_time"))
            enriched["status_badge"] = "Open Now" if enriched["is_open"] else "Closed"

            # Query real grocery product count in store inventory
            inv = self.get_store_inventory(st["id"])
            grocery_items = [p for p in inv if p.get("category") == "Daily Essentials & Groceries" and p.get("is_available") and p.get("stock_quantity", 0) > 0]
            enriched["grocery_product_count"] = len(grocery_items)

            # Filtering
            if open_only and not enriched["is_open"]:
                continue
            if delivery_only and not enriched["delivery_available"]:
                continue
            if pickup_only and not enriched["pickup_available"]:
                continue

            if category_filter and category_filter.strip() and category_filter.strip().lower() != "all":
                cat_lower = category_filter.strip().lower()
                has_cat = any(cat_lower in (p.get("sub_category", "").lower() + " " + p.get("title", "").lower()) for p in grocery_items)
                desc_match = cat_lower in (st.get("store_description", "").lower() + " " + st.get("store_name", "").lower())
                if not (has_cat or desc_match):
                    continue

            nearby_stores.append(enriched)

        # Sorting: Default nearest first
        if sort_by == "farthest":
            nearby_stores.sort(key=lambda s: s["distance_km"], reverse=True)
        elif sort_by == "name_asc":
            nearby_stores.sort(key=lambda s: s["store_name"].lower())
        elif sort_by == "fee_asc":
            nearby_stores.sort(key=lambda s: s["delivery_fee"])
        else: # 'nearest' is default
            nearby_stores.sort(key=lambda s: s["distance_km"])

        return nearby_stores

    def get_store_detail_with_catalog(self, store_id: int, user_lat: Optional[float] = None, user_lng: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """
        Retrieves store details along with categorized grocery catalog and
        calculates distance to customer location if provided.
        """
        store = self.get_store_by_id(store_id)
        if not store:
            return None

        enriched = self._enrich_store_metadata(dict(store))
        if user_lat is not None and user_lng is not None and store.get("latitude") and store.get("longitude"):
            try:
                d = calculate_haversine_distance(float(user_lat), float(user_lng), float(store["latitude"]), float(store["longitude"]))
                enriched["distance_km"] = d
                enriched["distance_text"] = f"{d:.1f} km (approx. straight-line)"
            except Exception:
                enriched["distance_km"] = None
                enriched["distance_text"] = None
        else:
            enriched["distance_km"] = None
            enriched["distance_text"] = None

        enriched["is_open"] = self._is_store_open_now(store.get("opening_time"), store.get("closing_time"))
        enriched["status_badge"] = "Open Now" if enriched["is_open"] else "Closed"

        inv = self.get_store_inventory(store_id)
        grocery_items = [p for p in inv if p.get("category") == "Daily Essentials & Groceries"]

        fruits_vegetables_items = []
        dairy_bakery_items = []
        rice_atta_dal_items = []
        snacks_beverages_items = []
        household_personal_items = []

        for item in grocery_items:
            sub = item.get("sub_category", "")
            t = (item.get("title") or "").lower()
            if sub in ("Fruits & Vegetables", "Fresh Produce") or any(k in t for k in ["potato", "onion", "tomato", "banana", "apple", "orange", "capsicum", "vegetable", "coriander", "chillies", "ginger"]):
                fruits_vegetables_items.append(item)
            elif sub in ("Dairy & Bakery", "Dairy & Breakfast") or any(k in t for k in ["milk", "curd", "dahi", "paneer", "butter", "ghee", "cheese", "bread", "egg"]):
                dairy_bakery_items.append(item)
            elif sub in ("Rice, Atta & Dal", "Rice & Grains") or any(k in t for k in ["rice", "atta", "wheat", "dal", "besan", "chana", "poha", "rajma"]):
                rice_atta_dal_items.append(item)
            elif sub == "Snacks & Beverages" or any(k in t for k in ["tea", "coffee", "sugar", "honey", "oat", "flake"]):
                snacks_beverages_items.append(item)
            else:
                household_personal_items.append(item)

        return {
            "store": enriched,
            # Phase 14 simplified 5 categories
            "fruits_vegetables_items": fruits_vegetables_items,
            "dairy_bakery_items": dairy_bakery_items,
            "rice_atta_dal_items": rice_atta_dal_items,
            "snacks_beverages_items": snacks_beverages_items,
            "household_personal_items": household_personal_items,
            # Aliases for backward compatibility
            "dairy_items": dairy_bakery_items,
            "grains_items": rice_atta_dal_items,
            "produce_items": fruits_vegetables_items,
            "essentials_items": snacks_beverages_items + [x for x in household_personal_items if any(k in (x.get("title") or "").lower() for k in ["oil", "salt", "masala"])],
            "household_items": household_personal_items,
            "all_products": grocery_items,
            "total_products_count": len([p for p in grocery_items if p.get("is_available") and p.get("stock_quantity", 0) > 0])
        }

    # =========================================================================
    # Phase 7: Advanced Multi-Store Cart & Checkout Database Architecture
    # =========================================================================

    def calculate_retail_delivery_fee(self, store_id: int, customer_lat: Optional[float] = None, customer_lng: Optional[float] = None, fulfillment: str = "delivery") -> float:
        """
        Calculates store delivery fee according to Phase 7 specifications:
        - In-store pickup: ₹0.0
        - 0 to 5 km: ₹20.0
        - Above 5 to 10 km: ₹40.0
        - Above 10 to 15 km: ₹60.0
        - Above 15 km: Delivery not eligible (raises ValueError)
        - Fallback (no coordinates): Store base fee or ₹20.0
        """
        if fulfillment == "pickup":
            return 0.0

        store = self.get_store_by_id(store_id)
        if not store:
            return 20.0

        if customer_lat is not None and customer_lng is not None and store.get("latitude") and store.get("longitude"):
            d = calculate_haversine_distance(float(customer_lat), float(customer_lng), float(store["latitude"]), float(store["longitude"]))
            if d <= 5.0:
                return 20.0
            elif d <= 10.0:
                return 40.0
            elif d <= 15.0:
                return 60.0
            else:
                raise ValueError(f"Store #{store_id} ({store.get('store_name', '')}) is {d:.1f} km away, exceeding the 15 km retail delivery radius. Please choose in-store pickup.")

        return float(store.get("delivery_fee") or 20.0)

    def _get_cart_scope_key(self, customer_id: Optional[int], session_id: Optional[str], shopping_mode: str, store_id: Optional[int]) -> str:
        mode = "RETAIL_NEAR_ME" if str(shopping_mode).upper() in ["RETAIL", "RETAIL_NEAR_ME"] else "ONLINE"
        s_id = int(store_id) if (mode == "RETAIL_NEAR_ME" and store_id) else 0
        user_part = f"c_{customer_id}" if customer_id else f"s_{session_id or 'anon'}"
        return f"{user_part}:{mode}:{s_id}"

    def get_or_create_cart(self, customer_id: Optional[int] = None, session_id: Optional[str] = None, shopping_mode: str = "ONLINE", store_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Finds or creates an active cart for the customer/session within the designated scope.
        - Online: customer/session + shopping_mode='ONLINE' + store_id=NULL
        - Retail: customer/session + shopping_mode='RETAIL_NEAR_ME' + store_id=<store_id>
        """
        mode = "RETAIL_NEAR_ME" if str(shopping_mode).upper() in ["RETAIL", "RETAIL_NEAR_ME"] else "ONLINE"
        s_id = int(store_id) if (mode == "RETAIL_NEAR_ME" and store_id) else None
        scope_key = self._get_cart_scope_key(customer_id, session_id, mode, s_id)

        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    if customer_id:
                        cur.execute("""
                            SELECT id, customer_id, session_id, shopping_mode, store_id, status, created_at, updated_at
                            FROM carts
                            WHERE customer_id = %s AND shopping_mode = %s AND (store_id = %s OR (store_id IS NULL AND %s IS NULL)) AND status = 'ACTIVE'
                            LIMIT 1;
                        """, (customer_id, mode, s_id, s_id))
                    else:
                        cur.execute("""
                            SELECT id, customer_id, session_id, shopping_mode, store_id, status, created_at, updated_at
                            FROM carts
                            WHERE (session_id = %s OR session_id = %s) AND shopping_mode = %s AND (store_id = %s OR (store_id IS NULL AND %s IS NULL)) AND status = 'ACTIVE'
                            LIMIT 1;
                        """, (scope_key, session_id, mode, s_id, s_id))
                    row = cur.fetchone()
                    if row:
                        return dict(row)

                    cur.execute("""
                        INSERT INTO carts (customer_id, session_id, shopping_mode, store_id, status)
                        VALUES (%s, %s, %s, %s, 'ACTIVE')
                        RETURNING id, customer_id, session_id, shopping_mode, store_id, status, created_at, updated_at;
                    """, (customer_id, scope_key, mode, s_id))
                    new_row = cur.fetchone()
                    conn.commit()
                    return dict(new_row)
            finally:
                conn.close()
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                if customer_id:
                    cur.execute("""
                        SELECT id, customer_id, session_id, shopping_mode, store_id, status, created_at, updated_at
                        FROM carts
                        WHERE customer_id = ? AND shopping_mode = ? AND (store_id = ? OR (store_id IS NULL AND ? IS NULL)) AND status = 'ACTIVE'
                        LIMIT 1;
                    """, (customer_id, mode, s_id, s_id))
                else:
                    cur.execute("""
                        SELECT id, customer_id, session_id, shopping_mode, store_id, status, created_at, updated_at
                        FROM carts
                        WHERE (session_id = ? OR session_id = ?) AND shopping_mode = ? AND (store_id = ? OR (store_id IS NULL AND ? IS NULL)) AND status = 'ACTIVE'
                        LIMIT 1;
                    """, (scope_key, session_id, mode, s_id, s_id))
                row = cur.fetchone()
                if row:
                    cols = [c[0] for c in cur.description]
                    return dict(zip(cols, row))

                cur.execute("""
                    INSERT INTO carts (customer_id, session_id, shopping_mode, store_id, status)
                    VALUES (?, ?, ?, ?, 'ACTIVE');
                """, (customer_id, scope_key, mode, s_id))
                conn.commit()
                new_id = cur.lastrowid
                return {
                    "id": new_id,
                    "customer_id": customer_id,
                    "session_id": scope_key,
                    "shopping_mode": mode,
                    "store_id": s_id,
                    "status": "ACTIVE"
                }
            finally:
                conn.close()

    def get_cart(self, customer_id: Optional[int] = None, session_id: Optional[str] = None, shopping_mode: str = "ONLINE", store_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Retrieves a cart with live product prices, titles, images and availability.
        """
        mode = "RETAIL_NEAR_ME" if str(shopping_mode).upper() in ["RETAIL", "RETAIL_NEAR_ME"] else "ONLINE"
        s_id = int(store_id) if (mode == "RETAIL_NEAR_ME" and store_id) else None
        scope_key = self._get_cart_scope_key(customer_id, session_id, mode, s_id)

        cart_record = None
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    if customer_id:
                        cur.execute("""
                            SELECT id, customer_id, session_id, shopping_mode, store_id, status
                            FROM carts
                            WHERE customer_id = %s AND shopping_mode = %s AND (store_id = %s OR (store_id IS NULL AND %s IS NULL)) AND status = 'ACTIVE'
                            LIMIT 1;
                        """, (customer_id, mode, s_id, s_id))
                    else:
                        cur.execute("""
                            SELECT id, customer_id, session_id, shopping_mode, store_id, status
                            FROM carts
                            WHERE (session_id = %s OR session_id = %s) AND shopping_mode = %s AND (store_id = %s OR (store_id IS NULL AND %s IS NULL)) AND status = 'ACTIVE'
                            LIMIT 1;
                        """, (scope_key, session_id, mode, s_id, s_id))
                    row = cur.fetchone()
                    if row:
                        cart_record = dict(row)
            finally:
                conn.close()
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                if customer_id:
                    cur.execute("""
                        SELECT id, customer_id, session_id, shopping_mode, store_id, status
                        FROM carts
                        WHERE customer_id = ? AND shopping_mode = ? AND (store_id = ? OR (store_id IS NULL AND ? IS NULL)) AND status = 'ACTIVE'
                        LIMIT 1;
                    """, (customer_id, mode, s_id, s_id))
                else:
                    cur.execute("""
                        SELECT id, customer_id, session_id, shopping_mode, store_id, status
                        FROM carts
                        WHERE (session_id = ? OR session_id = ?) AND shopping_mode = ? AND (store_id = ? OR (store_id IS NULL AND ? IS NULL)) AND status = 'ACTIVE'
                        LIMIT 1;
                    """, (scope_key, session_id, mode, s_id, s_id))
                row = cur.fetchone()
                if row:
                    cols = [c[0] for c in cur.description]
                    cart_record = dict(zip(cols, row))
            finally:
                conn.close()

        if not cart_record:
            return {
                "cart_id": None,
                "shopping_mode": mode,
                "store_id": s_id,
                "items": [],
                "total_items": 0,
                "subtotal": 0.0
            }

        cart_id = cart_record["id"]
        items = []
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT ci.id, ci.cart_id, ci.product_id, ci.store_id, ci.quantity, ci.unit_price, ci.fulfillment,
                               p.title, p.brand, p.image_url, p.category, p.sub_category, p.price as catalog_price,
                               COALESCE(i.stock_quantity, 0) as catalog_stock
                        FROM cart_items ci
                        JOIN products p ON ci.product_id = p.id
                        LEFT JOIN inventory i ON p.id = i.product_id
                        WHERE ci.cart_id = %s
                        ORDER BY ci.id ASC;
                    """, (cart_id,))
                    rows = cur.fetchall()
                    for r in rows:
                        items.append(dict(r))
            finally:
                conn.close()
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT ci.id, ci.cart_id, ci.product_id, ci.store_id, ci.quantity, ci.unit_price, ci.fulfillment,
                           p.title, p.brand, p.image_url, p.category, p.sub_category, p.price as catalog_price,
                           COALESCE(i.stock_quantity, 0) as catalog_stock
                    FROM cart_items ci
                    JOIN products p ON ci.product_id = p.id
                    LEFT JOIN inventory i ON p.id = i.product_id
                    WHERE ci.cart_id = ?
                    ORDER BY ci.id ASC;
                """, (cart_id,))
                cols = [c[0] for c in cur.description]
                for r in cur.fetchall():
                    items.append(dict(zip(cols, r)))
            finally:
                conn.close()

        total_qty = 0
        grand_subtotal = 0.0
        enriched_items = []

        store_name = None
        if s_id:
            store_obj = self.get_store_by_id(s_id)
            if store_obj:
                store_name = store_obj["store_name"]

        for it in items:
            pid = it["product_id"]
            qty = it["quantity"]
            if mode == "RETAIL_NEAR_ME" and s_id:
                inv = self.get_store_product(s_id, pid)
                live_price = float(inv["selling_price"]) if inv else float(it["unit_price"])
                live_stock = int(inv["stock_quantity"]) if inv else 0
                is_available = bool(inv and inv.get("is_available") and live_stock > 0)
            else:
                live_price = float(it["catalog_price"])
                live_stock = int(it["catalog_stock"])
                is_available = bool(live_stock > 0)

            item_sub = round(live_price * qty, 2)
            total_qty += qty
            grand_subtotal = round(grand_subtotal + item_sub, 2)

            enriched_items.append({
                "id": it["id"],
                "item_id": it["id"],
                "cart_id": cart_id,
                "product_id": pid,
                "store_id": s_id,
                "store_name": store_name,
                "title": it["title"],
                "brand": it.get("brand", ""),
                "image_url": it.get("image_url", ""),
                "category": it.get("category", ""),
                "sub_category": it.get("sub_category", ""),
                "quantity": qty,
                "unit_price": live_price,
                "price": live_price,
                "subtotal": item_sub,
                "live_stock": live_stock,
                "is_available": is_available,
                "fulfillment": it.get("fulfillment") or "delivery"
            })

        res = {
            "cart_id": cart_id,
            "shopping_mode": mode,
            "store_id": s_id,
            "store_name": store_name,
            "items": enriched_items,
            "total_items": total_qty,
            "subtotal": grand_subtotal
        }
        if s_id:
            res["delivery_fee"] = self.calculate_retail_delivery_fee(s_id, fulfillment=enriched_items[0]["fulfillment"] if enriched_items else "delivery")
        return res

    def get_all_retail_carts(self, customer_id: Optional[int] = None, session_id: Optional[str] = None, customer_lat: Optional[float] = None, customer_lng: Optional[float] = None) -> Dict[str, Any]:
        """
        Returns all active retail store baskets for a customer/session, grouped by shop.
        """
        carts_list = []
        user_sess_prefix = f"c_{customer_id}:RETAIL_NEAR_ME:%" if customer_id else f"s_{session_id or 'anon'}:RETAIL_NEAR_ME:%"

        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    if customer_id:
                        cur.execute("""
                            SELECT id, customer_id, session_id, shopping_mode, store_id, status
                            FROM carts
                            WHERE customer_id = %s AND shopping_mode = 'RETAIL_NEAR_ME' AND status = 'ACTIVE'
                            ORDER BY store_id ASC;
                        """, (customer_id,))
                    else:
                        cur.execute("""
                            SELECT id, customer_id, session_id, shopping_mode, store_id, status
                            FROM carts
                            WHERE (session_id LIKE %s OR session_id = %s) AND shopping_mode = 'RETAIL_NEAR_ME' AND status = 'ACTIVE'
                            ORDER BY store_id ASC;
                        """, (user_sess_prefix, session_id))
                    rows = cur.fetchall()
                    carts_list = [dict(r) for r in rows]
            finally:
                conn.close()
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                if customer_id:
                    cur.execute("""
                        SELECT id, customer_id, session_id, shopping_mode, store_id, status
                        FROM carts
                        WHERE customer_id = ? AND shopping_mode = 'RETAIL_NEAR_ME' AND status = 'ACTIVE'
                        ORDER BY store_id ASC;
                    """, (customer_id,))
                else:
                    cur.execute("""
                        SELECT id, customer_id, session_id, shopping_mode, store_id, status
                        FROM carts
                        WHERE (session_id LIKE ? OR session_id = ?) AND shopping_mode = 'RETAIL_NEAR_ME' AND status = 'ACTIVE'
                        ORDER BY store_id ASC;
                    """, (user_sess_prefix, session_id))
                cols = [c[0] for c in cur.description]
                carts_list = [dict(zip(cols, r)) for r in cur.fetchall()]
            finally:
                conn.close()

        shops_breakdown = []
        grand_total_items = 0
        grand_product_subtotal = 0.0
        total_delivery_fees = 0.0

        for c in carts_list:
            s_id = c.get("store_id")
            if not s_id:
                continue
            cart_details = self.get_cart(customer_id, session_id, shopping_mode="RETAIL_NEAR_ME", store_id=s_id)
            if not cart_details["items"]:
                continue

            store_obj = self.get_store_by_id(s_id) or {}
            fulfillment = cart_details["items"][0].get("fulfillment", "delivery") if cart_details["items"] else "delivery"
            try:
                del_fee = self.calculate_retail_delivery_fee(s_id, customer_lat=customer_lat, customer_lng=customer_lng, fulfillment=fulfillment)
                delivery_eligible = True
                delivery_ineligible_reason = None
            except ValueError as ve:
                del_fee = 60.0
                delivery_eligible = False
                delivery_ineligible_reason = str(ve)

            shop_entry = {
                "cart_id": cart_details["cart_id"],
                "store_id": s_id,
                "store_name": store_obj.get("store_name", f"Store #{s_id}"),
                "area": store_obj.get("area", ""),
                "city": store_obj.get("city", ""),
                "full_address": store_obj.get("full_address", ""),
                "contact_phone": store_obj.get("contact_phone", ""),
                "opening_time": store_obj.get("opening_time", "06:30 AM"),
                "closing_time": store_obj.get("closing_time", "11:00 PM"),
                "is_open": self._is_store_open_now(store_obj.get("opening_time"), store_obj.get("closing_time")),
                "items": cart_details["items"],
                "total_items": cart_details["total_items"],
                "subtotal": cart_details["subtotal"],
                "fulfillment": fulfillment,
                "fulfillment_type": fulfillment,
                "delivery_fee": del_fee,
                "delivery_eligible": delivery_eligible,
                "delivery_ineligible_reason": delivery_ineligible_reason,
                "min_order": float(store_obj.get("min_order_value") or 99.0),
                "store_total": round(cart_details["subtotal"] + del_fee, 2)
            }
            shops_breakdown.append(shop_entry)
            grand_total_items += cart_details["total_items"]
            grand_product_subtotal = round(grand_product_subtotal + cart_details["subtotal"], 2)
            total_delivery_fees = round(total_delivery_fees + del_fee, 2)

        summary = {
            "store_count": len(shops_breakdown),
            "total_items": grand_total_items,
            "product_subtotal": grand_product_subtotal,
            "subtotal": grand_product_subtotal,
            "total_delivery_fee": total_delivery_fees,
            "grand_total": round(grand_product_subtotal + total_delivery_fees, 2)
        }

        return {
            "success": True,
            "shops": shops_breakdown,
            "summary": summary,
            "total_items": grand_total_items,
            "subtotal": grand_product_subtotal,
            "product_subtotal": grand_product_subtotal,
            "total_delivery_fee": total_delivery_fees,
            "grand_total": round(grand_product_subtotal + total_delivery_fees, 2)
        }

    def set_store_inventory_stock(self, store_id: int, product_id: int, stock: int) -> bool:
        """Sets stock for a product at a physical store directly."""
        if self.is_live_postgres:
            conn = self._get_pg_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("UPDATE store_inventory SET stock_quantity = %s, is_available = %s, updated_at = CURRENT_TIMESTAMP WHERE store_id = %s AND product_id = %s;", (stock, stock > 0, store_id, product_id))
                    conn.commit()
            finally:
                conn.close()
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                cur.execute("UPDATE store_inventory SET stock_quantity = ?, is_available = ?, updated_at = CURRENT_TIMESTAMP WHERE store_id = ? AND product_id = ?;", (stock, 1 if stock > 0 else 0, store_id, product_id))
                conn.commit()
            finally:
                conn.close()
        return True

    def add_to_cart(self, customer_id: Optional[int] = None, session_id: Optional[str] = None, shopping_mode: str = "ONLINE", product_id: int = 0, quantity: int = 1, store_id: Optional[int] = None, fulfillment: str = "delivery") -> Dict[str, Any]:
        """
        Adds a product to the appropriate cart (Online or Store-Specific Retail).
        Strictly enforces category mode isolation and real live inventory bounds.
        """
        if quantity <= 0:
            raise ValueError(f"Quantity must be strictly positive, got {quantity}")

        product = self.get_product_by_id(product_id)
        if not product:
            raise ValueError(f"Product #{product_id} not found in catalog.")

        mode = "RETAIL_NEAR_ME" if str(shopping_mode).upper() in ["RETAIL", "RETAIL_NEAR_ME"] else "ONLINE"

        if mode == "RETAIL_NEAR_ME":
            if not store_id:
                raise ValueError("store_id is required for Retail shopping.")
            s_id = int(store_id)
            store = self.get_store_by_id(s_id)
            if not store or not store.get("is_active"):
                raise ValueError(f"Store #{s_id} is inactive or does not exist.")

            # Catalog isolation: Retail is strictly groceries
            if product.get("category") != "Daily Essentials & Groceries":
                raise ValueError(f"Product '{product['title']}' is not a daily retail grocery product and cannot be added to a retail basket.")

            # Store inventory & stock check
            inv = self.get_store_product(s_id, product_id)
            if not inv or not inv.get("is_available") or int(inv.get("stock_quantity", 0)) <= 0:
                raise ValueError(f"Product '{product['title']}' is currently out of stock at {store['store_name']}.")

            available_stock = int(inv["stock_quantity"])
            unit_price = float(inv["selling_price"])
        else:
            s_id = None
            # Catalog isolation: Online cart cannot have hyper-local groceries
            if product.get("category") == "Daily Essentials & Groceries":
                raise ValueError(f"Product '{product['title']}' is a hyper-local retail grocery item and cannot be added to the Online Marketplace cart. Please switch to Retail Near Me mode.")

            available_stock = int(product.get("stock", 0))
            if available_stock <= 0:
                raise ValueError(f"Product '{product['title']}' is currently out of stock.")

            unit_price = float(product.get("price", 0.0))

        cart = self.get_or_create_cart(customer_id, session_id, mode, s_id)
        cart_id = cart["id"]

        existing_qty = 0
        existing_item_id = None
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT id, quantity FROM cart_items WHERE cart_id = %s AND product_id = %s LIMIT 1;", (cart_id, product_id))
                    row = cur.fetchone()
                    if row:
                        existing_item_id = row["id"]
                        existing_qty = row["quantity"]
            finally:
                conn.close()
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT id, quantity FROM cart_items WHERE cart_id = ? AND product_id = ? LIMIT 1;", (cart_id, product_id))
                row = cur.fetchone()
                if row:
                    existing_item_id = row[0]
                    existing_qty = row[1]
            finally:
                conn.close()

        new_qty = existing_qty + quantity
        if new_qty > available_stock:
            raise ValueError(f"Requested total quantity ({new_qty}) exceeds available stock ({available_stock}) for '{product['title']}'.")

        fulfillment_val = fulfillment if fulfillment in ["delivery", "pickup"] else "delivery"

        if self.is_live_postgres:
            conn = self._get_pg_connection()
            try:
                with conn.cursor() as cur:
                    if existing_item_id:
                        cur.execute("""
                            UPDATE cart_items
                            SET quantity = %s, unit_price = %s, fulfillment = %s, updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s;
                        """, (new_qty, unit_price, fulfillment_val, existing_item_id))
                    else:
                        cur.execute("""
                            INSERT INTO cart_items (cart_id, product_id, store_id, quantity, unit_price, fulfillment)
                            VALUES (%s, %s, %s, %s, %s, %s);
                        """, (cart_id, product_id, s_id, quantity, unit_price, fulfillment_val))
                    conn.commit()
            finally:
                conn.close()
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                if existing_item_id:
                    cur.execute("""
                        UPDATE cart_items
                        SET quantity = ?, unit_price = ?, fulfillment = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?;
                    """, (new_qty, unit_price, fulfillment_val, existing_item_id))
                else:
                    cur.execute("""
                        INSERT INTO cart_items (cart_id, product_id, store_id, quantity, unit_price, fulfillment)
                        VALUES (?, ?, ?, ?, ?, ?);
                    """, (cart_id, product_id, s_id, quantity, unit_price, fulfillment_val))
                conn.commit()
            finally:
                conn.close()

        return self.get_cart(customer_id, session_id, mode, s_id)

    def update_cart_item(self, item_id: int, quantity: Optional[int] = None, fulfillment: Optional[str] = None, customer_id: Optional[int] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Updates quantity or fulfillment type for an item in the cart.
        """
        item_row = None
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT ci.id, ci.cart_id, ci.product_id, ci.store_id, ci.quantity, ci.unit_price, ci.fulfillment,
                               c.customer_id, c.session_id, c.shopping_mode
                        FROM cart_items ci
                        JOIN carts c ON ci.cart_id = c.id
                        WHERE ci.id = %s;
                    """, (item_id,))
                    row = cur.fetchone()
                    if row:
                        item_row = dict(row)
            finally:
                conn.close()
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT ci.id, ci.cart_id, ci.product_id, ci.store_id, ci.quantity, ci.unit_price, ci.fulfillment,
                           c.customer_id, c.session_id, c.shopping_mode
                    FROM cart_items ci
                    JOIN carts c ON ci.cart_id = c.id
                    WHERE ci.id = ?;
                """, (item_id,))
                cols = [c[0] for c in cur.description]
                row = cur.fetchone()
                if row:
                    item_row = dict(zip(cols, row))
            finally:
                conn.close()

        if not item_row:
            raise ValueError(f"Cart item #{item_id} not found.")

        if customer_id:
            if item_row.get("customer_id") and item_row["customer_id"] != customer_id:
                raise PermissionError("Access denied: cart item belongs to another customer.")
        else:
            if item_row.get("customer_id"):
                raise PermissionError("Access denied: cart item belongs to a registered customer.")
            if session_id and item_row.get("session_id") and not item_row["session_id"].startswith(f"s_{session_id}") and item_row["session_id"] != session_id:
                raise PermissionError("Access denied: cart item belongs to another session.")

        product_id = item_row["product_id"]
        store_id = item_row["store_id"]
        mode = item_row["shopping_mode"]

        if quantity is not None:
            if quantity <= 0:
                if self.is_live_postgres:
                    conn = self._get_pg_connection()
                    try:
                        with conn.cursor() as cur:
                            cur.execute("DELETE FROM cart_items WHERE id = %s;", (item_id,))
                            conn.commit()
                    finally:
                        conn.close()
                else:
                    conn = self._get_sqlite_connection()
                    try:
                        cur = conn.cursor()
                        cur.execute("DELETE FROM cart_items WHERE id = ?;", (item_id,))
                        conn.commit()
                    finally:
                        conn.close()
            else:
                if mode == "RETAIL_NEAR_ME" and store_id:
                    inv = self.get_store_product(store_id, product_id)
                    if not inv or not inv.get("is_available") or int(inv.get("stock_quantity", 0)) <= 0:
                        raise ValueError("Product is no longer available at this store.")
                    avail = int(inv["stock_quantity"])
                    if quantity > avail:
                        raise ValueError(f"Requested quantity ({quantity}) exceeds available store stock ({avail}).")
                    unit_price = float(inv["selling_price"])
                else:
                    prod = self.get_product_by_id(product_id)
                    if not prod or int(prod.get("stock", 0)) <= 0:
                        raise ValueError("Product is currently out of stock.")
                    avail = int(prod["stock"])
                    if quantity > avail:
                        raise ValueError(f"Requested quantity ({quantity}) exceeds available stock ({avail}).")
                    unit_price = float(prod.get("price", 0.0))

                f_val = fulfillment if fulfillment in ["delivery", "pickup"] else item_row["fulfillment"]
                if self.is_live_postgres:
                    conn = self._get_pg_connection()
                    try:
                        with conn.cursor() as cur:
                            cur.execute("""
                                UPDATE cart_items
                                SET quantity = %s, unit_price = %s, fulfillment = %s, updated_at = CURRENT_TIMESTAMP
                                WHERE id = %s;
                            """, (quantity, unit_price, f_val, item_id))
                            conn.commit()
                    finally:
                        conn.close()
                else:
                    conn = self._get_sqlite_connection()
                    try:
                        cur = conn.cursor()
                        cur.execute("""
                            UPDATE cart_items
                            SET quantity = ?, unit_price = ?, fulfillment = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?;
                        """, (quantity, unit_price, f_val, item_id))
                        conn.commit()
                    finally:
                        conn.close()
        elif fulfillment in ["delivery", "pickup"]:
            if self.is_live_postgres:
                conn = self._get_pg_connection()
                try:
                    with conn.cursor() as cur:
                        cur.execute("UPDATE cart_items SET fulfillment = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;", (fulfillment, item_id))
                        conn.commit()
                finally:
                    conn.close()
            else:
                conn = self._get_sqlite_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("UPDATE cart_items SET fulfillment = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;", (fulfillment, item_id))
                    conn.commit()
                finally:
                    conn.close()

        return self.get_cart(customer_id, session_id, mode, store_id)

    def remove_cart_item(self, item_id: int, customer_id: Optional[int] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Removes an item from cart with customer-level ownership validation.
        """
        item_row = None
        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT ci.id, ci.cart_id, ci.product_id, ci.store_id, c.customer_id, c.session_id, c.shopping_mode
                        FROM cart_items ci
                        JOIN carts c ON ci.cart_id = c.id
                        WHERE ci.id = %s;
                    """, (item_id,))
                    row = cur.fetchone()
                    if row:
                        item_row = dict(row)
            finally:
                conn.close()
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT ci.id, ci.cart_id, ci.product_id, ci.store_id, c.customer_id, c.session_id, c.shopping_mode
                    FROM cart_items ci
                    JOIN carts c ON ci.cart_id = c.id
                    WHERE ci.id = ?;
                """, (item_id,))
                cols = [c[0] for c in cur.description]
                row = cur.fetchone()
                if row:
                    item_row = dict(zip(cols, row))
            finally:
                conn.close()

        if not item_row:
            raise ValueError(f"Cart item #{item_id} not found.")

        if customer_id:
            if item_row.get("customer_id") and item_row["customer_id"] != customer_id:
                raise PermissionError("Access denied: cart item belongs to another customer.")
        else:
            if item_row.get("customer_id"):
                raise PermissionError("Access denied: cart item belongs to a registered customer.")
            if session_id and item_row.get("session_id") and not item_row["session_id"].startswith(f"s_{session_id}") and item_row["session_id"] != session_id:
                raise PermissionError("Access denied: cart item belongs to another session.")

        mode = item_row["shopping_mode"]
        store_id = item_row["store_id"]

        if self.is_live_postgres:
            conn = self._get_pg_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM cart_items WHERE id = %s;", (item_id,))
                    conn.commit()
            finally:
                conn.close()
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM cart_items WHERE id = ?;", (item_id,))
                conn.commit()
            finally:
                conn.close()

        return self.get_cart(customer_id, session_id, mode, store_id)

    def clear_cart(self, customer_id: Optional[int] = None, session_id: Optional[str] = None, shopping_mode: str = "ONLINE", store_id: Optional[int] = None) -> bool:
        """
        Clears items from the specified cart.
        """
        cart = self.get_or_create_cart(customer_id, session_id, shopping_mode, store_id)
        cart_id = cart["id"]
        if self.is_live_postgres:
            conn = self._get_pg_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM cart_items WHERE cart_id = %s;", (cart_id,))
                    conn.commit()
            finally:
                conn.close()
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM cart_items WHERE cart_id = ?;", (cart_id,))
                conn.commit()
            finally:
                conn.close()
        return True

    def clear_all_retail_carts(self, customer_id: Optional[int] = None, session_id: Optional[str] = None) -> bool:
        """
        Clears all retail store carts for this customer/session.
        """
        user_sess_prefix = f"c_{customer_id}:RETAIL_NEAR_ME:%" if customer_id else f"s_{session_id or 'anon'}:RETAIL_NEAR_ME:%"
        if self.is_live_postgres:
            conn = self._get_pg_connection()
            try:
                with conn.cursor() as cur:
                    if customer_id:
                        cur.execute("""
                            DELETE FROM cart_items
                            WHERE cart_id IN (
                                SELECT id FROM carts WHERE customer_id = %s AND shopping_mode = 'RETAIL_NEAR_ME' AND status = 'ACTIVE'
                            );
                        """, (customer_id,))
                    else:
                        cur.execute("""
                            DELETE FROM cart_items
                            WHERE cart_id IN (
                                SELECT id FROM carts WHERE (session_id LIKE %s OR session_id = %s) AND shopping_mode = 'RETAIL_NEAR_ME' AND status = 'ACTIVE'
                            );
                        """, (user_sess_prefix, session_id))
                    conn.commit()
            finally:
                conn.close()
        else:
            conn = self._get_sqlite_connection()
            try:
                cur = conn.cursor()
                if customer_id:
                    cur.execute("""
                        DELETE FROM cart_items
                        WHERE cart_id IN (
                            SELECT id FROM carts WHERE customer_id = ? AND shopping_mode = 'RETAIL_NEAR_ME' AND status = 'ACTIVE'
                        );
                    """, (customer_id,))
                else:
                    cur.execute("""
                        DELETE FROM cart_items
                        WHERE cart_id IN (
                            SELECT id FROM carts WHERE (session_id LIKE ? OR session_id = ?) AND shopping_mode = 'RETAIL_NEAR_ME' AND status = 'ACTIVE'
                        );
                    """, (user_sess_prefix, session_id))
                conn.commit()
            finally:
                conn.close()
        return True

    def checkout_online_cart(self, customer_id: int, session_id: Optional[str], customer_info: Dict[str, Any], payment_method: str = "UPI") -> Dict[str, Any]:
        """
        Executes independent Online Shopping checkout using ACID row locking.
        """
        cart = self.get_cart(customer_id, session_id, shopping_mode="ONLINE")
        if not cart or not cart.get("items"):
            raise ValueError("Online cart is empty. Please add items to your basket before checkout.")

        items_payload = [{"product_id": it["product_id"], "quantity": it["quantity"]} for it in cart["items"]]

        order = self.process_checkout_transaction(
            customer_info=customer_info,
            items=items_payload,
            shipping_city=customer_info.get("city") or "Bengaluru",
            shipping_address=customer_info.get("address") or "Customer Delivery Address",
            payment_info={"method": payment_method, "status": "PENDING"}
        )

        cart_id = cart["cart_id"]
        if cart_id:
            if self.is_live_postgres:
                conn = self._get_pg_connection()
                try:
                    with conn.cursor() as cur:
                        cur.execute("UPDATE carts SET status = 'CONVERTED', updated_at = CURRENT_TIMESTAMP WHERE id = %s;", (cart_id,))
                        conn.commit()
                finally:
                    conn.close()
            else:
                conn = self._get_sqlite_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("UPDATE carts SET status = 'CONVERTED', updated_at = CURRENT_TIMESTAMP WHERE id = ?;", (cart_id,))
                    conn.commit()
                finally:
                    conn.close()

        return order

    def checkout_retail_multi_store(self, customer_id: int, session_id: Optional[str], selected_store_ids: List[int], customer_info: Dict[str, Any], delivery_address: Dict[str, Any], payment_method: str = "UPI") -> Dict[str, Any]:
        """
        Executes multi-store checkout for selected Retail baskets.
        - Atomically verifies stock and commits sales for each store.
        - Calculates individual store delivery fees.
        - Creates a parent master order and store-specific suborders.
        - Converts carts for checked-out stores while leaving unselected store baskets intact.
        """
        if not selected_store_ids:
            raise ValueError("No store baskets selected for checkout.")

        cust_lat = delivery_address.get("latitude") or delivery_address.get("lat")
        cust_lng = delivery_address.get("longitude") or delivery_address.get("lng")
        shipping_city = delivery_address.get("city") or customer_info.get("city") or "Bengaluru"
        shipping_addr_str = delivery_address.get("formatted") or delivery_address.get("full_address") or customer_info.get("address") or "Customer Address"

        store_baskets = []
        for s_id in selected_store_ids:
            cart = self.get_cart(customer_id, session_id, shopping_mode="RETAIL_NEAR_ME", store_id=s_id)
            if not cart or not cart.get("items"):
                raise ValueError(f"Cart for Store #{s_id} is empty.")

            store_obj = self.get_store_by_id(s_id)
            if not store_obj or not store_obj.get("is_active"):
                raise ValueError(f"Store #{s_id} is currently inactive.")

            fulfillment = cart["items"][0].get("fulfillment", "delivery")
            del_fee = self.calculate_retail_delivery_fee(s_id, customer_lat=cust_lat, customer_lng=cust_lng, fulfillment=fulfillment)

            for it in cart["items"]:
                inv = self.get_store_product(s_id, it["product_id"])
                if not inv or not inv.get("is_available") or int(inv.get("stock_quantity", 0)) < it["quantity"]:
                    raise ValueError(f"Insufficient stock for '{it['title']}' at {store_obj['store_name']}. Available: {inv.get('stock_quantity', 0) if inv else 0}.")

            store_baskets.append({
                "store_id": s_id,
                "store_name": store_obj["store_name"],
                "cart": cart,
                "fulfillment": fulfillment,
                "delivery_fee": del_fee,
                "subtotal": cart["subtotal"],
                "total": round(cart["subtotal"] + del_fee, 2)
            })

        parent_order_num = f"BK-RET-P-{uuid.uuid4().hex[:8].upper()}"
        combined_product_subtotal = round(sum(b["subtotal"] for b in store_baskets), 2)
        combined_delivery_fees = round(sum(b["delivery_fee"] for b in store_baskets), 2)
        combined_grand_total = round(combined_product_subtotal + combined_delivery_fees, 2)

        is_single_store = (len(store_baskets) == 1)
        suborders = []
        parent_id = None
        single_order_id = None
        single_order_num = None

        if self.is_live_postgres:
            from psycopg2.extras import RealDictCursor
            conn = self._get_pg_connection()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    if not is_single_store:
                        cur.execute("""
                            INSERT INTO orders (order_number, customer_id, total_amount, shipping_fee, status, payment_method, payment_status, shipping_city, shipping_address, shopping_mode)
                            VALUES (%s, %s, %s, %s, 'CONFIRMED', %s, 'PAID', %s, %s, 'RETAIL_NEAR_ME')
                            RETURNING id, created_at;
                        """, (parent_order_num, customer_id, combined_grand_total, combined_delivery_fees, payment_method, shipping_city, shipping_addr_str))
                        p_row = cur.fetchone()
                        parent_id = p_row["id"]

                    for b in store_baskets:
                        s_id = b["store_id"]
                        sub_order_num = f"BK-RET-S{s_id}-{uuid.uuid4().hex[:6].upper()}"
                        cur.execute("""
                            INSERT INTO orders (order_number, customer_id, total_amount, shipping_fee, status, payment_method, payment_status, shipping_city, shipping_address, shopping_mode, store_id, parent_order_id, fulfillment_type)
                            VALUES (%s, %s, %s, %s, 'CONFIRMED', %s, 'PAID', %s, %s, 'RETAIL_NEAR_ME', %s, %s, %s)
                            RETURNING id, created_at;
                        """, (sub_order_num, customer_id, b["total"], b["delivery_fee"], payment_method, shipping_city, shipping_addr_str, s_id, parent_id, b["fulfillment"]))
                        sub_row = cur.fetchone()
                        sub_id = sub_row["id"]
                        if is_single_store:
                            single_order_id = sub_id
                            single_order_num = sub_order_num

                        for it in b["cart"]["items"]:
                            cur.execute("""
                                INSERT INTO order_items (order_id, product_id, quantity, unit_price, subtotal)
                                VALUES (%s, %s, %s, %s, %s);
                            """, (sub_id, it["product_id"], it["quantity"], it["unit_price"], it["subtotal"]))

                            from app.schema import atomic_commit_store_sale
                            atomic_commit_store_sale(cur, is_postgres=True, store_id=s_id, product_id=it["product_id"], quantity=it["quantity"], reference_type="ORDER", reference_id=str(sub_id))

                        cur.execute("UPDATE carts SET status = 'CONVERTED', updated_at = CURRENT_TIMESTAMP WHERE id = %s;", (b["cart"]["cart_id"],))

                        suborders.append({
                            "suborder_id": sub_id,
                            "suborder_number": sub_order_num,
                            "store_id": s_id,
                            "store_name": b["store_name"],
                            "items_count": len(b["cart"]["items"]),
                            "subtotal": b["subtotal"],
                            "delivery_fee": b["delivery_fee"],
                            "total_amount": b["total"],
                            "fulfillment": b["fulfillment"]
                        })
                    conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        else:
            conn = self._get_sqlite_connection()
            cur = conn.cursor()
            try:
                if not is_single_store:
                    cur.execute("""
                        INSERT INTO orders (order_number, customer_id, total_amount, shipping_fee, status, payment_method, payment_status, shipping_city, shipping_address, shopping_mode)
                        VALUES (?, ?, ?, ?, 'CONFIRMED', ?, 'PAID', ?, ?, 'RETAIL_NEAR_ME');
                    """, (parent_order_num, customer_id, combined_grand_total, combined_delivery_fees, payment_method, shipping_city, shipping_addr_str))
                    parent_id = cur.lastrowid

                for b in store_baskets:
                    s_id = b["store_id"]
                    sub_order_num = f"BK-RET-S{s_id}-{uuid.uuid4().hex[:6].upper()}"
                    cur.execute("""
                        INSERT INTO orders (order_number, customer_id, total_amount, shipping_fee, status, payment_method, payment_status, shipping_city, shipping_address, shopping_mode, store_id, parent_order_id, fulfillment_type)
                        VALUES (?, ?, ?, ?, 'CONFIRMED', ?, 'PAID', ?, ?, 'RETAIL_NEAR_ME', ?, ?, ?);
                    """, (sub_order_num, customer_id, b["total"], b["delivery_fee"], payment_method, shipping_city, shipping_addr_str, s_id, parent_id, b["fulfillment"]))
                    sub_id = cur.lastrowid
                    if is_single_store:
                        single_order_id = sub_id
                        single_order_num = sub_order_num

                    for it in b["cart"]["items"]:
                        cur.execute("""
                            INSERT INTO order_items (order_id, product_id, quantity, unit_price, subtotal)
                            VALUES (?, ?, ?, ?, ?);
                        """, (sub_id, it["product_id"], it["quantity"], it["unit_price"], it["subtotal"]))

                        from app.schema import atomic_commit_store_sale
                        atomic_commit_store_sale(cur, is_postgres=False, store_id=s_id, product_id=it["product_id"], quantity=it["quantity"], reference_type="ORDER", reference_id=str(sub_id))

                    cur.execute("UPDATE carts SET status = 'CONVERTED', updated_at = CURRENT_TIMESTAMP WHERE id = ?;", (b["cart"]["cart_id"],))

                    suborders.append({
                        "suborder_id": sub_id,
                        "suborder_number": sub_order_num,
                        "store_id": s_id,
                        "store_name": b["store_name"],
                        "items_count": len(b["cart"]["items"]),
                        "subtotal": b["subtotal"],
                        "delivery_fee": b["delivery_fee"],
                        "total_amount": b["total"],
                        "fulfillment": b["fulfillment"]
                    })
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        # Record initial status transitions in audit ledger
        if parent_id:
            try:
                self.record_order_status_transition(parent_id, None, "CONFIRMED", notes="Multi-store order placed", changed_by="CUSTOMER")
            except Exception as e:
                logger.warning(f"Status history record notice: {e}")

        for sub in suborders:
            try:
                self.record_order_status_transition(sub["suborder_id"], None, "CONFIRMED", notes=f"Suborder placed for {sub['store_name']}", changed_by="CUSTOMER")
            except Exception as e:
                logger.warning(f"Status history record notice: {e}")

        if is_single_store and single_order_id:
            try:
                self.record_order_status_transition(single_order_id, None, "CONFIRMED", notes=f"Retail order placed for {store_baskets[0]['store_name']}", changed_by="CUSTOMER")
            except Exception as e:
                logger.warning(f"Status history record notice: {e}")

        if is_single_store:
            b0 = store_baskets[0]
            return {
                "success": True,
                "order_id": single_order_id,
                "order_number": single_order_num,
                "store_id": b0["store_id"],
                "store_name": b0["store_name"],
                "customer_id": customer_id,
                "status": "CONFIRMED",
                "payment_status": "PAID",
                "payment_method": payment_method,
                "items_count": len(b0["cart"]["items"]),
                "subtotal": b0["subtotal"],
                "delivery_fee": b0["delivery_fee"],
                "grand_total": b0["total"],
                "total_amount": b0["total"],
                "fulfillment": b0["fulfillment"],
                "suborders": []
            }

        return {
            "success": True,
            "parent_order_id": parent_id,
            "parent_order_number": parent_order_num,
            "order_id": parent_id,
            "order_number": parent_order_num,
            "customer_id": customer_id,
            "status": "CONFIRMED",
            "payment_status": "PAID",
            "payment_method": payment_method,
            "stores_count": len(suborders),
            "subtotal": combined_product_subtotal,
            "total_delivery_fee": combined_delivery_fees,
            "grand_total": combined_grand_total,
            "total_amount": combined_grand_total,
            "suborders": suborders
        }



def calculate_haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculates the approximate straight-line great-circle distance between two geographic coordinates
    using the Haversine formula. Earth radius R = 6371.0 km.
    """
    try:
        lat1_f = float(lat1)
        lon1_f = float(lon1)
        lat2_f = float(lat2)
        lon2_f = float(lon2)
    except (ValueError, TypeError):
        raise ValueError("Invalid coordinates format: must be numeric.")

    if not (-90.0 <= lat1_f <= 90.0 and -90.0 <= lat2_f <= 90.0):
        raise ValueError("Latitude must be between -90 and 90 degrees.")
    if not (-180.0 <= lon1_f <= 180.0 and -180.0 <= lon2_f <= 180.0):
        raise ValueError("Longitude must be between -180 and 180 degrees.")

    R = 6371.0
    phi1 = math.radians(lat1_f)
    phi2 = math.radians(lat2_f)
    delta_phi = math.radians(lat2_f - lat1_f)
    delta_lambda = math.radians(lon2_f - lon1_f)

    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    a = min(1.0, max(0.0, a))
    c = 2.0 * math.asin(math.sqrt(a))
    return round(R * c, 2)



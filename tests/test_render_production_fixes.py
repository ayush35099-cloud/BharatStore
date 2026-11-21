"""
BharatStore — Render Production Fixes & PostgreSQL Schema Integrity Test Suite
Verifies:
1. Strict topological table ordering in PostgreSQL DDL (zero forward foreign key references).
2. Strict topological table ordering in SQLite DDL.
3. Explicit foreign key validation: every table referenced by a FOREIGN KEY exists earlier in DDL order.
4. Python 3.10.12 runtime pinning (.python-version & runtime.txt).
5. Catalog products API (/api/products) returns HTTP 200 with complete catalog list.
6. Health endpoint (/api/health) returns honest product and store statistics.
7. Retail context construction (build_retail_context) executes cleanly without error.
8. Production PostgreSQL fail-fast enforcement (never falls back to SQLite in production).
"""

import os
import re
import unittest
from unittest.mock import patch, MagicMock
from run import app
from app.config import Config
from app.database import DatabaseService
from app.schema import get_pg_schema_ddl, get_sqlite_schema_ddl


class TestRenderProductionFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.client = cls.app.test_client()
        cls.db = DatabaseService()

    def test_01_ddl_topological_order_no_forward_references(self):
        """Spec 1: PostgreSQL DDL has zero forward foreign key references."""
        pg_ddls = get_pg_schema_ddl()
        created_tables = []
        table_regex = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_]+)", re.IGNORECASE)
        fk_regex = re.compile(r"REFERENCES\s+([a-zA-Z0-9_]+)\s*\(", re.IGNORECASE)

        for ddl in pg_ddls:
            t_match = table_regex.search(ddl)
            self.assertIsNotNone(t_match, f"Could not extract table name from DDL:\n{ddl}")
            table_name = t_match.group(1).lower()

            # Find all tables referenced by foreign keys in this DDL
            for fk in fk_regex.finditer(ddl):
                ref_table = fk.group(1).lower()
                # Self-referential foreign keys are allowed in PostgreSQL
                if ref_table == table_name:
                    continue
                self.assertIn(
                    ref_table,
                    created_tables,
                    f"Forward reference violation: Table '{table_name}' references '{ref_table}', but '{ref_table}' was not created yet!"
                )
            created_tables.append(table_name)

        # Confirm all 26 core tables are created
        self.assertEqual(len(created_tables), 26)
        self.assertIn("stores", created_tables)
        self.assertIn("store_inventory", created_tables)
        self.assertIn("carts", created_tables)
        self.assertIn("cart_items", created_tables)

        # Explicitly verify 'stores' was created before 'carts', 'cart_items', and 'orders'
        stores_idx = created_tables.index("stores")
        carts_idx = created_tables.index("carts")
        cart_items_idx = created_tables.index("cart_items")
        orders_idx = created_tables.index("orders")
        self.assertLess(stores_idx, carts_idx, "'stores' must be created before 'carts'")
        self.assertLess(stores_idx, cart_items_idx, "'stores' must be created before 'cart_items'")
        self.assertLess(stores_idx, orders_idx, "'stores' must be created before 'orders'")
        print(" [PASSED] 1. PostgreSQL DDL topological order verified with zero forward foreign key references")

    def test_02_sqlite_ddl_topological_order_matches_pg(self):
        """Spec 2: SQLite DDL table order matches PostgreSQL DDL exactly."""
        pg_ddls = get_pg_schema_ddl()
        sqlite_ddls = get_sqlite_schema_ddl()
        self.assertEqual(len(pg_ddls), len(sqlite_ddls), "PostgreSQL and SQLite DDLs must have identical table count")

        table_regex = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_]+)", re.IGNORECASE)
        pg_tables = [table_regex.search(d).group(1).lower() for d in pg_ddls]
        sqlite_tables = [table_regex.search(d).group(1).lower() for d in sqlite_ddls]
        self.assertEqual(pg_tables, sqlite_tables, "PostgreSQL and SQLite table definitions must follow identical order")
        print(" [PASSED] 2. SQLite DDL topological order strictly matches PostgreSQL DDL")

    def test_03_python_version_pinning_files(self):
        """Spec 3: .python-version and runtime.txt correctly pin Python 3.10.12."""
        pyver_path = os.path.join(os.path.dirname(__file__), "..", ".python-version")
        self.assertTrue(os.path.exists(pyver_path))
        with open(pyver_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), "3.10.12")

        runtime_path = os.path.join(os.path.dirname(__file__), "..", "runtime.txt")
        self.assertTrue(os.path.exists(runtime_path))
        with open(runtime_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), "python-3.10.12")
        print(" [PASSED] 3. .python-version and runtime.txt correctly specify Python 3.10.12")

    def test_04_api_products_response(self):
        """Spec 4: /api/products returns HTTP 200 with total count and non-empty product list."""
        res = self.client.get("/api/products")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("total", data)
        self.assertIn("products", data)
        self.assertGreaterEqual(data["total"], 20)
        self.assertEqual(len(data["products"]), data["total"])
        sample_prod = data["products"][0]
        self.assertIn("title", sample_prod)
        self.assertIn("price", sample_prod)
        self.assertIn("stock", sample_prod)
        print(" [PASSED] 4. /api/products returns HTTP 200 with complete catalog list")

    def test_05_api_health_detailed_metrics(self):
        """Spec 5: /api/health accurately reports product_count and store_count."""
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "healthy")
        pg_svc = data["services"]["postgresql"]
        self.assertIn("product_count", pg_svc)
        self.assertIn("store_count", pg_svc)
        self.assertGreater(pg_svc["product_count"], 0)
        self.assertGreater(pg_svc["store_count"], 0)
        print(f" [PASSED] 5. /api/health reports {pg_svc['product_count']} products and {pg_svc['store_count']} stores")

    def test_06_build_retail_context_and_homepage(self):
        """Spec 6: Homepage and retail storefront views render cleanly."""
        res_home = self.client.get("/")
        self.assertEqual(res_home.status_code, 200)

        res_retail = self.client.get("/retail")
        self.assertEqual(res_retail.status_code, 200)
        self.assertIn(b"Bharat Fresh Mart", res_retail.data)
        print(" [PASSED] 6. Homepage and /retail render cleanly with retail stores and catalog")

    def test_07_production_fail_fast_never_silent_fallback(self):
        """Spec 7: In production, PostgreSQL failure raises RuntimeError and never creates SQLite database."""
        with patch.object(Config, "is_production", return_value=True):
            with patch.object(Config, "is_pg_configured", return_value=True):
                with patch("psycopg2.connect", side_effect=Exception("connection refused to postgresql://avnadmin:SecretPass123@host:5432/db")):
                    with self.assertRaises(RuntimeError) as cm:
                        DatabaseService()
                    err = str(cm.exception)
                    self.assertIn("Production PostgreSQL connection failed", err)
                    self.assertNotIn("SecretPass123", err)
        print(" [PASSED] 7. Production fail-fast verified: raises sanitized RuntimeError on PostgreSQL failure")


if __name__ == "__main__":
    unittest.main()
